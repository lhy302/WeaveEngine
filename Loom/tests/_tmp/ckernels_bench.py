# -*- coding: utf-8 -*-
"""ckernels_bench.py — aabbs 内核三路计时 (C vs numba vs numpy)
规模 = 混合500 实际形态 (n=500, V=2035); 预热后 100 轮均值。
闸门: C >= numba×0.8 (即慢不超过 25%), 且 >= numpy×1.5。
"""
import os
import sys
import time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import fastpath
assert fastpath._CKERNELS is not None, 'C DLL 未加载'

n, V = 500, 2035
rng = np.random.default_rng(42)
vh = rng.standard_normal((n, V, 4)).astype(np.float64)
vh[:, :, 3] = 1.0
m3 = (rng.standard_normal((n, 4, 3)) * 0.3).astype(np.float64)
mn = np.empty((n, 3)); mx = np.empty((n, 3))

ROUNDS = 100

def bench(fn, label):
    fn(vh, m3, mn, mx)                     # 预热 (numba JIT/缓存/页)
    t0 = time.perf_counter()
    for _ in range(ROUNDS):
        fn(vh, m3, mn, mx)
    dt = (time.perf_counter() - t0) / ROUNDS * 1000
    print(f'{label:12s} {dt:8.3f} ms')
    return dt

t_c = bench(fastpath._aabbs_minmax_c, 'C 串行')
t_cp = bench(lambda a, b, c, d: fastpath._aabbs_minmax_c(a, b, c, d, par=True),
             'C 并行')

# numba 参考: fastpath 模块级实例疑似反复重编病 (0.67.0, 每调用 ~5s), 另建
# 无 cache 实例测纯编译性能 (与 C 同算法同数据)。
t_numba = None
if fastpath._NUMBA:
    from fastpath import _aabbs_minmax_impl
    from numba import njit as _njit
    _ref = _njit(nogil=True)(_aabbs_minmax_impl)
    t_numba = bench(_ref, 'numba 参考')
else:
    print('numba 参考     (不可用)')

t_np = bench(fastpath._aabbs_minmax_np, 'numpy B\'')

print('---')
ok = True
if t_numba:
    r1 = t_c / t_numba
    print(f'C/numba = {r1:.2f}x  (闸门 <=1.25: {"PASS" if r1 <= 1.25 else "FAIL"})')
    ok &= r1 <= 1.25
r2 = t_np / t_c
print(f'numpy/C = {r2:.2f}x  (闸门 >=1.5: {"PASS" if r2 >= 1.5 else "FAIL"})')
ok &= r2 >= 1.5
print('ALL PASS' if ok else 'GATE FAIL')
sys.exit(0 if ok else 1)
