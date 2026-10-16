# -*- coding: utf-8 -*-
"""P0-2 终版 (方案 B') 验收探针 (2026-09-02): aabbs numpy 降级内核连续归约布局.
1) 微基准: 旧内核 (axis=1 跨步, 复刻) vs 新内核 _aabbs_minmax_np (B')
2) 对拍: B' vs 旧内核 (f64 全程, min/max 纯比较 -> 必须逐位一致)
3) engine._aabbs_batched 全链路对拍 (默认内核 vs 强制 numpy 内核)
纯 ASCII 输出.
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..'))
import fastpath

N, V = 500, 2035
rng = np.random.default_rng(42)
vh = rng.standard_normal((N, V, 4))
vh[:, :, 3] = 1.0
m3 = rng.standard_normal((N, 4, 3)) * 0.1
m3[:, 3, :] = 0.0

fails = 0


def check(name, ok, detail=''):
    global fails
    print(('[PASS] ' if ok else '[FAIL] ') + name + (' | ' + detail if detail else ''))
    if not ok:
        fails += 1


# ---- 旧内核复刻 (axis=1 跨步, 改前形态) -------------------------------
_w_old = {}


def old_kernel(vh, m3, out_mn, out_mx):
    n, V = vh.shape[0], vh.shape[1]
    w = _w_old.get((n, V))
    if w is None:
        w = _w_old[(n, V)] = np.empty((n, V, 3), dtype=np.float64)
    np.matmul(vh, m3, out=w)
    w.min(axis=1, out=out_mn)
    w.max(axis=1, out=out_mx)
    return out_mn, out_mx


mn_old = np.empty((N, 3)); mx_old = np.empty((N, 3))
mn_new = np.empty((N, 3)); mx_new = np.empty((N, 3))

for _ in range(3):
    old_kernel(vh, m3, mn_old, mx_old)
    fastpath._aabbs_minmax_np(vh, m3, mn_new, mx_new)

t0 = time.time()
for _ in range(30):
    old_kernel(vh, m3, mn_old, mx_old)
t_old = (time.time() - t0) * 1000.0 / 30
t0 = time.time()
for _ in range(30):
    fastpath._aabbs_minmax_np(vh, m3, mn_new, mx_new)
t_new = (time.time() - t0) * 1000.0 / 30
print('old kernel (axis=1 strided): %.2f ms/call' % t_old)
print("new kernel (B-prime contiguous): %.2f ms/call  speedup %.2fx"
      % (t_new, t_old / max(t_new, 1e-9)))

# ---- 对拍: 逐位一致 (f64 纯比较无求和序) ------------------------------
check('min 逐位一致 (max abs diff %.2e)'
      % np.abs(mn_old - mn_new).max(), np.array_equal(mn_old, mn_new))
check('max 逐位一致 (max abs diff %.2e)'
      % np.abs(mx_old - mx_new).max(), np.array_equal(mx_old, mx_new))

# ---- engine 全链路: 默认 (numba) vs 强制 numpy 降级 -------------------
from engine import GLEngine
from mesh import create_sphere
eng = GLEngine.__new__(GLEngine)
eng._bb_cache = {}
eng._aabb_staging = None
mesh = create_sphere(0.8, 36, 54)
models = []
for i in range(50):
    m = type('M', (), {})()
    m.mesh = mesh
    m.visible = True
    models.append(m)
fw = [np.eye(4) for _ in range(50)]
fw[0] = fw[0].copy(); fw[0][:3, 3] = (1.0, 2.0, 3.0)

r_default = eng._aabbs_batched(models, fw)
staging_dtype = [str(v[0].dtype) for v in eng._aabb_staging.bufs.values()]
check('默认路径 staging 仍 f64 (numba 源码语义不变)',
      all(d == 'float64' for d in staging_dtype), str(staging_dtype))

# 强制走 numpy 内核 (猴子补丁分派, 模拟冻结环境)
eng._aabb_staging = None
_orig = fastpath.aabbs_minmax
fastpath.aabbs_minmax = fastpath._aabbs_minmax_np
try:
    r_np = eng._aabbs_batched(models, fw)
finally:
    fastpath.aabbs_minmax = _orig

bit_equal = all(
    a[0].x == b[0].x and a[0].y == b[0].y and a[0].z == b[0].z
    and a[1].x == b[1].x and a[1].y == b[1].y and a[1].z == b[1].z
    for a, b in zip(r_default, r_np))
check('engine 全链路: numpy B-prime 内核 vs 默认内核 逐位一致', bit_equal)

# ---- 500 球全链路基准 (单线程, 模拟冻结 exe 池前开销) -----------------
models500 = models * 10
fw500 = fw * 10
eng2 = GLEngine.__new__(GLEngine)
eng2._bb_cache = {}
eng2._aabb_staging = None
fastpath.aabbs_minmax = fastpath._aabbs_minmax_np
try:
    for _ in range(3):
        eng2._aabbs_batched(models500, fw500)
    t0 = time.time()
    for _ in range(20):
        eng2._aabbs_batched(models500, fw500)
    t_full = (time.time() - t0) * 1000.0 / 20
finally:
    fastpath.aabbs_minmax = _orig
print('engine 全链路 500球 (staging 拷贝 + B-prime 内核, 单线程): %.2f ms/call' % t_full)
print('  (冻结 exe 池化 8 worker 墙钟预期 ~%.1f-%.1f ms, 原实测 24.9ms)'
      % (t_full / 8, t_full / 4))

print('RESULT:', 'ALL PASS' if fails == 0 else 'FAIL (%d)' % fails)
sys.exit(0 if fails == 0 else 1)
