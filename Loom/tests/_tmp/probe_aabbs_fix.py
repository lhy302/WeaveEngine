# -*- coding: utf-8 -*-
"""探针 5: 冻结环境 aabbs 内核优化方案实测 (不动 numba 定案):
   A. 现状: matmul(n,V,4)@(n,4,3) -> (n,V,3), min/max axis=1 (stride 24B)
   B. 转置布局: matmul (n,3,4)@(n,4,V) -> (n,3,V), min/max axis=2 (连续)
   C. reduceat 方案: (n*V,3) 段归约
   D. f32 转置布局
   E. einsum 直出 (n,3,V)
"""
import os
import time

import numpy as np

N, V = 500, 2035
rng = np.random.default_rng(7)

# 真实感数据 (与探针4 同源)
st = np.linspace(0, np.pi, 37)
ct = np.linspace(0, 2 * np.pi, 55)
P, T = np.meshgrid(st, ct, indexing='ij')
vs = np.stack([0.8 * np.sin(P) * np.cos(T),
               0.8 * np.cos(P),
               0.8 * np.sin(P) * np.sin(T)], axis=-1).reshape(-1, 3)
vh = np.empty((N, V, 4))
vh[:, :, :3] = vs[None, :, :]
vh[:, :, 3] = 1.0
m3 = np.zeros((N, 4, 3))
from math import cos as _c, sin as _s
for i in range(N):
    a = rng.random() * np.pi
    cx, sx = _c(a), _s(a)
    m3[i, :3, :3] = [[cx, -sx, 0], [sx, cx, 0], [0, 0, 1]]
    m3[i, 3, :] = rng.random(3) * 40 - 20 + [0, 1, 0]

mn = np.empty((N, 3))
mx = np.empty((N, 3))
w = np.empty((N, V, 3))


def t(label, fn, reps=15):
    fn()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    dt = (time.perf_counter() - t0) / reps * 1000
    print(f'  {label}: {dt:.2f} ms')
    return dt


print('=== A. 现状 (冻结环境当前内核) ===')
def A():
    np.matmul(vh, m3, out=w)
    np.min(w, axis=1, out=mn)
    np.max(w, axis=1, out=mx)
t('A 全链', A)

print('=== B. 转置布局 matmul (n,3,4)@(n,4,V) -> (n,3,V) + 连续归约 ===')
# 输入转置: vh_T (n,4,V) 每帧堆叠 (真实引擎里 vh 来自 _homogeneous_vertices 缓存,
# 堆叠拷贝 vhN_T[r]=vh[r].T 与现状 vhN[r]=vh[r] 同量级, 不新增负担)
vh_T = np.ascontiguousarray(vh.transpose(0, 2, 1))
m3_T = np.ascontiguousarray(m3.transpose(0, 2, 1))
wT = np.empty((N, 3, V))
mnT = np.empty((N, 3))
mxT = np.empty((N, 3))
def B():
    np.matmul(m3_T, vh_T, out=wT)          # (n,3,4)@(n,4,V) -> (n,3,V)
    np.min(wT, axis=2, out=mnT)
    np.max(wT, axis=2, out=mxT)
t('B 全链', B)
# 数值对拍
A()
ref_mn, ref_mx = mn.copy(), mx.copy()
B()
print('  数值差 max(|mn|):', float(np.abs(mnT - ref_mn).max()),
      ' max(|mx|):', float(np.abs(mxT - ref_mx).max()))

print('=== B2. 含每帧 vh 转置堆叠的真实成本 ===')
vhN_T = np.empty((N, 4, V))
def B2():
    for r in range(N):
        vhN_T[r] = vh[r].T                 # 堆叠拷贝 (现状同量级)
    np.matmul(m3_T, vhN_T, out=wT)
    np.min(wT, axis=2, out=mnT)
    np.max(wT, axis=2, out=mxT)
t('B2 全链(含堆叠)', B2)

print('=== C. reduceat 段归约 (n*V,3) axis=0 ===')
w2 = w.reshape(N * V, 3)
idx = np.arange(0, N * V, V)
def C():
    np.matmul(vh, m3, out=w)
    np.minimum.reduceat(w2, idx, axis=0, out=mn) if False else None
    mn2 = np.minimum.reduceat(w2, idx, axis=0)
    mx2 = np.maximum.reduceat(w2, idx, axis=0)
t('C 全链(matmul+reduceat×2, 含输出分配)', C)

print('=== D. f32 转置布局 ===')
vh_T32 = vh_T.astype(np.float32)
m3_T32 = m3_T.astype(np.float32)
wT32 = np.empty((N, 3, V), dtype=np.float32)
mnT32 = np.empty((N, 3), dtype=np.float32)
mxT32 = np.empty((N, 3), dtype=np.float32)
def D():
    np.matmul(m3_T32, vh_T32, out=wT32)
    np.min(wT32, axis=2, out=mnT32)
    np.max(wT32, axis=2, out=mxT32)
t('D f32 全链', D)

print('=== E. 单次遍历伪融合: min 与 max 同一遍 (numpy 无融合, 用 umath 对比基线) ===')
# 仅测纯归约带宽: 连续 axis=2 两次遍历 vs stride axis=1 两次遍历
t('纯 min stride (现状)', lambda: np.min(w, axis=1, out=mn))
t('纯 min 连续 (转置)', lambda: np.min(wT, axis=2, out=mnT))
