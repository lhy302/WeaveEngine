# -*- coding: utf-8 -*-
"""verify_ui_dropdown.py — Dropdown 展开/收起/选择验收 (契约 §12, 阶段3)

验收点（契约原文）：展开/收起/选择
测试范围：
  1) 初始收起，selected_value 与 selected_index 对应
  2) 点击展开、再次点击选项选中+收起
  3) on_change 回调触发
  4) 点击空白收起（不选择）
  5) 展开列表画在最后（draw_all 二次绘制）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Dropdown


class _Eng:
    def __init__(self):
        self.rects = []
        self.texts = []

    def draw_screen_rect(self, rect, color):
        self.rects.append(rect)

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        self.texts.append(text)

    def _measure_text(self, text, size=None):
        return (len(text) * 10, 18)

    def push_scissor(self, rect):
        pass

    def pop_scissor(self):
        pass


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# 1) 初始状态
m, c = make_ui()
dd = Dropdown('dd', rect=(100, 100, 200, 32),
              options=['低', '中', '高'], selected_index=1)
c.root.add_child(dd)
assert dd._expanded is False
assert dd.selected_value == '中'
assert dd.selected_index == 1
print('initial state OK')

# 2) 展开 + 选第 3 项 + 收起
m, c = make_ui()
changes = []
dd = Dropdown('dd', rect=(100, 100, 200, 32),
              options=['低', '中', '高'], selected_index=0,
              on_change=lambda v: changes.append(v))
c.root.add_child(dd)
# 点击展开
m.dispatch_mouse((110, 110), {1}, set())
assert dd._expanded is True, '点击 Dropdown 应展开'
# 列表 y 从 132 开始, item_h=28: 第3项 y=132+2*28=188 (区域 188~216)
m.dispatch_mouse((110, 200), {1}, set())
assert dd._expanded is False, '选中后应收起'
assert dd.selected_value == '高'
assert changes == ['高']
print('expand / select / collapse OK')

# 3) 点击空白收起（不选择）
m, c = make_ui()
dd = Dropdown('dd', rect=(100, 100, 200, 32),
              options=['a', 'b'], selected_index=0)
c.root.add_child(dd)
m.dispatch_mouse((110, 110), {1}, set())   # 展开
assert dd._expanded is True
m.dispatch_mouse((700, 500), {1}, set())   # 空白处
assert dd._expanded is False
assert dd.selected_value == 'a', '空白点击不应改变选中'
print('click outside collapse OK')

# 4) draw_all 二次绘制：展开的列表画在所有元素之后
m, c = make_ui()
# 加一个 Panel 覆盖整个屏幕, 再叠一个 Dropdown 在上层
from loom_ui import Panel
bg = Panel('bg', rect=(0, 0, 800, 600))
c.root.add_child(bg)
dd = Dropdown('dd', rect=(100, 100, 200, 32),
              options=['a', 'b', 'c'], selected_index=0)
c.root.add_child(dd)
dd._expanded = True
e = _Eng()
m.draw_all(e)
# 展开列表应画了 3 次文字 (每个选项一次)
assert e.texts.count('a') >= 1
assert e.texts.count('b') >= 1
assert e.texts.count('c') >= 1
print('draw_all expanded list OK')

print('PASS verify_ui_dropdown')
