# -*- coding: utf-8 -*-
"""loom_collision.py — 碰撞配对 / 事件派发的**共享实现**（两端同一份）。

背景（B7-26 / 属 B7-20 门面收敛第一块）：
  GL 的碰撞事件链原本整段长在 {BT}PhysicsMixin{BT} 上（配对走 SAP + C 内核，派发走 mixin 方法），
  VK 的 {BT}SceneDriver{BT} 一个都没有 —— 于是脚本的 {BT}on_collision_*{BT} / {BT}on_trigger_*{BT} 在 VK 下永不触发。
  把「配对 / 判重 / 派发 / 回调」抽成本模块的纯函数后：
    · GL 侧保持自己的 SAP + C 内核配对（性能路径不变），只把**派发**改为调用本模块；
    · VK 侧用本模块的 {BT}pairs(){BT}（朴素 O(n²) + AABB 早退）生成配对，再用同一份 {BT}dispatch(){BT} 派发。

一致性承诺：
  {BT}pairs(){BT} 与 GL 的 {BT}_collision_pairs_parallel(){BT} **必须产出同一集合**（门：
  {BT}tests/test_vk_logic_frame_parity.py{BT} 的「配对集合对拍」）。几何判定逐条照抄
  {BT}loom_physics._pair_overlap{BT}（严格 <，贴边不算碰撞）。

性能口径（明确不做对齐，见路线登记 §6.5）：
  VK 走朴素 O(n²) 候选对（GL 走 SAP 粗筛 + C 内核）。物体数大时 VK 侧慢，
  **这是有意的取舍**：先把语义对齐，性能下沉另立项（beta8 优化项）。
"""

import numpy as np

from kernels.fastpath import ancestry_dfs as _fp_ancestry


# ============ 脚本钩子判定（原 loom_physics 模块级函数，搬来这里共享） ============

def _script_overrides_stay(inst):
    """C1: 脚本实例是否重写了 on_collision_stay (非 Script 基类空方法).
    未定义 → 走原热路径早退 (保持「无事件零开销」契约)."""
    if inst is None:
        return False
    try:
        from script.scripts import Script as _BaseScript
    except ImportError:
        return False
    fn = getattr(type(inst), 'on_collision_stay', None)
    return fn is not None and fn is not getattr(_BaseScript, 'on_collision_stay', None)


def _script_overrides_trigger_stay(inst):
    """脚本实例是否重写了 on_trigger_stay (非 Script 基类空方法)。"""
    if inst is None:
        return False
    try:
        from script.scripts import Script as _BaseScript
    except ImportError:
        return False
    fn = getattr(type(inst), 'on_trigger_stay', None)
    return fn is not None and fn is not getattr(_BaseScript, 'on_trigger_stay', None)


def _any_script_needs_stay(scripts):
    """物体上任一脚本覆盖了 on_collision_stay 或 on_trigger_stay（任一即需 stay 派发）。"""
    for sc in scripts:
        inst = getattr(sc, '_script', None)
        if inst is None or getattr(sc, '_script_broken', False):
            continue
        if _script_overrides_stay(inst):
            return True
        if _script_overrides_trigger_stay(inst):
            return True
    return False


def _is_trigger_pair(m_a, m_b):
    """两物体任一 collider 的 is_trigger=True 则走 Trigger 事件路径（Unity 语义）。"""
    ca = getattr(m_a, 'collider', None)
    cb = getattr(m_b, 'collider', None)
    ta = bool(getattr(ca, 'is_trigger', False)) if ca is not None else False
    tb = bool(getattr(cb, 'is_trigger', False)) if cb is not None else False
    return ta or tb


# ==================== 包围盒 / 碰撞体数据 ====================

def homogeneous_vertices(mesh, cache):
    """网格顶点 -> 齐次 (V,4) float64，按 id(mesh) 缓存（网格创建后不可变）。
    与 loom_transform._homogeneous_vertices 同式（校验 vertices 列表身份防过期缓存）。"""
    key = id(mesh)
    ent = cache.get(key)
    if ent is not None and ent[0] is mesh.vertices:
        return ent[1]
    v = np.asarray(mesh.vertices, dtype=np.float64)
    if v.ndim != 2 or v.shape[1] != 3:
        raise ValueError('mesh.vertices 形状非法: %r' % (v.shape,))
    vh = np.ones((v.shape[0], 4), dtype=np.float64)
    vh[:, :3] = v
    cache[key] = (mesh.vertices, vh)
    return vh


def aabb_of(model, M, cache):
    """模型轴对齐包围盒（世界矩阵变换后）-> (mn3, mx3) 元组。
    与 loom_transform.get_bounding_box 同式（只算 3 列 + 连续归约）。"""
    vh = homogeneous_vertices(model.mesh, cache)
    w3t = np.ascontiguousarray((vh @ M[:, :3]).T)
    mn, mx = w3t.min(axis=1), w3t.max(axis=1)
    return ((float(mn[0]), float(mn[1]), float(mn[2])),
            (float(mx[0]), float(mx[1]), float(mx[2])))


def collider_of(model, M, cache):
    """世界空间碰撞体 -> ('box', (mn, mx)) 或 ('sphere', ((cx,cy,cz), r))。
    sphere 取 AABB 中心 + 最大半长（与 loom_physics.collider_bounds 同式）。"""
    mn, mx = aabb_of(model, M, cache)
    if model.collider.shape == 'sphere':
        c = ((mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, (mn[2] + mx[2]) * 0.5)
        r = max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) * 0.5
        return ('sphere', (c, r))
    return ('box', (mn, mx))


def overlap(a, b):
    """两个 (shape, data) 碰撞体是否相交（纯几何，严格 <：贴边不算碰撞）。"""
    sa, da = a
    sb, db = b
    if sa == 'box' and sb == 'box':
        (amn, amx), (bmn, bmx) = da, db
        return all(amn[i] < bmx[i] and bmn[i] < amx[i] for i in (0, 1, 2))
    if sa == 'sphere' and sb == 'sphere':
        (ca, ra), (cb, rb) = da, db
        dx, dy, dz = ca[0] - cb[0], ca[1] - cb[1], ca[2] - cb[2]
        return dx * dx + dy * dy + dz * dz < (ra + rb) ** 2
    if sa == 'sphere':
        (sc, r), (bmn, bmx) = da, db
    else:
        (bmn, bmx), (sc, r) = da, db
    cx = max(bmn[0], min(sc[0], bmx[0]))
    cy = max(bmn[1], min(sc[1], bmx[1]))
    cz = max(bmn[2], min(sc[2], bmx[2]))
    dx, dy, dz = sc[0] - cx, sc[1] - cy, sc[2] - cz
    return dx * dx + dy * dy + dz * dz < r * r


# ==================== 祖先关系（同树不算碰撞） ====================

def ancestry_ranges(models):
    """模型森林 DFS 序区间 (tin, tout)：a 是 b 祖先 ⟺ tin[a] <= tin[b] < tout[a]。
    与 loom_physics._ancestry_ranges 同源（委托 fastpath.ancestry_dfs）。"""
    n = len(models)
    id2i = {id(m): i for i, m in enumerate(models)}
    parent_idx = np.full(n, -1, dtype=np.int64)
    for i, m in enumerate(models):
        if m.parent is not None:
            parent_idx[i] = id2i.get(id(m.parent), -1)
    return _fp_ancestry(parent_idx)


def is_related_idx(a, b, tin, tout):
    """下标 a/b 是否同一棵变换树（自身/祖先/后代）。"""
    if a == b:
        return True
    if tin[a] <= tin[b] < tout[a]:
        return True
    if tin[b] <= tin[a] < tout[b]:
        return True
    return False


# ==================== 配对生成 ====================

def candidate_indices(models):
    """参与碰撞的物体下标（有 collider / 启用 / 形状非 none）。"""
    out = []
    for i, m in enumerate(models):
        c = getattr(m, 'collider', None)
        if c is None or not c.enabled or c.shape == 'none':
            continue
        if getattr(m, 'mesh', None) is None:
            continue
        out.append(i)
    return out


def pairs(models, worlds, cache=None):
    """全部碰撞对 [(i, j)]（i < j，无副作用）。

    models: 物体列表；worlds: 与 models 对齐的 (N,4,4) 世界矩阵（行向量 S@R@T）。
    与 GL 的 _collision_pairs_parallel() 产出的**集合必须相同**（门会逐对拍）。
    """
    if cache is None:
        cache = {}
    cand = candidate_indices(models)
    if len(cand) < 2:
        return []
    colls = {i: collider_of(models[i], worlds[i], cache) for i in cand}
    tin, tout = ancestry_ranges(models)
    out = []
    nc = len(cand)
    for a in range(nc):
        i = cand[a]
        ci = colls[i]
        for b in range(a + 1, nc):
            j = cand[b]
            if is_related_idx(i, j, tin, tout):
                continue
            if overlap(ci, colls[j]):
                out.append((i, j))
    return out


# ==================== 事件派发 ====================

def call_cb(m, hook, other):
    """调物体上所有脚本的碰撞回调（坏脚本标记不崩帧）。"""
    for sc in m.scripts:
        inst = getattr(sc, '_script', None)
        if inst is None or getattr(sc, '_script_broken', False):
            continue
        fn = getattr(inst, hook, None)
        if fn is None:
            continue
        try:
            fn(other)
        except Exception as e:
            print('[脚本] %s(%s) %s 出错: %r' % (m.name, sc.script_id, hook, e))
            sc._script_broken = True


def dispatch(models, pairs):
    """把碰撞对串行派发成 on_collision_start/end/stay + on_trigger_*（改脚本状态，必须主线程）。

    逐行照抄 loom_physics._dispatch_collision_events（GL 侧同一份语义）：
      · 新出现的对 → on_collision_start / on_trigger_enter（任一方 is_trigger 走 trigger）
      · 消失的对   → on_collision_end   / on_trigger_exit
      · 持续的对   → 仅当某脚本覆盖了 stay 类方法才派发 on_collision_stay / on_trigger_stay
    """
    neigh = {}
    for i, j in pairs:
        neigh.setdefault(i, set()).add(j)
        neigh.setdefault(j, set()).add(i)
    id2m = {id(o): o for o in models}
    for i, m in enumerate(models):
        if not m.scripts:
            continue
        current = {id(models[j]) for j in neigh.get(i, ())}
        prev = getattr(m, '_colliding', set())
        has_stay = _any_script_needs_stay(m.scripts)
        if current == prev and not has_stay:
            continue
        for cid in current - prev:
            other = id2m.get(cid)
            if other is not None and _is_trigger_pair(m, other):
                call_cb(m, 'on_trigger_enter', other)
            else:
                call_cb(m, 'on_collision_start', other)
        for cid in prev - current:
            other = id2m.get(cid)
            if other is not None and _is_trigger_pair(m, other):
                call_cb(m, 'on_trigger_exit', other)
            else:
                call_cb(m, 'on_collision_end', other)
        if has_stay:
            for cid in current & prev:
                other = id2m.get(cid)
                if other is not None and _is_trigger_pair(m, other):
                    call_cb(m, 'on_trigger_stay', other)
                else:
                    call_cb(m, 'on_collision_stay', other)
        m._colliding = current
