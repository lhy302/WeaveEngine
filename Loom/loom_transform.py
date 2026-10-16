# -*- coding: utf-8 -*-
"""loom_transform.py — GLEngine 变换层次子系统 (模型选择 / 世界矩阵 / 父链层次 / 包围盒)。

从 engine.py 抽出 (作为 TransformMixin 供 GLEngine 继承)。注意: 原 engine.py 中
本块被"逻辑帧线程"方法群 (_start/_stop_logic_thread / _logic_loop / _logic_snapshot)
打断为两段, 本文件把两段合并 (逻辑线程域留待独立 Mixin)。

抽出方法:
  [段A 模型选择] select_next_model / get_current_model
  [段A 变换入口] model_world_matrix / _transform_snapshot
  [段B 批量世界矩阵] compute_world_matrices / _consume_xform_gen
  [段B 渲染矩阵] _render_parent_depth / compute_render_matrices / _batch_rotations
  [段B 层次访问器] parent_world_matrix / world_position / world_rotation_matrix /
                   world_scale / world_to_local / is_ancestor / set_parent /
                   collect_subtree / get_bounding_box / _homogeneous_vertices

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self.models / self.current_model_index / self._struct_gen / self._bump_struct
  self._soa_snap / self._soa_snap_gen / self._soa_last_keys / self._soa_double_bufs / self._soa_buf_slot
  self._fw_cache / self._pd_cache / self._bb_cache / self._prep_sig / self._frame_world / self._render_world
  self._sched_pool / self._interp / self._interp_mode / self._logic_steps / self._prof_t0 / self._prof_add
  self.is_playing / self._last_xform_gen
"""
import os

import numpy as np

from matlib import (mat4_scale, mat4_rotation, mat4_translation, decompose_euler)
from fastpath import depths as _fp_depths
from loom_types import Point3D
from loom_components import TransformComponent
from interp_state import InterpState


class TransformMixin:

    # ================ 模型管理 ================
    def select_next_model(self):
        """选择下一个模型 (安全加固 2026-08-20: 空场景不崩)"""
        if not self.models:
            return
        self.current_model_index = (self.current_model_index + 1) % len(self.models)

    def get_current_model(self):
        """获取当前选中的模型 (空场景/索引越界返回 None, 安全加固 2026-08-20)"""
        if not self.models:
            return None
        if self.current_model_index >= len(self.models):
            self.current_model_index = 0
        return self.models[self.current_model_index]

    # ================ 变换层次 (M14) ================
    def model_world_matrix(self, m):
        """物体世界模型矩阵 (行向量): local(S@R@T) @ 父世界矩阵 沿父链合成"""
        M = (mat4_scale(np, m.scale[0], m.scale[1], m.scale[2])
             @ mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
             @ mat4_translation(np, m.position.x, m.position.y, m.position.z))
        if m.parent is not None:
            M = M @ self.model_world_matrix(m.parent)
        return M

    def _transform_snapshot(self, models):
        """组3层1 (2026-08-30) SoA 变换平面快照: 一次抓取全部物体 position/rotation/
        scale 成三个 (N,3) float64 平面, 返回 (stamp, pos, rot, scl) ——
        compute_world_matrices 的 9 次"属性链列取"收拢到此, 之后列取走 numpy 切片.
        ★AUDIT-29 优化: 连续 SoA 预分配双缓冲 (Double Buffer), 消灭动态帧
        每帧构造中间 tuple 列表与临时 numpy 数组的 GC 抖动, 保证纯连续内存复用."""
        n = len(models)
        stamp = (id(models), getattr(self, '_struct_gen', 0), n)
        gen = TransformComponent._xform_gen
        snap = getattr(self, '_soa_snap', None)
        if (snap is not None and snap[0] == stamp
                and getattr(self, '_soa_snap_gen', None) == gen):
            self._soa_last_keys = snap[1]
            return snap[0], snap[2], snap[3], snap[4]

        cur = tuple((m.position, m.rotation, m.scale) for m in models)
        keys = tuple((id(p), id(r), id(s)) for p, r, s in cur)
        self._soa_last_keys = keys
        if snap is not None and snap[0] == stamp and snap[1] == keys:
            self._soa_snap_gen = gen
            return snap[0], snap[2], snap[3], snap[4]

        if n:
            bufs = getattr(self, '_soa_double_bufs', None)
            cur_cap = bufs[0][0].shape[0] if bufs is not None else 0
            if bufs is None or cur_cap < n:
                cap = max(64, n, cur_cap * 2)
                bufs = self._soa_double_bufs = [
                    (np.empty((cap, 3), dtype=np.float64),
                     np.empty((cap, 3), dtype=np.float64),
                     np.empty((cap, 3), dtype=np.float64)),
                    (np.empty((cap, 3), dtype=np.float64),
                     np.empty((cap, 3), dtype=np.float64),
                     np.empty((cap, 3), dtype=np.float64))
                ]
                self._soa_buf_slot = 0
            slot = 1 - getattr(self, '_soa_buf_slot', 0)
            self._soa_buf_slot = slot
            b_pos, b_rot, b_scl = bufs[slot]

            for i in range(n):
                p, r, s = cur[i]
                b_pos[i, 0] = p.x; b_pos[i, 1] = p.y; b_pos[i, 2] = p.z
                b_rot[i, 0] = r.x; b_rot[i, 1] = r.y; b_rot[i, 2] = r.z
                b_scl[i, 0] = s[0]; b_scl[i, 1] = s[1]; b_scl[i, 2] = s[2]

            pos = b_pos[:n]
            rot = b_rot[:n]
            scl = b_scl[:n]
        else:
            pos = np.empty((0, 3), dtype=np.float64)
            rot = np.empty((0, 3), dtype=np.float64)
            scl = np.empty((0, 3), dtype=np.float64)

        self._soa_snap = (stamp, keys, pos, rot, scl, cur)
        self._soa_snap_gen = gen
        return stamp, pos, rot, scl

    def compute_world_matrices(self, models):
        """批量算全部模型世界矩阵 (2026-08-14 多核优化).

        一次性 numpy 批量 (局部 S@R@T 全向量化 + 沿父链按层级每层一次批量 matmul),
        与逐模型 model_world_matrix 数值一致. 返回 (N,4,4) float64, 顺序与 models 对齐.

        组6件4 (2026-09-02) 静止缓存: 变换对象 id 集合 (_transform_snapshot 的 keys,
        按 _soa_snap 同款 id 钉住语义) + 结构 stamp + 父链 parent 数组全与上帧一致
        ⟹ 返回**缓存矩阵对象本体** (不拷贝). 失效面按构造穷尽: Point3D/tuple 不可
        变, 改值必换对象 ⟹ id 变 ⟹ keys 失配; 结构变更走 _struct_gen; 列表替换走
        id(models); 父链挂父走 _bump_struct (进 stamp). 不枚举写者 (脚本/物理/动画/
        undo 全覆盖). ★返回对象跨帧复用, 消费方禁原地改 (已核对: _frame_world 无
        原地写消费者; 外来 models 参数 (测试桩) 每次传不同对象, id(models) 兜住)."""
        n = len(models)
        if n == 0:
            return np.empty((0, 4, 4), dtype=np.float64)
        # 父链索引 + 层级深度: ★M3-P3 复用 _render_parent_depth 缓存 ——
        # 失效面 = (id(models), _struct_gen, n); GameObject.parent 是 property,
        # setter 对所有活引擎实例调 _bump_struct(), 全库无 .transform.parent 直写
        # 旁路 (已 grep 核实) ⟹ 挂父必进 stamp。原每渲染帧重建 id2i 字典 +
        # Python 循环 + _fp_depths ≈ 0.19 ms/帧 (n=501)。
        parent, depth = self._render_parent_depth(models, n)
        # 组6件4: 静止命中判定 —— keys (变换对象 id 三件套) + 结构 stamp.
        # ★M3-P3: parent 数组逐位比较随缓存落地而冗余 (stamp 已含 _struct_gen),
        # 保留 shape 断言作廉价的防御性检查。
        _, pos, rot, scl = self._transform_snapshot(models)
        fw_cache = getattr(self, '_fw_cache', None)
        keys = getattr(self, '_soa_last_keys', None)
        if fw_cache is not None and keys is not None:
            hit_stamp, hit_keys, hit_parent, hit_fw = fw_cache
            if (hit_stamp == (id(models), getattr(self, '_struct_gen', 0), n)
                    and hit_keys == keys
                    and hit_parent.shape == parent.shape):
                return hit_fw
        # 组3层1: 深度 DP 循环 -> fastpath.depths (Numba可选, 降级纯Python同源;
        # 语义逐位同: 沿 parent 爬根, d<n 防环截断, int() 转换当下标)
        # ---- pipeline.dll 世界矩阵路径 (C, 无 GIL) —— B2 后唯一路径 ----
        # 局部 S@R@T + 按 depth 升序父链合成整段在 DLL 完成。数值口径: 局部段
        # 逐元素精确, 世界矩阵为乘法链 → 全局缩放误差 ≤ depth×1e-15 (实测
        # n=501 链长 12 = 7.4e-16, 深链 199: 1.1e-15); 对拍 pipeline_world_check。
        # ★B2 退役 (2026-10-16): 删 LOOM_NO_PIPELINE 门 + numpy 回退 + _sched_wm_local
        # 死代码 (pipeline 官方件唯一路径; 见 docs/design/逃生门退役设计.md §6)。
        import pipeline_glue as _pg
        _wm = _pg.world_matrices(rot, scl, pos, parent, depth)
        # 组6件4: 入缓存 (stamp + keys + parent + 矩阵本体; keys 已在 _soa_snap
        # 钉住对象本体, id 不可能复用)
        self._fw_cache = ((id(models), getattr(self, '_struct_gen', 0), n),
                          keys, parent, _wm)
        return _wm

    def _consume_xform_gen(self):
        """编辑态插值失同步修复 (2026-09-06): TransformComponent._xform_gen
        变化 = 有物体被直接改位 (编辑器 gizmo/检查器/命令) — 插值快照还停在
        旧位 (prev==curr 恒成立, static_frame 误判静止), 渲染矩阵必须对齐:
        _interp.align() (prev=curr=重抓现值) + _render_world 失效重算。
        返回 True = 本帧有对齐发生 (观测/测试用)。
        ★仅编辑态消费 (2026-09-06 编译版 9FPS 回归修正): 播放态物理/脚本
        每逻辑帧本来就走 setter bump gen — 若播放态也消费, 每帧 align +
        _frame_world/_prep_sig 全失效 → AABB 行级缓存 id(fw) 全 miss
        (编译版 aabbs 0.4→26ms, 9FPS)。播放态同步由逻辑帧 advance 翻页
        天然保证 (R3), 编辑态没有逻辑帧才需要本机制。"""
        if getattr(self, 'is_playing', False):
            return False
        gen = TransformComponent._xform_gen
        last = getattr(self, '_last_xform_gen', None)
        if last is None:
            self._last_xform_gen = gen      # 首帧锚定 (建引擎前的写入不追溯)
            return False
        if gen == last:
            return False
        self._last_xform_gen = gen
        it = getattr(self, '_interp', None)
        if it is not None:
            it.align()
        self._render_world = None
        # prep 缓存一并失效 (AABB/光源 VP 挂着旧位形)
        self._prep_sig = None
        self._frame_world = None
        return True

    def _render_parent_depth(self, models, n):
        """★M3-P1: 渲染帧父链索引 + 层级深度 (结构不变则复用上帧结果).
        失效面与 compute_world_matrices 的 _fw_cache 同源: id(models) / _struct_gen / n
        (挂父走 _bump_struct → 进 _struct_gen, 故复用安全)。原每渲染帧重建
        id2i 字典 + Python 循环 + _fp_depths, 实测 0.190 ms/帧 (n=501)。"""
        stamp = (id(models), getattr(self, '_struct_gen', 0), n)
        c = getattr(self, '_pd_cache', None)
        if c is not None and c[0] == stamp:
            return c[1], c[2]
        id2i = {id(m): i for i, m in enumerate(models)}
        parent = np.full(n, -1, dtype=np.int64)
        for i, m in enumerate(models):
            if m.parent is not None:
                parent[i] = id2i.get(id(m.parent), -1)
        depth = _fp_depths(parent)
        self._pd_cache = (stamp, parent, depth)
        return parent, depth

    def compute_render_matrices(self, models):
        """分离批2 (2026-09-05): 插值版世界矩阵 (渲染专用).
        与 compute_world_matrices 同数学 (S@R@T 沿父链批量), 区别仅在
        输入平面 = InterpState.render_pose(alpha) 插值平面 (不回写
        GameObject, R3: 逻辑状态/碰撞/阴影共享的 _frame_world 不受影响).
        分离未开/无快照 → 等价调 compute_world_matrices (逃生门归一).
        方案二 (2026-09-05): 设置键 'interp_mode' = 'extrapolate' 时外推
        (a'=1+alpha 封顶 1.5); 物理落点帧 (本渲染帧跑过逻辑步, steps>0)
        自动回退插值 — 防碰撞时刻画面超前现实 (调研 §六方案二).
        ★不入 _fw_cache (缓存语义=逻辑位姿, 混入会破件4 失效协议);
        每渲染帧重算 (500 物体 ~1-2ms, 渲染帧预算内)."""
        it = getattr(self, '_interp', None)
        if it is None:
            return self.compute_world_matrices(models)
        # 外推资格: 设置开 + 本渲染帧没跑逻辑步 (落点帧回退, 防物理落点超前)
        mode = InterpState.INTERP_LERP
        if (str(getattr(self, '_interp_mode', 'interpolate')) == 'extrapolate'
                and not getattr(self, '_logic_steps', 0)):
            mode = InterpState.INTERP_EXTRAP
        n = len(models)
        _t = self._prof_t0()
        parent, depth = self._render_parent_depth(models, n)
        self._prof_add('mt_interp_parent', _t)
        # ★M3-N6 (2026-09-09): 插值平面 → 世界矩阵**整段**一次 C 调用
        #   (中间 pos/rot/scl 不出 C)。★B2 退役 (2026-10-16): 删
        #   LOOM_NO_PIPELINE / LOOM_NO_INTERP_WORLD_DLL 门; 有新物体 → 落下方。
        _a = it.alpha
        if mode == InterpState.INTERP_EXTRAP:
            _a = min(1.0 + _a, InterpState._EXTRAP_CAP)
        _t = self._prof_t0()
        _w = it.render_world(models, parent, depth,
                             int(depth.max()) if n else 0, _a)
        self._prof_add('mt_interp_world_dll', _t)
        if _w is not None:
            return _w
        _t = self._prof_t0()
        if os.environ.get('LOOM_PROFILE_POSE') == '1':
            # ★M3 诊断: 仅 LOOM_PROFILE_POSE=1 时注入计时钩子 —— 实测钩子本身
            #   会让 interp 段虚高 (0.53 → 1.08 ms/帧), 故与 LOOM_PROFILE 分离,
            #   不污染权威分段口径。
            it._prof = (self._prof_t0, self._prof_add)
        pos, rot, scl = it.render_pose(it.alpha, models, mode=mode)
        self._prof_add('mt_interp_pose', _t)
        if pos is None:
            return self.compute_world_matrices(models)
        _t = self._prof_t0()
        parent, depth = self._render_parent_depth(models, n)
        self._prof_add('mt_interp_parent', _t)
        # ★M3-A 首个剥离点 (2026-09-09): 局部 S@R@T + 按 depth 升序父链合成整段
        #   改走 pipeline.dll (C, 无 GIL) —— 与 compute_world_matrices 同一 C 入口,
        #   数学与数值口径完全一致 (pipeline_world_check 7/7, ≤ depth×1e-15)。
        # ★B2 退役 (2026-10-16): 删 LOOM_NO_INTERP_DLL 门 + numpy S@R@T 回退 +
        #   LOOM_VERIFY_INTERP 对拍块 (pipeline 官方件唯一路径)。
        import pipeline_glue as _pg
        _t = self._prof_t0()
        _wm = _pg.world_matrices(rot, scl, pos, parent, depth)
        self._prof_add('mt_interp_wm_call', _t)
        return _wm

    @staticmethod
    def _batch_rotations(models, rot=None):
        """批量旋转矩阵 (与 mat4_rotation 逐元素一致: Rx @ Ry @ Rz 行主序).
        组3层1: rot 可选 (N,3) f64 平面 (compute_world_matrices 传 _transform_snapshot
        的 rot 切片, 免 3 次属性链列取); 不传走旧列取 (防御: 其他调用点/测试桩)."""
        n = len(models)
        if rot is not None:
            rx, ry, rz = rot[:, 0], rot[:, 1], rot[:, 2]
        else:
            rx = np.array([m.rotation.x for m in models], dtype=np.float64)
            ry = np.array([m.rotation.y for m in models], dtype=np.float64)
            rz = np.array([m.rotation.z for m in models], dtype=np.float64)
        cx, sx = np.cos(rx), np.sin(rx)
        cy, sy = np.cos(ry), np.sin(ry)
        cz, sz = np.cos(rz), np.sin(rz)
        Rx = np.zeros((n, 4, 4), dtype=np.float64)
        Rx[:, 0, 0] = 1.0
        Rx[:, 1, 1] = cx; Rx[:, 1, 2] = sx
        Rx[:, 2, 1] = -sx; Rx[:, 2, 2] = cx
        Rx[:, 3, 3] = 1.0
        Ry = np.zeros((n, 4, 4), dtype=np.float64)
        Ry[:, 0, 0] = cy; Ry[:, 0, 2] = -sy
        Ry[:, 1, 1] = 1.0
        Ry[:, 2, 0] = sy; Ry[:, 2, 2] = cy
        Ry[:, 3, 3] = 1.0
        Rz = np.zeros((n, 4, 4), dtype=np.float64)
        Rz[:, 0, 0] = cz; Rz[:, 0, 1] = sz
        Rz[:, 1, 0] = -sz; Rz[:, 1, 1] = cz
        Rz[:, 2, 2] = 1.0; Rz[:, 3, 3] = 1.0
        return Rx @ Ry @ Rz

    def parent_world_matrix(self, m):
        """父物体的世界矩阵 (根=单位阵), 用于局部<->世界换算"""
        if m.parent is None:
            return np.eye(4, dtype=np.float64)
        return self.model_world_matrix(m.parent)

    def world_position(self, m):
        """物体中心的世界坐标 (父链合成)"""
        p = np.array([m.position.x, m.position.y, m.position.z, 1.0])
        if m.parent is not None:
            p = p @ self.model_world_matrix(m.parent)
        return Point3D(float(p[0]), float(p[1]), float(p[2]))

    def world_rotation_matrix(self, m):
        """物体旋转部分的世界矩阵 (忽略缩放, 供 gizmo 旋转换算)"""
        R = mat4_rotation(np, m.rotation.x, m.rotation.y, m.rotation.z)
        if m.parent is not None:
            R = R @ self.world_rotation_matrix(m.parent)
        return R

    def world_scale(self, m):
        """物体世界缩放 (沿父链各局部缩放分量相乘, 忽略父旋转; 与引擎缩放处理一致)"""
        s = Point3D(m.scale[0], m.scale[1], m.scale[2])
        cur = m.parent
        while cur is not None:
            s = Point3D(s.x * cur.scale[0], s.y * cur.scale[1], s.z * cur.scale[2])
            cur = cur.parent
        return s

    def world_to_local(self, m, p):
        """世界点 -> 该物体父空间的局部坐标 (行向量: local = world @ inv(parentWorldM))"""
        pw = np.array([p[0], p[1], p[2], 1.0])
        loc = pw @ np.linalg.inv(self.parent_world_matrix(m))
        return Point3D(float(loc[0] / loc[3]), float(loc[1] / loc[3]), float(loc[2] / loc[3]))

    def is_ancestor(self, ancestor, m):
        """ancestor 是否为 m 的祖先 (沿父链向上找)"""
        cur = m
        while cur is not None:
            if cur is ancestor:
                return True
            cur = cur.parent
        return False

    def set_parent(self, child, new_parent, preserve_world=True):
        """把 child 挂到 new_parent 下 (None=根). 拒绝设置自身或设为子孙 (防环).

        preserve_world=True (默认, Unity 挂父语义): 换父后按新父空间重新换算 child
        的局部位置/旋转/缩放, 使 child (及其整棵子树) 的**世界位置/旋转/缩放不变**——
        挂父/脱父那一下物体不会跳。位置用 world_to_local, 旋转 R_local = R_world @
        inv(R_parent), 缩放分量相除; 旋转矩阵用 decompose_euler 还原欧拉角。
        preserve_world=False: 仅改父指针, 局部值原样保留 (调用方已按父空间备好局部值,
        如复制命令/播放退出精确还原; 场景加载不走此方法, 直接 m.parent= 赋值).
        """
        if child is new_parent:
            return
        if new_parent is not None and self.is_ancestor(child, new_parent):
            return
        if child.parent is new_parent:
            return
        # 记录换父前世界变换 (旧父链)
        if preserve_world:
            wp = self.world_position(child)
            wr = self.world_rotation_matrix(child)
            ws = self.world_scale(child)
        # 换父 (children 列表重建)
        if child.parent is not None:
            if child in child.parent.children:
                child.parent.children.remove(child)
        child.parent = new_parent
        if new_parent is not None:
            new_parent.children.append(child)
        self._bump_struct()                    # 组3: 挂父变更失效 (ancestry+SoA)
        # 按新父空间换算局部变换, 保持世界位置/旋转/缩放
        if preserve_world:
            loc = self.world_to_local(child, wp)
            child.position = loc
            Rp = self.world_rotation_matrix(new_parent) if new_parent is not None \
                else np.eye(4, dtype=np.float64)
            Rl = wr @ np.linalg.inv(Rp)
            a, b, g = decompose_euler(Rl)
            child.rotation = Point3D(a, b, g)
            ps = self.world_scale(new_parent) if new_parent is not None else Point3D(1, 1, 1)
            child.scale = Point3D(ws.x / ps.x, ws.y / ps.y, ws.z / ps.z)

    def collect_subtree(self, model):
        """收集 model 及其全部子孙 (DFS, 删除/序列化/Prefab 用)"""
        out = [model]
        for c in list(model.children):
            out.extend(self.collect_subtree(c))
        return out

    def get_bounding_box(self, model, M=None):
        """获取模型的轴对齐包围盒 (AABB), 用世界矩阵变换 (含父链 S@R@T).
        M 可选: 传入当帧批量矩阵避免重算 (多核优化).
        顶点列表->齐次数组结果按 id(mesh) 缓存 (网格创建后不可变, 高面数球一次转换省
        每帧/每包围盒调用重复 asarray 开销; 2026-08-15 8 核均摊压测发现的瓶颈)."""
        M = M if M is not None else self.model_world_matrix(model)
        vh = self._homogeneous_vertices(model.mesh)
        # 只算需要的 3 列, 转置成 (3,V) 连续后沿连续轴归约 (微基准: axis=0 归约慢 4 倍,
        # 高面数球每帧 51+ 次包围盒时差 ~6ms/帧, 压测发现的瓶颈)
        w3t = np.ascontiguousarray((vh @ M[:, :3]).T)       # (3,V) 连续
        mn, mx = w3t.min(axis=1), w3t.max(axis=1)
        return (Point3D(float(mn[0]), float(mn[1]), float(mn[2])),
                Point3D(float(mx[0]), float(mx[1]), float(mx[2])))

    def _homogeneous_vertices(self, mesh):
        """网格顶点 -> 齐次 (V,4) float64 数组, 按 id(mesh) 缓存 (网格不可变).
        校验 vertices 列表身份, 防外部替换列表后用过期缓存.
        _bb_cache 惰性建 (测试桩用 __new__ 不跑 __init__)."""
        cache = getattr(self, '_bb_cache', None)
        if cache is None:
            cache = self._bb_cache = {}
        key = id(mesh)
        ent = cache.get(key)
        if ent is not None and ent[0] is mesh.vertices:
            return ent[1]
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        vh = np.concatenate([verts, np.ones((verts.shape[0], 1))], axis=1)
        if len(cache) > 2048:                   # 防资产频繁增删时无限膨胀
            cache.clear()
        cache[key] = (mesh.vertices, vh)
        return vh
