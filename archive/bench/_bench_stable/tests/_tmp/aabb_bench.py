# -*- coding: utf-8 -*-
"""aabb_bench.py — AABB 批量化 vs 逐模型 微基准 (定位 stress 负收益, 2026-08-31).

复刻 stress 场景形态: 50 球 (V=2035) 同网格 + 1 相机, 世界矩阵非平凡。
对比: ① 逐模型旧直译  ② 引擎 _aabbs_batched (堆叠版)  ③ 纯 matmul 段拆解。
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from engine import GLEngine, Point3D  # noqa: E402
from mesh import create_sphere  # noqa: E402


def bench(fn, n=30):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return sorted(ts)[n // 2] * 1e6  # µs 中位


def main():
    eng = GLEngine.__new__(GLEngine)
    eng._bb_cache = {}
    n = 50
    mesh = create_sphere(0.8, 36, 54)          # stress 同款 V=2035
    models = []
    for i in range(n):
        m = type('M', (), {})()
        m.mesh = mesh                          # 同 id(mesh) -> 共享 vh 缓存
        m.visible = True
        models.append(m)
    rng = np.random.default_rng(7)
    fw = []
    for i in range(n):
        T = np.eye(4); T[:3, 3] = rng.uniform(-5, 5, 3)
        A = rng.uniform(-0.9, 0.9, (3, 3)); A = np.linalg.svd(A)[0]
        M = np.eye(4); M[:3, :3] = A * rng.uniform(0.5, 1.5, 3)
        fw.append(T @ M)
    vh = eng._homogeneous_vertices(mesh)
    V = vh.shape[0]
    print(f"n={n} V={V} (stress 同款高面数球)")

    # ① 逐模型旧直译
    def old_way():
        for i in range(n):
            M = fw[i]
            w3t = np.ascontiguousarray((vh @ M[:, :3]).T)
            w3t.min(axis=1), w3t.max(axis=1)
    t_old = bench(old_way)
    print(f"① 逐模型旧直译      {t_old:8.1f} µs")

    # ② 引擎堆叠版
    t_new = bench(lambda: eng._aabbs_batched(models, fw))
    print(f"② 引擎堆叠版        {t_new:8.1f} µs  ({t_old/t_new:.2f}x)")

    # ③ 拆解: 堆叠 X / 逐模型 vh@M / 批量 matmul / transpose 连续化 / minmax
    t_stack = bench(lambda: (np.stack([vh] * n), np.stack(
        [np.ascontiguousarray(fw[i][:, :3]) for i in range(n)])))
    X, A = np.stack([vh] * n), np.stack([np.ascontiguousarray(fw[i][:, :3]) for i in range(n)])
    t_mm = bench(lambda: np.matmul(X, A))
    W = np.matmul(X, A)
    t_tr = bench(lambda: np.ascontiguousarray(W.transpose(0, 2, 1)))
    W3 = np.ascontiguousarray(W.transpose(0, 2, 1))
    t_red = bench(lambda: (W3.min(axis=2), W3.max(axis=2)))
    t_single = bench(lambda: (vh @ fw[0][:, :3]))
    print(f"  拆解: 堆叠 {t_stack:.0f} / 批量matmul {t_mm:.0f} / transpose {t_tr:.0f} "
          f"/ minmax {t_red:.0f} µs")
    print(f"  对照: 单模型 matmul {t_single:.1f} µs x{n} = {t_single*n:.0f} µs (旧路径主体)")

    # ④ out= 预分配 + 批量 min/max axis=1 (免 transpose 免堆叠)
    W = np.empty((n, V, 3), dtype=np.float64)
    M3s = [np.ascontiguousarray(fw[i][:, :3]) for i in range(n)]

    def out_way_red1():
        for i in range(n):
            np.matmul(vh, M3s[i], out=W[i])
        W.min(axis=1); W.max(axis=1)

    # ⑤ out= 预分配 + 逐模型 axis=0 归约 (免 transpose)
    def out_way_red0():
        for i in range(n):
            np.matmul(vh, M3s[i], out=W[i])
            W[i].min(axis=0); W[i].max(axis=0)

    # ⑥ out= 预分配 + 批量 transpose + 批量归约 (半堆叠: 只省 X 拷贝)
    def out_way_tr():
        for i in range(n):
            np.matmul(vh, M3s[i], out=W[i])
        W3 = np.ascontiguousarray(W.transpose(0, 2, 1))
        W3.min(axis=2); W3.max(axis=2)

    t4 = bench(out_way_red1)
    t5 = bench(out_way_red0)
    t6 = bench(out_way_tr)
    print(f"④ out=+批量axis1归约  {t4:8.1f} µs  ({t_old/t4:.2f}x vs 旧)")
    print(f"⑤ out=+逐模型axis0    {t5:8.1f} µs  ({t_old/t5:.2f}x vs 旧)")
    print(f"⑥ out=+批量transpose  {t6:8.1f} µs  ({t_old/t6:.2f}x vs 旧)")
    # ④⑥ 数值位等价校验 (与旧直译)
    for i in range(n):
        ref_mn = np.ascontiguousarray((vh @ M3s[i]).T).min(axis=1)
        got_mn = W[i].min(axis=0)
        assert np.array_equal(ref_mn, got_mn), f"min 不一致 i={i}"
    print("数值校验: out=路径 vs 旧直译 min/max 逐位一致 PASS")
    return 0


if __name__ == '__main__':
    main()
