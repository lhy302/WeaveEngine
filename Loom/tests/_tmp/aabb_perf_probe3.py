# -*- coding: utf-8 -*-
"""P0-2 性能探针 3: 内核形态对比 (min/max 归约布局优化).
背景: 探针2 实锤 matmul 9ms + min/max axis=1 (中轴跨步) 77ms = 85.6ms 单线程.
exe 实测 aabbs 24.9ms = 帧池 8 worker 分块后的墙钟 (500>=64 阈值).
本探针对比内核形态 (单线程, OPENBLAS_NUM_THREADS=1 稳定):
  A) 现状: matmul->(n,V,3) + min/max axis=1 (跨步)
  B) matmul + ascontiguous 转置 + min/max axis=1 (连续中轴)
  C) einsum 'ivk,kj->ijv' -> (n,3,V) + min/max axis=2 (连续末轴)
  D) C 的 f32 版
纯 ASCII 输出.
"""
import os
import sys
import time

import numpy as np

N, V = 500, 2035
rng = np.random.default_rng(42)
vh = rng.standard_normal((N, V, 4))
vh[:, :, 3] = 1.0
m3 = rng.standard_normal((N, 4, 3)) * 0.1
m3[:, 3, :] = 0.0


def bench(fn, reps=30):
    for _ in range(3):
        fn()
    t0 = time.time()
    for _ in range(reps):
        fn()
    return (time.time() - t0) * 1000.0 / reps


mn = np.empty((N, 3)); mx = np.empty((N, 3))

# A) 现状内核
w = np.empty((N, V, 3))


def ker_a():
    np.matmul(vh, m3, out=w)
    w.min(axis=1, out=mn)
    w.max(axis=1, out=mx)


t_a = bench(ker_a)

# B) matmul + 转置连续化
wt = np.empty((N, 3, V))


def ker_b():
    np.matmul(vh, m3, out=w)
    np.copyto(wt, w.transpose(0, 2, 1))
    wt.min(axis=2, out=mn)
    wt.max(axis=2, out=mx)


t_b = bench(ker_b)

# C) einsum 一步到 (n,3,V)
we = np.empty((N, 3, V))


def ker_c():
    np.einsum('nvk,nkj->njv', vh, m3, out=we)
    we.min(axis=2, out=mn)
    we.max(axis=2, out=mx)


try:
    t_c = bench(ker_c)
except Exception as exc:
    print('C failed:', exc)
    t_c = float('nan')

# C2) einsum optimize=True (可能走 BLAS)
we2 = np.empty((N, 3, V))


def ker_c2():
    np.einsum('nvk,nkj->njv', vh, m3, out=we2, optimize=True)
    we2.min(axis=2, out=mn)
    we2.max(axis=2, out=mx)


try:
    t_c2 = bench(ker_c2)
except Exception as exc:
    print('C2 failed:', exc)
    t_c2 = float('nan')

# D) C 的 f32 版 (vh/m3 预转 f32, 模拟 engine staging f32)
vh32 = np.ascontiguousarray(vh.astype(np.float32))
m332 = np.ascontiguousarray(m3.astype(np.float32))
we32 = np.empty((N, 3, V), dtype=np.float32)
mn32 = np.empty((N, 3), dtype=np.float32)
mx32 = np.empty((N, 3), dtype=np.float32)


def ker_d():
    np.einsum('nvk,nkj->njv', vh32, m332, out=we32)
    we32.min(axis=2, out=mn32)
    we32.max(axis=2, out=mx32)


try:
    t_d = bench(ker_d)
except Exception as exc:
    print('D failed:', exc)
    t_d = float('nan')

# D2) f32: matmul 到 (n,V,3) f32 + min/max axis=1 (现状布局 f32)
w32 = np.empty((N, V, 3), dtype=np.float32)


def ker_d2():
    np.matmul(vh32, m332, out=w32)
    w32.min(axis=1, out=mn32)
    w32.max(axis=1, out=mx32)


t_d2 = bench(ker_d2)

# 正确性: C vs A, D vs A (f32 容差)
np.matmul(vh, m3, out=w)
ref_mn = w.min(axis=1); ref_mx = w.max(axis=1)
np.einsum('nvk,nkj->njv', vh, m3, out=we)
scale = np.linalg.norm(ref_mx - ref_mn, axis=1) / 2 + 1e-9
err_c = np.linalg.norm(mn - ref_mn, axis=1) / scale
print('C vs A max rel err: %.2e' % err_c.max())
np.einsum('nvk,nkj->njv', vh32, m332, out=we32)
mnf = we32.min(axis=2).astype(np.float64)
mxf = we32.max(axis=2).astype(np.float64)
err_d = np.linalg.norm(mnf - ref_mn, axis=1) / scale
print('D vs A max rel err: %.2e' % err_d.max())

print('')
print('A matmul+strided minmax (f64, 现状): %.2f ms' % t_a)
print('B matmul+transpose+contig minmax   : %.2f ms' % t_b)
print('C einsum->(n,3,V)+axis2 minmax     : %.2f ms' % t_c)
print('C2 einsum optimize=True            : %.2f ms' % t_c2)
print('D einsum f32 ->(n,3,V)+axis2       : %.2f ms' % t_d)
print('D2 matmul f32 +strided minmax      : %.2f ms' % t_d2)
print('')
print('池化预期 (8 worker, /8 粗估):')
for name, t in (('A', t_a), ('B', t_b), ('C', t_c), ('D', t_d), ('D2', t_d2)):
    print('  %s -> %.2f ms/块 (x2 块同步余量 ~%.1f ms)'
          % (name, t / 8, t / 8 * 2))
