# -*- coding: utf-8 -*-
"""
physics_bridge.py — B1: Culverin (Jolt) 物理桥 (零 GL, 可独立导入; 无库自动禁用)

角色 (设计文档 B1_物理换库设计.md §1-§3):
  - **混合式架构**: Jolt 只接管**刚体动力学** (R1 重力/速度/接触解算/摩擦滚动/
    角速度); 引擎几何碰撞管线 (脚本 API move_with_collision/get_collisions/
    collider_hit / 事件差分 / 同树不互撞 / 编辑-播放快照) **全部保留** ——
    本模块不改变任何契约语义, 只做 "模型 <-> Jolt 世界" 的每帧桥梁.
  - PhysicsWorldBridge: build/destroy/ensure_models/pre_step/step/post_step +
    R1 重力/策略 R 速度门控/R2 slop/R3 形状冻结/R4 欧拉转换器/树位分配.
  - 几何静态助手 (world_matrix/collider_bounds/get_collisions/move_with_collision/
    collider_hit...): 供 SceneDriver (Vk 播放器) 与测试复用 —— 公式与
    engine.GLEngine 对应方法**逐位一致** (P1 已对拍), 且零 GL.
  - 零 GL 约束: 不 import engine/pygame (只依赖 numpy + culverin try/except);
    对象模型按鸭子类型 (m.position/rotation/scale .x 或下标 + m.parent +
    m.mesh.vertices + m.collider + m.rigidbody), 引擎 GameObject 与驱动共用.

关键方案 (P2 实施, 硬性):
  - R1: 世界重力 = (0,0,0), 桥手动复刻 engine.update_physics 累加次序
        (use_gravity 才 v.y += gravity*dt; gravity 每帧由引擎实例传入
        getattr(engine,'gravity',-9.8))。use_gravity=False 天然精确。
  - 策略 R: 每帧写速度仅当 (a) 脚本改过 rb.velocity (脏检测 vs 上次写出值), 或
        (b) is_active(handle) 清醒中 (累加重力后写回); 睡眠体跳过写 (性能红利,
        Jolt 2.4µs/步场景成立)。写速度不会防睡 (P1-B-⑤ 已证)。
  - P1 必修项: post_step 对 is_active=False 的体**回读速度归 0** —— Jolt 入睡时
        存留残速 (每帧写的 -g*dt) 不对外暴露, 维持引擎 "碰就停 |v|→0" 契约
        (否则 first_person 的 abs(rb.velocity.y)<0.01 接地检测失效)。
  - R3: 建体取当帧 collider_bounds (box=世界 AABB 半长 + identity 旋转 → Jolt
        OBB 随体转更贴合; sphere=AABB 中心+最大半长); 缩放/旋转动画期间形状
        不重建 (级 1 已知差异)。
  - R4: 欧拉转换器桥上自带 (引擎行向量 Rx@Ry@Rz ⟷ culverin 列四元数 [x,y,z,w]),
        勿用 culverin euler_to_quat (约定不同, P1-B-③ 实测桥转换器与其逐位一致)。
  - 树位: 每根根树 1 位 category (mask=0xFFFFFFFF & ~bit); 全程显式传 (默认
        0xFFFF 是陷阱); >31 根轮转位+警告。⚠️ 收窄项: 表亲同树 (同根非祖先)
        不再互撞 (引擎 _related=仅祖先), 已列人工裁决清单。
  - 静态体被脚本/动画移动: pre_step 一次性升级 MOTION_STATIC→KINEMATIC
        (设计 §1.1#4: 让其能唤醒压着的动态体 + 被物理感知)。
"""
import math
import os
from collections import namedtuple as _namedtuple

import numpy as np
import physics_glue as _phys_glue

try:
    import culverin as cv
    _IMPORT_ERROR = None
except ImportError as _e:                       # 无库环境: enabled=False, 引擎自动 legacy
    cv = None
    _IMPORT_ERROR = _e

# 库可用标志 (引擎/驱动 import 本模块查询, 一次性)
cv_available = cv is not None

GRAVITY_Y = -9.8            # 引擎 _GRAVITY (桥 standalone 默认; 引擎会逐帧传实例重力)
ALL_MASK = 0xFFFFFFFF
DT_DEFAULT = 1.0 / 60.0
# Jolt 默认线性阻尼 (mLinearDamping=0.05): 桥无法关闭 (culverin 无 API) ->
# 预补偿抵消 (写 v*(1+DAMP*dt), step 阻尼后回到 v), 对齐 Unity Rigidbody.drag=0.
JOLT_LINEAR_DAMP = 0.05

# ---- B1 修复 (2026-08-30) ----
# P1 滚动摩擦: culverin 0.14.0 **无原生实现** (create_body 合法关键字里没有
# linear/angular_damping/rolling; _culverin_c.pyi 的 set_linear_damping/
# set_angular_damping 也被注释禁用) -> 桥内对 DYNAMIC 体实现指数衰减:
#   f = max(0, 1 - mu * rolling * K * dt),  ω 与水平线速度同乘 f
# (滚动阻力同时作用平移; vy 保留不动, 不影响下落/弹跳)。仅清醒 (is_active)
# 且 |ω| > ROLLING_ANG_EPS 才写回; 阈值以下停写 -> Jolt 自然睡眠 (睡眠红利保留)。
# mu = 物体自身摩擦系数 (动态体=rb.friction, 与用户"与 μ 相关"需求对应: 摩擦
# 越大滚筒停得越快), rolling = rolling_friction (0=关闭, 默认 0.1, 范围 0-3)。
# ROLLING_K 标定: 0.5m 半径球, μ=0.5, rolling=0.1, 地面平, 3m/s 起滚 ->
# 实测 ~2.6-3.2s 停止 (见 B1_P2_修复_a.txt 标定记录)。
ROLLING_K = 23.0
ROLLING_ANG_EPS = 0.06      # |ω| 低于该值停止衰减写回 (rad/s; Jolt 睡眠阈 0.3 内)
# P2 浮空修复: 建体后"激活保底"帧数 (60fps 下 1.5s)。新动态体若以睡眠态入世且
# 从未被脚本/碰撞碰过, 此前策略 R (仅清醒才累加重力) 永不给它重力 -> 永悬空。
# 保底 = 帧内仍睡眠时调用 activate + 当帧手加一次重力; 一旦该体曾被观察到
# 清醒过一次 (guard 清零) 便不再触碰 -> 落定后自然入眠 (active=0 红利保留)。
GRAVITY_GUARD_FRAMES = 90
# ---- B1 修复_b (2026-08-30 用户二轮实测) ----
# ① 无碰撞体动态体 = 自由落体/自由移动 (契约对齐 legacy 与 Unity: 刚体重力与
#    碰撞体无关 —— 原桥对 collider 禁用/None/shape='none' 的动态体**不建体**,
#    世界重力=0 + 不建体 => 永不受重力, 正是用户"碰撞器+重力=浮空"的实锤根因
#    (P2 落地说明 §4.7 '已知差异' 被用户命中)。修复 = Python 侧积分
#    (v.y += g·dt; p += v·dt, 无碰撞), 与 legacy update_physics '累加-移动' 语义
#    逐位一致 (legacy 对无碰撞体同样自由运动, 不做任何碰撞)。
# ② 滑动/滚动残速死带: 用户"有减速但仍有极轻微缓慢移动" = Jolt 库仑摩擦亚阈值
#    尾巴 (0.0x m/s 级, 可能漂数秒)。对清醒 DYNAMIC 体: **同时** |v_h|<V_STALL_EPS
#    且 |ω|<W_STALL_EPS 且 |vy|<VY_STOP_GATE (竖直下落/弹跳不碰) -> 水平速度+角速度
#    清 0。写零实测不防睡 (P1-B-⑤) -> Jolt 自然入睡, 睡后 post_step 速度归零兜底。
V_STALL_EPS = 0.03       # 水平残速死带 (m/s; 可标定区间 0.02-0.05, 取中值)
W_STALL_EPS = 0.3        # 角残速死带 (rad/s; 与 Jolt 睡眠角速阈同量级)
VY_STOP_GATE = 1.0       # |vy| 超过该值 = 明显竖直运动, 死带不判 (下落/弹跳零影响)

# culverin PhysicsWorld settings 合法键 (validate_settings; 其余键 TypeEror)
_ALLOWED_KEYS = ('gravity', 'penetration_slop', 'max_bodies', 'max_pairs',
                 'max_contact_constraints', 'temp_allocator_size',
                 'max_physics_jobs', 'max_physics_barriers', 'num_threads')

# 桥写回 body 用 (与引擎 Point3D 同构: .x/.y/.z + 可迭代; 引擎 setter 只解构/属性,
# 脚本只读 .x/.y/.z —— 鸭子类型, 引擎 GameObject 的 setter 会转成引擎自身 Point3D)
Point3D = _namedtuple('Point3D', ['x', 'y', 'z'])


# =============================================================================
# ========== 几何静态助手 (与 engine.GLEngine 公式逐位一致, 零 GL) ==========
# =============================================================================
# 供 SceneDriver (Vk 播放器) 与测试复用: move_with_collision/get_collisions/
# collider_hit/world_position 等。与 engine.py 的 2343-2669 段同源 (勿分叉公式)。

def _t3(v):
    """任意三维向量 (Vector3/Point3D/元组/列表) -> (float, float, float)."""
    if isinstance(v, (tuple, list)) and len(v) == 3:
        return float(v[0]), float(v[1]), float(v[2])
    x = getattr(v, 'x', None)
    if x is not None:
        return float(x), float(getattr(v, 'y')), float(getattr(v, 'z'))
    return float(v[0]), float(v[1]), float(v[2])


def is_ancestor(ancestor, m):
    """ancestor 是否为 m 的祖先 (沿父链向上) — 与 engine.is_ancestor 同语义."""
    cur = m
    while cur is not None:
        if cur is ancestor:
            return True
        cur = getattr(cur, 'parent', None)
    return False


def related(a, b):
    """a/b 是否有祖先/后代关系 (同一棵变换树)。同树物体间不互相碰撞 — 与
    engine._related 同语义 (仅祖先-后代, 不含表亲)."""
    return a is b or is_ancestor(a, b) or is_ancestor(b, a)


def _mesh_of(m):
    return getattr(m, 'mesh', None)


def model_vertices(m, cache=None):
    """模型网格顶点 (V,3) float64; 与 engine._homogeneous_vertices 同缓存策略
    (按 id(mesh) + 顶点列表身份缓存, 网格不可变)."""
    mesh = _mesh_of(m)
    if mesh is None or getattr(mesh, 'vertices', None) is None:
        return np.zeros((0, 3), dtype=np.float64)
    if cache is not None:
        ent = cache.get(('vh', id(mesh)))
        if ent is not None and ent[0] is mesh.vertices:
            return ent[1]
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    if cache is not None:
        if len(cache) > 2048:
            cache.clear()
        cache[('vh', id(mesh))] = (mesh.vertices, verts)
    return verts


def _local_matrix(m):
    """局部行主序 4x4: S @ R @ T (R = Rx@Ry@Rz, 与 engine.mat4 约定一致)."""
    s = _t3(m.scale)
    r = _t3(m.rotation)
    p = _t3(m.position)
    S = np.eye(4, dtype=np.float64)
    S[0, 0], S[1, 1], S[2, 2] = s
    cx, sx = math.cos(r[0]), math.sin(r[0])
    cy, sy = math.cos(r[1]), math.sin(r[1])
    cz, sz = math.cos(r[2]), math.sin(r[2])
    Rx = np.eye(4, dtype=np.float64)
    Rx[1, 1], Rx[1, 2] = cx, sx
    Rx[2, 1], Rx[2, 2] = -sx, cx
    Ry = np.eye(4, dtype=np.float64)
    Ry[0, 0], Ry[0, 2] = cy, -sy
    Ry[2, 0], Ry[2, 2] = sy, cy
    Rz = np.eye(4, dtype=np.float64)
    Rz[0, 0], Rz[0, 1] = cz, sz
    Rz[1, 0], Rz[1, 1] = -sz, cz
    T = np.eye(4, dtype=np.float64)
    T[3, :3] = p
    return S @ Rx @ Ry @ Rz @ T


def _local_matrices_batch(models):
    """批5 性能批 (2026-09-05): _local_matrix 的 SoA 批量版 — M 个物体一次
    向量化构建局部矩阵 (M,4,4), 与逐体 _local_matrix 逐位一致 (同公式同序:
    S @ Rx @ Ry @ Rz @ T, 各矩阵元素赋值顺序一致 → 浮点运算序一致).
    消每体 5 次 np.eye + 5 次小矩阵 matmul 的 Python/numpy 开销."""
    M = len(models)
    s = np.empty((M, 3), dtype=np.float64)
    r = np.empty((M, 3), dtype=np.float64)
    p = np.empty((M, 3), dtype=np.float64)
    for i, m in enumerate(models):
        # 内联抓取 (2026-09-07 重帧治理): _t3 调用 x3M 换直接属性链 —
        # Point3D/scale 恒三维, _t3 的 isinstance 分派是纯开销 (500 体 ~0.3ms)。
        # 数值逐位一致 (同字段同 float() 语义)。
        sc = m.scale
        s[i, 0] = sc[0]; s[i, 1] = sc[1]; s[i, 2] = sc[2]
        ro = m.rotation
        r[i, 0] = ro.x; r[i, 1] = ro.y; r[i, 2] = ro.z
        po = m.position
        p[i, 0] = po.x; p[i, 1] = po.y; p[i, 2] = po.z
    # pipeline.dll 原生 C 批量 (唯一路径; ★B2 退役: 删 numpy S@R@T 回退段)
    out = np.empty((M, 4, 4), dtype=np.float64)
    import pipeline_glue as _pg
    _pg.local_matrices(r, s, p, out)   # rc != 0 已由 glue 硬 raise
    return out


def model_world_matrix(m, cache=None):
    """模型世界矩阵 (行主序): local(S@R@T) @ 父世界矩阵 沿父链 — 与
    engine.model_world_matrix 同公式. cache: {('wm', id(m)): M} 帧内记忆化."""
    if cache is not None:
        c = cache.get(('wm', id(m)))
        if c is not None:
            return c
    M = _local_matrix(m)
    p = getattr(m, 'parent', None)
    if p is not None:
        M = M @ model_world_matrix(p, cache)
    if cache is not None:
        cache[('wm', id(m))] = M
    return M


def world_position_vec(m, cache=None):
    """物体中心世界坐标 (3,) — 与 engine.world_position 同."""
    return model_world_matrix(m, cache)[3, :3]


def world_rotation_3x3(m, cache=None):
    """去缩放的世界旋转 3x3 (行主序, = Rx@Ry@Rz 链式) — 与
    engine.world_rotation_matrix 旋转部分同."""
    M = model_world_matrix(m, cache)[:3, :3]
    rows = np.linalg.norm(M, axis=1)
    rows = np.where(rows < 1e-12, 1.0, rows)
    return M / rows[:, None]


def collider_bounds(m, cache=None):
    """世界空间碰撞体数据 (与 engine.collider_bounds 逐位一致):
    ('box', (mn, mx)) | ('sphere', (center, radius)).
    box = 整网格世界 AABB (含父链, 轴对齐); sphere = AABB 中心 + 最大半长
    (对球网格 = 真实半径, 比 AABB 更贴合)."""
    vh = model_vertices(m, cache)
    if len(vh) == 0:                       # 防御: 无网格 -> 按缩放的单位盒
        sc = _t3(m.scale)
        vh = (np.array([(sx, sy, sz) for sx in (-1, 1) for sy in (-1, 1)
                        for sz in (-1, 1)]) * np.array(sc))
    M = model_world_matrix(m, cache)
    wp = np.concatenate([vh, np.ones((len(vh), 1))], axis=1) @ M
    w3 = wp[:, :3]
    mn, mx = w3.min(axis=0), w3.max(axis=0)
    shape = getattr(getattr(m, 'collider', None), 'shape', 'box')
    if shape == 'sphere':
        c = (mn + mx) * 0.5
        r = max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) * 0.5
        return ('sphere', (c, r))
    return ('box', (mn, mx))


def pair_overlap(ba, bb):
    """两个 (shape, data) 碰撞体是否相交 — 与 engine._pair_overlap 逐位一致
    (严格 <: 恰好贴边不算碰撞, 静止物不会反复被推)."""
    sa, da = ba
    sb, db = bb
    if sa == 'box' and sb == 'box':
        (amn, amx), (bmn, bmx) = da, db
        return all(amn[i] < bmx[i] and bmn[i] < amx[i] for i in (0, 1, 2))
    if sa == 'sphere' and sb == 'sphere':
        (ca, ra), (cb, rb) = da, db
        dx, dy, dz = ca[0] - cb[0], ca[1] - cb[1], ca[2] - cb[2]
        return dx * dx + dy * dy + dz * dz < (ra + rb) ** 2
    # box-sphere: 球心到盒最近点距离 < 半径 (球在盒内也算相交)
    if sa == 'sphere':
        (sc, r), (bmn, bmx) = da, db
    else:
        (bmn, bmx), (sc, r) = da, db
    cx = max(bmn[0], min(sc[0], bmx[0]))
    cy = max(bmn[1], min(sc[1], bmx[1]))
    cz = max(bmn[2], min(sc[2], bmx[2]))
    dx, dy, dz = sc[0] - cx, sc[1] - cy, sc[2] - cz
    return dx * dx + dy * dy + dz * dz < r * r


def get_collisions(models, m, bounds=None):
    """碰撞查询: 返回当前与 m 碰撞的所有其他物体 (按 models 顺序) — 与
    engine.get_collisions 同语义 (跳过同树/禁用/none)."""
    col_m = getattr(m, 'collider', None)
    if col_m is None or not col_m.enabled or col_m.shape == 'none':
        return []
    if bounds is None:
        bounds = {}
    bm = None
    out = []
    for o in models:
        if o is m or related(m, o):
            continue
        col_o = getattr(o, 'collider', None)
        if col_o is None or not col_o.enabled or col_o.shape == 'none':
            continue
        bo = bounds.get(id(o))
        if bo is None:
            if bm is None:
                bm = collider_bounds(m, bounds)
            bo = collider_bounds(o, bounds)
            bounds[id(o)] = bo
        elif bm is None:
            bm = collider_bounds(m, bounds)
        if pair_overlap(bm, bo):
            out.append(o)
    return out


def collider_hit(a, b):
    """两物体是否碰撞 — 与 engine.collider_hit 同语义 (都启用且非 none 才判;
    同树物体不算)."""
    if related(a, b):
        return False
    ca, cb = getattr(a, 'collider', None), getattr(b, 'collider', None)
    if ca is None or cb is None:
        return False
    if not (ca.enabled and cb.enabled):
        return False
    if ca.shape == 'none' or cb.shape == 'none':
        return False
    return pair_overlap(collider_bounds(a), collider_bounds(b))


def push_out(a, b, bounds=None):
    """把 a 推出 b 的碰撞体 (仅已相交时调用) — 与 engine._push_out 逐位一致.
    bounds: b 的碰撞体缓存 (帧内静止复用; a 自身不缓存, 每次现算)."""
    ba = collider_bounds(a)
    if bounds is not None:
        bb = bounds.get(id(b))
        if bb is None:
            bb = collider_bounds(b)
            bounds[id(b)] = bb
    else:
        bb = collider_bounds(b)
    if ba[0] == 'box' and bb[0] == 'box':
        (amn, amx), (bmn, bmx) = ba[1], bb[1]
        best_axis = best_sign = best_push = None
        for i in (0, 1, 2):
            a0, a1 = amn[i], amx[i]
            b0, b1 = bmn[i], bmx[i]
            if a0 >= b1 or b0 >= a1:
                continue
            dist_right = b1 - a0
            dist_left = a1 - b0
            if dist_left < dist_right - 1e-9:
                sign, dist = -1.0, dist_left
            elif dist_right < dist_left - 1e-9:
                sign, dist = +1.0, dist_right
            else:
                sign = +1.0 if (a0 + a1) >= (b0 + b1) else -1.0
                dist = dist_right if sign > 0 else dist_left
            if best_push is None or dist < best_push:
                best_push, best_sign, best_axis = dist, sign, i
        if best_axis is not None:
            p = list(_t3(a.position))
            p[best_axis] += best_sign * (best_push + 1e-4)
            a.position = Point3D(*p)
        return
    if ba[0] == 'sphere' and bb[0] == 'sphere':
        (ca, ra), (cb, rb) = ba[1], bb[1]
        dx, dy, dz = ca[0] - cb[0], ca[1] - cb[1], ca[2] - cb[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
        need = ra + rb - dist + 1e-4
        u = (dx / dist, dy / dist, dz / dist)
        p = list(_t3(a.position))
        p[0] += u[0] * need
        p[1] += u[1] * need
        p[2] += u[2] * need
        a.position = Point3D(*p)
        return
    # 盒-球 (与 _pair_overlap 判定一致; 大地面平面不会被当球推出)
    if ba[0] == 'sphere':
        sc, r = ba[1]
        bmn, bmx = bb[1]
        a_is_sphere = True
    else:
        bmn, bmx = ba[1]
        sc, r = bb[1]
        a_is_sphere = False
    nx = min(max(sc[0], bmn[0]), bmx[0])
    ny = min(max(sc[1], bmn[1]), bmx[1])
    nz = min(max(sc[2], bmn[2]), bmx[2])
    dx, dy, dz = sc[0] - nx, sc[1] - ny, sc[2] - nz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1e-9:
        cc = ((bmn[0] + bmx[0]) / 2, (bmn[1] + bmx[1]) / 2, (bmn[2] + bmx[2]) / 2)
        vx, vy, vz = sc[0] - cc[0], sc[1] - cc[1], sc[2] - cc[2]
        vl = math.sqrt(vx * vx + vy * vy + vz * vz) or 1e-6
        u = (vx / vl, vy / vl, vz / vl)
        need = r + 1e-4
    else:
        need = r - dist + 1e-4
        u = (dx / dist, dy / dist, dz / dist)
        if not a_is_sphere:
            u = (-u[0], -u[1], -u[2])
    p = list(_t3(a.position))
    p[0] += u[0] * need
    p[1] += u[1] * need
    p[2] += u[2] * need
    a.position = Point3D(*p)


def resolve_collisions(models, m, max_iter=4, bounds=None):
    """把 m 推干净: 迭代推离所有相交物体 — 与 engine.resolve_collisions 同."""
    hit = False
    for _ in range(max_iter):
        coll = get_collisions(models, m, bounds=bounds)
        if not coll:
            break
        hit = True
        for o in coll:
            push_out(m, o, bounds=bounds)
    return hit


def move_with_collision(models, m, dx, dy, dz, bounds=None):
    """带碰撞的位移 (M28 响应) — 与 engine.move_with_collision 逐位一致 (子步拆
    分防穿透薄面; 每步推出所有相交). 返回 True = 被挡住/发生碰撞."""
    shape, data = collider_bounds(m)
    if shape == 'sphere':
        step = max(data[1], 0.02)
    else:
        mn, mx = data
        step = max(min(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) * 0.5, 0.02)
    n = max(1, math.ceil(max(abs(dx), abs(dy), abs(dz)) / step))
    n = min(n, 5000)
    if bounds is None:
        bounds = {}
    hit = False
    for _ in range(n):
        p = _t3(m.position)
        m.position = Point3D(p[0] + dx / n, p[1] + dy / n, p[2] + dz / n)
        if resolve_collisions(models, m, bounds=bounds):
            hit = True
    bounds.pop(id(m), None)
    return hit


# =============================================================================
# ========== R4 欧拉 <-> 四元数转换器 (numpy 批量; 引擎行向量 Rx@Ry@Rz) ==========
# =============================================================================
# P1 已实证: 与 culverin MathService.euler_to_quat 逐位一致 (max 3.4e-08);
# 勿用 culverin euler 助手 (公开模块函数坏 + 约定不同, 见 P1-B-③).

def engine_mat3_from_euler(euler_rad):
    """(n,3) 弧度欧拉 -> (n,3,3) 引擎行主序 Rx@Ry@Rz (matlib.mat4_rotation 等价)."""
    e = np.asarray(euler_rad, dtype=np.float64).reshape(-1, 3)
    rx, ry, rz = e[:, 0], e[:, 1], e[:, 2]
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    n = len(rx)
    Rx = np.zeros((n, 3, 3)); Ry = np.zeros((n, 3, 3)); Rz_ = np.zeros((n, 3, 3))
    Rx[:, 0, 0] = 1.0
    Rx[:, 1, 1] = cx; Rx[:, 1, 2] = sx
    Rx[:, 2, 1] = -sx; Rx[:, 2, 2] = cx
    Ry[:, 0, 0] = cy; Ry[:, 0, 2] = -sy
    Ry[:, 1, 1] = 1.0
    Ry[:, 2, 0] = sy; Ry[:, 2, 2] = cy
    Rz_[:, 0, 0] = cz; Rz_[:, 0, 1] = sz
    Rz_[:, 1, 0] = -sz; Rz_[:, 1, 1] = cz
    Rz_[:, 2, 2] = 1.0
    return Rx @ Ry @ Rz_


def quat_from_mat3(M_row):
    """(n,3,3) 引擎行主序旋转 -> (n,4) [x,y,z,w] (culverin 列约定, Shepperd 分解).
    ★ 旋转矩阵本来就正交, 不要做整矩阵归一 (Frobenius 范数 = sqrt(3), 会错移对角量)."""
    m = np.asarray(M_row, dtype=np.float64)
    m = np.transpose(m, (0, 2, 1))
    tr = m[:, 0, 0] + m[:, 1, 1] + m[:, 2, 2]
    n = len(tr)
    q = np.empty((n, 4), dtype=np.float64)
    q[:, 3] = 1.0
    c0 = np.where(tr > 0.0)[0]
    if len(c0):
        s = np.sqrt(tr[c0] + 1.0) * 2.0
        q[c0, 3] = 0.25 * s
        q[c0, 0] = (m[c0, 2, 1] - m[c0, 1, 2]) / s
        q[c0, 1] = (m[c0, 0, 2] - m[c0, 2, 0]) / s
        q[c0, 2] = (m[c0, 1, 0] - m[c0, 0, 1]) / s
    idx = np.where(tr <= 0.0)[0]
    sel = idx[(m[idx, 0, 0] > m[idx, 1, 1]) & (m[idx, 0, 0] > m[idx, 2, 2])]
    if len(sel):
        s = np.sqrt(1.0 + m[sel, 0, 0] - m[sel, 1, 1] - m[sel, 2, 2]) * 2.0
        q[sel, 3] = (m[sel, 2, 1] - m[sel, 1, 2]) / s
        q[sel, 0] = 0.25 * s
        q[sel, 1] = (m[sel, 0, 1] + m[sel, 1, 0]) / s
        q[sel, 2] = (m[sel, 0, 2] + m[sel, 2, 0]) / s
    sel2 = idx[(m[idx, 0, 0] <= m[idx, 1, 1]) & (m[idx, 1, 1] > m[idx, 2, 2])]
    if len(sel2):
        s = np.sqrt(1.0 + m[sel2, 1, 1] - m[sel2, 0, 0] - m[sel2, 2, 2]) * 2.0
        q[sel2, 3] = (m[sel2, 0, 2] - m[sel2, 2, 0]) / s
        q[sel2, 0] = (m[sel2, 0, 1] + m[sel2, 1, 0]) / s
        q[sel2, 1] = 0.25 * s
        q[sel2, 2] = (m[sel2, 1, 2] + m[sel2, 2, 1]) / s
    sel3 = idx[(m[idx, 0, 0] <= m[idx, 1, 1]) & (m[idx, 1, 1] <= m[idx, 2, 2])]
    if len(sel3):
        s = np.sqrt(1.0 + m[sel3, 2, 2] - m[sel3, 0, 0] - m[sel3, 1, 1]) * 2.0
        q[sel3, 3] = (m[sel3, 1, 0] - m[sel3, 0, 1]) / s
        q[sel3, 0] = (m[sel3, 0, 2] + m[sel3, 2, 0]) / s
        q[sel3, 1] = (m[sel3, 1, 2] + m[sel3, 2, 1]) / s
        q[sel3, 2] = 0.25 * s
    return q


def engine_mat3_from_quat(quat_xyzw):
    """(n,4) [x,y,z,w] -> (n,3,3) 引擎行主序旋转 (列矩阵转置)."""
    q = np.asarray(quat_xyzw, dtype=np.float64).reshape(-1, 4)
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    norm = np.sqrt(x * x + y * y + z * z + w * w)
    norm = np.where(norm < 1e-12, 1.0, norm)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    n = len(x)
    C = np.zeros((n, 3, 3))
    C[:, 0, 0] = 1 - 2 * (y * y + z * z)
    C[:, 0, 1] = 2 * (x * y - z * w)
    C[:, 0, 2] = 2 * (x * z + y * w)
    C[:, 1, 0] = 2 * (x * y + z * w)
    C[:, 1, 1] = 1 - 2 * (x * x + z * z)
    C[:, 1, 2] = 2 * (y * z - x * w)
    C[:, 2, 0] = 2 * (x * z - y * w)
    C[:, 2, 1] = 2 * (y * z + x * w)
    C[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return C.transpose(0, 2, 1)


def quat_to_euler_batch(quat_xyzw):
    """(n,4) [x,y,z,w] -> 引擎弧度欧拉 (n,3) (matlib.decompose_euler 反解;
    万向锁 |cos beta|<1e-9: gamma=0)."""
    M = engine_mat3_from_quat(quat_xyzw)
    beta = np.arcsin(np.clip(-M[:, 0, 2], -1.0, 1.0))
    cb = np.cos(beta)
    alpha = np.where(np.abs(cb) < 1e-9,
                     np.arctan2(M[:, 1, 0], M[:, 1, 1]),
                     np.arctan2(M[:, 1, 2], M[:, 2, 2]))
    gamma = np.where(np.abs(cb) < 1e-9, 0.0, np.arctan2(M[:, 0, 1], M[:, 0, 0]))
    return np.stack([alpha, beta, gamma], axis=-1)


def euler_to_quat_batch(euler_rad):
    """引擎弧度欧拉 (n,3) -> culverin 列四元数 (n,4) [x,y,z,w]."""
    return quat_from_mat3(engine_mat3_from_euler(euler_rad))


# =============================================================================
# ========== PhysicsWorldBridge (R1/R2/R3/R4 + 树位 + 策略 R) ==========
# =============================================================================

class PhysicsWorldBridge:
    """引擎/驱动模型 <-> culverin 世界桥.

    R1: 世界 gravity=(0,0,0); 桥手动复刻引擎累加次序 (use_gravity 才
        v.y += gravity*dt; gravity 每帧由引擎经 pre_step(dt, gravity) 传入).
    策略 R: 每帧写速度仅当 (a) 脚本改过 rb.velocity (脏检测) 或 (b) is_active
        清醒 (累加重力后写回); 睡眠体跳过写 (性能红利, 2.4µs/步场景成立).
    R2: settings['penetration_slop'] 默认 0.005 (P1 实测无效但无害 — 静止穿透
        由撞击速度决定, 0-2cm 在 0.03 容差内).
    R3: 建体取当帧 collider_bounds (box=世界 AABB 半长+identity 旋转; sphere=
        AABB 中心+最大半长); 旋转/缩放动画不重建形状 (级 1 已知差异).
    R4: 欧拉转换器桥上自带 (勿用 culverin euler 助手).
    树位: 每根根树 1 位 category (mask=ALL_MASK & ~bit); 全程显式传; >31 树
        轮转位+警告 (收窄项=表亲同树不再互撞, 已列人工裁决).
    静态体被移动: pre_step 升级 MOTION_STATIC->MOTION_KINEMATIC (一次性,
        设计 §1.1#4: 唤醒压着的动态体 + 被物理感知).

    线程: 桥自身不建线程; Jolt 步进内部线程池 (settings['num_threads']).
    """

    def __init__(self, settings=None):
        self.enabled = cv is not None
        self._w = None
        self._entries = []            # [{'model','handle','id','cat','mask','motion','signature'}]
        self._next_id = 0             # 单调 body 登记号 (user_data; 移除后不复用)
        self._tree_bit = {}           # id(root) -> bit
        self._warned_tree_rot = 0
        self._last_sync = {}          # id(m) -> [pos3, rot3, vel3] (float 元组)
        self._dmb_cache = None        # 2026-09-07: 跨子步脏检测缓存 (见 _dirty_mask_batch)
        self._tmp_cache = {}
        self._last_dt = DT_DEFAULT    # P1 滚动摩擦用 (step 里记录; post_step 兜底)
        self._free = []               # 修复_b①: 无碰撞体动态体模型 (Python 侧积分)
        self.gravity = GRAVITY_Y      # 默认; 引擎每帧 pre_step 传实例重力
        self.settings = {
            'gravity': (0.0, 0.0, 0.0),          # R1: 世界无重力, 桥手动累加
            'penetration_slop': 0.005,
            'max_bodies': 10240,
            'num_threads': max(1, min((os.cpu_count() or 2) - 2, 2048)),
        }
        if settings:
            for k in _ALLOWED_KEYS:
                if k in settings:
                    self.settings[k] = settings[k]

    # ---------- 公开统计 ----------
    @property
    def body_count(self):
        return self._w.count if self._w is not None else 0

    @property
    def active_count(self):
        """当前清醒 (非睡眠) 动态体数 (诊断/测试用)."""
        if self._w is None or cv is None:
            return 0
        n = 0
        for e in self._entries:
            if e['motion'] == cv.MOTION_DYNAMIC:
                try:
                    if self._w.is_active(e['handle']):
                        n += 1
                except RuntimeError:
                    n += 1
        return n

    # ---------- 世界生命周期 ----------
    def create_world(self):
        if not self.enabled:
            return None
        w = cv.PhysicsWorld(settings=dict(self.settings))
        w.set_gravity(*self.settings['gravity'])
        return w

    def rebuild(self):
        """settings 变更后重建世界 (帧外调用; 引擎一般在 create 前定死 settings)."""
        self._w = self.create_world()
        self._entries = []
        self._next_id = 0
        self._last_sync.clear()
        self._dmb_cache = None           # 结构重建: 脏检测缓存一并失效
        self._tree_bit.clear()

    def destroy(self):
        """销毁世界 (播放结束/退出清理). 幂等. ensure_models 在 destroy 后禁用."""
        self._w = None
        self._entries = []
        self._last_sync.clear()
        self._dmb_cache = None

    # ---------- 树位分配 ----------
    def _root_of(self, m):
        r = m
        seen = 0
        while getattr(r, 'parent', None) is not None and seen < 1024:
            r = r.parent
            seen += 1
        return r

    def _tree_bit_for(self, m):
        """每根根树 1 位 category; >31 轮转位+每场警告 (设计 §1.1 #9)."""
        root = self._root_of(m)
        key = id(root)
        bit = self._tree_bit.get(key)
        if bit is None:
            t = len(self._tree_bit)
            if t > 31:
                bit = 1 << (t % 32)
                if self._warned_tree_rot < 3:
                    print("  [物理] WARN 树数>31: 第 %d 根树轮转位=%s"
                          " (与其它树共用位 -> 其间不互撞)" % (t + 1, bin(bit)))
                    self._warned_tree_rot += 1
            else:
                bit = 1 << t
            self._tree_bit[key] = bit
        return bit

    # ---------- 形态签名 (ensure_models 差量) ----------
    def _entry_signature(self, m):
        col = getattr(m, 'collider', None)
        rb = getattr(m, 'rigidbody', None)
        # 2026-08-30: 数值字段用 float() 而非 bool() 参与签名 —— 原 bool()
        # 区分不了 0.5 vs 0.2 的摩擦改动 (播放期调摩擦不会重建体)。另加
        # B1-P1 rolling_friction 字段 (摩擦/弹性/滚动摩擦三件套)。
        return (
            getattr(col, 'shape', 'box'),
            getattr(col, 'enabled', True), float(getattr(col, 'friction', 0.5)),
            float(getattr(col, 'restitution', 0.0)),
            float(getattr(col, 'rolling_friction', 0.1)),
            None if rb is None else (bool(rb.is_kinematic), float(rb.mass),
                                     bool(rb.use_gravity),
                                     float(getattr(rb, 'friction', 0.5)),
                                     float(getattr(rb, 'restitution', 0.0)),
                                     float(getattr(rb, 'rolling_friction', 0.1))),
        )

    # ---------- 建体 (R3 形状冻结 + 树位 + 全显式 category/mask + 摩擦/弹性) ----------
    @staticmethod
    def _is_dynamic_free(m):
        """修复_b①: 该模型是否属于"无碰撞体动态体" (桥不建体, Python 侧自由积分).
        与 _build_one 的建体条件 (rb 非 None + 非 kinematic + 碰撞体无效) 互补:
        碰撞体无效 = None / enabled=False / shape='none' —— 此时 Jolt 无可建形状,
        但刚体重力/速度语义仍须生效 (legacy/Unity 均如此)。"""
        rb = getattr(m, 'rigidbody', None)
        if rb is None or getattr(rb, 'is_kinematic', False):
            return False
        col = getattr(m, 'collider', None)
        if col is None or not getattr(col, 'enabled', True) \
                or getattr(col, 'shape', 'none') == 'none':
            return True
        return False

    def _build_one(self, m, motion_override=None):
        if not (self.enabled and cv is not None):
            return
        col = getattr(m, 'collider', None)
        if col is None or not getattr(col, 'enabled', True) \
                or getattr(col, 'shape', 'none') == 'none':
            return                                     # 设计 §1.1#7: 不建物理体
        if self._w is None:
            self._w = self.create_world()
        w = self._w
        cache = self._tmp_cache
        cache.clear()
        shape, data = collider_bounds(m, cache)
        rb = getattr(m, 'rigidbody', None)
        if rb is None:
            motion, mass = cv.MOTION_STATIC, 1.0
        elif getattr(rb, 'is_kinematic', False):
            motion, mass = cv.MOTION_KINEMATIC, 1.0
        else:
            motion, mass = cv.MOTION_DYNAMIC, float(rb.mass) if float(rb.mass) > 0 else 1.0
        if motion_override is not None:                # 静态体升级 KINEMATIC 用
            motion = motion_override
        bit = self._tree_bit_for(m)
        cat, mask = bit, ALL_MASK & ~bit
        if shape == 'box':
            mn, mx = data
            size = ((mx[0] - mn[0]) * 0.5, (mx[1] - mn[1]) * 0.5, (mx[2] - mn[2]) * 0.5)
            c = ((mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, (mn[2] + mx[2]) * 0.5)
            shp = cv.SHAPE_BOX
        else:
            c, r = data
            size = float(r)
            shp = cv.SHAPE_SPHERE
        # 摩擦/弹性/滚动摩擦 (用户新需求): 动态体用刚体组件值, 静态/运动学用
        # 碰撞体组件值; roll = B1-P1 rolling_friction (0=关闭, 默认 0.1)
        if rb is None:
            fric = float(getattr(col, 'friction', 0.5))
            rest = float(getattr(col, 'restitution', 0.0))
            roll = float(getattr(col, 'rolling_friction', 0.1))
        else:
            fric = float(getattr(rb, 'friction', 0.5))
            rest = float(getattr(rb, 'restitution', 0.0))
            roll = float(getattr(rb, 'rolling_friction', 0.1))
        bid = self._next_id
        self._next_id += 1
        h = w.create_body(pos=(float(c[0]), float(c[1]), float(c[2])),
                          rot=(0.0, 0.0, 0.0, 1.0), size=size, shape=shp,
                          motion=motion, mass=mass, category=cat, mask=mask,
                          user_data=bid, friction=fric, restitution=rest)
        if motion == cv.MOTION_DYNAMIC:
            # 关键: 模型当前速度在创建时就要进 Jolt —— 若建模前脚本已设
            # velocity (脚本先写速再被 ensure_models 建体), 只靠 pre_step 的
            # 脏检测 (v == sync) 就永远不会写, 新体将静止. 现在直接推入.
            v0 = _t3(getattr(rb, 'velocity', (0.0, 0.0, 0.0)))
            if v0 != (0.0, 0.0, 0.0):
                w.set_linear_velocity(h, v0[0], v0[1], v0[2])
            # P2 浮空修复 (2026-08-30 用户实测): immediate activate —— culverin
            # 文档写明对 PENDING_CREATE 兼容 (排队到下次 step 生效), 保证新体
            # 第一帧就参与模拟; 否则世界重力=0 + 建时速度=0 的新体若以睡眠态
            # 入世, 策略 R (仅清醒才累加重力) 永不写重力 -> 物体永悬空.
            # 仅对 use_gravity 体激活 (use_gravity=False 的悬浮体由脚本/碰撞接管,
            # 没必要醒着耗 CPU; 其零速自然入眠不受此次改动影响).
            if getattr(rb, 'use_gravity', False):
                try:
                    w.activate(h)
                except Exception:
                    pass
        ent = {'model': m, 'handle': h, 'id': bid, 'cat': cat, 'mask': mask,
               'motion': motion, 'signature': self._entry_signature(m),
               'roll': roll, 'mu': fric, 'guard_left': 0}
        if motion == cv.MOTION_DYNAMIC:
            ent['guard_left'] = GRAVITY_GUARD_FRAMES     # P2 激活保底帧数上限
        self._entries.append(ent)
        p, r, v = _t3(m.position), _t3(m.rotation), _t3(getattr(rb, 'velocity', (0, 0, 0)))
        self._last_sync[id(m)] = [p, r, v]

    def build(self, models):
        """从模型列表建体 (播放开始). 结束后 step(0) 冲刷查询缓冲
        (culverin: 建体后查询须先冲刷, 否则 RuntimeError; "0 步不模拟")."""
        for m in models:
            self._build_one(m)
        self._refresh_free(models)                 # 修复_b①: 同步自由积分名单
        if self._w is not None and self._entries:
            self._w.step(0.0)

    def _refresh_free(self, models):
        """修复_b①: 无碰撞体动态体名单 (build/ensure_models 每帧/每次刷新)."""
        self._free = [m for m in models if self._is_dynamic_free(m)]

    def ensure_models(self, models):
        """差量: 新增 -> create; 移除 -> destroy_body; collider/rb 形态变 -> 重建.
        返回 (created, destroyed, rebuilt). 桥已 destroy (播放结束) 时幂等 no-op."""
        if not self.enabled or cv is None or self._w is None:
            self._refresh_free(models)             # 修复_b①: 名单仍须与本帧一致
            return 0, 0, 0
        self._refresh_free(models)                 # 修复_b①: 播放中开/关碰撞器即时切换
        keep = {id(m) for m in models}
        created = destroyed = rebuilt = 0
        alive = []
        for ent in self._entries:
            if id(ent['model']) not in keep:
                self._w.destroy_body(ent['handle'])
                destroyed += 1
            else:
                alive.append(ent)
        if destroyed:
            self._entries = alive
            self._w.step(0.0)
        # 项A (2026-09-02 多物体批): O(n²)→O(n) —— 旧实现每模型 next() 线性扫
        # _entries 全表 (500 体 = ~12.5 万次比较/帧, 实测 ensure 7.28ms). 查找表
        # 每调用从 _entries 重建一次 (O(n)), 循环内 O(1) 命中; rebuilt 分支
        # destroy+remove 后同步从表摘除 (表内其余条目仍有效).
        by_model = {id(e['model']): e for e in self._entries}
        for m in models:
            ent = by_model.get(id(m))
            if ent is None:
                self._build_one(m)
                created += 1
            else:
                sig = self._entry_signature(m)
                if sig != ent['signature']:
                    self._w.destroy_body(ent['handle'])
                    self._entries.remove(ent)
                    self._last_sync.pop(id(m), None)
                    by_model.pop(id(m), None)
                    self._build_one(m)
                    rebuilt += 1
        if created or rebuilt:
            self._w.step(0.0)
        return created, destroyed, rebuilt

    # ---------- 每帧三段 (顺序 per 设计 §3.1) ----------
    def _sync_of(self, m):
        sync = self._last_sync.get(id(m))
        if sync is None:
            sync = self._last_sync[id(m)] = [_t3(m.position), _t3(m.rotation),
                                             _t3(getattr(m, 'rigidbody', None).velocity)
                                             if getattr(m, 'rigidbody', None) is not None
                                             else (0.0, 0.0, 0.0)]
        return sync

    def _model_dirty(self, m):
        sync = self._sync_of(m)
        return _t3(m.position) != sync[0] or _t3(m.rotation) != sync[1]

    def _dirty_mask_batch(self, entries):
        """批5 性能批 (2026-09-05): pre_step 脏检测批量化 — 逐体 _model_dirty
        (501 次 sync 查找+_t3×2 元组比较, ~9.8ms/步) → SoA 平面一次抓 +
        numpy 广播比较。dirty 集合与逐体版**逐位一致** (同一比较语义:
        pos/rot 任一元组不等 = 脏; 只改实现不改语义, R1 红线不动)。
        返回 {id(m): bool} (含祖先传播后结果) — 与旧 dict 推导同构。

        ★2026-09-07 重帧治理 (播放态相机卡顿排查): 跨子步缓存 — 多子步逻辑帧
        (TPS20=3 子步) 中子步间唯一写者是本桥自身 (pre_step 推位姿并更新 sync /
        post_step 回读并对齐 sync; 脚本只在逻辑帧首跑, 动画并发写会改 rows 平面)。
        缓存命中判据 = ids 序 + 位姿平面 + sync 平面 + 父链 id 拓扑 四者逐位相等
        — 任何写者 (脚本/回读/动画/升级重建/挂父) 都会改其中之一 → miss → 现算,
        不依赖时序推理。
        传播 (父脏→子脏) 结果随基础 dirty 一同缓存; parents 拓扑也入键
        (reparent preserve_world=True 不改世界位姿 → rows/sync 不变, 拓扑
        变化必须 miss, 防陈旧传播闭包)。
        返回缓存 dict 的拷贝 (调用方可写, 缓存本体不可变)。
        实测 TPS20 混合500: 子步 3 命中, 每逻辑帧省 ~2.6ms 抓取+比较+传播。"""
        ids = []
        rows = []
        syncs = []
        parents = []
        for e in entries:
            m = e['model']
            sync = self._sync_of(m)
            ids.append(id(m))
            p = m.position
            r = m.rotation
            rows.append((p.x, p.y, p.z, r.x, r.y, r.z))
            syncs.append(sync)
            parents.append(id(getattr(m, 'parent', None)))
        n = len(ids)
        if n == 0:
            return {}
        ids_t = tuple(ids)
        cur = np.array(rows, dtype=np.float64).reshape(n, 2, 3)
        old = np.array([(s[0][0], s[0][1], s[0][2],
                         s[1][0], s[1][1], s[1][2]) for s in syncs],
                       dtype=np.float64).reshape(n, 2, 3)
        # 缓存命中: 位姿平面 + sync 平面 + 父链 id 拓扑与上次完全一致
        # → 基础 dirty 与传播闭包同上次
        cache = getattr(self, '_dmb_cache', None)
        if (cache is not None and cache[0] == n and cache[1] == ids_t
                and cache[5] == tuple(parents)
                and bool((cache[2] == cur).all()) and bool((cache[3] == old).all())):
            return dict(cache[4])
        id2idx = {idd: i for i, idd in enumerate(ids)}
        pidx = [id2idx.get(pidd, -1) for pidd in parents]

        # pipeline.dll 原生 C 脏检测与拓扑传播 (唯一路径; ★B2 退役: 删 numpy 回退)
        import pipeline_glue as _pg
        out_mask = np.zeros(n, dtype=np.uint8)
        cur_flat = cur.reshape(n, 6)
        old_flat = old.reshape(n, 6)
        pidx_arr = np.array(pidx, dtype=np.int64)
        _pg.dirty_mask(cur_flat, old_flat, pidx_arr, out_mask)  # rc != 0 硬 raise
        dirty = {ids[i]: bool(out_mask[i]) for i in range(n)}
        self._dmb_cache = (n, ids_t, cur, old, dirty, tuple(parents))
        return dict(dirty)

    def _active_ok(self, h):
        try:
            return self._w.is_active(h)
        except RuntimeError:
            return True

    def pre_step(self, dt, gravity=None):
        """① 脏检测 -> set_position/set_rotation (世界位姿, R4);
        ② 速度策略 R (脚本改过 或 清醒才写); ③ R1 重力累加 (仅清醒且 use_gravity);
        ④ 修复_b①: 自由积分名单 (无碰撞体动态体, 桥外 Python 侧)."""
        if not (self.enabled and cv is not None and (self._entries or self._free)):
            return
        w = self._w
        cache = self._tmp_cache
        cache.clear()
        g = GRAVITY_Y if gravity is None else float(gravity)
        # 修复_b①: 无碰撞体动态体 —— Python 侧自由积分 (contract 对齐 legacy/Unity:
        # 刚体重力/速度不依赖碰撞体; legacy 对无碰撞体同样 '累加-移动', 无任何碰撞).
        # 顺序在 Jolt 三段之外的模型侧: v.y += g·dt; p += v·dt (竖直下落无限深也照走
        # legacy 语义; use_gravity=False 的脚本速度体同样自由移动).
        for m in self._free:
            rb_f = getattr(m, 'rigidbody', None)
            if rb_f is None or getattr(rb_f, 'is_kinematic', False):
                continue
            v = _t3(rb_f.velocity)
            if getattr(rb_f, 'use_gravity', False):
                av = v[1] + g * dt
                rb_f.velocity = Point3D(v[0], av, v[2])
                v = (v[0], av, v[2])
            if v != (0.0, 0.0, 0.0):
                p = _t3(m.position)
                m.position = Point3D(p[0] + v[0] * dt, p[1] + v[1] * dt,
                                     p[2] + v[2] * dt)
        dirty = self._dirty_mask_batch(self._entries)      # 批5: 批量脏检测 (逐位同旧;
                                    # ★09-07 祖先传播已移入本方法 + 跨子步缓存, 语义逐位)
        # 祖先链脏传播 — 已移入 _dirty_mask_batch (2026-09-07 重帧治理,
        # 与基础 dirty 同缓存; 本处旧循环删除, 行为逐位一致)
        for ent in list(self._entries):                # 快照遍历: 升级分支会 remove/append
            m = ent['model']
            if not dirty[id(m)]:
                continue
            if ent['motion'] == cv.MOTION_STATIC:
                # 设计 §1.1#4: 静态体被脚本/动画移动 -> 一次性升级 KINEMATIC
                # (让其能唤醒压着的动态体 + 被物理感知). ★culverin 0.14.0 的
                # set_motion_type(STATIC->KINEMATIC) 在下次 step() 直接原生崩溃
                # (0xC0000005, 实测复现/交叉验证), 改用 **销毁重建** 为 KINEMATIC.
                try:
                    w.destroy_body(ent['handle'])
                except Exception:
                    pass
                self._entries.remove(ent)
                self._last_sync.pop(id(m), None)
                self._build_one(m, motion_override=cv.MOTION_KINEMATIC)
                if not self._entries or self._entries[-1]['model'] is not m:
                    continue                     # 防御: 重建未发生 -> 跳过本帧
                ent = self._entries[-1]
            if m.parent is None:
                continue     # 批5: 根物体 set_position 交给下方批量段 (一次算好)
            pos = world_position_vec(m, cache)
            rotm = world_rotation_3x3(m, cache)
            q = quat_from_mat3(rotm[np.newaxis, :, :])[0]
            w.set_position(ent['handle'], float(pos[0]), float(pos[1]), float(pos[2]))
            w.set_rotation(ent['handle'], float(q[0]), float(q[1]), float(q[2]), float(q[3]))
            sync = self._last_sync[id(m)]
            sync[0] = _t3(m.position)
            sync[1] = _t3(m.rotation)
        # 批5 性能批 (2026-09-05): 根 dirty 体的 set_position 批量段 — SoA 一次
        # 构建全部局部矩阵 + 批量行归一 + 批量四元数, 再逐体 C 调用 (数值与
        # 逐体路径逐位一致: 同公式同序, R4 对拍守恒). 有父体仍在上方逐体段
        # (父链 world 矩阵依赖逐体缓存, 量少). 无 dirty 根体时零开销跳过.
        batch = [e for e in self._entries
                 if dirty.get(id(e['model']), False)
                 and e['model'].parent is None]
        if batch:
            bm = [e['model'] for e in batch]
            lms = _local_matrices_batch(bm)
            rotms = lms[:, :3, :].copy()
            # world_rotation_3x3 同款行归一化 (批量)
            rows = np.linalg.norm(rotms, axis=2)
            rows = np.where(rows < 1e-12, 1.0, rows)
            rotms = rotms / rows[:, :, None]
            qs = quat_from_mat3(rotms)
            for k, e in enumerate(batch):
                m = e['model']
                w.set_position(e['handle'], float(lms[k, 3, 0]),
                               float(lms[k, 3, 1]), float(lms[k, 3, 2]))
                w.set_rotation(e['handle'], float(qs[k, 0]), float(qs[k, 1]),
                               float(qs[k, 2]), float(qs[k, 3]))
                sync = self._last_sync[id(m)]
                sync[0] = _t3(m.position)
                sync[1] = _t3(m.rotation)
        # 速度策略 R + 重力 R1 (仅动态体)
        # Jolt 阻尼预补偿 (对齐 Unity Rigidbody.drag=0): Jolt 每步内建线性阻尼
        # (v *= 1/(1+DAMP*dt), culverin 无法关闭)。写 Jolt 前把模型速度预乘
        # _c=(1+DAMP*dt), Jolt 阻尼后恰好回到模型速度 → 位形积分 (用补偿速度) 与
        # 速度回读均无净衰减。★须每子步写: 只在速度变化时写会漏掉 Jolt 内自由
        # 衰减 (实测水平匀速体 4s 内 5.0→4.09, 即 exp(-DAMP·t))。
        _c = 1.0 + JOLT_LINEAR_DAMP * dt
        for ent in self._entries:
            if ent['motion'] != cv.MOTION_DYNAMIC:
                continue
            m = ent['model']
            rb = getattr(m, 'rigidbody', None)
            if rb is None:
                continue
            ent['guard_left'] = max(0, ent.get('guard_left', 0) - 1)  # P2 保底帧计数
            sync = self._last_sync[id(m)]
            v = _t3(rb.velocity)
            vel_dirty = (v != sync[2])
            if vel_dirty:
                sync[2] = v
                ent['guard_left'] = 0            # 脚本已接管: 保底使命完成
                w.set_linear_velocity(ent['handle'], v[0] * _c, v[1] * _c,
                                      v[2] * _c)   # 脚本改速 (唤醒)
                continue
            if getattr(rb, 'use_gravity', False):
                if self._active_ok(ent['handle']):
                    ent['guard_left'] = 0        # ≥1 次被观测到清醒: 保底完成
                    av = v[1] + g * dt                                # R1 手动累加
                    rb.velocity = Point3D(v[0], av, v[2])
                    sync[2] = (v[0], av, v[2])
                    w.set_linear_velocity(ent['handle'], v[0] * _c, av * _c,
                                          v[2] * _c)
                    continue
                if ent.get('guard_left', 0) > 0:
                    # P2 激活保底: 建体后 GRAVITY_GUARD_FRAMES 帧内, 新体若仍
                    # 睡眠且从未被脚本/碰撞碰过 (|v|≈0) -> 唤醒排队 + 当帧重力
                    # (策略 R 清醒才累积 -> 不保底则永悬空)。保底窗口 (90 帧 =
                    # 1.5s) 每帧重试 (activate 排队到下次 step, 与创建同帧兼容);
                    # 窗口结束或曾清醒后永不触碰 -> 落定后自然入眠, 睡眠红利
                    # (active=0) 不受影响。
                    if abs(v[0]) < 1e-3 and abs(v[1]) < 1e-3 and abs(v[2]) < 1e-3:
                        try:
                            w.activate(ent['handle'])
                        except RuntimeError:
                            pass
                        av = v[1] + g * dt
                        rb.velocity = Point3D(v[0], av, v[2])
                        sync[2] = (v[0], av, v[2])
                        w.set_linear_velocity(ent['handle'], v[0] * _c, av * _c,
                                              v[2] * _c)
                        continue
                # 睡眠体: 跳过写 (睡眠红利; 写速度实测不防睡, P1-B-⑤)
                continue
            # 无重力且脚本未改速: 清醒有速体每子步补写 (抵消 Jolt 内阻尼衰减)。
            # 写速度实测不防睡 (P1-B-⑤), 零速体不写 (让 Jolt 自然入眠)。
            if v[0] or v[1] or v[2]:
                w.set_linear_velocity(ent['handle'], v[0] * _c, v[1] * _c,
                                      v[2] * _c)

    def step(self, dt):
        """一次 C 步进 (GIL 释放; Jolt 内部线程池). 记录 dt 供 post_step
        (P1 滚动摩擦衰减用; 引擎调用序列 pre→step→post 无 dt 透传)."""
        self._last_dt = float(dt)
        if self.enabled and cv is not None and self._w is not None and self._entries:
            self._w.step(dt)

    def post_step(self, dt=None):
        """④ 批式回读 (positions f64 / rotations f32 / velocities f32) -> 写回模型.
        按 user_data 登记号映射行 (Jolt 体序任意); 睡眠体速度归 0 (P1 必修).
        ⑤ B1-P1 滚动摩擦: 清醒 DYNAMIC 体 ω/水平线速度指数衰减 (模块常量注释)."""
        if not (self.enabled and cv is not None and self._entries):
            return
        # 项E1 (2026-09-02 多物体批): dyn 判空早退前移 —— 场景无 DYNAMIC 体时
        # (纯静态/KINEMATIC: 装饰场景/编辑器播放静态堆) 连 Jolt 四数组读取也
        # 不必做 (读取 + argsort + 映射全为动态回读服务). dyn 列表构建 O(entries)
        # 挪到读取之前, 有动态体时顺序不变 (语义无差).
        if not any(e['motion'] == cv.MOTION_DYNAMIC for e in self._entries):
            return
        if dt is None:
            dt = self._last_dt
        w = self._w
        cnt = w.count
        if cnt == 0:
            return
        ud = np.asarray(w.user_data).reshape(-1).astype(np.int64)
        pos = np.asarray(w.positions).reshape(-1, 4)
        rotsq = np.asarray(w.rotations).reshape(-1, 4)
        vel = np.asarray(w.velocities).reshape(-1, 4)
        cache = self._tmp_cache
        cache.clear()
        # 映射: user_data=登记号 -> 世界行下标 (一次 argsort, C 级)
        order = np.argsort(ud)
        ids = ud[order]
        row_full = np.full(max(self._next_id, 1), -1, dtype=np.int64)
        okm = ids < len(row_full)
        row_full[ids[okm]] = order[okm]
        dyn = [(i, e) for i, e in enumerate(self._entries)
               if e['motion'] == cv.MOTION_DYNAMIC]
        if not dyn:
            return
        r_all = np.array([row_full[e['id']] for _, e in dyn], dtype=np.int64)
        valid = r_all >= 0
        r_sub = r_all[valid]
        wp = pos[r_sub, :3].astype(np.float64)
        wq = rotsq[r_sub].astype(np.float64)
        wv = vel[r_sub, :3].astype(np.float64)
        lpq = quat_to_euler_batch(wq)                     # 批量反解世界欧拉
        ws = np.array([self._active_ok(e['handle']) for _, e in dyn])[valid]
        wv = np.where(ws[..., None], wv, 0.0)             # 睡眠体: 速度归 0 (P1 必修)
        # P1 滚动摩擦: 角速度批量读取 (f32, 行序同 velocities) -> 与 wv 同映射
        try:
            angw = np.asarray(w.angular_velocities).reshape(-1, 4)[r_sub, :3] \
                .astype(np.float64)
        except Exception:
            angw = np.zeros_like(wv)                      # 读数失败 -> 无衰减 (安全)
        # B优化 (2026-10-14): 摩擦+残速整段下沉 C (loom_physics_pre_step, gravity_y=0
        # -> 纯摩擦+残速)。逐位一致已验证 (bench_frict_c: maxdiff=0, 23x)。含 Jolt
        # 写回 (仅变化行)。
        # ★B4 退役 (2026-10-16): 删 LOOM_NO_BATCH_PHYS 门 + physics.dll 不可用回退段
        # (逐体路径); physics.dll 唯一路径, rc != 0 硬 raise (官方件不兜底)。
        _n = len(dyn)
        _mu = np.array([float(e.get('mu', 0.5)) for _, e in dyn], dtype=np.float64)
        _roll = np.array([float(e.get('roll', 0.0)) for _, e in dyn], dtype=np.float64)
        _isd = np.ones(_n, dtype=np.uint8)
        _ug = np.ones(_n, dtype=np.uint8)
        _wsu = ws.astype(np.uint8)
        _lv = np.ascontiguousarray(wv, dtype=np.float64).copy()
        _av = np.ascontiguousarray(angw, dtype=np.float64).copy()
        _rc = _phys_glue.pre_step(_lv, _av, _isd, _ug, _wsu,
                                  _mu, _roll, 0.0, dt)
        if _rc != 0:
            raise RuntimeError('physics.dll pre_step 失败 rc=%d' % _rc)
        _chg = np.where((_lv != wv).any(axis=1)
                        | (_av != angw).any(axis=1))[0]
        for _k in _chg:
            _ent = dyn[_k][1]
            try:
                w.set_angular_velocity(_ent['handle'],
                                       float(_av[_k, 0]),
                                       float(_av[_k, 1]),
                                       float(_av[_k, 2]))
                w.set_linear_velocity(_ent['handle'],
                                      float(_lv[_k, 0]),
                                      float(_lv[_k, 1]),
                                      float(_lv[_k, 2]))
            except (RuntimeError, ValueError):
                continue
            wv[_k, :] = _lv[_k, :]
            angw[_k, :] = _av[_k, :]
        for k, ((_, ent), ok) in enumerate(zip(dyn, valid)):
            if not ok:
                continue
            m = ent['model']
            rb = getattr(m, 'rigidbody', None)
            p = getattr(m, 'parent', None)
            fr = (float(wv[k, 0]), float(wv[k, 1]), float(wv[k, 2]))
            if p is None:
                lp = (float(wp[k, 0]), float(wp[k, 1]), float(wp[k, 2]))
                lrot = lpq[k]
            else:                                          # 有父: 世界 -> 局部 (逐体)
                pw = model_world_matrix(p, cache)
                inv = np.linalg.inv(pw[:3, :3])
                lpv = (wp[k] - pw[3, :3]) @ inv
                lp = (float(lpv[0]), float(lpv[1]), float(lpv[2]))
                Rw = engine_mat3_from_quat(wq[k][np.newaxis, :])[0]
                Rl = Rw @ np.linalg.inv(world_rotation_3x3(p, cache))
                lrot = np.array([math.atan2(Rl[1, 2], Rl[2, 2]),
                                 math.asin(max(-1.0, min(1.0, -Rl[0, 2]))),
                                 math.atan2(Rl[0, 1], Rl[0, 0])])
            m.position = Point3D(lp[0], lp[1], lp[2])
            m.rotation = Point3D(float(lrot[0]), float(lrot[1]), float(lrot[2]))
            if rb is not None:
                rb.velocity = Point3D(fr[0], fr[1], fr[2])   # 真实解算后速度 (睡眠=0)
            sync = self._last_sync.get(id(m))
            if sync is None:
                sync = self._last_sync[id(m)] = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                                 (0.0, 0.0, 0.0)]
            sync[0] = m.position.x, m.position.y, m.position.z
            sync[1] = m.rotation.x, m.rotation.y, m.rotation.z
            sync[2] = fr

    def frame(self, dt, gravity=None):
        """完整一帧 (pre + step + post) — 测试/驱动同用."""
        self.pre_step(dt, gravity)
        self.step(dt)
        self.post_step()

