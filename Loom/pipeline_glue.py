# -*- coding: utf-8 -*-
r"""pipeline_glue.py — 基座 ↔ pipeline.dll 接线层 (M2a-3, 2026-09-08)

职责: 把 engine 侧已算好的 AABB 行表 + 光源描述交给 pipeline.dll, 取回
      光源 view-proj 矩阵/场景包围盒。**只做数据搬运与格式转换**, 不含任何
      数值算法 (算法在 C 侧, 逐位对拍见 tests\_tmp\pipeline_val_check.py)。

分层 (M2 设计文档 §2):
  · 本模块 = 基座侧适配器 (可选, 缺席时 engine 走现行 Python 路径)。
  · module_loader/module_registry = M1 契约层 (加载/校验/回退)。
  · pipeline.dll = 计算层 (C, 无 GIL)。

逃生门 (两层, 分层不重叠):
  · LOOM_NO_PIPELINE=1 → 本模块整体禁用 (engine 回退现行 Python 路径)。
  · LOOM_NO_DLL='pipeline' → 注册表层跳过该槽位 (get 抛 ModuleNotAvailable)。

线程安全: 句柄在首次使用时惰性组装并缓存; ctypes 调用本身无共享状态。
"""
import ctypes
import os
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_CC = os.path.join(_HERE, 'core_components')
for _p in (_CC, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_ENGINE_ROOT = os.path.dirname(_HERE)

LOCK = threading.Lock()
_STATE = {'tried': False, 'handle': None, 'error': None}


class LoomLight(ctypes.Structure):
    r"""与 core_components\loom_pipeline.h 的 LOOM_LIGHT 逐字段对应。"""
    _fields_ = [('kind', ctypes.c_int32), ('shadow', ctypes.c_int32),
                ('mode', ctypes.c_int32), ('_pad', ctypes.c_int32),
                ('position', ctypes.c_double * 3),
                ('direction', ctypes.c_double * 3),
                ('up', ctypes.c_double * 3),
                ('size', ctypes.c_double)]


LOOM_LIGHT_DIRECTIONAL = 0
LOOM_LIGHT_POINT = 1
LOOM_LIGHT_MODE_FULL = 0
LOOM_LIGHT_MODE_BEAM = 1
LOOM_ERR_PARAM = -2
LOOM_ERR_UNSUPPORTED = -6


def handle():
    """惰性组装并返回 pipeline 句柄; 失败硬 raise (官方件不兜底)。

    ★B2 退役 (2026-10-16): 删 LOOM_NO_PIPELINE 整体禁用门 + 静默降级。
    pipeline 是官方组件, 唯一路径; 缺失/加载失败 = 引擎缺陷, 硬 raise
    (与 B1 ckernels 同纪律, 见 docs/design/逃生门退役设计.md §6)。
    注意: LOOM_NO_DLL='pipeline' (注册表层跳过槽位) 时 get 抛 ModuleNotAvailable
    → 同样硬 raise (该 env 仅注册表探针使用, 生产不设)。
    """
    if _STATE['tried']:
        return _STATE['handle']
    with LOCK:
        if _STATE['tried']:
            return _STATE['handle']
        _STATE['tried'] = True
        import module_registry as mr
        asm = mr.assemble(persist=False)
        _STATE['assembly'] = asm
        _STATE['handle'] = asm.get('pipeline')       # 拿不到硬抛 ModuleNotAvailable
        return _STATE['handle']


def _fill_lights(lights):
    """engine Light 对象序列 → (LoomLight 数组, 原序索引列表)。

    engine Light 字段: kind('directional'/其他) / shadow / mode / position /
    direction / up_vector() / size。不可用字段按契约默认值填。
    """
    arr = (LoomLight * len(lights))()
    for i, l in enumerate(lights):
        arr[i].kind = (LOOM_LIGHT_DIRECTIONAL
                       if getattr(l, 'kind', '') == 'directional'
                       else LOOM_LIGHT_POINT)
        arr[i].shadow = 1 if getattr(l, 'shadow', False) else 0
        arr[i].mode = (LOOM_LIGHT_MODE_BEAM
                       if getattr(l, 'mode', 'full') == 'beam'
                       else LOOM_LIGHT_MODE_FULL)
        p = getattr(l, 'position', None)
        if p is not None:
            arr[i].position[0] = float(p.x)
            arr[i].position[1] = float(p.y)
            arr[i].position[2] = float(p.z)
        d = getattr(l, 'direction', None)
        if d is not None:
            arr[i].direction[0] = float(d.x)
            arr[i].direction[1] = float(d.y)
            arr[i].direction[2] = float(d.z)
        up = None
        fn = getattr(l, 'up_vector', None)
        if callable(fn):
            try:
                up = fn()
            except Exception:
                up = None
        if up is not None:
            arr[i].up[0] = float(up.x)
            arr[i].up[1] = float(up.y)
            arr[i].up[2] = float(up.z)
        arr[i].size = float(getattr(l, 'size', 1.0))
    return arr


def light_vps(aabb_rows, lights, vis_idx=None):
    """批量算光源 VP。

    aabb_rows : (n,6) f64 numpy (行序与 models 下标对齐) 或 None
    lights    : engine Light 对象序列 (只传阴影光源)
    vis_idx   : 可选可见行下标 (list/np.ndarray int32); None = 用全量行表

    返回 (out_vp, out_kind) 或 None (DLL 不可用 → 调用方回退)。
      out_vp   : (m, 6, 4, 4) f64 — directional 只用 [i,0], point 用 6 面
      out_kind : (m,) int32 — 0=单矩阵 1=6面 -1=无 VP (与 Python None 等价)
    """
    h = handle()
    if h is None or not lights:
        return None
    import numpy as np
    n = 0
    rows = None
    if aabb_rows is not None:
        rows = np.ascontiguousarray(aabb_rows, dtype=np.float64)
        n = int(rows.shape[0])
    arr = _fill_lights(lights)
    out = np.zeros((len(lights), 6, 4, 4), dtype=np.float64)
    kinds = np.zeros((len(lights),), dtype=np.int32)
    vi = None
    nv = 0
    if vis_idx is not None and len(vis_idx):
        vi = np.ascontiguousarray(vis_idx, dtype=np.int32)
        nv = int(vi.size)
    pd = ctypes.POINTER(ctypes.c_double)
    pi = ctypes.POINTER(ctypes.c_int32)
    try:
        fn = h.get_fn('loom_pipeline_light_vps', ctypes.c_int32,
                      [pd, ctypes.c_int64, pi, ctypes.c_int64,
                       ctypes.POINTER(LoomLight), ctypes.c_int64, pd, pi])
        rc = int(fn((rows.ctypes.data_as(pd) if rows is not None else None),
                    ctypes.c_int64(n),
                    (vi.ctypes.data_as(pi) if vi is not None else None),
                    ctypes.c_int64(nv), arr, ctypes.c_int64(len(lights)),
                    out.ctypes.data_as(pd), kinds.ctypes.data_as(pi)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return out, kinds


def scene_bounds(view_4x4, aabb_rows):
    """AABB 行表 8 角变换到 view 空间取 (mn, mx); 不可用/空表返回 None。"""
    h = handle()
    if h is None or aabb_rows is None:
        return None
    import numpy as np
    rows = np.ascontiguousarray(aabb_rows, dtype=np.float64)
    if rows.shape[0] == 0:
        return None
    view = np.ascontiguousarray(view_4x4, dtype=np.float64)
    mn = np.zeros(3, dtype=np.float64)
    mx = np.zeros(3, dtype=np.float64)
    pd = ctypes.POINTER(ctypes.c_double)
    try:
        fn = h.get_fn('loom_pipeline_scene_bounds', ctypes.c_int32,
                      [pd, pd, ctypes.c_int64, pd, pd])
        rc = int(fn(view.ctypes.data_as(pd), rows.ctypes.data_as(pd),
                    ctypes.c_int64(rows.shape[0]),
                    mn.ctypes.data_as(pd), mx.ctypes.data_as(pd)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return mn, mx


def aabbs(vh, m3, out_mn, out_mx):
    """AABB 批量归约 (薄包装; 与 fastpath C 路径逐位同序)。成功返 True。"""
    h = handle()
    if h is None:
        return False
    import numpy as np
    vh = np.ascontiguousarray(vh, dtype=np.float64)
    m3 = np.ascontiguousarray(m3, dtype=np.float64)
    n = int(vh.shape[0]) if vh.ndim == 3 else 0
    V = int(vh.shape[1]) if vh.ndim == 3 else 0
    pd = ctypes.POINTER(ctypes.c_double)
    try:
        fn = h.get_fn('loom_pipeline_aabbs', ctypes.c_int32,
                      [pd, pd, pd, pd, ctypes.c_int64, ctypes.c_int64])
        rc = int(fn(vh.ctypes.data_as(pd), m3.ctypes.data_as(pd),
                    out_mn.ctypes.data_as(pd), out_mx.ctypes.data_as(pd),
                    ctypes.c_int64(n), ctypes.c_int64(V)))
    except Exception as e:
        _STATE['error'] = repr(e)
        raise
    if rc != 0:
        raise RuntimeError('pipeline.dll aabbs 调用失败 rc=%d' % rc)
    return True


def world_matrices(rot, scl, pos, parent, depth):
    """世界矩阵批量 (M2 续): 局部 S@R@T + 按 depth 升序父链合成。

    rot/scl/pos : (n,3) f64 C 连续平面
    parent      : (n,) int64 (-1 = 根)
    depth       : (n,) int64 (由调用方算, 如 fastpath.depths)
    返回 (n,4,4) f64 或 None (DLL 不可用 → 调用方回退 numpy 路径)。
    数值口径: 局部段逐元素精确, 世界矩阵为乘法链 → 全局缩放误差 ≤ depth×1e-15
    (实测 n=501 链长 12: 7.4e-16; 深链 199: 1.1e-15)。
    """
    h = handle()
    if h is None:
        return None
    import numpy as np
    rot = np.ascontiguousarray(rot, dtype=np.float64)
    scl = np.ascontiguousarray(scl, dtype=np.float64)
    pos = np.ascontiguousarray(pos, dtype=np.float64)
    par = np.ascontiguousarray(parent, dtype=np.int64)
    dep = np.ascontiguousarray(depth, dtype=np.int64)
    n = int(rot.shape[0])
    if n == 0:
        return np.empty((0, 4, 4), dtype=np.float64)
    world = np.empty((n, 4, 4), dtype=np.float64)
    md = int(dep.max()) if n else 0
    pd = ctypes.POINTER(ctypes.c_double)
    pi = ctypes.POINTER(ctypes.c_int64)
    try:
        fn = h.get_fn('loom_pipeline_world_matrices', ctypes.c_int32,
                      [pd, pd, pd, pi, pi, ctypes.c_int64, ctypes.c_int64, pd, pd])
        rc = int(fn(rot.ctypes.data_as(pd), scl.ctypes.data_as(pd),
                    pos.ctypes.data_as(pd), par.ctypes.data_as(pi),
                    dep.ctypes.data_as(pi), ctypes.c_int64(n),
                    ctypes.c_int64(md), None, world.ctypes.data_as(pd)))
    except Exception as e:
        _STATE['error'] = repr(e)
        raise
    if rc != 0:
        raise RuntimeError('pipeline.dll world_matrices 调用失败 rc=%d' % rc)
    return world


def interp_pose(cur_ids, known_sorted, order, prev_pos, curr_pos,
                prev_rot, curr_rot, prev_scl, curr_scl, alpha,
                loc_out, out_pos, out_rot, out_scl):
    """渲染帧插值平面 (M3-N4): 行映射 + pos/rot/scl lerp 整段入 C (nogil)。

    与 interp_state.InterpState.render_pose 的 numpy 路径逐位等价
    (对拍 tests\\_tmp\\interp_pose_check.py)。
    输入: cur_ids (n,) i64; known_sorted/order (known_n,) i64;
          prev_/curr_ pos/rot/scl (cap,3) f64; alpha (外推已封顶)
    输出 (调用方缓冲, 本函数不分配): loc_out (n,) i64;
          out_pos/out_rot/out_scl (n,3) f64
    返回: (loc_out, out_pos, out_rot, out_scl) 或 None (DLL 不可用 → 调用方回退)。
    """
    h = handle()
    if h is None:
        return None
    import numpy as np
    cur = np.ascontiguousarray(cur_ids, dtype=np.int64)
    ks = np.ascontiguousarray(known_sorted, dtype=np.int64)
    od = np.ascontiguousarray(order, dtype=np.int64)
    pp = np.ascontiguousarray(prev_pos, dtype=np.float64)
    cp = np.ascontiguousarray(curr_pos, dtype=np.float64)
    pr = np.ascontiguousarray(prev_rot, dtype=np.float64)
    cr = np.ascontiguousarray(curr_rot, dtype=np.float64)
    ps = np.ascontiguousarray(prev_scl, dtype=np.float64)
    cs = np.ascontiguousarray(curr_scl, dtype=np.float64)
    loc = np.ascontiguousarray(loc_out, dtype=np.int64)
    op = np.ascontiguousarray(out_pos, dtype=np.float64)
    orr = np.ascontiguousarray(out_rot, dtype=np.float64)
    osl = np.ascontiguousarray(out_scl, dtype=np.float64)
    n = int(cur.shape[0])
    kn = int(ks.shape[0])
    if n == 0 or kn == 0:
        return None
    pd = ctypes.POINTER(ctypes.c_double)
    pi = ctypes.POINTER(ctypes.c_int64)
    try:
        fn = h.get_fn('loom_pipeline_interp_pose', ctypes.c_int32,
                      [pi, pi, pi, ctypes.c_int64, pd, pd, pd, pd, pd, pd,
                       ctypes.c_int64, ctypes.c_double, pi, pd, pd, pd])
        rc = int(fn(cur.ctypes.data_as(pi), ks.ctypes.data_as(pi),
                    od.ctypes.data_as(pi), ctypes.c_int64(kn),
                    pp.ctypes.data_as(pd), cp.ctypes.data_as(pd),
                    pr.ctypes.data_as(pd), cr.ctypes.data_as(pd),
                    ps.ctypes.data_as(pd), cs.ctypes.data_as(pd),
                    ctypes.c_int64(n), ctypes.c_double(alpha),
                    loc.ctypes.data_as(pi), op.ctypes.data_as(pd),
                    orr.ctypes.data_as(pd), osl.ctypes.data_as(pd)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return loc, op, orr, osl


def interp_world(cur_ids, known_sorted, order, prev_pos, curr_pos,
                 prev_rot, curr_rot, prev_scl, curr_scl,
                 parent, depth, max_depth, alpha, loc_out, world_out):
    """★M3-N6: 插值平面 → 世界矩阵整段 (interp_pose + world_matrices 合并)。

    与「先 interp_pose 再 world_matrices」逐位等价 (对拍 interp_pose_check.py)。
    返回 (loc_out, world_out) 或 None (DLL 不可用 → 调用方回退旧路径)。
    """
    h = handle()
    if h is None:
        return None
    import numpy as np
    cur = np.ascontiguousarray(cur_ids, dtype=np.int64)
    ks = np.ascontiguousarray(known_sorted, dtype=np.int64)
    od = np.ascontiguousarray(order, dtype=np.int64)
    pp = np.ascontiguousarray(prev_pos, dtype=np.float64)
    cp = np.ascontiguousarray(curr_pos, dtype=np.float64)
    pr = np.ascontiguousarray(prev_rot, dtype=np.float64)
    cr = np.ascontiguousarray(curr_rot, dtype=np.float64)
    ps = np.ascontiguousarray(prev_scl, dtype=np.float64)
    cs = np.ascontiguousarray(curr_scl, dtype=np.float64)
    par = np.ascontiguousarray(parent, dtype=np.int64)
    dep = np.ascontiguousarray(depth, dtype=np.int64)
    loc = np.ascontiguousarray(loc_out, dtype=np.int64)
    world = np.ascontiguousarray(world_out, dtype=np.float64)
    n = int(cur.shape[0])
    kn = int(ks.shape[0])
    if n == 0 or kn == 0:
        return None
    pd = ctypes.POINTER(ctypes.c_double)
    pi = ctypes.POINTER(ctypes.c_int64)
    try:
        fn = h.get_fn('loom_pipeline_interp_world', ctypes.c_int32,
                      [pi, pi, pi, ctypes.c_int64, pd, pd, pd, pd, pd, pd,
                       pi, pi, ctypes.c_int64, ctypes.c_int64, ctypes.c_double,
                       pi, pd])
        rc = int(fn(cur.ctypes.data_as(pi), ks.ctypes.data_as(pi),
                    od.ctypes.data_as(pi), ctypes.c_int64(kn),
                    pp.ctypes.data_as(pd), cp.ctypes.data_as(pd),
                    pr.ctypes.data_as(pd), cr.ctypes.data_as(pd),
                    ps.ctypes.data_as(pd), cs.ctypes.data_as(pd),
                    par.ctypes.data_as(pi), dep.ctypes.data_as(pi),
                    ctypes.c_int64(int(max_depth)), ctypes.c_int64(n),
                    ctypes.c_double(alpha),
                    loc.ctypes.data_as(pi), world.ctypes.data_as(pd)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return loc, world


def pack_bucket_instances(fw32, n_models, idxs, sat, rgba, out_main, out_sha):
    """★M3 渲染预计算: 桶级实例缓冲打包 (C 原生实现).

    将 fw32[idxs] 和 sat / rgba 逐元素以 SIMD/连续 memcpy 填入 out_main(k,24) 与 out_sha(k,16)。
    与 Python np.take + 赋值逐位一致。
    返回 0 (成功) 或 None (DLL 不可用 → 调用方回退旧路径)。
    """
    h = handle()
    import numpy as np
    k = len(idxs)
    if k == 0:
        return 0
    fw = np.ascontiguousarray(fw32, dtype=np.float32)
    id_arr = np.ascontiguousarray(idxs, dtype=np.int32)
    om = np.ascontiguousarray(out_main, dtype=np.float32)
    os_ = np.ascontiguousarray(out_sha, dtype=np.float32) if out_sha is not None else None

    sat_arr = np.ascontiguousarray(sat, dtype=np.float32) if sat is not None else None
    col_arr = np.ascontiguousarray(rgba, dtype=np.float32) if rgba is not None else None

    pf = ctypes.POINTER(ctypes.c_float)
    pi32 = ctypes.POINTER(ctypes.c_int32)
    try:
        fn = h.get_fn('loom_pipeline_pack_bucket_instances', ctypes.c_int32,
                      [pf, ctypes.c_int64, pi32, ctypes.c_int64,
                       pf, pf, pf, pf])
        p_sat = sat_arr.ctypes.data_as(pf) if sat_arr is not None else None
        p_col = col_arr.ctypes.data_as(pf) if col_arr is not None else None
        p_sha = os_.ctypes.data_as(pf) if os_ is not None else None
        rc = int(fn(fw.ctypes.data_as(pf), ctypes.c_int64(n_models),
                    id_arr.ctypes.data_as(pi32), ctypes.c_int64(k),
                    p_sat, p_col, om.ctypes.data_as(pf), p_sha))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return 0



def dirty_mask(cur_rows, old_rows, pidx, out_mask):
    """★物理桥批量脏检测 (C 原生实现).
    cur_rows (n,6) f64, old_rows (n,6) f64, pidx (n,) i64, out_mask (n,) u8.
    返回 0 (成功) 或 None (失败/回退).
    """
    h = handle()
    import numpy as np
    cur = np.ascontiguousarray(cur_rows, dtype=np.float64)
    old = np.ascontiguousarray(old_rows, dtype=np.float64)
    par = np.ascontiguousarray(pidx, dtype=np.int64) if pidx is not None else None
    out = np.ascontiguousarray(out_mask, dtype=np.uint8)
    n = int(cur.shape[0])
    if n == 0:
        return 0
    pd = ctypes.POINTER(ctypes.c_double)
    pi64 = ctypes.POINTER(ctypes.c_int64)
    pu8 = ctypes.POINTER(ctypes.c_uint8)
    try:
        fn = h.get_fn('loom_pipeline_dirty_mask', ctypes.c_int32,
                      [pd, pd, pi64, ctypes.c_int64, pu8])
        p_par = par.ctypes.data_as(pi64) if par is not None else None
        rc = int(fn(cur.ctypes.data_as(pd), old.ctypes.data_as(pd),
                    p_par, ctypes.c_int64(n), out.ctypes.data_as(pu8)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return 0



def local_matrices(rot, scl, pos, out_m):
    """★物理桥批量局部变换矩阵 (C 原生实现).
    rot (n,3) f64, scl (n,3) f64, pos (n,3) f64, out_m (n,4,4) f64.
    返回 0 (成功) 或 None (失败/回退).
    """
    h = handle()
    import numpy as np
    r = np.ascontiguousarray(rot, dtype=np.float64)
    s = np.ascontiguousarray(scl, dtype=np.float64)
    p = np.ascontiguousarray(pos, dtype=np.float64)
    om = np.ascontiguousarray(out_m, dtype=np.float64)
    n = int(r.shape[0])
    if n == 0:
        return 0
    pd = ctypes.POINTER(ctypes.c_double)
    try:
        fn = h.get_fn('loom_pipeline_local_matrices', ctypes.c_int32,
                      [pd, pd, pd, ctypes.c_int64, pd])
        rc = int(fn(r.ctypes.data_as(pd), s.ctypes.data_as(pd),
                    p.ctypes.data_as(pd), ctypes.c_int64(n),
                    om.ctypes.data_as(pd)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return 0




def depths(parent, out_depth=None):
    """★C 原生深度 DP 求解 (替换纯 Python/Numba 依赖).
    parent: (n,) int64 父索引 (-1 = 根).
    返回 out_depth (n,) int64 或 None (失败回退).
    """
    h = handle()
    import numpy as np
    par = np.ascontiguousarray(parent, dtype=np.int64)
    n = int(par.shape[0])
    if n == 0:
        return out_depth if out_depth is not None else np.empty(0, dtype=np.int64)
    if out_depth is None or out_depth.shape[0] < n:
        out = np.empty(n, dtype=np.int64)
    else:
        out = out_depth
    pi = ctypes.POINTER(ctypes.c_int64)
    try:
        fn = h.get_fn('loom_pipeline_depths', ctypes.c_int32,
                      [pi, ctypes.c_int64, pi])
        rc = int(fn(par.ctypes.data_as(pi), ctypes.c_int64(n), out.ctypes.data_as(pi)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return out


def ancestry_dfs(parent, out_tin=None, out_tout=None):
    """★C 原生森林 DFS 区间查询 (替换纯 Python/Numba 依赖).
    parent: (n,) int64 父索引 (-1 = 根).
    返回 (tin, tout) 或 None (失败回退).
    """
    h = handle()
    import numpy as np
    par = np.ascontiguousarray(parent, dtype=np.int64)
    n = int(par.shape[0])
    if n == 0:
        return (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64))
    if out_tin is None or out_tin.shape[0] < n:
        tin = np.empty(n, dtype=np.int64)
    else:
        tin = out_tin
    if out_tout is None or out_tout.shape[0] < n:
        tout = np.empty(n, dtype=np.int64)
    else:
        tout = out_tout
    pi = ctypes.POINTER(ctypes.c_int64)
    try:
        fn = h.get_fn('loom_pipeline_ancestry_dfs', ctypes.c_int32,
                      [pi, ctypes.c_int64, pi, pi])
        rc = int(fn(par.ctypes.data_as(pi), ctypes.c_int64(n),
                    tin.ctypes.data_as(pi), tout.ctypes.data_as(pi)))
    except Exception as e:
        _STATE['error'] = repr(e)
        return None
    if rc != 0:
        raise RuntimeError('pipeline.dll 调用失败 rc=%d (官方件契约违约)' % rc)
    return tin, tout


def shutdown():
    """释放接线层持有的注册表 (进程退出/热重载用)。幂等。"""
    asm = _STATE.get('assembly')
    if asm is not None:
        try:
            asm.shutdown()
        except Exception:
            pass
    _STATE['assembly'] = None
    _STATE['handle'] = None
    _STATE['tried'] = False


def status():
    """一行诊断串 (HUD/探针用)。"""
    h = handle()
    return 'pipeline: %s v%s official=%d' % (h.module_id, h.version, h.official)
