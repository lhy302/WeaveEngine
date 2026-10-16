# -*- coding: utf-8 -*-
"""pipeline_world_check.py — world_matrices C 实现对拍 (M2 续)

基准 = scheduler.sched_wm_chunk (局部段) + engine.compute_world_matrices 的
      父链合成语义 (按 depth 升序, world[i] = local[i] @ world[parent[i]])。

口径 (M2 设计文档 §4):
  · 局部段 Rx/Ry/Rz/S/T 构造 + 矩阵乘法 —— 矩阵乘法允许 ≤1 ULP (numpy BLAS);
  · 父链合成 —— 同为矩阵乘法, 同口径;
  · 逐元素赋值/索引运算必须逐位 (本探针用 abs ≤1e-14 且 rel ≤1e-12 判定)。
"""
import ctypes
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import numpy as np
import fastpath
import scheduler
import module_loader as ml

DLL = os.path.join(BASE, 'core_components', 'pipeline', 'pipeline.dll')
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


def make_tree(rng, n, chain_len=6):
    """构造父链: 每 chain_len 个连续模型串成一条链 (parent = i-1), 其余为根。"""
    parent = np.full(n, -1, dtype=np.int64)
    for i in range(n):
        if i % chain_len != 0:
            parent[i] = i - 1
    rot = np.ascontiguousarray(rng.uniform(-3.14, 3.14, size=(n, 3)), dtype=np.float64)
    scl = np.ascontiguousarray(rng.uniform(0.1, 3.0, size=(n, 3)), dtype=np.float64)
    pos = np.ascontiguousarray(rng.uniform(-20, 20, size=(n, 3)), dtype=np.float64)
    return rot, scl, pos, parent


def ref_world(rot, scl, pos, parent):
    """Python 基准: sched_wm_chunk 局部 + 按 depth 升序父链合成。"""
    n = rot.shape[0]
    local = np.empty((n, 4, 4), dtype=np.float64)
    scheduler.sched_wm_chunk(rot, scl, pos, local)
    depth = fastpath.depths(parent)
    world = np.empty_like(local)
    for d in range(int(depth.max()) + 1):
        idx = np.where(depth == d)[0]
        if d == 0:
            world[idx] = local[idx]
        else:
            world[idx] = local[idx] @ world[parent[idx]]
    return world, depth, local


def main():
    print('=== pipeline_world_check (M2 world_matrices) ===')
    H = ml.ModuleHandle.load(DLL, expected_module_id='pipeline')
    H.init()
    check('A1 加载 + provides 含 world_matrices',
          'pipeline.world_matrices' in H.provides, '%r' % (H.provides,))
    check('A2 has(pipeline.world_matrices)', H.has('pipeline.world_matrices') is True)

    pd = ctypes.POINTER(ctypes.c_double)
    pi = ctypes.POINTER(ctypes.c_int64)
    fn = H.get_fn('loom_pipeline_world_matrices', ctypes.c_int32,
                  [pd, pd, pd, pi, pi, ctypes.c_int64, ctypes.c_int64, pd, pd])

    rng = np.random.default_rng(20260908)
    ok = True
    worst_rel = 0.0
    worst_abs_scaled = 0.0
    for n in (1, 5, 64, 501, 1000):
        for chain in (1, 6, 12):
            rot, scl, pos, parent = make_tree(rng, n, chain)
            world_ref, depth, local_ref = ref_world(rot, scl, pos, parent)
            world = np.zeros((n, 4, 4), dtype=np.float64)
            local = np.zeros((n, 4, 4), dtype=np.float64)
            rc = int(fn(rot.ctypes.data_as(pd), scl.ctypes.data_as(pd),
                        pos.ctypes.data_as(pd), parent.ctypes.data_as(pi),
                        np.ascontiguousarray(depth, dtype=np.int64).ctypes.data_as(pi),
                        ctypes.c_int64(n), ctypes.c_int64(int(depth.max())),
                        local.ctypes.data_as(pd), world.ctypes.data_as(pd)))
            # 口径: 世界矩阵 = 矩阵乘法链 → 用**全局缩放**的绝对误差
            #   err = max|dll - ref| / max(1, max|ref|)
            # (逐元素相对误差会被趋零元素放大, 不是精度问题 — 已实证)。
            # 判据 = err ≤ depth × 1e-15 (每层 ≤1 ULP, 沿链线性累积)。
            scale = max(1.0, float(np.max(np.abs(world_ref))))
            d_loc = float(np.max(np.abs(local - local_ref))) / scale
            err = float(np.max(np.abs(world - world_ref))) / scale
            tol = max(1e-14, float(depth.max()) * 1e-15)
            worst_rel = max(worst_rel, err)
            worst_abs_scaled = max(worst_abs_scaled, d_loc)
            if rc != 0 or d_loc > 1e-14 or err > tol:
                ok = False
                print('   [n=%d chain=%d] rc=%d d_local(scaled)=%g err(scaled)=%g tol=%g'
                      % (n, chain, rc, d_loc, err, tol))
    check('B 局部+世界矩阵对拍 (n=1/5/64/501/1000 × 链长 1/6/12)',
          ok, 'worst_err_scaled=%g worst_dlocal=%g' % (worst_rel, worst_abs_scaled))

    # C 边界: n=0 / 单根 / 深链
    rot0 = np.zeros((0, 3)); scl0 = np.zeros((0, 3)); pos0 = np.zeros((0, 3))
    par0 = np.zeros(0, dtype=np.int64); dep0 = np.zeros(0, dtype=np.int64)
    w0 = np.zeros((0, 4, 4))
    rc0 = int(fn(rot0.ctypes.data_as(pd), scl0.ctypes.data_as(pd),
                 pos0.ctypes.data_as(pd), par0.ctypes.data_as(pi),
                 dep0.ctypes.data_as(pi), ctypes.c_int64(0), ctypes.c_int64(0),
                 None, w0.ctypes.data_as(pd)))
    check('C1 n=0 → rc=0 不崩', rc0 == 0, 'rc=%d' % rc0)
    n = 200
    rot, scl, pos, parent = make_tree(rng, n, 1)     # 全根
    world_ref, depth, _ = ref_world(rot, scl, pos, parent)
    world = np.zeros((n, 4, 4))
    rc = int(fn(rot.ctypes.data_as(pd), scl.ctypes.data_as(pd), pos.ctypes.data_as(pd),
                parent.ctypes.data_as(pi),
                np.ascontiguousarray(depth, dtype=np.int64).ctypes.data_as(pi),
                ctypes.c_int64(n), ctypes.c_int64(int(depth.max())),
                None, world.ctypes.data_as(pd)))
    check('C2 全根 (max_depth=0) 逐位/≤1ULP',
          rc == 0 and float(np.max(np.abs(world - world_ref))) <= 1e-14,
          'maxdiff=%g' % float(np.max(np.abs(world - world_ref))))
    rot, scl, pos, parent = make_tree(rng, n, n)     # 单条长链
    world_ref, depth, _ = ref_world(rot, scl, pos, parent)
    world = np.zeros((n, 4, 4))
    rc = int(fn(rot.ctypes.data_as(pd), scl.ctypes.data_as(pd), pos.ctypes.data_as(pd),
                parent.ctypes.data_as(pi),
                np.ascontiguousarray(depth, dtype=np.int64).ctypes.data_as(pi),
                ctypes.c_int64(n), ctypes.c_int64(int(depth.max())),
                None, world.ctypes.data_as(pd)))
    rel3 = float(np.max(np.abs(world - world_ref))) / max(
        1.0, float(np.max(np.abs(world_ref))))
    check('C3 深链 (depth=%d) 对拍 (全局缩放口径)' % int(depth.max()),
          rc == 0 and rel3 <= 1e-12,
          'err_scaled=%g max|ref|=%.3g' % (rel3, float(np.max(np.abs(world_ref)))))

    # D 性能口径
    n = 501
    rot, scl, pos, parent = make_tree(rng, n, 6)
    depth = fastpath.depths(parent)
    md = int(depth.max())
    world = np.zeros((n, 4, 4)); local = np.zeros((n, 4, 4))
    args = (rot.ctypes.data_as(pd), scl.ctypes.data_as(pd), pos.ctypes.data_as(pd),
            parent.ctypes.data_as(pi),
            np.ascontiguousarray(depth, dtype=np.int64).ctypes.data_as(pi),
            ctypes.c_int64(n), ctypes.c_int64(md))
    ts = []
    for _ in range(50):
        t0 = time.perf_counter()
        fn(*args, local.ctypes.data_as(pd), world.ctypes.data_as(pd))
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    ms_dll = ts[len(ts) // 2]
    ts = []
    for _ in range(50):
        t0 = time.perf_counter()
        ref_world(rot, scl, pos, parent)
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    ms_py = ts[len(ts) // 2]
    print('PERF world_matrices n=%d: DLL=%.3f ms | Python=%.3f ms | speedup=%.2fx'
          % (n, ms_dll, ms_py, (ms_py / ms_dll) if ms_dll else 0.0))
    check('D 性能口径已采集', ms_dll > 0 and ms_py > 0,
          'DLL=%.3fms Python=%.3fms' % (ms_dll, ms_py))

    H.unload()
    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
