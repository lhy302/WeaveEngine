# -*- coding: utf-8 -*-
"""探针 3: OpenBLAS 线程数扫描 + f64 vs f32 对 aabbs matmul 的影响."""
import os
import time

import numpy as np


def bench(n_models=500, V=2035, dtype=np.float64, reps=10, threads=None):
    if threads is not None:
        os.environ['OPENBLAS_NUM_THREADS'] = str(threads)
        try:
            from threadpoolctl import threadpool_limits
        except Exception:
            pass
    rng = np.random.default_rng(7)
    vh = rng.standard_normal((n_models, V, 4)).astype(dtype)
    vh[:, :, 3] = 1.0
    m3 = rng.standard_normal((n_models, 4, 3)).astype(dtype)
    mn = np.empty((n_models, 3), dtype=dtype)
    mx = np.empty((n_models, 3), dtype=dtype)
    w = np.empty((n_models, V, 3), dtype=dtype)
    np.matmul(vh, m3, out=w)   # 预热
    t0 = time.perf_counter()
    for _ in range(reps):
        np.matmul(vh, m3, out=w)
        w.min(axis=1, out=mn)
        w.max(axis=1, out=mx)
    return (time.perf_counter() - t0) / reps * 1000


if __name__ == '__main__':
    # 环境变量法 (numpy 首次 BLAS 调用前设)
    print('=== OpenBLAS 线程扫描 (环境变量需在新进程设置, 本进程内子进程测) ===')
    import subprocess
    import sys
    code = r'''
import os, time
import numpy as np
n, V = 500, 2035
rng = np.random.default_rng(7)
vh = rng.standard_normal((n, V, 4)); vh[:,:,3]=1.0
m3 = rng.standard_normal((n, 4, 3))
mn = np.empty((n,3)); mx = np.empty((n,3))
w = np.empty((n,V,3))
np.matmul(vh, m3, out=w)
t0=time.perf_counter()
for _ in range(10):
    np.matmul(vh, m3, out=w)
    w.min(axis=1, out=mn); w.max(axis=1, out=mx)
print("%.2f" % ((time.perf_counter()-t0)/10*1000))
'''
    for th in (1, 2, 4, 8, 18):
        env = dict(os.environ)
        env['OPENBLAS_NUM_THREADS'] = str(th)
        r = subprocess.run([sys.executable, '-c', code], env=env,
                           capture_output=True, text=True, timeout=300)
        print(f'  OPENBLAS_NUM_THREADS={th}: {r.stdout.strip()} ms/帧')
    print()
    print('=== f64 vs f32 (本进程, 默认线程) ===')
    print(f'  f64: {bench(dtype=np.float64):.2f} ms')
    print(f'  f32: {bench(dtype=np.float32):.2f} ms')
