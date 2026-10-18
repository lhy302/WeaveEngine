# -*- coding: utf-8 -*-
"""verify_ui_button_slider_toggle.py — 四种交互元素状态流转 (契约 §3.3, 阶段2)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Button, Slider, Toggle, ProgressBar


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# ---- Button: 四态 + 按下松开同元素 ----
m, c = make_ui()
hits = []
btn = Button('b', rect=(100, 100, 120, 40), on_click=lambda: hits.append(1))
c.root.add_child(btn)
assert btn._hover is False and btn._pressed is False
m.dispatch_mouse((110, 110), set(), set())
assert btn._hover is True
assert btn._pressed is False
m.dispatch_mouse((110, 110), {1}, set())
assert btn._pressed is True
m.dispatch_mouse((110, 110), set(), {1})
assert btn._pressed is False and len(hits) == 1
print('button normal/hover/pressed/click OK')

# ---- Button: 按下移出后松开不触发 ----
hits.clear()
m.dispatch_mouse((110, 110), {1}, set())
m.dispatch_mouse((700, 500), set(), set())   # 移出
m.dispatch_mouse((700, 500), set(), {1})     # 松在外部
assert len(hits) == 0
print('button drag-out cancel OK')

# ---- Slider: min/max 钳制 + 拖拽锁定 ----
m, c = make_ui()
vals = []
sl = Slider('s', rect=(100, 100, 200, 24), min_value=0, max_value=100, value=0,
            on_change=lambda v: vals.append(v))
c.root.add_child(sl)
# 拖拽
m.dispatch_mouse((150, 110), {1}, set())
assert sl._dragging is True
m.dispatch_mouse((250, 110), set(), set())
assert abs(sl.value - 75) < 1, sl.value    # (250-100)/200 * 100 = 75
m.dispatch_mouse((500, 110), set(), set())  # 超出右边界
assert sl.value == 100
m.dispatch_mouse((0, 110), set(), set())    # 超出左边界
assert sl.value == 0
# 松开
m.dispatch_mouse((0, 110), set(), {1})
assert sl._dragging is False
# 松开后移动不再改变值
m.dispatch_mouse((250, 110), set(), set())
assert sl.value == 0
print('slider drag-lock+clamp OK, vals sample=%s' % vals[:4])

# ---- Toggle: 点击切换 ----
m, c = make_ui()
states = []
tg = Toggle('t', rect=(0, 0, 100, 24), is_on=False, on_change=lambda v: states.append(v))
c.root.add_child(tg)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_mouse((10, 10), set(), {1})
assert tg.is_on is True and states == [True]
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_mouse((10, 10), set(), {1})
assert tg.is_on is False and states == [True, False]
print('toggle switch OK')

# ---- ProgressBar: 只读, value 钳制 [0,1] ----
pb = ProgressBar('p', rect=(0, 0, 100, 16), value=0.5)
pb.value = 1.5
assert pb.value == 1.0
pb.value = -0.3
assert pb.value == 0.0
# 点击不应消费 (ProgressBar 无交互)
m, c = make_ui()
c.root.add_child(ProgressBar('p2', rect=(0, 0, 100, 16), value=0.5))
consumed = m.dispatch_mouse((10, 10), {1}, set())
assert consumed is False, 'ProgressBar 点击不应被消费'
print('progress bar read-only OK')

print('PASS verify_ui_button_slider_toggle')
