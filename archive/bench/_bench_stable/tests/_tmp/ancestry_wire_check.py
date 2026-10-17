# -*- coding: utf-8 -*-
"""ancestry_wire_check.py — 组3层2 接线验证 (D1):
GLEngine._ancestry_ranges 已把 DFS 计算委托 fastpath.ancestry_dfs 后,
用 6 种手造树逐位对拍 (engine 接线版 vs 旧内联 DFS 直译参考版)。

比对对象:
  a) GLEngine._ancestry_ranges(models, gen=1)   —— 接线后真路径 (fastpath 委托 + 缓存)
  b) ref_ranges(models)                          —— engine.py 旧 2654-2686 内联实现直译
                                                     (children 列表 + 栈式 tin/tout + 兜底)

6 种树:
  ①线性链10层 ②宽扇出1父32子 ③三棵独立森林 ④单根单叶
  ⑤环状父链 (防御隔离) ⑥孤儿混合 (parent 指向不在 models 的对象)

场景⑤⑥用只带 .parent 属性的 stub 对象直接构造 —— _ancestry_ranges 是
@staticmethod, 只读 m.parent, 不需要真引擎实例。
输出每场景 PASS/FAIL, 退出码 0/1。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # -> Loom 根

from engine import GLEngine  # noqa: E402


# ---------------------------------------------------------------------------
# 参考实现: engine.py 旧 2648-2686 直译 (parent_idx 构建 + children 列表 +
# 栈式 DFS + 兜底), 与接线前的内联代码逐行同构。
# ---------------------------------------------------------------------------
def ref_ranges(models):
    n = len(models)
    id2i = {id(m): i for i, m in enumerate(models)}
    parent_idx = np.full(n, -1, dtype=np.int64)
    for i, m in enumerate(models):
        if m.parent is not None:
            parent_idx[i] = id2i.get(id(m.parent), -1)
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


class _Stub:
    """只带 .parent 的最小桩 (引擎对 models 元素仅读 .parent)。"""
    __slots__ = ('parent',)

    def __init__(self, parent=None):
        self.parent = parent


def _chain(n):
    """线性链 n 层: m0 为根, mi.parent = m(i-1)。"""
    models = [_Stub()]
    for _ in range(n - 1):
        models.append(_Stub(models[-1]))
    return models


def _fanout(width):
    """1 父 width 子宽扇出。"""
    root = _Stub()
    return [root] + [_Stub(root) for _ in range(width)]


def _forest3():
    """三棵独立树拼成一个 models 森林 ( sizes 3/2/4, 根序 = 下标升序)。"""
    a = _chain(3)
    b = _chain(2)
    c0 = _Stub()
    c1, c2 = _Stub(c0), _Stub(c0)
    c3 = _Stub(c2)
    return a + b + [c0, c1, c2, c3]


def _single_root_leaf():
    """单根单叶。"""
    return _chain(2)


def _cycle():
    """环状父链 (防御隔离): 3-环 A→B→C→A + 2-环 D↔E (parent 全在 models 内,
    无根可走, 主 DFS 不启动, 全靠兜底逐个补 tin/tout)。"""
    a, b, c = _Stub(), _Stub(), _Stub()
    a.parent, b.parent, c.parent = b, c, a
    d, e = _Stub(), _Stub()
    d.parent, e.parent = e, d
    return [a, b, c, d, e]


def _orphan_mix():
    """孤儿混合: parent 指向不在 models 的对象 -> 视为根; 与正常树/双根混排。"""
    detached = _Stub()                 # 故意不放进 models
    o0 = _Stub()                       # 根
    o1, o2 = _Stub(o0), _Stub(o0)
    o3 = _Stub(detached)               # 孤儿 (父不在 models) -> 根
    o4 = _Stub(o3)
    o5 = _Stub()                       # 第二个 None 根
    o6 = _Stub(o1)
    o7 = _Stub(o5)
    return [o0, o1, o2, o3, o4, o5, o6, o7]


def build_scenarios():
    """一次性构造全部 6 场景并整表持有 (对象全程存活, 防 id 复用串缓存)。"""
    return [
        ("①线性链10层", _chain(10)),
        ("②宽扇出1父32子", _fanout(32)),
        ("③三棵独立森林", _forest3()),
        ("④单根单叶", _single_root_leaf()),
        ("⑤环状父链(防御隔离)", _cycle()),
        ("⑥孤儿混合", _orphan_mix()),
    ]


def main():
    scenarios = build_scenarios()
    print(f"numba 加速: fastpath._NUMBA 已在 engine 导入时决定 (wire 走真路径)")
    print(f"6 场景, 每场景 GLEngine._ancestry_ranges(models, gen=1) vs ref_ranges 逐位比对\n")
    all_ok = True
    for idx, (name, models) in enumerate(scenarios, 1):
        GLEngine._ANCESTRY_CACHE = None          # 场景间清类级缓存, 防 (id, gen) 撞键误命中
        tin, tout = GLEngine._ancestry_ranges(models, gen=1)
        rtin, rtout = ref_ranges(models)
        ok = np.array_equal(tin, rtin) and np.array_equal(tout, rtout)
        all_ok = all_ok and ok
        print(f"场景{idx} {name}: n={len(models)}  {'PASS' if ok else 'FAIL'}")
        if not ok:
            print(f"  engine tin={np.asarray(tin).tolist()} tout={np.asarray(tout).tolist()}")
            print(f"  ref    tin={rtin.tolist()} tout={rtout.tolist()}")
    print()
    print("总结果:", "ALL 6 PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
