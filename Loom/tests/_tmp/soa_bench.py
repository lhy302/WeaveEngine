# -*- coding: utf-8 -*-
"""soa_bench.py — 组3层1 SoA 采集段性能对比 (旧属性链 vs 新快照, 2026-08-31).

复用 soa_val_check 的场景构造与新旧采集函数, 每场景复制基础树到 200 物体
(copy.deepcopy 整份复制, 份间对象独立、份内父子引用由 memo 保持; 基础场景
均为父在子前排列, 截断 [:200] 只可能切最后一份尾部叶子, parent 仍指向份内
保留物体, 不产生孤儿 —— 附 sanity 断言验证).

计时口径 (协调者指令): 只计采集段, 组装段新旧同款不计。
  旧 = old_collect (9 次属性链列取) + old_parent_depth (id2i+parent+深度while)
  新 = new_collect (_transform_snapshot + id2i+parent + fastpath.depths)
两侧均含等量的 id2i/parent 构建, 对比公平。

公平性关键: _transform_snapshot 带 _soa_snap 缓存 (stamp+keys 命中直接返回),
若不失效, 第 2 遍起测的是缓存命中而非真实重建。故新路径每遍计时前调
engine._bump_struct() 强制失效 (生产热路径: 物理/脚本每帧换属性对象必失效,
失效重建即最常见路径)。缓存命中收益另列一组对照 (供参考)。

numba 预热: fastpath.depths 首调触发 njit 编译 (cache=True), 计时前对 200
规模数组预热一次, 编译耗时计入报告头但绝不进计时。
"""
import copy
import gc
import os
import sys
import time
from statistics import median

import numpy as np

# 脚本在 tests/_tmp/ 下, 比既有 tests/*.py 深一层: 三重 dirname 到 Loom 根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import GLEngine                                   # noqa: E402
import fastpath                                               # noqa: E402
from soa_val_check import (SCENES, old_collect,               # noqa: E402
                           old_parent_depth, new_collect)

N_TARGET = 200
REPEAT = 50


def build_200(fn):
    """基础树 deepcopy 逐份堆到 >=200, 截断到恰好 200。附孤儿断言。"""
    base = fn()
    models = []
    while len(models) < N_TARGET:
        models.extend(copy.deepcopy(base))
    models = models[:N_TARGET]
    # sanity: 无孤儿 (parent 要么 None 要么在列表内), 截断安全
    idset = {id(m) for m in models}
    for m in models:
        assert m.parent is None or id(m.parent) in idset, "截断产生孤儿!"
    return models


def main():
    e = GLEngine.__new__(GLEngine)
    gc.collect()

    print("=" * 78)
    print(f"soa_bench: 采集段对比 (旧属性链 vs 新快照), n={N_TARGET}/场景, "
          f"{REPEAT} 遍取中位, 每遍前 _bump_struct() 强制快照失效")
    print(f"numba: {'可用 v' + __import__('numba').__version__ if fastpath._NUMBA else '未装(纯Python降级)'}")

    # ---- numba 预热 (编译不计时) ----
    dummy = np.arange(N_TARGET - 1, -1, -1, dtype=np.int64)  # 最坏: 199层链
    dummy[:-1] = np.arange(1, N_TARGET, dtype=np.int64)      # parent[i]=i+1, 链爬根
    dummy[-1] = -1
    t0 = time.perf_counter()
    fastpath.depths(dummy)
    print(f"numba depths 预热(200节点199层链, 含首次JIT编译): "
          f"{(time.perf_counter() - t0) * 1e3:.1f} ms (不进计时)")

    print("=" * 78)
    print(f"{'场景':<14}{'旧us':>10}{'新us':>10}{'倍率':>8}   逐位对拍")
    print("-" * 78)

    speedups = []
    sum_old = sum_new = 0.0
    for name, fn in SCENES:
        models = build_200(fn)

        # sanity 对拍 (不计时): 200 物体下新旧采集逐位一致
        o_pos, o_rot, o_scl = old_collect(models)
        o_par, o_dep = old_parent_depth(models)
        e._bump_struct()
        n_pos, n_rot, n_scl, n_par, n_dep = new_collect(e, models)
        same = (np.array_equal(o_pos, n_pos) and np.array_equal(o_rot, n_rot)
                and np.array_equal(o_scl, n_scl) and np.array_equal(o_dep, n_dep))

        # 旧路径计时
        ts_old = []
        for _ in range(REPEAT):
            t0 = time.perf_counter()
            old_collect(models)
            old_parent_depth(models)
            ts_old.append(time.perf_counter() - t0)

        # 新路径计时 (每遍前强制快照失效 = 真实重建)
        ts_new = []
        for _ in range(REPEAT):
            e._bump_struct()
            t0 = time.perf_counter()
            new_collect(e, models)
            ts_new.append(time.perf_counter() - t0)

        med_old = median(ts_old) * 1e6
        med_new = median(ts_new) * 1e6
        sp = med_old / med_new
        speedups.append(sp)
        sum_old += med_old
        sum_new += med_new
        print(f"{name:<14}{med_old:>10.1f}{med_new:>10.1f}{sp:>7.2f}x   "
              f"{'OK' if same else 'MISMATCH!'}")

    # 参考组: 缓存命中 (不失效连调) 的成本
    models = build_200(SCENES[0][1])
    e._bump_struct()
    new_collect(e, models)                    # 先建缓存
    t0 = time.perf_counter()
    for _ in range(REPEAT):
        new_collect(e, models)
    hit_us = (time.perf_counter() - t0) / REPEAT * 1e6

    print("-" * 78)
    print(f"平均倍率 (6场景算术平均): {sum(speedups) / len(speedups):.2f}x")
    print(f"总耗时比 (Σ旧/Σ新中位):   {sum_old / sum_new:.2f}x")
    print(f"参考: 快照缓存命中路径 (场景①, 不失效): {hit_us:.1f} us "
          f"(vs 失效重建, 体现结构/属性未变帧的额外收益)")
    print("=" * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
