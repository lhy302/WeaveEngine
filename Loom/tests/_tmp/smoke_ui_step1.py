# -*- coding: utf-8 -*-
"""smoke_ui_step1.py — Canvas/UI 阶段1 第1步冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIElement, Canvas, UIManager

# 1) anchor/pivot 四种组合
PARENT = (100.0, 50.0, 400.0, 300.0)

e = UIElement('a', rect=(10, 20, 100, 40), anchor=(0, 0), pivot=(0, 0))
assert e.screen_rect(PARENT) == (110.0, 70.0, 100.0, 40.0), e.screen_rect(PARENT)

e = UIElement('b', rect=(0, 0, 100, 40), anchor=(1, 1), pivot=(1, 1))
assert e.screen_rect(PARENT) == (400.0, 310.0, 100.0, 40.0), e.screen_rect(PARENT)

e = UIElement('c', rect=(0, 0, 100, 40), anchor=(0.5, 0.5), pivot=(0.5, 0.5))
sr = e.screen_rect(PARENT)
assert abs(sr[0] - 250.0) < 1e-6 and abs(sr[1] - 180.0) < 1e-6, sr

e = UIElement('d', rect=(5, 7, 100, 40), anchor=(1, 0), pivot=(1, 0))
sr = e.screen_rect(PARENT)
assert abs(sr[0] - 405.0) < 1e-6 and abs(sr[1] - 57.0) < 1e-6, sr
print('anchor/pivot OK')

# 2) 非法 rect/anchor/pivot 钳制
e = UIElement('e', rect=(0, 0, -10, -5))
assert e.rect[2] == 0.0 and e.rect[3] == 0.0, e.rect
e.anchor = (5, -1)
assert e.anchor == (1.0, 0.0), e.anchor
e.pivot = (-2, 3)
assert e.pivot == (0.0, 1.0), e.pivot
print('clamp OK')

# 3) 树操作 + find + walk
root = UIElement('root', rect=(0, 0, 400, 300))
p1 = UIElement('p1', rect=(0, 0, 200, 100))
p2 = UIElement('p2', rect=(0, 100, 200, 100))
t1 = UIElement('t1', rect=(10, 10, 50, 20))
t2 = UIElement('t2', rect=(10, 10, 50, 20))
root.add_child(p1)
root.add_child(p2)
p1.add_child(t1)
p2.add_child(t2)

assert root.find('t2') is t2
assert root.find('nope') is None
names = [n.name for n in root.walk()]
assert names == ['root', 'p1', 't1', 'p2', 't2'], names
# 重名
dup = UIElement('t1', rect=(0, 0, 10, 10))
p2.add_child(dup)
assert len(root.find_all('t1')) == 2
print('tree/find/walk OK')

# 4) 防环
assert root.add_child(root) is root
assert root.parent is None
p1.add_child(root)   # root 是 p1 祖先, 应拒绝
assert root.parent is None and p1 in root.children
print('cycle guard OK')

# 5) 脱原父
assert t1.parent is p1
p2.add_child(t1)
assert t1.parent is p2 and t1 not in p1.children
print('reparent OK')

# 6) 命中测试 (根容器矩形用 (0,0,400,300))
ROOT = (0.0, 0.0, 400.0, 300.0)
root2 = UIElement('r', rect=(0, 0, 100, 100))
bg = UIElement('bg', rect=(0, 0, 100, 100))
fg = UIElement('fg', rect=(20, 20, 30, 30))
root2.add_child(bg)
root2.add_child(fg)
# fg 屏幕矩形 (20,20,30,30) -> 内部点用 (40,40); 边界点 (50,50) 应落在外面
assert root2.hit_test((40, 40), ROOT).name == 'fg', '重叠应命中上层'
assert root2.hit_test((10, 10), ROOT).name == 'bg'
assert root2.hit_test((500, 500), ROOT) is None
fg.visible = False
assert root2.hit_test((40, 40), ROOT).name == 'bg'
fg.visible = True
fg.enabled = False
assert root2.hit_test((40, 40), ROOT).name == 'bg'
print('boundary: (50,50) 落在半开区间外, 命中 bg ->', root2.hit_test((50, 50), ROOT).name)
print('hit_test OK')

# 7) Canvas
c = Canvas(width=800, height=600)
assert c.find('root') is c.root
c.resize(1024, 768)
assert c.root.rect == (0, 0, 1024, 768), c.root.rect
rects = c.screen_rects()
assert id(c.root) in rects
print('Canvas OK')

# 8) UIManager
m = UIManager()
c1 = Canvas(width=100, height=100, z_order=0)
c2 = Canvas(width=100, height=100, z_order=10)
m.add_canvas(c2)
m.add_canvas(c1)
assert [c.z_order for c in m.canvases] == [0, 10]
btn = UIElement('btn', rect=(0, 0, 100, 100))
c2.root.add_child(btn)
assert m.find('btn') is btn
cv, el = m.hit_test((50, 50))
assert el is btn and cv is c2
m.resize(500, 500)
assert c1.width == 500 and c2.width == 500
print('UIManager OK')
print('SMOKE_PASS')
