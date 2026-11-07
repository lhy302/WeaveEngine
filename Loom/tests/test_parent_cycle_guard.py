# -*- coding: utf-8 -*-
"""test_parent_cycle_guard.py — GameObject.parent 直写成环保护.

背景 (_fix_summary §5 遗留 3)
----------------------------
引擎 set_parent(child, new_parent) 早已拒绝自身/子孙 (防环), 但 GameObject.parent
直写只维护双向 children, 不检查父链: 一旦写出 A->B->A, collect_subtree 会
无限递归 (保存/删除/Prefab/包围盒全走它), 直接 RecursionError 或卡死。

修复: GameObject.parent setter 在改指针前沿 v 的父链上溯, 遇到自己就
raise ValueError (拒绝且不改任何状态); 另加 10000 层上限防已损坏父链死循环。

本文件断言:
  A: 自环 (m.parent = m) 拒绝。
  B: 二元环 (a.parent=b 后 b.parent=a) 拒绝。
  C: 多元环 (a->b->c 后 c.parent=a) 拒绝。
  D: 深链 (50 层) 回挂祖先仍拒绝, 且拒绝后整条链原样。
  E: 合法换父/脱父仍工作, children 双向关系正确 (不误伤)。
  F: 被拒绝的赋值不污染旧父/新父的 children。
  G: 拒绝后 collect_subtree 仍能正常结束 (返回有限列表)。

运行: python tests/test_parent_cycle_guard.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import engine as E
from mesh import create_cube

E.GLEngine._build_gpu = lambda self, m: None

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def mk(name):
    m = E.GameObject(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                     name=name)
    m.guid = uuid.uuid4().hex
    return m


def new_eng(models):
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = models
    e.materials = []
    e.lights = []
    e.cameras = []
    e.active_camera = None
    e.current_model_index = 0
    return e


def raises_value(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def chain_ok(*pairs):
    """pairs = [(child, expected_parent), ...] 全部成立才算链完好."""
    return all(c.parent is p for c, p in pairs)


# ====================================================================
# A: 自环
# ====================================================================
def t_self_parent():
    print("=== A: 自环 ===")
    a = mk('A')
    ok = raises_value(lambda: setattr(a, 'parent', a))
    check("[A] a.parent = a -> ValueError", ok)
    check("[A] 拒绝后 parent 仍为 None", a.parent is None)
    check("[A] 拒绝后 children 仍空", list(a.children) == [])


# ====================================================================
# B: 二元环
# ====================================================================
def t_two_node_cycle():
    print("=== B: 二元环 ===")
    a, b = mk('A'), mk('B')
    a.parent = b
    ok = raises_value(lambda: setattr(b, 'parent', a))
    check("[B] a.parent=b 后 b.parent=a -> ValueError", ok)
    check("[B] 拒绝后 a.parent 仍是 b", a.parent is b)
    check("[B] 拒绝后 b.parent 仍是 None", b.parent is None)
    check("[B] 拒绝后 b.children 仍只有 a", list(b.children) == [a])
    check("[B] 拒绝后 a.children 仍空", list(a.children) == [])


# ====================================================================
# C: 多元环 (c -> a, a -> b -> c)
# ====================================================================
def t_three_node_cycle():
    print("=== C: 多元环 ===")
    a, b, c = mk('A'), mk('B'), mk('C')
    a.parent = b
    b.parent = c
    ok = raises_value(lambda: setattr(c, 'parent', a))
    check("[C] c.parent=a (a->b->c) -> ValueError", ok)
    check("[C] 拒绝后链完好", chain_ok((a, b), (b, c), (c, None)))
    ok2 = raises_value(lambda: setattr(c, 'parent', b))
    check("[C] c.parent=b (自己的孙) -> ValueError", ok2)
    check("[C] 拒绝后 c.parent 仍 None", c.parent is None)


# ====================================================================
# D: 深链回挂祖先
# ====================================================================
def t_deep_chain():
    print("=== D: 50 层深链 ===")
    nodes = [mk('N%d' % i) for i in range(50)]
    for i in range(1, 50):
        nodes[i].parent = nodes[i - 1]          # N49 -> ... -> N0
    ok = raises_value(lambda: setattr(nodes[0], 'parent', nodes[49]))
    check("[D] 根挂到最深叶 -> ValueError", ok)
    check("[D] 拒绝后根 parent 仍 None", nodes[0].parent is None)
    check("[D] 拒绝后叶 parent 仍 N48", nodes[49].parent is nodes[48])
    cur, depth = nodes[49], 0
    while cur is not None and depth < 100:
        cur = cur.parent
        depth += 1
    check("[D] 深链上溯正常结束 (50 步)", cur is None and depth == 50, depth)


# ====================================================================
# E: 合法换父/脱父不误伤
# ====================================================================
def t_valid_reparent():
    print("=== E: 合法换父/脱父 ===")
    p1, p2, c = mk('P1'), mk('P2'), mk('C')
    c.parent = p1
    check("[E] 首次挂父: p1.children=[c]", list(p1.children) == [c])
    c.parent = p2
    check("[E] 换父: 旧父摘除", list(p1.children) == [])
    check("[E] 换父: 新父登记", list(p2.children) == [c])
    check("[E] 换父: c.parent=p2", c.parent is p2)
    c.parent = None
    check("[E] 脱父: c.parent=None", c.parent is None)
    check("[E] 脱父: p2.children 清空", list(p2.children) == [])
    c.parent = p1
    c.parent = p1
    check("[E] 重复挂同一父不重复登记", list(p1.children) == [c], p1.children)


# ====================================================================
# F: 拒绝的赋值不污染 children
# ====================================================================
def t_reject_no_side_effect():
    print("=== F: 拒绝时无副作用 ===")
    a, b, c = mk('A'), mk('B'), mk('C')
    a.parent = b
    b.parent = c
    before_b, before_c = list(b.children), list(c.children)
    raises_value(lambda: setattr(c, 'parent', a))
    check("[F] b.children 未被改动", list(b.children) == before_b, b.children)
    check("[F] c.children 未被改动", list(c.children) == before_c, c.children)


# ====================================================================
# G: collect_subtree 正常结束
# ====================================================================
def t_collect_subtree_terminates():
    print("=== G: collect_subtree 仍能结束 ===")
    a, b, c, d = mk('A'), mk('B'), mk('C'), mk('D')
    a.parent = b
    b.parent = c
    raises_value(lambda: setattr(c, 'parent', a))
    d.parent = a
    e = new_eng([a, b, c, d])
    names = [m.name for m in e.collect_subtree(c)]
    check("[G] 子树 DFS = [C,B,A,D]", names == ['C', 'B', 'A', 'D'], names)
    check("[G] 结果无重复", len(names) == len(set(names)), names)


if __name__ == "__main__":
    print("========== GameObject.parent 成环保护 (_fix_summary §5 遗留 3) ==========")
    t_self_parent()
    t_two_node_cycle()
    t_three_node_cycle()
    t_deep_chain()
    t_valid_reparent()
    t_reject_no_side_effect()
    t_collect_subtree_terminates()
    print()
    if _fails:
        print("总结果: FAIL", _fails)
        sys.exit(1)
    print("总结果: ALL PASS")
