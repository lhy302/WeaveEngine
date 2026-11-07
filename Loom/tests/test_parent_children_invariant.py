# -*- coding: utf-8 -*-
"""
test_parent_children_invariant.py — parent/children 双向不变式回归
(scan_01_core P-09, 2026-11-07)

背景
----
`GameObject.parent` setter 原本只写 transform.parent + bump 引擎结构代, 不维护
children。脚本/编辑器"直写 parent"后, 旧父仍把该子树算在自己名下:
  eng.set_parent(c, p)  -> P.children=[C], c.parent=P
  c.parent = q          -> P.children=[C] (脏), Q.children=[] (缺失), c.parent=Q
后果: collect_subtree(P) 仍返回 [P,C], remove_subtree(P) 会误删已移走的 C;
Q 的子树不完整。

本文件断言:
  A: set_parent 后双向关系一致。
  B: 直写 parent 到新父 -> 旧父摘除、新父登记、collect_subtree 两边都正确。
  C: 直写 parent = None -> 从旧父摘除。
  D: 重复写同一父 / 新父 children 已有该子 (sceneio 旧调用点先 append 再赋值)
     不产生重复登记 (幂等)。
  E: 改挂后 children 顺序保持 (旧父剩余子顺序不变)。
  F: sceneio 场景 round-trip 后 children 表恰好 1 项 (旧 `_link_by_map` 会再 append
     一次, 幂等列表必须兜住)。
  G: remove_subtree(父) 连子树删 —— 直写挂出的子树同样生效。

运行: python tests\test_parent_children_invariant.py   (无头, 无 GPU)
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

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def mk(name, pos=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    m = E.GameObject(create_cube(1.0), E.Point3D(*pos), E.Point3D(*rot),
                     name=name, scale=scale)
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


def names(lst):
    return [x.name for x in lst]


# ====================================================================
# A: set_parent 双向关系
# ====================================================================
def t_set_parent_bidirectional():
    p, c = mk('P'), mk('C')
    e = new_eng([p, c])
    e.set_parent(c, p)
    check("[A] c.parent is p", c.parent is p)
    check("[A] p.children == [c]", p.children == [c], names(p.children))
    check("[A] 子树 [P,C]", names(e.collect_subtree(p)) == ['P', 'C'])


# ====================================================================
# B: 直写 parent 到新父
# ====================================================================
def t_direct_write_reparent():
    p, q, c = mk('P'), mk('Q'), mk('C')
    e = new_eng([p, q, c])
    e.set_parent(c, p)
    c.parent = q
    check("[B] c.parent is q", c.parent is q)
    check("[B] 旧父 P.children 已摘除", p.children == [], names(p.children))
    check("[B] 新父 Q.children == [c]", q.children == [c], names(q.children))
    check("[B] collect_subtree(P) 只剩 P", names(e.collect_subtree(p)) == ['P'],
          names(e.collect_subtree(p)))
    check("[B] collect_subtree(Q) = [Q,C]", names(e.collect_subtree(q)) == ['Q', 'C'],
          names(e.collect_subtree(q)))


# ====================================================================
# C: 直写 parent = None
# ====================================================================
def t_direct_write_detach():
    p, c = mk('P'), mk('C')
    e = new_eng([p, c])
    e.set_parent(c, p)
    c.parent = None
    check("[C] c.parent is None", c.parent is None)
    check("[C] P.children 空", p.children == [], names(p.children))
    check("[C] 子树只剩 P", names(e.collect_subtree(p)) == ['P'])


# ====================================================================
# D: 幂等 (重复写同一父 / 新父已手工登记)
# ====================================================================
def t_idempotent():
    p, q, c = mk('P'), mk('Q'), mk('C')
    e = new_eng([p, q, c])
    e.set_parent(c, p)
    c.parent = p
    c.parent = p
    check("[D] 重复写同一父不重复登记", p.children == [c], names(p.children))
    # 模拟 sceneio._link_by_map: 先手工 append 再写 parent
    q.children.append(c)
    c.parent = q
    check("[D] 新父已含该子时不重复", q.children == [c], names(q.children))
    check("[D] 旧父已摘除", p.children == [], names(p.children))
    # 模拟 sceneio 顺序: 写 parent 后旧调用点再 append 一次
    p2 = mk('P2')
    e.models.append(p2)
    c.parent = p2
    p2.children.append(c)
    check("[D] parent 后再 append 一次仍 1 项", p2.children == [c], names(p2.children))


# ====================================================================
# E: 改挂后旧父剩余子顺序
# ====================================================================
def t_order_kept():
    p, q, c1, c2, c3 = mk('P'), mk('Q'), mk('C1'), mk('C2'), mk('C3')
    e = new_eng([p, q, c1, c2, c3])
    for c in (c1, c2, c3):
        e.set_parent(c, p)
    c1.parent = q
    check("[E] P.children 保持 [C2,C3]", p.children == [c2, c3], names(p.children))
    check("[E] Q.children == [C1]", q.children == [c1], names(q.children))


# ====================================================================
# F: sceneio round-trip children 不重复
# ====================================================================
def t_scene_roundtrip():
    import sceneio as S
    a, b, c = mk('A', (0, 0, 0)), mk('B', (2, 0, 0)), mk('C', (1, 0, 0))
    e = new_eng([a, b, c])
    e.set_parent(b, a)
    e.set_parent(c, b)
    data = S.scene_to_dict(e)
    e2 = new_eng([])
    S.scene_from_dict(e2, data)
    gmap = {m.guid: m for m in e2.models}
    ra, rb, rc = gmap[a.guid], gmap[b.guid], gmap[c.guid]
    check("[F] 父链恢复", rb.parent is ra and rc.parent is rb)
    check("[F] A.children 恰好 [B]", ra.children == [rb], names(ra.children))
    check("[F] B.children 恰好 [C]", rb.children == [rc], names(rb.children))
    check("[F] 无重复登记 (len==1)", len(ra.children) == 1 and len(rb.children) == 1)
    check("[F] collect_subtree(A) = [A,B,C]",
          names(e2.collect_subtree(ra)) == ['A', 'B', 'C'])


# ====================================================================
# G: 删父连子树删 (直写挂出的子树)
# ====================================================================
def t_remove_subtree():
    p, c, g, other = mk('P'), mk('C'), mk('G'), mk('O')
    e = new_eng([p, c, g, other])
    c.parent = p                    # 直写挂父
    g.parent = c
    check("[G] 直写后子树 [P,C,G]",
          names(e.collect_subtree(p)) == ['P', 'C', 'G'])
    e.remove_subtree(p)
    check("[G] remove_subtree(P) 连子树删", [m.name for m in e.models] == ['O'],
          [m.name for m in e.models])
    check("[G] 未受牵连的 O 仍在", other in e.models)


if __name__ == "__main__":
    print("========== parent/children 双向不变式 (scan_01 P-09) ==========")
    t_set_parent_bidirectional()
    t_direct_write_reparent()
    t_direct_write_detach()
    t_idempotent()
    t_order_kept()
    t_scene_roundtrip()
    t_remove_subtree()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
