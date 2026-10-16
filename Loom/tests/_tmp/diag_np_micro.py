# -*- coding: utf-8 -*-
"""diag_np_micro.py — numpy 微基准 A/B (2026-09-06 诊断代理, 任务3)

判别 "numpy 本身在 Nuitka 编译环境慢" vs "引擎调用层慢"。
同一份脚本两种运行方式:
  (a) py -3.12 diag_np_micro.py --out <json>
  (b) Nuitka standalone 编译成 exe 后 exe --out <json> (冻结环境形态)

基准项 (对齐引擎真实内核形状, n=500 主体 + V=2035 球体):
  1. batch_matmul_444 : (500,4,4)@(500,4,4)  —— compute_world_matrices 层级批
  2. aabbs_kernel     : fastpath._aabbs_minmax_np 原函数 (500,2035,4)@(500,4,3)
                        + transpose + min/max axis=2 (B' 连续归约)
  3. elementwise      : (500,4,4) f32 乘加链 (buckets f32 转换形态)
  4. np_any_row       : (500,4,4)!=(500,4,4) -> np.any(axis=(1,2)) —— aabbs 行级脏判
  5. np_empty_alloc   : np.empty (500,2035,3) f64 分配+填弃 (24.5MB/次)
  6. reduction_sum    : (500,2035,3) sum(axis=2) —— 归约形态
  7. f32_tobytes      : (4,4) f32 转换+tobytes ×500 —— uniform 上传形态
每项: 预热 3 次, 计时 repeat 轮取中位。结果写 JSON (stdout 同步打印)。
"""
import json
import os
import sys
import time

import numpy as np

N = 500
V = 2035
REPEAT = 12


def _bench(name, fn, warm=3):
    for _ in range(warm):
        fn()
    ts = []
    for _ in range(REPEAT):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    med = ts[len(ts) // 2]
    lo, hi = ts[0], ts[-1]
    print("  %-18s med=%8.3f ms  (min %.3f max %.3f)" % (name, med, lo, hi),
          flush=True)
    return {'med_ms': round(med, 4), 'min_ms': round(lo, 4),
            'max_ms': round(hi, 4)}


def main():
    rng = np.random.default_rng(7)
    # ---- 数据 (引擎同形状) ----
    fw = rng.uniform(-1, 1, (N, 4, 4))                    # 世界矩阵批
    local = rng.uniform(-1, 1, (N, 4, 4))                 # 局部矩阵批
    vh = rng.uniform(-1, 1, (N, V, 4))                    # 齐次顶点批
    m3 = rng.uniform(-1, 1, (N, 4, 3))                    # 矩阵切片批
    out_mn = np.empty((N, 3))
    out_mx = np.empty((N, 3))
    w = np.empty((N, V, 3))
    wt = np.empty((N, 3, V))
    f32m = rng.uniform(-1, 1, (N, 4, 4)).astype('f4')
    cache_fw = fw.copy()

    def aabbs_kernel():
        np.matmul(vh, m3, out=w)
        np.copyto(wt, w.transpose(0, 2, 1))
        wt.min(axis=2, out=out_mn)
        wt.max(axis=2, out=out_mx)

    def batch_matmul_444():
        return np.matmul(fw, local)                       # (500,4,4)@(500,4,4)

    def elementwise():
        return f32m * 2.0 + 1.0                           # (500,4,4) f32 链

    def np_any_row():
        return np.any(fw != cache_fw, axis=(1, 2))        # 行级脏判 (aabbs 缓存)

    def np_empty_alloc():
        buf = np.empty((N, V, 3), dtype=np.float64)       # 24.5MB
        buf[0] = 1.0
        return None

    def reduction_sum():
        return w.sum(axis=2)                              # (500,3) 归约

    def f32_tobytes():
        sink = 0
        for i in range(N):
            sink += len(f32m[i].tobytes())                # 每物体 4x4 f32 上传
        return sink

    print("[env] frozen=%s compiled=%s numpy=%s"
          % (getattr(sys, 'frozen', False),
             '__compiled__' in globals(), np.__version__), flush=True)
    results = {}
    results['env'] = {'frozen': bool(getattr(sys, 'frozen', False)),
                      'nuitka': '__compiled__' in globals(),
                      'numpy': np.__version__,
                      'python': sys.version.split()[0]}
    print("[1] batch_matmul_444 (500,4,4)@(500,4,4)", flush=True)
    results['batch_matmul_444'] = _bench('matmul444', batch_matmul_444)
    print("[2] aabbs_kernel (B': matmul+transpose+minmax)", flush=True)
    results['aabbs_kernel'] = _bench('aabbs', aabbs_kernel)
    print("[3] elementwise f32 (500,4,4)", flush=True)
    results['elementwise'] = _bench('elementwise', elementwise)
    print("[4] np_any_row (dirty check)", flush=True)
    results['np_any_row'] = _bench('any_row', np_any_row)
    print("[5] np_empty_alloc (500,2035,3) f64", flush=True)
    results['np_empty_alloc'] = _bench('empty', np_empty_alloc)
    print("[6] reduction_sum (500,2035,3) axis=2", flush=True)
    results['reduction_sum'] = _bench('reduce', reduction_sum)
    print("[7] f32_tobytes x500", flush=True)
    results['f32_tobytes'] = _bench('tobytes', f32_tobytes)

    out = None
    for i, a in enumerate(sys.argv):
        if a == '--out' and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("[done]", out, flush=True)


if __name__ == '__main__':
    main()
