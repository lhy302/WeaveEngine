# -*- coding: utf-8 -*-
"""探针 4: 真实场景矩阵下 aabbs 全链对比 (500球 V=2035):
   - numpy 内核 (冻结/编译版走)
   - numba njit 内核 (源码版走, 源码环境有 numba)
   - 拆分 matmul vs min/max 归约
   - 80ms 恒定 (线程不敏感) 的根因: 逐模型循环 500 次 numpy 调用? 不 —— 批量一次.
     检验是否 min/max 归约 (500*2035*3=3M 元素) 是大头.
"""
import os
import time

import numpy as np

N, V = 500, 2035
rng = np.random.default_rng(7)
# 真实感矩阵: 每模型平移+旋转
ang = rng.random((N, 3)) * np.pi
def make_m3():
    from math import cos, sin
    m3 = np.zeros((N, 4, 3))
    for i in range(N):
        cx, sx = cos(ang[i, 0]), sin(ang[i, 0])
        cy, sy = cos(ang[i, 1]), sin(ang[i, 1])
        r = rng.random(3) * 40 - 20 + np.array([0, 1, 0])
        Rz = np.array([[cx, -sx, 0], [sx, cx, 0], [0, 0, 1]])
        m3[i, :3, :3] = Rz
        m3[i, 3, :] = r
    return m3
m3 = make_m3()
vh = np.empty((N, V, 4))
for i in sphere_verts if False else []:
    pass
# 球面顶点 (单位球)
st = np.linspace(0, np.pi, 37)
ct = np.linspace(0, 2 * np.pi, 55)
P, T = np.meshgrid(st, ct, indexing='ij')
vs = np.stack([0.8 * np.sin(P) * np.cos(T),
               0.8 * np.cos(P),
               0.8 * np.sin(P) * np.sin(T)], axis=-1).reshape(-1, 3)
vh[:, :, :3] = vs[None, :, :]
vh[:, :, 3] = 1.0
print('vh', vh.shape, vh.dtype, 'm3', m3.shape)

mn = np.empty((N, 3))
mx = np.einsum('ijk->', np.zeros((1,1,1)))  # dummy
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

print('=== 拆分 ===')
t('numpy matmul (n,V,4)@(n,4,3)', lambda: np.matmul(vh, m3, out=w))
w_out = np.matmul(vh, m3)
t('min axis=1', lambda: np.min(w_out, axis=1, out=mn))
t('max axis=1', lambda: np.max(w_out, axis=1, out=mx))
t('numpy 全链 (matmul+min+max)', lambda: (np.matmul(vh, m3, out=w),
                                          np.min(w, axis=1, out=mn),
                                          np.max(w, axis=1, out=mx)))

print('=== numba 串行 njit 版 (源码版路径) ===')
import sys
try:
    sys_path = os.path.dirname(os.path.abspath(__file__))
    sys.path = [os.path.dirname(sys_path)] + sys.path  # 不改 — 直接 import
except Exception:
    pass
sys.path.insert(0, r'D:\my-project\Loom(py源代码-工作区)\Loom')
import fastpath
print('  _NUMBA =', fastpath._NUMBA, ' _FROZEN =', fastpath._FROZEN)
t('numba aabbs_minmax (源码路径)', lambda: fastpath.aabbs_minmax(vh, m3, mn, mx))

print('=== numba prange 版 (500>=512? no -> 未用; 参考) ===')
try:
    t('numba aabbs_minmax_par', lambda: fastpath.aabbs_minmax_par(vh, 0, 0, 0) if False else fastpath.aabbs_minmax_par(vh, m3, mn, mx))
except Exception as e:
    print('  par:', e)

print('=== 引擎真实调用形态: 500 模型单组 (V=2035) ===')
# engine._aabbs_batched 里 groups.setdefault(V) -> 500 个全同 V -> 单组 n=500
# n=500 >= _AABB_PAR_MIN_MODELS(512)? no -> 串行 aabbs_minmax
print('  _AABB_PAR_MIN_MODELS = 512, n=500 -> 走串行 aabbs_minmax (numba=njit / 冻结=numpy)')
