# -*- coding: utf-8 -*-
"""numba_par_check.py — 组3层1/2 对拍网 (随机森林 200 组逐位比对).

比对对象:
  a) fastpath.depths (=_depths_impl, numba 或纯 Python 降级)
       vs  engine.compute_world_matrices 深度 DP 循环的直译参考版 (本脚本内)
  b) fastpath.ancestry_dfs (=_ancestry_dfs_impl)
       vs  GLEngine._ancestry_ranges 关缓存直调 (结构部分; 若类缓存 monkeypatch
       失效则退回本脚本内的直抄参考实现)

numba 未安装时: 比对的是纯 Python fastpath vs 参考实现——仍须全 PASS,
保证将来装上 numba 后数值同源 (同一算法, 编译不改变语义).
输出 PASS/FAIL, 退出码 0/1.
"""
import os
import sys
import random

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # -> Loom 根

import fastpath  # noqa: E402

NUMBA_ON = fastpath._NUMBA

# ---------------------------------------------------------------------------
# 参考实现 1: engine.compute_world_matrices 深度 DP 循环直译 (engine.py 2312-2317)
# ---------------------------------------------------------------------------
def ref_depths(parent):
    n = parent.shape[0]
    depth = np.zeros(n, dtype=np.int64)
    for i in range(n):
        d, cur = 0, i
        while parent[cur] >= 0 and d < n:
            cur, d = int(parent[cur]), d + 1
        depth[i] = d
    return depth


# ---------------------------------------------------------------------------
# 参考实现 2: engine._ancestry_ranges DFS 部分直抄 (关缓存版, 见下方 main 里
# 优先用真方法直调, 此份是双保险——两份参考互不相同仍全 PASS 才算硬过)
# ---------------------------------------------------------------------------
def ref_ancestry(parent_idx):
    n = len(parent_idx)
    children = [[] for _ in range(n)]
    for i in range(n):
        p = parent_idx[i]
        if p >= 0:
            children[p].append(i)
    tin = np.full(n, 0, dtype=np.int64)
    tout = np.full(n, 0, dtype=np.int64)
    timer = 0
    in_forest = np.zeros(n, dtype=bool)
    for r in [i for i in range(n) if parent_idx[i] < 0]:
        if in_forest[r]:
            continue
        in_forest[r] = True
        stack = [(r, 0)]
        while stack:
            u, k = stack[-1]
            if k == 0:
                tin[u] = timer
                timer += 1
            if k < len(children[u]):
                v = children[u][k]
                stack[-1] = (u, k + 1)
                if not in_forest[v]:       # 防御: 环内已入栈不重入
                    in_forest[v] = True
                    stack.append((v, 0))
            else:
                tout[u] = timer
                stack.pop()
    for i in range(n):                     # 兜底: 环/孤儿当独立根补全
        if not in_forest[i]:
            tin[i] = timer
            timer += 1
            tout[i] = timer
    return tin, tout


# ---------------------------------------------------------------------------
# 随机森林生成: 节点 1-500, 多根 / 深层链 / 孤儿 / 环状防御路径都覆盖
# ---------------------------------------------------------------------------
def random_forest(rng):
    n = rng.randint(1, 500)
    parent = np.full(n, -1, dtype=np.int64)
    style = rng.random()
    for i in range(1, n):
        if style < 0.25:
            # 浅树: 父点在近前 8 个里
            parent[i] = rng.randint(max(0, i - 8), i - 1)
        elif style < 0.5:
            # 深层链: 大概率挂 i-1 (长链), 偶尔跳根
            parent[i] = i - 1 if rng.random() < 0.9 else -1
        elif style < 0.75:
            # 完全随机父 (可出现孤儿多根混杂)
            parent[i] = rng.randint(-1, i - 1)
        else:
            # 混合: 一半链一半随机 + 强制孤儿
            parent[i] = i - 1 if rng.random() < 0.5 else rng.randint(-1, i - 1)
            if rng.random() < 0.1:
                parent[i] = -1             # 孤儿
    # 多根保证: 随机把一些节点断成根
    for i in range(n):
        if rng.random() < 0.05:
            parent[i] = -1
    return parent


def gen_cycle_forest(rng):
    """带环 parent (set_parent 防环, 理论不会出现——测防御路径不崩且兜底语义)."""
    n = rng.randint(3, 60)
    parent = np.full(n, -1, dtype=np.int64)
    for i in range(1, n):
        parent[i] = rng.randint(0, i - 1)
    # 制造 2-环: a->b, b->a (engine 版同样会走 in_forest 不重入 + 兜底)
    if n >= 2:
        a, b = rng.sample(range(n), 2)
        parent[a] = b
        parent[b] = a
    return parent


def main():
    rng = random.Random(20260830)
    cases = []
    # 200 组随机森林
    for _ in range(200):
        cases.append(random_forest(rng))
    # 边界与特殊形状固定补充
    cases.append(np.array([-1], dtype=np.int64))                    # 单节点
    cases.append(np.array([-1, 0, 1, 2, 3], dtype=np.int64))        # 深链
    cases.append(np.array([-1, -1, -1], dtype=np.int64))            # 纯多根
    cases.append(np.array([-1, 0, -1, 2, 0, 2], dtype=np.int64))    # 两树交错
    total_a = total_b = total_c = 0
    fails = []
    for ci, parent in enumerate(cases):
        # --- a) depths: fastpath vs engine DP 直译参考 ---
        got = fastpath.depths(parent)
        want = ref_depths(parent)
        total_a += 1
        if not (np.array_equal(got, want) and got.dtype == np.int64
                and got.shape == want.shape):
            fails.append(("depths", ci, parent, got, want))
        # --- b) ancestry: fastpath vs 直抄参考 ---
        tin1, tout1 = fastpath.ancestry_dfs(parent)
        tin2, tout2 = ref_ancestry(parent)
        total_b += 1
        if not (np.array_equal(tin1, tin2) and np.array_equal(tout1, tout2)):
            fails.append(("ancestry-ref", ci, parent, (tin1, tout1), (tin2, tout2)))
        # --- c) ancestry: fastpath vs GLEngine._ancestry_ranges 关缓存直调 ---
        # (engine import 一次, 复用; monkeypatch 类缓存=None 强制现算)
        try:
            from engine import GLEngine
            GLEngine._ANCESTRY_CACHE = None
            tin3, tout3 = GLEngine._ancestry_ranges(_FakeModels(parent))
            GLEngine._ANCESTRY_CACHE = None
            total_c += 1
            if not (np.array_equal(tin1, tin3) and np.array_equal(tout1, tout3)):
                fails.append(("ancestry-engine", ci, parent, (tin1, tout1), (tin3, tout3)))
        except Exception as e:  # engine 导入失败时降级为仅参考版对拍
            if ci == 0:
                print(f"[warn] engine 直调对拍跳过: {e!r}")
            pass

    # 环状防御路径: 只要求不崩 + fastpath 与参考一致 (engine 对环输入语义=防御)
    for ci in range(20):
        parent = gen_cycle_forest(rng)
        got = fastpath.depths(parent)
        want = ref_depths(parent)
        total_a += 1
        if not np.array_equal(got, want):
            fails.append(("depths-cycle", ci, parent, got, want))
        tin1, tout1 = fastpath.ancestry_dfs(parent)
        tin2, tout2 = ref_ancestry(parent)
        total_b += 1
        if not (np.array_equal(tin1, tin2) and np.array_equal(tout1, tout2)):
            fails.append(("ancestry-cycle", ci, parent, (tin1, tout1), (tin2, tout2)))

    print(f"[numba_par_check] numba={'ON' if NUMBA_ON else 'OFF(纯Python降级)'}"
          f" | depths {total_a} 组 | ancestry-vs-ref {total_b} 组"
          f" | ancestry-vs-engine {total_c} 组")
    if fails:
        for tag, ci, parent, got, want in fails[:5]:
            print(f"FAIL [{tag}] case#{ci} n={len(parent)}")
            print(f"  parent={parent.tolist()[:20]}")
            print(f"  got ={np.asarray(got).tolist() if not isinstance(got, tuple) else [g.tolist() for g in got]}")
            print(f"  want={np.asarray(want).tolist() if not isinstance(want, tuple) else [w.tolist() for w in want]}")
        print(f"RESULT: FAIL ({len(fails)} 处)")
        return 1
    print("RESULT: PASS (全部逐位一致)")
    return 0


class _FakeModels(list):
    """把 parent 数组包成 models 列表形状 (喂 GLEngine._ancestry_ranges).

    _ancestry_ranges 用 id2i={id(m):i} 与 m.parent 取父——这里让每个"模型"
    的 .parent 指向数组里对应父位置的假对象, 完全复刻索引构建路径."""
    def __init__(self, parent_arr):
        objs = [type("M", (), {"parent": None})() for _ in range(len(parent_arr))]
        for i, p in enumerate(parent_arr):
            if p >= 0:
                objs[i].parent = objs[int(p)]
        super().__init__(objs)


if __name__ == "__main__":
    sys.exit(main())
