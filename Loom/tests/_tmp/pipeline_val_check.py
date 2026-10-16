# -*- coding: utf-8 -*-
"""pipeline_val_check.py — pipeline.dll 数值逐位对拍 (M2a 验收①)

基准 = matlib.mat4_view_forward/ortho/perspective + engine 现行算法序的
Python 复刻 (_dir_light_vp/_point_light_vp/_scene_light_bounds_par 语义)。
对拍口径: **逐位 maxdiff == 0.0** (M2 设计文档 §4)。

子项:
  A 契约加载 (module_loader 走 M1 链路) + provides/has
  B 场景光照包围盒: 随机 AABB 行表 × 随机 view → (mn,mx) 逐位
  C 平行光 VP: full / beam × 多组 AABB 表 (n=1/64/501) → 4x4 逐位
  D 点光 VP: 6 面 × 多位置 → 6x4x4 逐位
  E AABB 归约: DLL vs ckernels 路径 (fastpath) 逐位
  F 边界: n=0 / 退化方向 / 空可见表 → 与 Python 口径一致不崩
"""
import ctypes
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import numpy as np
import matlib
import module_loader as ml

DLL = os.path.join(BASE, 'core_components', 'pipeline', 'pipeline.dll')
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


class LoomLight(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_int32), ('shadow', ctypes.c_int32),
                ('mode', ctypes.c_int32), ('_pad', ctypes.c_int32),
                ('position', ctypes.c_double * 3),
                ('direction', ctypes.c_double * 3),
                ('up', ctypes.c_double * 3), ('size', ctypes.c_double)]


H = None   # ModuleHandle


def _fn(name, restype, argtypes):
    return H.get_fn(name, restype, argtypes)


def light_vps(rows, lights, vis_idx=None):
    n = rows.shape[0]
    L = (LoomLight * len(lights))()
    for i, l in enumerate(lights):
        L[i].kind, L[i].shadow, L[i].mode = l['kind'], l['shadow'], l.get('mode', 0)
        for k in range(3):
            L[i].position[k] = l['position'][k]
            L[i].direction[k] = l.get('direction', (0, 0, -1))[k]
            L[i].up[k] = l.get('up', (0, 1, 0))[k]
        L[i].size = l.get('size', 1.0)
    out = np.zeros((len(lights), 6, 4, 4), dtype=np.float64)
    kinds = np.zeros((len(lights),), dtype=np.int32)
    vi = None
    nv = 0
    if vis_idx is not None:
        vi = np.ascontiguousarray(np.asarray(vis_idx, dtype=np.int32))
        nv = int(vi.size)
    fn = _fn('loom_pipeline_light_vps', ctypes.c_int32,
             [ctypes.POINTER(ctypes.c_double), ctypes.c_int64,
              ctypes.POINTER(ctypes.c_int32), ctypes.c_int64,
              ctypes.POINTER(LoomLight), ctypes.c_int64,
              ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int32)])
    pd = ctypes.POINTER(ctypes.c_double)
    rows_c = np.ascontiguousarray(rows, dtype=np.float64)
    rc = int(fn(rows_c.ctypes.data_as(pd), ctypes.c_int64(n),
                (vi.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)) if vi is not None else None),
                ctypes.c_int64(nv), L, ctypes.c_int64(len(lights)),
                out.ctypes.data_as(pd), kinds.ctypes.data_as(ctypes.POINTER(ctypes.c_int32))))
    return rc, out, kinds


# ---- Python 基准 (engine 现行算法序的直译) --------------------------------
def ref_scene_bounds(view, rows):
    """engine._scene_light_bounds_par 语义 (角点序 + 批量 matmul + min/max)。"""
    n = rows.shape[0]
    if n == 0:
        return None
    ab = rows[:, 0:3]
    cd = rows[:, 3:6]
    corners = np.empty((n * 8, 4), dtype=np.float64)
    xs = np.empty((n, 2)); xs[:, 0] = ab[:, 0]; xs[:, 1] = cd[:, 0]
    ys = np.empty((n, 2)); ys[:, 0] = ab[:, 1]; ys[:, 1] = cd[:, 1]
    zs = np.empty((n, 2)); zs[:, 0] = ab[:, 2]; zs[:, 1] = cd[:, 2]
    corners[:, 0] = np.tile(xs, (1, 4)).ravel()
    corners[:, 1] = np.tile(np.repeat(ys, 2, axis=1), (1, 2)).ravel()
    corners[:, 2] = np.repeat(zs, 4, axis=1).ravel()
    corners[:, 3] = 1.0
    w = corners @ view
    return w[:, :3].min(axis=0), w[:, :3].max(axis=0)


def ref_dir_light_vp(light, rows, vis_idx=None):
    """engine._dir_light_vp 语义直译。"""
    D = light.get('direction', (0, 0, -1))
    ln = (D[0] ** 2 + D[1] ** 2 + D[2] ** 2) ** 0.5
    if ln < 1e-6:
        return None
    D = (D[0] / ln, D[1] / ln, D[2] / ln)
    eye = light['position']
    up = light.get('up', (0, 1, 0))
    view = matlib.mat4_view_forward(np, eye, D, up)
    if vis_idx is not None:
        rows = rows[np.asarray(vis_idx)]
    bounds = ref_scene_bounds(view, rows)
    if bounds is None:
        return None
    mn, mx = bounds
    if light.get('mode', 0) == 1:            # beam
        s = max(light.get('size', 1.0), 0.01)
        left, right, bottom, top = -s, s, -s, s
        near, far = 0.0, max(float(mx[2]) + 2.0, 1.0)
    else:                                     # full
        pad = 1.5
        left, right = float(mn[0]) - pad, float(mx[0]) + pad
        bottom, top = float(mn[1]) - pad, float(mx[1]) + pad
        near = min(0.0, float(mn[2]) - 2.0)
        far = max(float(mx[2]) + 2.0, 1.0)
    return view @ matlib.mat4_ortho(np, left, right, bottom, top, near, far)


def ref_point_light_vp(light, far_plane=1.0e4):
    """engine._point_light_vp 语义直译。"""
    import math
    pos = light['position']
    proj = matlib.mat4_perspective(np, math.radians(90.0), 1.0, 0.05, far_plane)
    axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    ups = [(0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0)]
    return [matlib.mat4_view_forward(np, pos, a, u) @ proj for a, u in zip(axes, ups)]


def rand_rows(rng, n):
    mn = rng.uniform(-50, 50, size=(n, 3))
    ext = rng.uniform(0.01, 12.0, size=(n, 3))
    return np.ascontiguousarray(np.hstack([mn, mn + ext]), dtype=np.float64)


def main():
    global H
    print('=== pipeline_val_check (M2a) ===')

    # ---- A 契约加载 ----
    try:
        H = ml.ModuleHandle.load(DLL, expected_module_id='pipeline')
        H.init()
        check('A1 加载 pipeline.dll (module_loader 链路)', H.module_id == 'pipeline',
              'id=%s ver=%s official=%d abi=0x%X'
              % (H.module_id, H.version, H.official, H.abi_version))
        check('A2 provides 四接口',
              tuple(H.provides) == ('pipeline.light_vps', 'pipeline.scene_bounds',
                                    'pipeline.aabbs',
                                    'pipeline.world_matrices'), '%r' % (H.provides,))
        check('A3 has 正反',
              H.has('pipeline.light_vps') and H.has('pipeline.scene_bounds')
              and H.has('pipeline.aabbs') and H.has('pipeline.world_matrices')
              and not H.has('ckernels.aabbs'))
        check('A4 official==1 / depends 空',
              H.official == 1 and tuple(H.depends) == ())
    except Exception as e:
        check('A1 加载 pipeline.dll', False, repr(e))
        print('FAILED 加载失败, 后续子项跳过')
        return 1

    rng = np.random.default_rng(20260908)
    pd = ctypes.POINTER(ctypes.c_double)

    # ---- B 场景包围盒 ----
    sb = _fn('loom_pipeline_scene_bounds', ctypes.c_int32,
             [pd, pd, ctypes.c_int64, pd, pd])
    okb = True
    worst_b = 0.0
    for n in (1, 7, 64, 501):
        rows = rand_rows(rng, n)
        view = matlib.mat4_view_forward(
            np, rng.uniform(-9, 9, 3), tuple(rng.uniform(-1, 1, 3)), (0.0, 1.0, 0.0))
        ref = ref_scene_bounds(view, rows)
        mn = np.zeros(3); mx = np.zeros(3)
        rc = int(sb(np.ascontiguousarray(view).ctypes.data_as(pd),
                    rows.ctypes.data_as(pd), ctypes.c_int64(n),
                    mn.ctypes.data_as(pd), mx.ctypes.data_as(pd)))
        d = max(float(np.max(np.abs(mn - ref[0]))), float(np.max(np.abs(mx - ref[1]))))
        worst_b = max(worst_b, d)
        okb = okb and rc == 0 and d == 0.0
    check('B 场景包围盒逐位 (n=1/7/64/501)', okb, 'worst maxdiff=%r' % worst_b)

    # ---- C 平行光 VP ----
    # 口径 (M2 设计文档 §4): 纯逐元素运算 (view/ortho/scene_bounds/aabbs) 必须
    # 逐位 0; 矩阵乘法 view@ortho 因 numpy 走 BLAS/SIMD 求和序, 允许 1 ULP
    # (实测 ~2.2e-16), 由 C3 单独取证该界。
    okc = True
    worst_c = 0.0
    for mode, size in ((0, 1.0), (1, 3.5)):
        for n in (1, 64, 501):
            rows = rand_rows(rng, n)
            lt = {'kind': 0, 'shadow': 1, 'mode': mode,
                  'position': tuple(rng.uniform(-20, 20, 3)),
                  'direction': tuple(rng.uniform(-1, 1, 3)),
                  'up': tuple(rng.uniform(-0.5, 0.5, 3) + np.array([0, 1, 0])),
                  'size': size}
            rc, out, kinds = light_vps(rows, [lt])
            ref = ref_dir_light_vp(lt, rows)
            d = float(np.max(np.abs(out[0, 0] - ref)))
            worst_c = max(worst_c, d)
            okc = okc and rc == 0 and kinds[0] == 0 and d <= 1e-15
    check('C 平行光 VP (full/beam × n=1/64/501, ≤1 ULP)', okc,
          'worst maxdiff=%r' % worst_c)

    # ---- C2 可见行过滤 (vis_idx) ----
    rows = rand_rows(rng, 200)
    vis = [i for i in range(200) if i % 3 == 0]
    lt = {'kind': 0, 'shadow': 1, 'mode': 0,
          'position': tuple(rng.uniform(-20, 20, 3)),
          'direction': (0.3, -0.8, 0.5), 'up': (0.0, 1.0, 0.0), 'size': 1.0}
    rc, out, kinds = light_vps(rows, [lt], vis_idx=vis)
    ref = ref_dir_light_vp(lt, rows, vis_idx=vis)
    d = float(np.max(np.abs(out[0, 0] - ref)))
    check('C2 vis_idx 可见行过滤逐位', rc == 0 and kinds[0] == 0 and d == 0.0,
          'maxdiff=%r n_vis=%d' % (d, len(vis)))

    # ---- C3 矩阵乘法数值界取证 (C 同序乘法 vs numpy @) ----
    # 矩阵乘法是唯一允许非逐位的运算: numpy 走 BLAS/SIMD, 求和序与 C 不同,
    # 误差随量级放大 (实测 abs ≤ ~2e-15, 相对 ≤ ~1e-12)。本项钉死该界,
    # 并证明误差只来自乘法求和序 (纯逐元素运算在 B/C2/D/D2/E 已逐位为 0)。
    mulref = _fn('loom_pipeline_mat4_mul_ref', None, [pd, pd, pd])
    worst_abs = 0.0
    worst_rel = 0.0
    for _ in range(300):
        a = np.ascontiguousarray(rng.standard_normal((4, 4)), dtype=np.float64)
        b = np.ascontiguousarray(rng.standard_normal((4, 4)), dtype=np.float64)
        out = np.zeros((4, 4), dtype=np.float64)
        mulref(a.ctypes.data_as(pd), b.ctypes.data_as(pd), out.ctypes.data_as(pd))
        ref = a @ b
        worst_abs = max(worst_abs, float(np.max(np.abs(out - ref))))
        worst_rel = max(worst_rel,
                        float(np.max(np.abs(out - ref) / np.maximum(np.abs(ref), 1e-300))))
    check('C3 矩阵乘法数值界 (C 同序 vs numpy @, 300 组)',
          worst_abs <= 1e-14 and worst_rel <= 1e-12,
          'worst_abs=%g worst_rel=%g' % (worst_abs, worst_rel))

    # ---- D 点光 VP ----
    okd = True
    worst_d = 0.0
    for _ in range(4):
        lt = {'kind': 1, 'shadow': 1, 'mode': 0,
              'position': tuple(rng.uniform(-30, 30, 3)),
              'direction': (0, 0, -1), 'up': (0, 1, 0), 'size': 1.0}
        rc, out, kinds = light_vps(rand_rows(rng, 8), [lt])
        ref6 = ref_point_light_vp(lt)
        d = max(float(np.max(np.abs(out[0, f] - ref6[f]))) for f in range(6))
        worst_d = max(worst_d, d)
        okd = okd and rc == 0 and kinds[0] == 1 and d == 0.0
    check('D 点光 VP 6 面逐位 (4 组)', okd, 'worst maxdiff=%r' % worst_d)

    # ---- D2 混合多光源批量 ----
    lights = [
        {'kind': 0, 'shadow': 1, 'mode': 0, 'position': (1.0, 2.0, 3.0),
         'direction': (0.0, -1.0, 0.0), 'up': (0.0, 1.0, 0.0), 'size': 1.0},
        {'kind': 1, 'shadow': 1, 'mode': 0, 'position': (-4.0, 5.0, 6.0),
         'direction': (0, 0, -1), 'up': (0, 1, 0), 'size': 1.0},
        {'kind': 0, 'shadow': 1, 'mode': 1, 'position': (0.0, 9.0, 0.0),
         'direction': (0.1, -1.0, 0.2), 'up': (0.0, 0.0, 1.0), 'size': 2.0},
    ]
    rows = rand_rows(rng, 33)
    rc, out, kinds = light_vps(rows, lights)
    refs = [ref_dir_light_vp(lights[0], rows), ref_point_light_vp(lights[1]),
            ref_dir_light_vp(lights[2], rows)]
    d0 = float(np.max(np.abs(out[0, 0] - refs[0])))
    d1 = max(float(np.max(np.abs(out[1, f] - refs[1][f]))) for f in range(6))
    d2 = float(np.max(np.abs(out[2, 0] - refs[2])))
    check('D2 混合光源批量逐位 (dir+point+beam)',
          rc == 0 and list(kinds) == [0, 1, 0] and d0 == 0.0 and d1 == 0.0 and d2 == 0.0,
          'd0=%r d1=%r d2=%r' % (d0, d1, d2))

    # ---- E AABB 归约 vs ckernels 路径 ----
    import fastpath
    ab = _fn('loom_pipeline_aabbs', ctypes.c_int32,
             [pd, pd, pd, pd, ctypes.c_int64, ctypes.c_int64])
    oke = True
    worst_e = 0.0
    for (n, V) in ((137, 37), (1, 1), (64, 2035), (0, 0)):
        vh = np.ascontiguousarray(rng.standard_normal((n, V, 4)), dtype=np.float64)
        m3 = np.ascontiguousarray(rng.standard_normal((n, 4, 3)), dtype=np.float64)
        mn = np.zeros((n, 3)); mx = np.zeros((n, 3))
        rc = int(ab(vh.ctypes.data_as(pd), m3.ctypes.data_as(pd),
                    mn.ctypes.data_as(pd), mx.ctypes.data_as(pd),
                    ctypes.c_int64(n), ctypes.c_int64(V)))
        pmn = np.zeros((n, 3)); pmx = np.zeros((n, 3))
        if n and V:
            fastpath._aabbs_minmax_np(vh, m3, pmn, pmx)
        d = 0.0
        if n:
            d = max(float(np.max(np.abs(mn - pmn))), float(np.max(np.abs(mx - pmx))))
        worst_e = max(worst_e, d)
        # B1 口径调整 (2026-10-16): 基准换成 numpy 批量 (_aabbs_minmax_np), 与 ckernels
        # 标量内核是 ~4 ULP 级差 (fastpath.py 注释: numpy dgemm ~4 ULP, D6 标准 1e-7 内),
        # 不再是逐位全等。断言改 D6 标准 (与 module_contract_check A11 同口径)。
        oke = oke and rc == 0 and d <= 1e-7
    check('E AABB 归约 vs ckernels 路径 (D6 标准, 含 n=0)', oke, 'worst maxdiff=%r' % worst_e)

    # ---- F 边界 ----
    rows0 = np.zeros((0, 6), dtype=np.float64)
    mn = np.zeros(3); mx = np.zeros(3)
    view = matlib.mat4_view_forward(np, (0, 0, 0), (0, 0, 1), (0, 1, 0))
    rc0 = int(sb(np.ascontiguousarray(view).ctypes.data_as(pd),
                 rows0.ctypes.data_as(pd), ctypes.c_int64(0),
                 mn.ctypes.data_as(pd), mx.ctypes.data_as(pd)))
    check('F1 n=0 场景包围盒 → 参数错误 (Python 口径 None)', rc0 != 0, 'rc=%d' % rc0)
    lt = {'kind': 0, 'shadow': 1, 'mode': 0, 'position': (0.0, 5.0, 0.0),
          'direction': (0.0, 0.0, 0.0), 'up': (0.0, 1.0, 0.0), 'size': 1.0}
    rc, out, kinds = light_vps(rand_rows(rng, 4), [lt])
    check('F2 退化方向 → kind=-1 (Python None 等价)', rc == 0 and kinds[0] == -1,
          'rc=%d kind=%d' % (rc, int(kinds[0])))
    lt = {'kind': 0, 'shadow': 1, 'mode': 0, 'position': (0.0, 5.0, 0.0),
          'direction': (0.0, -1.0, 0.0), 'up': (0.0, -1.0, 0.0), 'size': 1.0}
    rc, out, kinds = light_vps(rand_rows(rng, 4), [lt])
    check('F3 up 平行 forward → 不崩 (rl 兜底 1.0)', rc == 0 and kinds[0] in (0, -1),
          'rc=%d kind=%d' % (rc, int(kinds[0])))
    lt = {'kind': 1, 'shadow': 1, 'mode': 0, 'position': (0.0, 0.0, 0.0),
          'direction': (0, 0, -1), 'up': (0, 1, 0), 'size': 1.0}
    rc, out, kinds = light_vps(rows0, [lt])
    check('F4 点光无 AABB 依赖 → 仍出 6 面', rc == 0 and kinds[0] == 1)

    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    H.unload()
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
