# -*- coding: utf-8 -*-
"""verify_ui_hit_test.py — 命中测试 (契约 §6.2, 阶段2)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, UIElement, Panel, Button

ROOT = (0.0, 0.0, 800.0, 600.0)


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# 1) 重叠取最上层
m, c = make_ui()
a = Panel('a', rect=(0, 0, 400, 400))
b = Panel('b', rect=(100, 100, 200, 200))
c.root.add_child(a)
c.root.add_child(b)
hit = c.root.hit_test((150, 150), ROOT)
assert hit is b, '重叠应命中后加的 (上层)'
print('overlap -> topmost OK')

# 2) 不可见元素及子树跳过
b.visible = False
hit = c.root.hit_test((150, 150), ROOT)
assert hit is a, '不可见元素应被跳过'
b.visible = True
print('invisible skip OK')

# 3) 禁用元素: 命中的是它时返回 None; 但其可见的父/兄弟仍可命中
b.enabled = False
hit = c.root.hit_test((150, 150), ROOT)
# 注意: b 禁用且不可交互 -> 但 b 仍然画在 a 上层, 命中测试到 b 后返回 None
# 契约 §6.2 "元素 visible 且 enabled 才参与命中" -> 禁用时整个 b 不参与, 落到 a
assert hit is a, '禁用元素应跳过, 落到父/兄弟'
b.enabled = True
print('disabled skip OK')

# 4) 半开区间边界 (右/下边界不含)
e = UIElement('e', rect=(100, 100, 50, 50))
c2 = Canvas(width=800, height=600)
c2.root.add_child(e)
assert c2.root.hit_test((100, 100), ROOT) is e, '左/上边界包含'
assert c2.root.hit_test((149, 149), ROOT) is e, '内部包含'
# 右/下边界 (150,150) 落在半开区间外 -> 不命中 e (但命中 root 本身)
assert c2.root.hit_test((150, 150), ROOT) is not e, '右/下边界不应命中 e'
print('half-open boundary OK')

# 5) 深层嵌套: 子优先于父
m3, c3 = make_ui()
outer = Panel('outer', rect=(0, 0, 500, 500))
inner = Button('inner', rect=(100, 100, 100, 40))
outer.add_child(inner)
c3.root.add_child(outer)
hit = c3.root.hit_test((150, 120), ROOT)
assert hit is inner, '子元素优先'
print('child priority OK')

# 6) UIManager.hit_test 多 Canvas: 从最上层 (最大 z_order) 往下
m4 = UIManager()
c_low = Canvas(width=800, height=600, z_order=0)
c_high = Canvas(width=800, height=600, z_order=100)
m4.add_canvas(c_low)
m4.add_canvas(c_high)
p_low = Panel('low', rect=(0, 0, 800, 600))
p_high = Panel('high', rect=(0, 0, 800, 600))
c_low.root.add_child(p_low)
c_high.root.add_child(p_high)
cv, el = m4.hit_test((400, 300))
assert cv is c_high and el is p_high, '高 z_order Canvas 优先'
print('multi canvas priority OK')

print('PASS verify_ui_hit_test')
