# -*- coding: utf-8 -*-
"""diag_aabb_scale_probe.py — aabbs 内核 n-缩放 + BLAS 线程 A/B (任务5 残段)

背景: 播放态 aabbs 走行级缓存 dirty 路径 (100/501 行), 池分块 6-7 行/块,
实测每块 ~3.4ms (微基准推算 0.26ms, 13× 异常)。本探针单进程直测:
  1. fastpath.aabbs_minmax 在 n=7/16/32/64/100/500 的墙钟 (冻结模拟内核)
  2. OMP/BLAS 线程数 = 默认 vs 1 的对比 (子进程 env 控制)
输出 stdout 表格。
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.environ.setdefault('LOOM_NO_NUMBA', '1')   # 冻结模拟内核 (_aabbs_minmax_np)
import fastpath                                    # noqa: E402

V = 2035
rng = np.random.default_rng(3)


def bench_n(n, repeat=30):
    vh = rng.uniform(-1, 1, (n, V, 4))
    m3 = rng.uniform(-1, 1, (n, 4, 3))
    mn = np.empty((n, 3))
    mx = np.empty((n, 3))
    for _ in range(3):
        fastpath.aabbs_minmax(vh, m3, mn, mx)
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fastpath.aabbs_minmax(vh, m3, mn, mx)
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    return ts[len(ts) // 2]


def main():
    print("[env] OMP_NUM_THREADS=%s OPENBLAS_NUM_THREADS=%s numpy_threads=%s"
          % (os.environ.get('OMP_NUM_THREADS'),
             os.environ.get('OPENBLAS_NUM_THREADS'),
             getattr(np.__config__, 'blas_opt_info', {}).get(
                 'define_macros', '?')), flush=True)
    try:
        from threadpoolctl import threadpool_info
        for t in threadpool_info():
            print("  tpl: %s internal=%s" % (t.get('internal_api'),
                                             t.get('num_threads')), flush=True)
    except ImportError:
        print("  (threadpoolctl 不可用, 跳过)", flush=True)
    print("\nn-缩放 (默认 BLAS 线程):", flush=True)
    for n in (7, 16, 32, 64, 100, 200, 500):
        med = bench_n(n)
        print("  n=%-4d med=%8.3f ms  (%.4f ms/行)" % (n, med, med / n),
              flush=True)


if __name__ == '__main__':
    main()
