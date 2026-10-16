# -*- coding: utf-8 -*-
"""P0-2 性能探针 2: 定位 90ms 异常 (exe 实测 24.9ms).
隔离变量: BLAS 线程数 / matmul 维度形态 / min/max 归约占比.
纯 ASCII 输出.
"""
import os
import sys
import time

import numpy as np

print('numpy', np.__version__)
try:
    np.show_config()
except Exception:
    pass

N, V = 500, 2035
rng = np.random.default_rng(42)
vh = rng.standard_normal((N, V, 4))
vh[:, :, 3] = 1.0
m3 = rng.standard_normal((N, 4, 3)) * 0.1
m3[:, 3, :] = 0.0
w = np.empty((N, V, 3))
mn = np.empty((N, 3)); mx = np.empty((N, 3))


def bench(fn, reps=50):
    for _ in range(3):
        fn()
    t0 = time.time()
    for _ in range(reps):
        fn()
    return (time.time() - t0) * 1000.0 / reps


t_matmul = bench(lambda: np.matmul(vh, m3, out=w))
t_minmax = bench(lambda: (w.min(axis=1, out=mn), w.max(axis=1, out=mx)))
print('matmul only : %.2f ms' % t_matmul)
print('min/max only: %.2f ms' % t_minmax)
print('sum         : %.2f ms (np 内核版全路径)' % (t_matmul + t_minmax))

# 参照: 转 (V,3) 转置归约 (旧 get_bounding_box 形态)
wT = np.empty((V, 3))
t_one = bench(lambda: np.matmul(vh[0], m3[0]))
print('single model matmul: %.3f ms -> x500 = %.1f ms' % (t_one, t_one * 500))

# f32 形态
vh32 = vh.astype(np.float32); m332 = m3.astype(np.float32)
w32 = np.empty((N, V, 3), dtype=np.float32)
t32 = bench(lambda: np.matmul(vh32, m332, out=w32))
print('f32 matmul only: %.2f ms (speedup %.2fx)'
      % (t32, t_matmul / max(t32, 1e-9)))
