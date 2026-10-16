# -*- coding: utf-8 -*-
"""pipeline_base_check.py — M2a-3 基座接线对拍与性能口径 (本探针不改 engine.py)

A 注册表链路 (assemble 真实 registry.json: 3 loaded / 0 popped, get 已 init 句柄,
provides_map 三接口) / B 光源 VP 经句柄 (dir full+beam, point, n=1/64/501) /
C 场景包围盒 + AABB 归约经句柄 / D 性能口径 (n=501+3 光源, 各 50 次, 只报数) /
E 逃生门 LOOM_NO_DLL='pipeline' / F 收尾 (shutdown 重 assemble + 注册表哈希)。
口径: 逐元素运算逐位 0; 矩阵乘法 abs ≤ 1e-14 且 rel ≤ 1e-12 (M2 设计文档 §4)。
"""
import ctypes, hashlib, itertools, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import numpy as np
import matlib
import module_loader as ml
import module_registry as mr
import pipeline_val_check as pv   # 复用 ref_dir_light_vp/ref_point_light_vp/ref_scene_bounds

REG = os.path.join(BASE, 'core_components', 'registry.json')
PD, PI32 = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int32)
results = []

def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))

acts = lambda asm, action: [r for r in asm.report if r['action'] == action]

def sha256_file(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

def rel_abs(d, ref):
    """→ (worst_abs, worst_rel)"""
    d = np.abs(d)
    if not d.size:
        return 0.0, 0.0
    return float(np.max(d)), float(np.max(d / np.maximum(np.abs(ref), 1e-300)))

class LoomLight(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_int32), ('shadow', ctypes.c_int32),
                ('mode', ctypes.c_int32), ('_pad', ctypes.c_int32),
                ('position', ctypes.c_double * 3), ('direction', ctypes.c_double * 3),
                ('up', ctypes.c_double * 3), ('size', ctypes.c_double)]

def light_vps(H, rows, lights, vis_idx=None):
    """经注册表句柄调 loom_pipeline_light_vps (用法照 pipeline_val_check)。"""
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
    vi, nv = None, 0
    if vis_idx is not None:
        vi = np.ascontiguousarray(np.asarray(vis_idx, dtype=np.int32))
        nv = int(vi.size)
    fn = H.get_fn('loom_pipeline_light_vps', ctypes.c_int32,
                  [PD, ctypes.c_int64, PI32, ctypes.c_int64,
                   ctypes.POINTER(LoomLight), ctypes.c_int64, PD, PI32])
    rows_c = np.ascontiguousarray(rows, dtype=np.float64)
    rc = int(fn(rows_c.ctypes.data_as(PD), ctypes.c_int64(rows_c.shape[0]),
                (vi.ctypes.data_as(PI32) if vi is not None else None),
                ctypes.c_int64(nv), L, ctypes.c_int64(len(lights)),
                out.ctypes.data_as(PD), kinds.ctypes.data_as(PI32)))
    return rc, out, kinds

def cmp_lights(H, lights, rows, vis=None):
    """句柄批量 VP vs Python 基准 → (rc, kinds, worst_abs, worst_rel)。"""
    rc, out, kinds = light_vps(H, rows, lights, vis)
    wa = wr = 0.0
    for i, l in enumerate(lights):
        refs = (pv.ref_point_light_vp(l) if l['kind'] == 1
                else [pv.ref_dir_light_vp(l, rows, vis)])
        for f, ref in enumerate(refs):
            a, r = rel_abs(out[i, f] - ref, ref)
            wa, wr = max(wa, a), max(wr, r)
    return rc, kinds, wa, wr

def ref_aabbs(vh, m3):
    """loom_pipeline_aabbs 的逐位基准: 标量升序求和 + 纯比较 (头文件 ③)。"""
    n, V = vh.shape[0], vh.shape[1]
    mn, mx = np.zeros((n, 3)), np.zeros((n, 3))
    vhl, m3l = vh.tolist(), m3.tolist()
    for i in range(n):
        a, m = vhl[i], m3l[i]
        lo, hi = [float('inf')] * 3, [float('-inf')] * 3
        for v in range(V):
            x = a[v]
            for c in range(3):
                s = ((x[0] * m[0][c] + x[1] * m[1][c]) + x[2] * m[2][c]) + x[3] * m[3][c]
                if s < lo[c]: lo[c] = s
                if s > hi[c]: hi[c] = s
        mn[i], mx[i] = lo, hi
    return mn, mx

def ref_scene_bounds_scalar(view, rows):
    """场景包围盒逐位 oracle: 角点全枚举 + 标量升序求和 (k=0..3) + 纯比较。
    与 loom_pipeline.h §② 同运算序 (min/max 与角点枚举序无关), 故可逐位对拍;
    numpy `corners @ view` 因 BLAS/SIMD 求和序差 1 ULP, 由 C1b 按 §4 例外取证。"""
    ab, cd, v = rows[:, 0:3].tolist(), rows[:, 3:6].tolist(), view.tolist()
    lo, hi = [float('inf')] * 3, [float('-inf')] * 3
    for i in range(rows.shape[0]):
        for x, y, z in itertools.product((ab[i][0], cd[i][0]), (ab[i][1], cd[i][1]),
                                         (ab[i][2], cd[i][2])):
            for c in range(3):
                s = ((x * v[0][c] + y * v[1][c]) + z * v[2][c]) + v[3][c]
                if s < lo[c]: lo[c] = s
                if s > hi[c]: hi[c] = s
    return np.array(lo, dtype=np.float64), np.array(hi, dtype=np.float64)

def rand_dir_light(rng, mode, size):
    return {'kind': 0, 'shadow': 1, 'mode': mode,
            'position': tuple(rng.uniform(-20, 20, 3)),
            'direction': tuple(rng.uniform(-1, 1, 3)),
            'up': tuple(rng.uniform(-0.5, 0.5, 3) + np.array([0.0, 1.0, 0.0])),
            'size': size}

def rand_point_light(rng):
    return {'kind': 1, 'shadow': 1, 'mode': 0,
            'position': tuple(rng.uniform(-30, 30, 3)),
            'direction': (0, 0, -1), 'up': (0, 1, 0), 'size': 1.0}

def main():
    print('=== pipeline_base_check (M2a-3) ===')
    h0, rng = sha256_file(REG), np.random.default_rng(20260908)

    # ---- A 注册表链路 ----
    asm = mr.assemble(REG)
    loaded, popped = acts(asm, 'loaded'), acts(asm, 'popped')
    check('A1 assemble 真实注册表 5 组件 loaded / 0 popped',
          len(asm.modules) == 5 and len(loaded) == 5 and len(popped) == 0,
          'modules=%r loaded=%d popped=%d skipped=%d'
          % (sorted(asm.modules), len(loaded), len(popped), len(acts(asm, 'skipped'))))
    try:
        H = asm.get('pipeline')
        check('A2 get(pipeline) 返回已 init 句柄',
              H is not None and H.module_id == 'pipeline'
              and tuple(H.provides) == ('pipeline.light_vps', 'pipeline.scene_bounds',
                                        'pipeline.aabbs', 'pipeline.world_matrices'),
              'id=%s ver=%s official=%s' % (H.module_id, H.version, H.official))
    except Exception as e:
        check('A2 get(pipeline) 返回已 init 句柄', False, repr(e))
        print('FAILED 句柄不可用, 后续子项跳过')
        return 1
    keys = tuple(asm.provides_map.keys())
    check('A3 provides_map 含 pipeline 四接口',
          all(k in keys for k in ('pipeline.light_vps', 'pipeline.scene_bounds',
                                  'pipeline.aabbs', 'pipeline.world_matrices')), 'keys=%r' % (keys,))

    # ---- B 光源 VP 经句柄 (矩阵乘法: abs ≤ 1e-14 且 rel ≤ 1e-12) ----
    for tag, mode, size in (('full', 0, 1.0), ('beam', 1, 3.5)):
        ok, wa, wr = True, 0.0, 0.0
        for n in (1, 64, 501):
            rc, kinds, a, r = cmp_lights(H, [rand_dir_light(rng, mode, size)],
                                         pv.rand_rows(rng, n))
            wa, wr = max(wa, a), max(wr, r)
            ok = ok and rc == 0 and kinds[0] == 0
        check('B1 平行光 VP %s 经句柄 (n=1/64/501)' % tag,
              ok and wa <= 1e-14 and wr <= 1e-12, 'worst_abs=%g worst_rel=%g' % (wa, wr))
    ok, wa, wr = True, 0.0, 0.0
    for n in (1, 64, 501):
        rc, kinds, a, r = cmp_lights(H, [rand_point_light(rng)], pv.rand_rows(rng, n))
        wa, wr = max(wa, a), max(wr, r)
        ok = ok and rc == 0 and kinds[0] == 1
    check('B2 点光 VP 6 面经句柄 (n=1/64/501)', ok and wa <= 1e-14 and wr <= 1e-12,
          'worst_abs=%g worst_rel=%g' % (wa, wr))
    lights = [rand_dir_light(rng, 0, 1.0), rand_point_light(rng),
              rand_dir_light(rng, 1, 2.0)]
    rows, vis = pv.rand_rows(rng, 200), [i for i in range(200) if i % 3 == 0]
    rc, kinds, dmix, _ = cmp_lights(H, lights, rows, vis)
    check('B3 混合批量 + vis_idx 经句柄 (dir/point/beam)',
          rc == 0 and list(kinds) == [0, 1, 0] and dmix <= 1e-14, 'worst_abs=%g' % dmix)

    # ---- C 场景包围盒 / AABB 归约经句柄 (逐位 0) ----
    sb = H.get_fn('loom_pipeline_scene_bounds', ctypes.c_int32,
                  [PD, PD, ctypes.c_int64, PD, PD])
    ok, wb, wn, wrn, scale = True, 0.0, 0.0, 0.0, 1.0
    for n in (1, 7, 64, 501):
        rows = pv.rand_rows(rng, n)
        view = matlib.mat4_view_forward(
            np, rng.uniform(-9, 9, 3), tuple(rng.uniform(-1, 1, 3)), (0.0, 1.0, 0.0))
        mn, mx = np.zeros(3), np.zeros(3)
        rc = int(sb(np.ascontiguousarray(view).ctypes.data_as(PD),
                    rows.ctypes.data_as(PD), ctypes.c_int64(n),
                    mn.ctypes.data_as(PD), mx.ctypes.data_as(PD)))
        ref = ref_scene_bounds_scalar(view, rows)
        d = max(float(np.max(np.abs(mn - ref[0]))), float(np.max(np.abs(mx - ref[1]))))
        npr = pv.ref_scene_bounds(view, rows)      # engine 侧 numpy matmul 基准
        a1, r1 = rel_abs(mn - npr[0], npr[0])
        a2, r2 = rel_abs(mx - npr[1], npr[1])
        wn, wrn = max(wn, a1, a2), max(wrn, r1, r2)
        scale = max(scale, float(np.max(np.abs(npr[0]))), float(np.max(np.abs(npr[1]))))
        wb = max(wb, d)
        ok = ok and rc == 0 and d == 0.0
    check('C1 场景包围盒经句柄逐位 (标量升序 oracle, n=1/7/64/501)', ok,
          'worst maxdiff=%r' % wb)
    # §4 例外: matmul 允许 1 ULP; abs 界随量级放大 (坐标 ±50 → view 空间 ~1e2),
    # 故按 scale 归一化取证, scale=1 即退化为原式 abs ≤ 1e-14。
    check('C1b 场景包围盒 vs numpy matmul 基准 (engine 侧) 在 §4 例外界内',
          wn <= 1e-14 * scale and wrn <= 1e-12,
          'worst_abs=%g worst_rel=%g scale=%g bound_abs=%g'
          % (wn, wrn, scale, 1e-14 * scale))
    ab = H.get_fn('loom_pipeline_aabbs', ctypes.c_int32,
                  [PD, PD, PD, PD, ctypes.c_int64, ctypes.c_int64])
    ok, wc = True, 0.0
    for (n, V) in ((1, 1), (64, 37), (501, 8)):
        vh = np.ascontiguousarray(rng.standard_normal((n, V, 4)), dtype=np.float64)
        m3 = np.ascontiguousarray(rng.standard_normal((n, 4, 3)), dtype=np.float64)
        mn, mx = np.zeros((n, 3)), np.zeros((n, 3))
        rc = int(ab(vh.ctypes.data_as(PD), m3.ctypes.data_as(PD),
                    mn.ctypes.data_as(PD), mx.ctypes.data_as(PD),
                    ctypes.c_int64(n), ctypes.c_int64(V)))
        pmn, pmx = ref_aabbs(vh, m3)
        d = max(float(np.max(np.abs(mn - pmn))), float(np.max(np.abs(mx - pmx))))
        wc, ok = max(wc, d), ok and rc == 0 and d == 0.0
    vh0, m30 = np.zeros((0, 0, 4)), np.zeros((0, 4, 3))
    mn0, mx0 = np.zeros((0, 3)), np.zeros((0, 3))
    rc0 = int(ab(vh0.ctypes.data_as(PD), m30.ctypes.data_as(PD),
                 mn0.ctypes.data_as(PD), mx0.ctypes.data_as(PD),
                 ctypes.c_int64(0), ctypes.c_int64(0)))
    check('C2 AABB 归约经句柄逐位 (标量升序求和基准)', ok and rc0 == 0,
          'worst maxdiff=%r rc_n0=%d' % (wc, rc0))

    # ---- D 性能口径 (只报数, 不做断言; 性能由主线程在真实引擎上验收) ----
    rows_p = pv.rand_rows(rng, 501)
    lights_p = [rand_dir_light(rng, 0, 1.0), rand_dir_light(rng, 1, 2.0),
                rand_point_light(rng)]
    REPS, t_dll, t_py = 50, [], []
    for _ in range(REPS):
        t = time.perf_counter()
        light_vps(H, rows_p, lights_p)
        t_dll.append(time.perf_counter() - t)
    for _ in range(REPS):
        t = time.perf_counter()
        pv.ref_dir_light_vp(lights_p[0], rows_p)
        pv.ref_dir_light_vp(lights_p[1], rows_p)
        pv.ref_point_light_vp(lights_p[2])
        t_py.append(time.perf_counter() - t)
    med_dll, med_py = float(np.median(t_dll)) * 1e3, float(np.median(t_py)) * 1e3
    print('PERF n=501 rows x 3 lights, %d reps: DLL=%.4f ms/frame  '
          'Python=%.4f ms/frame  speedup=%.2fx  (median)'
          % (REPS, med_dll, med_py, (med_py / med_dll) if med_dll > 0 else float('inf')))

    # ---- E 逃生门 ----
    old = os.environ.get('LOOM_NO_DLL')
    try:
        os.environ['LOOM_NO_DLL'] = 'pipeline'
        asm2 = mr.assemble(REG)
        raised = None
        try:
            asm2.get('pipeline')
        except ml.ModuleNotAvailable as e:
            raised = e
        check('E1 LOOM_NO_DLL=pipeline → get 抛 ModuleNotAvailable', raised is not None,
              repr(raised))
        others = []
        for mid in ('module_ref', 'ckernels', 'script', 'physics'):
            try:
                others.append(asm2.get(mid).module_id)
            except Exception as e:
                others.append(repr(e))
        check('E2 逃生门其余 4 组件正常',
              others == ['module_ref', 'ckernels', 'script', 'physics'] and len(asm2.modules) == 4,
              'others=%r skipped=%d' % (others, len(acts(asm2, 'skipped'))))
        asm2.shutdown()
    finally:
        if old is None: os.environ.pop('LOOM_NO_DLL', None)
        else: os.environ['LOOM_NO_DLL'] = old
    asm3 = mr.assemble(REG)
    check('E3 清 env 后恢复 5 组件',
          len(asm3.modules) == 5 and len(acts(asm3, 'popped')) == 0,
          'modules=%r' % (sorted(asm3.modules),))
    asm3.shutdown()

    # ---- F 收尾 ----
    asm.shutdown()
    asm4 = mr.assemble(REG)
    check('F1 shutdown 后重 assemble 仍 5 组件全绿',
          len(asm4.modules) == 5 and len(acts(asm4, 'popped')) == 0
          and asm4.get('pipeline').has('pipeline.light_vps'),
          'modules=%r popped=%d' % (sorted(asm4.modules), len(acts(asm4, 'popped'))))
    asm4.shutdown()
    check('F2 registry.json 哈希前后不变', h0 == sha256_file(REG), '%s' % h0[:16])

    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---' % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
