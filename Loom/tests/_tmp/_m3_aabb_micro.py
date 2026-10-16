# -*- coding: utf-8 -*-
"""_m3_aabb_micro.py — M3 诊断: fastpath.aabbs_minmax 微基准 (只读)

目的: mt_aabb_minmax 实测 ~7 ms/帧 (跨池 worker) 与理论值差一个量级,
      需要确认 (a) 实际走的是 C / numba / numpy 哪条实现,
      (b) 单次调用的真实耗时, (c) n×V 规模敏感性。
用法: py -3.12 tests/_tmp/_m3_aabb_micro.py
"""
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import fastpath  # noqa: E402

print('numba available :', getattr(fastpath, '_NUMBA', None) is not None
      or getattr(fastpath, '_HAS_NUMBA', '?'))
print('_CKERNELS (dll) :', getattr(fastpath, '_CKERNELS', None) is not None)
print('aabbs_minmax    :', getattr(fastpath.aabbs_minmax, '__module__', '?'),
      getattr(fastpath.aabbs_minmax, 'py_func', None) is not None and 'numba-jit' or '')
print('aabbs_minmax_par:', getattr(fastpath.aabbs_minmax_par, '__module__', '?'))

rng = np.random.default_rng(1234)
for n, V in ((100, 2035), (30, 2035), (100, 24), (500, 24), (10, 2035)):
    vh = np.ascontiguousarray(rng.random((n, V, 4)))
    m3 = np.ascontiguousarray(rng.random((n, 4, 3)))
    mn = np.empty((n, 3))
    mx = np.empty((n, 3))
    # 预热
    fastpath.aabbs_minmax(vh, m3, mn, mx)
    reps = 20
    t0 = time.perf_counter()
    for _ in range(reps):
        fastpath.aabbs_minmax(vh, m3, mn, mx)
    t1 = (time.perf_counter() - t0) / reps * 1000.0
    # 并行版对比
    t2 = None
    try:
        fastpath.aabbs_minmax_par(vh, m3, mn, mx)
        t0 = time.perf_counter()
        for _ in range(reps):
            fastpath.aabbs_minmax_par(vh, m3, mn, mx)
        t2 = (time.perf_counter() - t0) / reps * 1000.0
    except Exception as e:
        t2 = 'err:%r' % e
    print('n=%4d V=%5d  work=%9d  串行=%.3f ms  并行=%s  (%.2f ns/顶点)'
          % (n, V, n * V, t1, ('%.3f ms' % t2) if isinstance(t2, float) else t2,
             t1 * 1e6 / (n * V)))
