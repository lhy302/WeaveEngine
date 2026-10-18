# -*- coding: utf-8 -*-
"""smoke_ui_step2_interact.py — 阶段2 交互元素 + 事件分发冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Button, Slider, Toggle, ProgressBar


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600, z_order=0)
    m.add_canvas(c)
    return m, c


# 1) hover 变化
m, c = make_ui()
btn = Button('b', rect=(100, 100, 120, 40), text='Go')
c.root.add_child(btn)
m.dispatch_mouse((110, 110), set(), set())
assert btn._hover is True, '进入后应 hover'
m.dispatch_mouse((10, 10), set(), set())
assert btn._hover is False, '移出后应取消 hover'
print('hover OK')

# 2) 按下+松开同元素 -> 触发
m, c = make_ui()
hits = []
btn = Button('b', rect=(100, 100, 120, 40), text='Go', on_click=lambda: hits.append(1))
c.root.add_child(btn)
consumed = m.dispatch_mouse((110, 110), {1}, set())   # 进入 + 按下
assert consumed is True
assert len(hits) == 0, '按下时不该触发'
consumed = m.dispatch_mouse((110, 110), set(), {1})   # 松开
assert consumed is True
assert len(hits) == 1, '松开应触发'
print('click OK')

# 3) 按下后移出 -> 不触发
m, c = make_ui()
hits = []
btn = Button('b', rect=(100, 100, 120, 40), on_click=lambda: hits.append(1))
c.root.add_child(btn)
m.dispatch_mouse((110, 110), {1}, set())   # 进入 + 按下
m.dispatch_mouse((10, 10), set(), set())   # 移出
m.dispatch_mouse((10, 10), set(), {1})     # 松在外部
assert len(hits) == 0, '移出后松开不该触发'
print('click-cancel OK')

# 4) 无效/禁用按钮
m, c = make_ui()
hits = []
btn = Button('b', rect=(0, 0, 100, 40), on_click=lambda: hits.append(1), enabled=False)
c.root.add_child(btn)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_mouse((10, 10), set(), {1})
assert len(hits) == 0, '禁用不应触发'
print('disabled OK')

# 5) Slider 拖拽锁定 + 边界钳制
m, c = make_ui()
vals = []
sl = Slider('s', rect=(100, 100, 200, 24), min_value=0, max_value=100,
            value=50, on_change=lambda v: vals.append(v))
c.root.add_child(sl)
# 按下在中间 (ratio=0.5)
m.dispatch_mouse((200, 110), {1}, set())
assert abs(sl.value - 50) < 1, sl.value
# 拖动到右侧 (ratio=1)
m.dispatch_mouse((300, 110), set(), set())
assert sl.value == 100, sl.value
# 拖出右边界 -> 钳制到 max
m.dispatch_mouse((500, 110), set(), set())
assert sl.value == 100, sl.value
# 拖出左边界 -> 钳制到 min
m.dispatch_mouse((0, 110), set(), set())
assert sl.value == 0, sl.value
# 松开
m.dispatch_mouse((0, 110), set(), {1})
assert sl._dragging is False
# 松开后移动鼠标不应该再改变值
m.dispatch_mouse((300, 110), set(), set())
assert sl.value == 0, sl.value
print('slider drag+clamp OK, vals=%s' % vals[:5])

# 6) Toggle 切换
m, c = make_ui()
states = []
tg = Toggle('t', rect=(0, 0, 100, 24), is_on=False,
            on_change=lambda v: states.append(v))
c.root.add_child(tg)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_mouse((10, 10), set(), {1})
assert tg.is_on is True and states == [True]
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_mouse((10, 10), set(), {1})
assert tg.is_on is False and states == [True, False]
print('toggle OK')

# 7) ProgressBar value 钳制
pb = ProgressBar('p', rect=(0, 0, 100, 16), value=0.5)
assert pb.value == 0.5
pb.value = 2.0
assert pb.value == 1.0
pb.value = -1
assert pb.value == 0.0
print('progress clamp OK')

# 8) 空点击不消费
m, c = make_ui()
m.dispatch_mouse((700, 500), {1}, set())
consumed = m.dispatch_mouse((700, 500), set(), {1})
assert consumed is False, '空点击不该消费'
print('empty click OK')

print('SMOKE_PASS')
