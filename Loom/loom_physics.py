# -*- coding: utf-8 -*-
"""loom_physics.py — GLEngine 的碰撞系统 (M28) + 刚体物理 (M31) 子系统。

从 engine.py 抽出的整段（原 2448-3297），作为 PhysicsMixin 供 GLEngine 继承。
包含：
  M28 碰撞系统:
    collider_bounds / _collider_from_aabb / _pair_overlap / _pair_overlap_vec /
    _related / _ancestry_ranges / collider_hit / get_collisions /
    _collider_center_radius / _push_out / resolve_collisions / move_with_collision
  M31 刚体物理 + 碰撞事件:
    update_physics / _update_physics_legacy / _update_physics_bridge /
    _ensure_phys_bridge / _ensure_phys_pipe / _destroy_phys_bridge /
    _stop_phys_pipe / _ensure_collision_pool / _update_collision_events /
    _collision_events_inline / _collision_events_parallel /
    _dispatch_collision_events / _collision_pairs_parallel
  类属性 (随 mixin 搬迁): _GRAVITY / _ANCESTRY_CACHE / _COLLISION_* /
    _AABB_* / _PAIR_GEN_NUMPY_MAX

依赖宿主 GLEngine 运行时提供:
  self.models / self.parallel / self.script_cores / self.gravity /
  self._frame_world / self._physics_bounds / self._phys_bridge / self._phys_pipe /
  self._collision_pool / self._struct_gen / self._profile /
  self.get_bounding_box / self.compute_world_matrices / self._call_collision_cb
mixin 只通过 self 按需访问 (语义与拆分前逐位一致)。
"""

import math
import os

import numpy as np

import fastpath
from fastpath import ancestry_dfs as _fp_ancestry
from loom_types import Point3D


def _script_overrides_stay(inst):
    """C1: 脚本实例是否重写了 on_collision_stay (非 Script 基类空方法).
    未定义 → 走原热路径早退 (保持'无事件零开销'契约)."""
    if inst is None:
        return False
    try:
        from scripts import Script as _BaseScript
    except ImportError:
        return False
    fn = getattr(type(inst), 'on_collision_stay', None)
    return fn is not None and fn is not getattr(_BaseScript, 'on_collision_stay', None)


def _any_script_overrides_stay(scripts):
    """物体上是否有任一脚本实例覆盖了 on_collision_stay."""
    for sc in scripts:
        inst = getattr(sc, '_script', None)
        if inst is None or getattr(sc, '_script_broken', False):
            continue
        if _script_overrides_stay(inst):
            return True
    return False


class PhysicsMixin:

    # 组2/组3: _ancestry_ranges 结果缓存 (tin/tout, 类级; 从 engine.GLEngine 迁入)
    _ANCESTRY_CACHE = None

    # ================ 碰撞系统 (M28: 简单物理) ================
    # 设计: 碰撞是"世界空间"实时计算的 —— 每帧按当前变换算世界体积 (含父链),
    # 所以父链移动/旋转子物体也会正确挡人. 支持 box(AABB) 与 sphere 两种碰撞体.
    def collider_bounds(self, m, M=None):
        """世界空间碰撞体数据 -> ('box', (mn, mx)) 或 ('sphere', (center, radius)).
        球体取 AABB 中心 + 最大半长: 对球体网格正好等于真实半径, 比 AABB 更贴合.
        M 可选: 传入当帧批量矩阵避免重算 (多核优化)."""
        if m.collider.shape == 'sphere':
            mn, mx = self.get_bounding_box(m, M)
            c = Point3D((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
            r = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) * 0.5
            return ('sphere', (c, r))
        return ('box', self.get_bounding_box(m, M))

    @staticmethod
    def _collider_from_aabb(shape, aabb):
        """从 AABB (mn,mx) 派生碰撞体数据, 与 collider_bounds 一致 (共享包围盒时免重算).
        sphere: 中心=AABB 中点, 半径=最大半长 (与 collider_bounds 相同); box: 即 AABB."""
        mn, mx = aabb
        if shape == 'sphere':
            c = Point3D((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
            r = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) * 0.5
            return ('sphere', (c, r))
        return ('box', (mn, mx))

    @staticmethod
    def _pair_overlap(ba, bb):
        """两个 (shape, data) 碰撞体是否相交 (纯几何, 无副作用).
        用严格 < : 恰好贴边不算碰撞, 静止物不会反复被推."""
        sa, da = ba
        sb, db = bb
        if sa == 'box' and sb == 'box':
            (amn, amx), (bmn, bmx) = da, db
            return all(amn[i] < bmx[i] and bmn[i] < amx[i] for i in (0, 1, 2))
        if sa == 'sphere' and sb == 'sphere':
            (ca, ra), (cb, rb) = da, db
            dx, dy, dz = ca.x - cb.x, ca.y - cb.y, ca.z - cb.z
            return dx * dx + dy * dy + dz * dz < (ra + rb) ** 2
        # box-sphere: 球心到盒最近点距离 < 半径 (球在盒内也算相交)
        if sa == 'sphere':                # a 是球, b 是盒
            (sc, r), (bmn, bmx) = da, db
        else:                             # a 是盒, b 是球
            (bmn, bmx), (sc, r) = da, db
        cx = max(bmn.x, min(sc.x, bmx.x))
        cy = max(bmn.y, min(sc.y, bmx.y))
        cz = max(bmn.z, min(sc.z, bmx.z))
        dx, dy, dz = sc.x - cx, sc.y - cy, sc.z - cz
        return dx * dx + dy * dy + dz * dz < r * r

    @staticmethod
    def _pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind):
        """向量化 _pair_overlap 判定 (多核优化: 碰撞检测拆分给线程池).

        ai/bj: 模型下标数组 (len K, 逐对); bmn/bmx (n,3) 盒 min/max; scn (n,3)
        球心; rad (n,) 球半径; kind (n,) 0=box 1=sphere. 返回 bool(K),
        与 _pair_overlap 逐位一致 (严格 <, 贴边不算碰撞)."""
        res = np.zeros(len(ai), dtype=bool)
        ki, kj = kind[ai], kind[bj]
        bb = (ki == 0) & (kj == 0)
        if bb.any():
            a, b = ai[bb], bj[bb]
            res[bb] = ((bmn[a, 0] < bmx[b, 0]) & (bmn[b, 0] < bmx[a, 0]) &
                       (bmn[a, 1] < bmx[b, 1]) & (bmn[b, 1] < bmx[a, 1]) &
                       (bmn[a, 2] < bmx[b, 2]) & (bmn[b, 2] < bmx[a, 2]))
        ss = (ki == 1) & (kj == 1)
        if ss.any():
            a, b = ai[ss], bj[ss]
            d = scn[a] - scn[b]
            res[ss] = np.einsum('ij,ij->i', d, d) < (rad[a] + rad[b]) ** 2
        bs = (ki != kj)                       # 盒-球 / 球-盒: 球心到盒最近点距离 < r
        if bs.any():
            a, b = ai[bs], bj[bs]
            sa = np.where(kind[a] == 1, a, b)       # 球下标
            bx = np.where(kind[a] == 1, b, a)       # 盒下标
            cx = np.clip(scn[sa][:, 0], bmn[bx][:, 0], bmx[bx][:, 0])
            cy = np.clip(scn[sa][:, 1], bmn[bx][:, 1], bmx[bx][:, 1])
            cz = np.clip(scn[sa][:, 2], bmn[bx][:, 2], bmx[bx][:, 2])
            dx = scn[sa][:, 0] - cx
            dy = scn[sa][:, 1] - cy
            dz = scn[sa][:, 2] - cz
            res[bs] = (dx * dx + dy * dy + dz * dz) < rad[sa] ** 2
        return res

    def _related(self, a, b):
        """a/b 是否有祖先/后代关系 (同一棵变换树). 同树物体间不互相碰撞."""
        return a is b or self.is_ancestor(a, b) or self.is_ancestor(b, a)

    @staticmethod
    def _ancestry_ranges(models, gen=None):
        """模型森林 DFS 序区间 (A1 2026-08-29, 每帧一次 O(n)):
        a 是 b 祖先 ⟺ tin[a] <= tin[b] < tout[a]。与旧 _related / is_ancestor 沿父链
        判定语义一致; parent 不在 models 视为根 (id2i.get -> -1); 环状父链防御性
        隔离 (理论上不可能, set_parent 防环)。
        组2 (2026-08-30): 结果挂函数对象缓存 (models 列表同一对象 且 gen 版本号
        未变则直接复用 tin/tout) —— 物理子步/A1 对生成每帧多次调用只算一次;
        六处结构变更点经 _bump_struct() 失效。列表对象身份校验防换场景串用。
        组3: gen 由调用方传 (实例计数器 _struct_gen); 不传=退化为 (id, None)
        键, 同一列表对象仅首算缓存 (静态域拿不到 self, 保守正确: 结构变更
        后列表对象通常仍同一 -> 调用方必须传 gen 才有失效语义, 见 _related3 处
        调用点全带 gen)。
        组3层2: DFS 计算委托 fastpath.ancestry_dfs (numba 编译/纯 Python 降级同源, 对拍网 numba_par_check.py 覆盖)。"""
        gen = getattr(models, '_loosed_gen', None) if gen is None else gen
        key = (id(models), gen)
        cache = PhysicsMixin._ANCESTRY_CACHE
        if cache is not None and cache[0] == key:
            return cache[1], cache[2]
        n = len(models)
        id2i = {id(m): i for i, m in enumerate(models)}
        parent_idx = np.full(n, -1, dtype=np.int64)
        for i, m in enumerate(models):
            if m.parent is not None:
                parent_idx[i] = id2i.get(id(m.parent), -1)
        tin, tout = _fp_ancestry(parent_idx)   # 组3层2: children构建+栈式DFS+兜底 委托 fastpath.ancestry_dfs (CSR/根序/防环/兜底语义逐位一致)
        PhysicsMixin._ANCESTRY_CACHE = (key, tin, tout)
        return tin, tout

    def collider_hit(self, a, b, Ma=None, Mb=None):
        """两物体是否碰撞 (都启用且形状非 none 才判; 同树物体不算).
        Ma/Mb: 可选当帧世界矩阵 (避免每对重算 model_world_matrix, 播放期碰撞检测热点)."""
        if self._related(a, b):
            return False
        ca, cb = a.collider, b.collider
        if not (ca.enabled and cb.enabled):
            return False
        if ca.shape == 'none' or cb.shape == 'none':
            return False
        return self._pair_overlap(self.collider_bounds(a, Ma),
                                  self.collider_bounds(b, Mb))

    def get_collisions(self, m, fw=None, bounds=None):
        """碰撞查询: 返回当前与 m 碰撞的所有其他物体 (按 self.models 顺序).
        脚本里用: others = self.engine.get_collisions(self.obj) —— 碰到就能反应.
        fw: 可选当帧世界矩阵列表 (对齐 self.models), 避免逐对重算 model_world_matrix.
        bounds: 可选共享缓存 dict (A3: move_with_collision 跨子步传同一 dict,
        其他物体子步间不动, 碰撞体每物体只算一次; 与逐调用现算数值一致,
        最终位形时刻所得结果逐位相同).
        A3 (2026-08-29): 每物体碰撞体本调用内也只算一次 —— 旧版逐对调
        collider_hit→collider_bounds = 每对一次全网格顶点变换 (高面数球
        逐子步×逐对, 播放物理场景主热点, 实测 7s/帧级).
        组2 (2026-08-30): m 的下标改在物序循环里顺带确定 (旧: models.index
        额外 O(n) 线性扫; 物理子步逐球调用的场景下省 N 次全表扫)."""
        mi = None
        col_m = m.collider
        if col_m is None or not col_m.enabled or col_m.shape == 'none':
            return []
        if bounds is None:
            bounds = {}
        bm = None
        out = []
        for i, o in enumerate(self.models):
            if o is m:
                if fw is not None:
                    mi = i                     # 顺带: m 在物序中的下标 (供 fw 取矩阵)
                continue
            if self._related(m, o):
                continue
            col_o = o.collider
            if col_o is None or not col_o.enabled or col_o.shape == 'none':
                continue
            bo = bounds.get(id(o))
            if bo is None:
                if bm is None:
                    Ma = fw[mi] if (fw is not None and mi is not None) else None
                    bm = self.collider_bounds(m, Ma)
                bo = self.collider_bounds(o, fw[i] if fw is not None else None)
                bounds[id(o)] = bo
            elif bm is None:
                Ma = fw[mi] if (fw is not None and mi is not None) else None
                bm = self.collider_bounds(m, Ma)
            if self._pair_overlap(bm, bo):
                out.append(o)
        return out

    def _collider_center_radius(self, m):
        """碰撞体 -> (中心, 特征半径). 球=真实半径; 盒=外接球半径 (推挤近似用)."""
        shape, data = self.collider_bounds(m)
        if shape == 'sphere':
            return data
        mn, mx = data
        c = Point3D((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
        r = math.sqrt(((mx.x - mn.x) ** 2 + (mx.y - mn.y) ** 2 + (mx.z - mn.z) ** 2) * 0.25)
        return (c, r)

    def _push_out(self, a, b, bounds=None):
        """把 a 推出 b 的碰撞体 (仅已相交时调用). 盒-盒走最小穿透轴 (滑墙自然),
        含球时沿球心连线推出. 只改 a.position.
        A3: bounds 缓存中 b 的碰撞体直接复用 (b 帧内静止, 免逐次全网格重算);
        a 自身不缓存 (每次推出都改了 a.position, 必须现算)."""
        ba = self.collider_bounds(a)
        if bounds is not None:
            bb = bounds.get(id(b))
            if bb is None:
                bb = self.collider_bounds(b)
                bounds[id(b)] = bb
        else:
            bb = self.collider_bounds(b)
        if ba[0] == 'box' and bb[0] == 'box':
            (amn, amx), (bmn, bmx) = ba[1], bb[1]
            # 每轴正确穿透量 = 把 a 沿 + / - 推到刚分开的最小位移 (取较小者).
            # 这样零厚度盒 (地面平面) 也能得到真实穿透量, 而不是 0.
            best_axis = best_sign = None
            best_push = None
            for i in (0, 1, 2):
                a0, a1 = amn[i], amx[i]
                b0, b1 = bmn[i], bmx[i]
                if a0 >= b1 or b0 >= a1:      # 该轴不相交 -> 不用推
                    continue
                dist_right = b1 - a0           # a 向右推这么多才分开 (>=0)
                dist_left = a1 - b0            # a 向左推这么多才分开
                if dist_left < dist_right - 1e-9:
                    sign, dist = -1.0, dist_left
                elif dist_right < dist_left - 1e-9:
                    sign, dist = +1.0, dist_right
                else:                          # 相等: 朝远离对方中心方向
                    sign = +1.0 if (a0 + a1) >= (b0 + b1) else -1.0
                    dist = dist_right if sign > 0 else dist_left
                if best_push is None or dist < best_push:
                    best_push, best_sign, best_axis = dist, sign, i
            if best_axis is not None:
                p = list(a.position)
                p[best_axis] += best_sign * (best_push + 1e-4)
                a.position = Point3D(*p)
            return
        # 球-球: 沿两中心连线推出 (球心到球心, 半径和)
        if ba[0] == 'sphere' and bb[0] == 'sphere':
            ca, ra = ba[1]
            cb, rb = bb[1]
            dx, dy, dz = ca.x - cb.x, ca.y - cb.y, ca.z - cb.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
            need = ra + rb - dist + 1e-4
            u = (dx / dist, dy / dist, dz / dist)
            p = list(a.position)
            p[0] += u[0] * need
            p[1] += u[1] * need
            p[2] += u[2] * need
            a.position = Point3D(*p)
            return
        # 盒-球: 用"球心到盒最近点"推出 (与 _pair_overlap 判定一致; 修复 2026-08-12:
        # 旧实现把盒当球取最大半长, 大平面(地面 10x10)被当半径5的球, 球被推出数个单位).
        if ba[0] == 'sphere':
            sc, r = ba[1]; bmn, bmx = bb[1]; a_is_sphere = True
        else:
            bmn, bmx = ba[1]; sc, r = bb[1]; a_is_sphere = False
        nx = min(max(sc.x, bmn.x), bmx.x)
        ny = min(max(sc.y, bmn.y), bmx.y)
        nz = min(max(sc.z, bmn.z), bmx.z)
        dx, dy, dz = sc.x - nx, sc.y - ny, sc.z - nz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist < 1e-9:
            # 球心在盒内: 沿盒中心指向球心方向推出 (球半径距离)
            cc = Point3D((bmn.x + bmx.x) / 2, (bmn.y + bmx.y) / 2,
                         (bmn.z + bmx.z) / 2)
            vx, vy, vz = sc.x - cc.x, sc.y - cc.y, sc.z - cc.z
            vl = math.sqrt(vx * vx + vy * vy + vz * vz) or 1e-6
            u = (vx / vl, vy / vl, vz / vl)
            need = r + 1e-4
        else:
            need = r - dist + 1e-4
            u = (dx / dist, dy / dist, dz / dist)      # 盒最近点 -> 球心
            if not a_is_sphere:
                u = (-u[0], -u[1], -u[2])             # a 是盒: 反方向推盒离球
        p = list(a.position)
        p[0] += u[0] * need
        p[1] += u[1] * need
        p[2] += u[2] * need
        a.position = Point3D(*p)

    def resolve_collisions(self, m, max_iter=4, bounds=None):
        """把 m 推干净: 迭代推离所有相交物体. 返回是否发生过碰撞 (被挡).
        脚本在移动后调用, 或直接交给 move_with_collision.
        bounds: 共享碰撞体缓存 (A3, 见 get_collisions; 其他物体帧内静止时
        一次算全程复用)."""
        hit = False
        for _ in range(max_iter):
            coll = self.get_collisions(m, bounds=bounds)
            if not coll:
                break
            hit = True
            for o in coll:
                self._push_out(m, o, bounds=bounds)
        return hit

    def move_with_collision(self, m, dx, dy, dz, bounds=None):
        """带碰撞的位移 (M28 响应): 子步移动防穿透薄物体 (每步 <= 碰撞体特征尺寸),
        每步移动后把 m 推出所有相交碰撞体. 返回 True = 被挡住/发生碰撞
        (脚本据此停下/反弹/触发事件).
        bounds: 可选共享碰撞体缓存 dict (A3) —— 子步间/同帧物理阶段其他物体静止,
        碰撞体每物体只算一次 (本物体自身每子步现算: m 每个子步后都在变, 且从不
        被写进缓存)。传帧级缓存时 (update_physics._physics_bounds) 特别精确:
        后移动物体查先移动物体的条目 = 首次现算所得 "先移动者的移动后位形"
        (它也不在该缓存里), 与逐调用现算逐位一致."""
        shape, data = self.collider_bounds(m)
        if shape == 'sphere':
            step = max(data[1], 0.02)                 # 球: 特征步长 = 半径
        else:
            mn, mx = data
            # 盒: 最小半边长 (沿任何轴移动该距离都不会跳过相邻薄面)
            step = max(min(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) * 0.5, 0.02)
        n = max(1, math.ceil(max(abs(dx), abs(dy), abs(dz)) / step))
        n = min(n, 5000)                              # 防御: 病态超大位移不卡死
        if bounds is None:
            bounds = {}
        hit = False
        for _ in range(n):
            m.position = Point3D(m.position.x + dx / n,
                                 m.position.y + dy / n,
                                 m.position.z + dz / n)
            if self.resolve_collisions(m, bounds=bounds):
                hit = True
        bounds.pop(id(m), None)                       # 自身条目不存在, 防御清理
        return hit

    # ================ 刚体物理 + 碰撞事件 (M31) ================
    _GRAVITY = -9.8

    def update_physics(self, delta_time, events=True):
        """M31: 每帧刚体步进 + 碰撞事件回调 (Unity Rigidbody 理念).
        B1 (2026-08-30): **桥分支** —— _phys_bridge 存在且 enabled 时, 刚体动力学
        交给 Culverin (Jolt) (physics_bridge.py: R1 手动重力/策略 R 速度门控/接触
        解算/摩擦滚动/睡眠; pre→step→post 三段内联于 _update_physics_bridge);
        无桥/库不可用/测试桩 -> **_update_physics_legacy** (原实现, 一行未删)。
        进入播放 (toggle_play) / 首次 update_physics 直调由 _ensure_phys_bridge
        惰性建桥 (仅完整 __init__ 实例: getattr(_phys_bridge_auto)); 测试桩
        (__new__ 不跑 __init__) 无该属性 -> 永走 legacy (现契约测试零受影响)。"""
        br = getattr(self, '_phys_bridge', None)
        if br is not None:
            if getattr(br, 'enabled', False):
                self._update_physics_bridge(delta_time, events)
                return
            self._phys_bridge = None            # 僵死桥 (库异常) -> 释放走 legacy
        elif getattr(self, '_phys_bridge_auto', False):
            self._ensure_phys_bridge()
            br = getattr(self, '_phys_bridge', None)
            if br is not None and getattr(br, 'enabled', False):
                self._update_physics_bridge(delta_time, events)
                return
        self._update_physics_legacy(delta_time, events)

    def _update_physics_legacy(self, delta_time, events=True):
        """自研物理 (M31 原实现, B1 起作为**回退分支**): 累加-移动-撞停模型.
        对每个带刚体的动态物体: 重力累加速度 -> 按速度带碰撞移动 (被挡停清速度).
        B1 桥路径下不调用; 无 culverin / 测试桩 / 桥异常回退时走这里 (行为逐位不变).
        events=False: 跳过碰撞事件 (2026-08-15 8 核均摊: 渲染路径把碰撞**检测**与阴影
        VP 并行后, 事件**派发**回主线程单独做; 直调本方法 (测试/旧路径) 默认 events=True 不变).
        A3 (2026-08-29): 物理阶段所有移动物体共享 _physics_bounds 缓存 —— 非移动
        物体的碰撞体本帧只算一次 (旧版每球移动调用逐对全网格变换); 移动者自身
        每子步现算 (move_with_collision 结束 pop 自身条目), 顺序精确性保持:
        后移动物体查先移动者时缓存必为"移动后位形" (先移动者条目未被写进缓存,
        等同现算, 见 move_with_collision 注释)."""
        dt = max(delta_time, 1e-4)
        self._physics_bounds = {}          # 本帧物理级缓存 (id(o) -> 碰撞体数据)
        for m in self.models:
            rb = m.rigidbody
            if rb is None or rb.is_kinematic:
                continue
            if rb.use_gravity:
                # 2026-08-30: 重力可调 (self.gravity, 场景/设置/面板); getattr 防御
                # 测试桩 (__new__ 不跑 __init__ 时无 gravity 属性)
                g = getattr(self, 'gravity', self._GRAVITY)
                rb.velocity = Point3D(rb.velocity.x,
                                      rb.velocity.y + g * dt,
                                      rb.velocity.z)
            vx, vy, vz = rb.velocity.x, rb.velocity.y, rb.velocity.z
            if not (vx or vy or vz):
                continue
            hit = self.move_with_collision(m, vx * dt, vy * dt, vz * dt,
                                           bounds=self._physics_bounds)
            if hit:
                # 撞到东西: 速度归零停住 (简单版; 后续可做轴向分离/反弹/滑墙)
                rb.velocity = Point3D(0.0, 0.0, 0.0)
        if events:
            self._update_collision_events(dt)

    # ================ B1: Culverin (Jolt) 物理桥路径 ================
    def _update_physics_bridge(self, delta_time, events):
        """桥路径: ensure_models 差量 -> pre_step (脏同步+策略R+重力) -> step
        (释放 GIL) -> post_step (批式回读) — 顺序 per 设计 §3.1; 其余不动
        (world matrices/几何事件在回读之后, 见 render/EditorApp.render)."""
        dt = max(delta_time, 1e-4)
        br = getattr(self, '_phys_bridge', None)
        if br is None or not getattr(br, 'enabled', False):
            if events:
                self._update_collision_events(dt)
            return
        try:
            # 2026-09-01 组8 细拆插桩: physics 22.84ms 拆四段 (ensure_models
            # O(N²)扫描嫌疑 vs Jolt step C 调用 vs pre/post), LOOM_PROFILE 子阶段
            g = getattr(self, 'gravity', self._GRAVITY)       # R1: 用引擎实例重力!
            # 批6: 流水线调度上收 _logic_frame (post 不等待 + S1 等待);
            # 本函数回归纯串行直跑 (测试/探针/legacy 直调语义同批4 之前).
            self._profile('phys_bridge_ensure', lambda: br.ensure_models(self.models))
            self._profile('phys_bridge_pre', lambda: br.pre_step(dt, g))
            self._profile('phys_bridge_step', lambda: br.step(dt))
            self._profile('phys_bridge_post', lambda: br.post_step())
        except Exception as e:
            # 桥异常: 本帧回退 legacy 并释放桥 (静默降级, 游戏不崩; 控制台留痕)
            print("[物理] 桥步进异常 (%r) -> 释放桥并回退 legacy" % (e,))
            self._destroy_phys_bridge()
            self._update_physics_legacy(dt, events)
            return
        if events:
            self._update_collision_events(dt)                 # 几何事件 (B1 保留, 见设计 §2.2)

    def _ensure_phys_bridge(self):
        """惰性建桥: 首次进入播放/首次 update_physics 直调. 返回桥实例或 None.
        无 culverin / 建体失败 -> 置 _phys_bridge_disabled 标记, 不再重试 (legacy).
        ★getattr 防御测试桩 (__new__ 无 __init__): _phys_bridge_auto 缺失 -> None."""
        if getattr(self, '_phys_bridge_auto', False) is not True:
            return None
        if getattr(self, '_phys_bridge_disabled', False):
            return None
        br = getattr(self, '_phys_bridge', None)
        if br is not None:
            return br
        try:
            from physics_bridge import PhysicsWorldBridge, cv_available
        except Exception as e:
            print("[物理] physics_bridge 导入失败:", e)
            self._phys_bridge_disabled = True
            return None
        if not cv_available:
            self._phys_bridge_disabled = True       # 无库环境: 静默 legacy (设计 P5 提示点)
            return None
        br = PhysicsWorldBridge()
        try:
            br.build(self.models)
        except Exception as e:
            print("[物理] Culverin 建体失败 (%r) -> 保持 legacy" % (e,))
            try:
                br.destroy()
            except Exception:
                pass
            self._phys_bridge_disabled = True
            return None
        self._phys_bridge = br
        print("[物理] Jolt (Culverin) 物理桥已建立: %d 体" % br.body_count)
        # 分离批4: 桥建好后启动常驻物理线程 (LOOM_NO_PIPE=1 逃生门 = 不建)
        self._ensure_phys_pipe(br)
        return br

    def _ensure_phys_pipe(self, br):
        """分离批4: 建常驻物理线程 (桥存在且未禁用时). 幂等。

        ★B4c 退役 (2026-10-16): 删 LOOM_NO_PIPE 逃生门 (A/B 基线)。
        唯一异常面 = 系统级资源耗尽 (Thread.start 失败, 非逃生门); 保留有限兜底:
          降级主线程串行跑物理 + 醒目双语告警 + 置 _phys_pipe_sysfail 标志
          (供 HUD / 状态栏暴露, 提醒用户立即保存+关闭+排查)。
        这是功能边界 (设计如此), 与"官方件不兜底"纪律不冲突——它不是回退路径,
        而是系统极限工况下的保命机制 (避免拖垮整个系统)。"""
        if getattr(self, '_phys_pipe', None) is not None:
            return self._phys_pipe
        try:
            from physics_pipe import PhysicsPipeThread
            _pol = (getattr(self, 'parallel', None) or {}).get('policy') or {}
            self._phys_pipe = PhysicsPipeThread(br, mask=_pol.get('pool_mask') or 0)
            return self._phys_pipe
        except Exception as e:
            # ★系统极限工况兜底: OS 线程数 / 内存耗尽
            print("=" * 72)
            print("[物理] !!! WARNING / 警告 !!!")
            print("[物理]   物理线程无法建立: %r" % (e,))
            print("[物理]   Physics thread creation failed: %r" % (e,))
            print("[物理]   可能原因 / Likely cause:")
            print("[物理]     - 系统线程数耗尽 / OS thread limit reached")
            print("[物理]     - 系统内存耗尽 / Out of memory")
            print("[物理]   已降级: 主线程直跑物理 (功能可用, 性能下降)")
            print("[物理]   Degraded to: main-thread physics (works, lower perf)")
            print("[物理]   ★ 请立即保存场景并关闭软件, 排查系统资源占用!")
            print("[物理]   ★ Save your work and close Loom NOW; investigate "
                  "system resource exhaustion.")
            print("[物理]   ★ 继续运行可能进一步耗尽资源, 下次崩溃可能是整个系统。")
            print("[物理]   ★ Continued running may exhaust resources further; "
                  "the next crash could take down the whole system.")
            print("=" * 72)
            self._phys_pipe_sysfail = True
            self._phys_pipe = None
            return None

    def _destroy_phys_bridge(self):
        """销毁桥 (播放结束/退出清理). 幂等. 快照还原在 destroy 之前完成
        (toggle_play 退出分支先 apply_snapshot 再 destroy, 见 editor.py)."""
        # 分离批4: 先停物理线程再销毁桥 (线程持有 _w 引用, 顺序不可反!)
        self._stop_phys_pipe()
        br = getattr(self, '_phys_bridge', None)
        if br is not None:
            try:
                br.destroy()
            except Exception:
                pass
        self._phys_bridge = None
        # 不置 disabled: 下次进入播放可重建 (播放-停止循环)

    def _stop_phys_pipe(self):
        """分离批4: 停物理线程 (幂等; 退出链三处调: _destroy_phys_bridge /
        _stop_parallel / 管线异常降级)."""
        pipe = getattr(self, '_phys_pipe', None)
        if pipe is not None:
            try:
                pipe.stop()
            except Exception:
                pass
            self._phys_pipe = None

    # 碰撞事件并行阈值: 模型数 >= 此值才启用线程池 (小场景走内联零线程开销)
    _COLLISION_PAR_THRESHOLD = 32
    # 碰撞对分块阈值: 碰撞对 >= 此值才真正分块丢线程池 (2026-08-15 实测: 单次向量化
    # 调用比线程池分块快 300 倍; 只有超大场景线程池并发才有收益)
    _COLLISION_POOL_PAIRS = 100000
    # AABB 并行阈值: 模型数 >= 此值才用预计算池分块算包围盒 (压测实测 51 模型池比串行慢,
    # 模型多时 numpy 分块才摊得开线程开销)
    _AABB_POOL_THRESHOLD = int(os.environ.get('LOOM_AABB_POOL_THRESHOLD', '64'))
    # ★M3-N2 (2026-09-09): 脏行路径**回池**的额外下限。实测 (混合500, 100 脏行/V≈2035):
    #   池路径把脏集切 16 块 (batches_per_thread=2) 且每块按 V 重分组 → 每逻辑步
    #   ~50 次小 kernel 调用 (每次仅 ~3.8k 工作量, in-situ 0.79 ms/次 vs 微基准
    #   4.6 ns/顶点) → mt_aabb_minmax 累计 7.2 ms/帧, 主线程等 1.49 ms/帧;
    #   同工作量**主线程串行**: kernel 总耗时 0.21 ms/帧, aabbs 段 0.35 ms/帧,
    #   paint_total 6.65 → 4.98, FPS 111 → 133 (交错 A/B n=2, 区间不重叠)。
    #   仅当脏行数足够大 (池调度/分组开销可摊薄) 才回池。
    _AABB_DIRTY_POOL_MIN = int(os.environ.get('LOOM_AABB_DIRTY_POOL_MIN', '2048'))
    # ★spin-wait 治理 (2026-08-31): prange 并行逃生门闸门 —— 单组模型数 >= 此值才
    # 切 aabbs_minmax_par (numba 线程池). 实测 51球组串行 njit ~104µs / 并行 ~54µs,
    # 差距 <100µs 无关紧要, 而 prange 唤醒的 18 个 worker 在帧间 busy-wait 空烧
    # (18 核满载 99.96% 无效负载, numba_spin_probe.py 实锤). 闸门 = 工作量足够大
    # 才值得付 spin 税 (估算: n_models × V 顶点, 512 模型×2035顶点 ≈ 1M 变换 ~1ms).
    _AABB_PAR_MIN_MODELS = 512
    # ★批4A (2026-09-07): 并行闸门改 n×V 工作量判据 (_aabbs_batched 调用点生效,
    # 本常量保留只为探针兼容 —— spin_gate_check / shadow_val_check / aabb_ab_e2e
    # 引用, 不再参与判定)。微基准 (Win32 线程 C 内核, NT=9): 并行地板 ~0.9-1.0ms
    # (线程创建 ~0.5ms + 派发/join), 串行 ≈4.6ns × n×V → 净收益 >15% 临界
    # n×V ≈ 0.26M; 取 0.30M 留裕度 (宁保守): 实测 (100,3015) +26% /
    # (~150,2035) +30% / (90,1247) 仍串行 (并行 -102% 倒退)。n-only 闸门在
    # 低 V 组会误开 (如 384×cube V=24 → 并行 -1200%), 工作量判据两侧都安全。
    # ★M3 (2026-09-09): 可经 LOOM_AABB_PAR_MIN_WORK 覆盖 (A/B 用; 默认 0.30M 不变)。
    # 动机: 池分块路径下每个 worker 各自调用 prange 版 → 嵌套并行 + 18 线程 spin 税,
    # 实测 mt_aabb_minmax 累计 7.06 ms/帧 (跨 worker)。置大值 = 永远走串行 C/njit。
    _AABB_PAR_MIN_WORK = int(os.environ.get('LOOM_AABB_PAR_MIN_WORK', '300000'))
    # A1 (2026-08-29): 候选对 numpy 生成上限 (triu 全对内存 ~ n^2*16B;
    # >2048 碰撞体即 >33MB, 现实场景不触发, 回退原 Python 循环只防内存)
    _PAIR_GEN_NUMPY_MAX = 2048
    # ★B5 退役 (2026-10-16): 删 _SAP_FALLBACK_PAIRS 死常量 (全库无使用点) +
    #   LOOM_NO_SAP 逃生门 (A/B 对拍门, 蓝图 §3 顺序 5)。

    def _ensure_collision_pool(self):
        """自适应创建碰撞检测线程池 (线程 affinity = 渲染核 pool_mask). 返回池或 None."""
        if self._collision_pool is None:
            try:
                from concurrent.futures import ThreadPoolExecutor
                from parallel import pin_current_thread
                pol = self.parallel.get('policy') if self.parallel else None
                pmask = (pol or {}).get('pool_mask') or 0

                def _init():
                    if pmask:
                        pin_current_thread(pmask)

                n_logical = (pol or {}).get('n_logical', 0) or (os.cpu_count() or 1)
                nw = min(4, max(1, n_logical - (self.script_cores or 0) - 1))
                self._collision_pool = ThreadPoolExecutor(
                    max_workers=nw, initializer=_init)
            except Exception as e:
                print("[parallel] 碰撞池初始化失败:", e)
                self._collision_pool = None
        return self._collision_pool

    def _update_collision_events(self, dt):
        """M31: 比较每物体当前碰撞集与上次, 触发脚本 on_collision_start/on_collision_end
        (Unity OnCollisionEnter/Exit 式). 只对有脚本的物体检测.
        多核优化: 大场景 (>=阈值) 且并行启用时, 碰撞检测走向量化+线程池 (只读),
        事件派发仍串行 (改脚本状态必须串行). 小场景内联零开销."""
        n = len(self.models)
        if (n >= self._COLLISION_PAR_THRESHOLD
                and getattr(self, 'parallel', None) is not None
                and self._ensure_collision_pool() is not None):
            self._collision_events_parallel()
        else:
            self._collision_events_inline()

    def _collision_events_inline(self):
        """小场景碰撞事件 (O(N^2) 逐对判定).
        2026-08-15 性能修复: **每个物体只算一次碰撞体包围盒 (O(N), 传当帧 _frame_world
        免重算 model_world_matrix), 逐对判定用缓存的包围盒走纯几何 _pair_overlap** ——
        原实现逐对调 collider_bounds 重算全部顶点变换, 20 脚本物体曾 53ms/帧 (19FPS)."""
        models = self.models
        fw = getattr(self, '_frame_world', None)
        n = len(models)
        # 每物体碰撞体缓存 (含当帧矩阵), None=无碰撞体
        bounds = [None] * n
        for i, m in enumerate(models):
            col = m.collider
            if col is not None and col.enabled and col.shape != 'none':
                Mi = fw[i] if fw is not None and i < n else None
                bounds[i] = (m, self.collider_bounds(m, Mi))
        for i, m in enumerate(models):
            if not m.scripts:
                continue
            if bounds[i] is None:
                m._colliding = set()
                continue
            bi = bounds[i][1]
            current = set()
            for j in range(n):
                if j == i or self._related(m, models[j]):
                    continue
                bj = bounds[j]
                if bj is None:
                    continue
                if self._pair_overlap(bi, bj[1]):
                    current.add(id(bj[0]))
            prev = getattr(m, '_colliding', set())
            # C1 (2026-10-16): 有脚本覆盖 on_collision_stay 时, 即使集合不变也要派发;
            # 否则保持原"无事件零开销"早退契约.
            has_stay = _any_script_overrides_stay(m.scripts)
            if current == prev and not has_stay:
                continue
            # 组2 (2026-08-30): id->对象 一次建 (旧: 每事件 next() O(n) 扫;
            # 仅在确有增减事件时才建, 无事件帧零开销)
            id2m = {id(o): o for o in models}
            for cid in current - prev:
                self._call_collision_cb(m, 'on_collision_start', id2m.get(cid))
            for cid in prev - current:
                self._call_collision_cb(m, 'on_collision_end', id2m.get(cid))
            if has_stay:
                for cid in current & prev:
                    self._call_collision_cb(m, 'on_collision_stay', id2m.get(cid))
            m._colliding = current

    def _collision_events_parallel(self):
        """并行版: 一次算全部碰撞对 (向量化 + 线程池), 串行派发事件.
        current 集合与内联版逐位一致."""
        pairs = self._collision_pairs_parallel()      # 只读检测
        self._dispatch_collision_events(pairs)        # 串行派发 (改脚本状态)

    def _dispatch_collision_events(self, pairs):
        """把碰撞对 [(i,j),...] 串行派发成 on_collision_start/end (改脚本状态, 必须主线程).
        2026-08-15: 从检测中拆出, 让检测能与阴影 VP 并行 (检测只读)."""
        neigh = {}
        for i, j in pairs:
            neigh.setdefault(i, set()).add(j)
            neigh.setdefault(j, set()).add(i)
        # 组2 (2026-08-30): id->对象 一次建 (旧: 每事件 next() 生成器全表扫 O(n))
        id2m = {id(o): o for o in self.models}
        for i, m in enumerate(self.models):
            if not m.scripts:
                continue
            current = {id(self.models[j]) for j in neigh.get(i, ())}
            prev = getattr(m, '_colliding', set())
            # C1 (2026-10-16): 有脚本覆盖 on_collision_stay 时, 即使集合不变也要派发.
            has_stay = _any_script_overrides_stay(m.scripts)
            if current == prev and not has_stay:
                continue
            for cid in current - prev:
                self._call_collision_cb(m, 'on_collision_start', id2m.get(cid))
            for cid in prev - current:
                self._call_collision_cb(m, 'on_collision_end', id2m.get(cid))
            if has_stay:
                for cid in current & prev:
                    self._call_collision_cb(m, 'on_collision_stay', id2m.get(cid))
            m._colliding = current

    def _collision_pairs_parallel(self, aabbs=None):
        """全部碰撞对 [(i,j), ...] (i<j, 无副作用).
        aabbs: 可选**全量对齐** AABB 列表 (阴影与碰撞共享的那份, 当帧位形) —— 给定则
        直接从 AABB 派生碰撞体数据, 免重算 world matrices + 免变换全部顶点 (播放期
        50 高面数球碰撞曾 ~10ms 的热点). 不给则现算 (直接调用方/测试, 行为不变).
        2026-08-15: 根对象对 (双方 parent=None) 直接判不相关, 免祖先链遍历 (快路径)."""
        models = self.models
        n = len(models)
        cand = [i for i, m in enumerate(models)
                if m.collider is not None and m.collider.enabled
                and m.collider.shape != 'none']
        if len(cand) < 2:
            return []
        bmn = np.zeros((n, 3), dtype=np.float64)
        bmx = np.zeros((n, 3), dtype=np.float64)
        scn = np.zeros((n, 3), dtype=np.float64)
        rad = np.zeros(n, dtype=np.float64)
        kind = np.zeros(n, dtype=np.int64)
        fw = None
        if aabbs is None:
            # ★C 一体内核 (2026-09-07): aabbs 给定时 (播放态 prep 共享路径)
            #   全局碰撞体数组延迟到 NO_SAP 逃生门路径才建 (旧提取 1.04ms 是热段
            #   第二大头, 见 collide_prof.py) — C 路自带碰撞体局部提取. aabbs=None
            #   (直接调用方/测试) 行为不变 (仍现算进全局数组, C 路不用也不重复算).
            #   B1 退役: 默认路只走 C 路 (numpy 回退段已删).
            fw = self.compute_world_matrices(models)   # 当帧当前位形 (直接调用方)
            for i in cand:
                shape, data = self.collider_bounds(models[i], fw[i])
                if shape == 'box':
                    (mn, mx) = data
                    bmn[i] = (mn.x, mn.y, mn.z)
                    bmx[i] = (mx.x, mx.y, mx.z)
                else:
                    (c, r) = data
                    scn[i] = (c.x, c.y, c.z)
                    rad[i] = r
                    kind[i] = 1
        # ---- 候选对生成 (A1 2026-08-29 numpy 化; 项C SAP 2026-09-02 粗筛) ----
        # ★B5 退役 (2026-10-16): 原三路 (A 内存上限 / B NO_SAP 对拍门 / C 默认 SAP)
        #   收敛为两路 (B 路已删)。剩:
        #   A) n_c > _PAIR_GEN_NUMPY_MAX: 旧 Python 双循环 (只防内存, 罕见);
        #   C) 默认: x 轴 sweep-and-prune **物体级**粗筛 —— C 一体内核
        #      (loom_kernels.loom_collide_pairs): SAP 窗口扫描 / yz / ancestry /
        #      精判 / 归一去重单次调用. 500球: 12.4万 triu 对 → ~百级精判,
        #      collide_pairs 19.5→1-2ms.
        n_c = len(cand)
        if n_c > self._PAIR_GEN_NUMPY_MAX:
            roots = [m.parent is None for m in models]
            pairs_i, pairs_j = [], []
            for a in range(n_c):
                i = cand[a]
                for b in range(a + 1, n_c):
                    j = cand[b]
                    if roots[i] and roots[j]:
                        pairs_i.append(i)
                        pairs_j.append(j)
                        continue
                    if not self._related(models[i], models[j]):
                        pairs_i.append(i)
                        pairs_j.append(j)
            if not pairs_i:
                return []
            ai = np.array(pairs_i, dtype=np.int64)
            bj = np.array(pairs_j, dtype=np.int64)
        else:
            tin, tout = self._ancestry_ranges(models, getattr(self, '_struct_gen', None))
            ci = np.asarray(cand, dtype=np.int64)
            # ★C 一体内核 (2026-09-07 任务: collide_pairs 4.2→≤1.5ms):
            #   候选提取向量化 (cand 局部 SoA, 取证 2× 快) + SAP 窗口扫描/yz/
            #   ancestry/精判/归一去重全进 loom_kernels.loom_collide_pairs 单次
            #   调用 (取证 collide_prof.py: Python 相位合计 3.4ms/帧, 解释器
            #   开销是大头). 输出 (i<j, key 升序去重) 与下方 numpy 段位相同集合
            #   (对拍闸门 collide_val_check.py 逐帧一致).
            #   B1 退役: 默认路只走 C 路; 失败即 raise (numpy 回退段已删).
            #   aabbs=None (fw 直调路): 全局数组已在上文建好, C 路改吃其局部行
            #   (fancy index 拷贝, ~0.1ms 级) — 两路同进 C 内核.
            if fastpath._CKERNELS is not None:
                if aabbs is not None:
                    ex = fastpath.collide_extract(
                        cand, [aabbs[i] for i in cand],
                        [models[i].collider.shape for i in cand], n)
                else:
                    ex = fastpath.collide_extract_local(
                        ci, bmn, bmx, scn, rad, kind)
                if ex[0] is None:
                    raise RuntimeError(
                        'collide_extract%s 失败 (cand/形状不符?)'
                        % ('' if aabbs is not None else '_local'))
                c_cmn, c_cmx, c_bmn, c_bmx, c_scn, c_rad, c_kind, \
                    c_cand = ex
                res_c = fastpath._collide_pairs_c(
                    c_cmn, c_cmx, c_cand, tin, tout,
                    c_bmn, c_bmx, c_scn, c_rad, c_kind, n)
                if res_c is None:
                    raise RuntimeError(
                        '_collide_pairs_c 容量拒绝 (ws_cap 语义回归?)')
                ai, bj = res_c
                return [(int(ai[k]), int(bj[k]))
                        for k in range(len(ai))]
        # ---- B1 退役: numpy 回退段已删; 默认路只走 C 路 (上面硬 return) ----
        # ★B5 退役 (2026-10-16): NO_SAP 逃生门 (B 路) 已删; 落到此处的只有
        #   A 路 (n_c > _PAIR_GEN_NUMPY_MAX 的内存兜底), 定义了 ai/bj.
        n_pairs = len(ai)
        # 压测实测线程池 map 的提交/轮询/GIL 开销 ~15ms/帧 >> 单次 numpy ~50µs).
        # 只有超大碰撞对 (几千物体) 分块丢线程池才有并发收益.
        if n_pairs < self._COLLISION_POOL_PAIRS or self._collision_pool is None:
            mask = PhysicsMixin._pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind)
        else:
            pool = self._collision_pool
            nw = pool._max_workers if pool is not None else 1
            chunks = np.array_split(np.arange(n_pairs), max(1, nw * 4))
            res = pool.map(
                lambda idx: PhysicsMixin._pair_overlap_vec(ai[idx], bj[idx],
                                                           bmn, bmx, scn, rad, kind),
                chunks)
            mask = np.concatenate(list(res))
        return [(int(ai[k]), int(bj[k])) for k in np.where(mask)[0]]
