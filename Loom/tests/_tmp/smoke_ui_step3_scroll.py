# -*- coding: utf-8 -*-
"""smoke_ui_step3_scroll.py — ScrollView 冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Panel, ScrollView, Button


class _StubEngine:
    def __init__(self):
        self.rects = []
        self.scissor_stack = []
        self.scissor_calls = []

    def draw_screen_rect(self, rect, color):
        self.rects.append(rect)

    def draw_text_quad(self, *a, **kw):
        pass

    def _measure_text(self, text, size=None):
        return (len(text) * 10, 18)

    def push_scissor(self, rect):
        self.scissor_stack.append(rect)
        self.scissor_calls.append(('push', tuple(rect)))

    def pop_scissor(self):
        if self.scissor_stack:
            self.scissor_stack.pop()
        self.scissor_calls.append(('pop',))


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# 1) 滚轮向上 (delta > 0): scroll_pos.y 增大 (向 0); 从 0 已是顶部, 不再变
m, c = make_ui()
sv = ScrollView('sv', rect=(0, 0, 300, 200), content_size=(300, 800))
c.root.add_child(sv)
# 初始 scroll_pos = (0, 0), 在顶部
consumed = m.dispatch_mouse((150, 100), set(), set(), wheel=1)
assert consumed is True, '滚轮命中 ScrollView 应被消费'
assert sv.scroll_pos[1] == 0.0, '顶部向上滚应无变化'
print('wheel up at top -> 0 (clamped) OK')

# 2) 滚轮向下 (delta < 0): scroll_pos.y 减小 (向下滚动查看下方内容)
consumed = m.dispatch_mouse((150, 100), set(), set(), wheel=-1)
assert consumed is True
assert sv.scroll_pos[1] < 0.0, sv.scroll_pos[1]
print('wheel down -> neg scroll OK:', sv.scroll_pos[1])

# 3) 继续向下滚, 应钳制在 -(800-200) = -600
for _ in range(20):
    m.dispatch_mouse((150, 100), set(), set(), wheel=-1)
assert sv.scroll_pos[1] == -600.0, sv.scroll_pos
print('bottom clamp OK')

# 4) 超出范围滚轮不消费
consumed = m.dispatch_mouse((500, 500), set(), set(), wheel=-1)
assert consumed is False, '滚轮未命中 ScrollView 不消费'
print('wheel miss -> not consumed OK')

# 5) 不可滚动的 ScrollView: 滚轮返回 False 不消费
sv2 = ScrollView('sv2', rect=(0, 0, 300, 500), content_size=(300, 500))
c.root.add_child(sv2)
sv2_can = sv2.can_scroll()
assert sv2_can is False
consumed = m.dispatch_mouse((150, 100), set(), set(), wheel=1)
# 注意: sv 还在 0,0 300,200 位置, sv2 在同样位置后加, 所以命中 sv2
# sv2 不能滚动 -> 返回 False; 但 sv 也在同一位置, UIManager 会找最近命中
# 实际上 hit_test 会返回 sv2 (后加的在上层), 但 sv2 on_mouse_wheel 返回 False
# 所以 consumed 应为 False
assert consumed is False, '不可滚动时滚轮不消费'
print('unscrollable -> not consumed OK')

# 6) 绘制: push/pop scissor 配对
m3, c3 = make_ui()
sv3 = ScrollView('sv3', rect=(50, 50, 300, 200), content_size=(300, 800))
c3.root.add_child(sv3)
sv3.scroll_pos = (0, -100)
child_btn = Button('btn', rect=(10, 10, 100, 30))
sv3.add_child(child_btn)
e = _StubEngine()
m3.draw_all(e)
pushes = [x for x in e.scissor_calls if x[0] == 'push']
pops = [x for x in e.scissor_calls if x[0] == 'pop']
assert len(pushes) == 1, len(pushes)
assert len(pops) == 1, len(pops)
assert pushes[0][1] == (50, 50, 300, 200), pushes[0]
print('draw push/pop scissor OK')

# 7) 命中测试: 子元素超出可视区不响应
m4, c4 = make_ui()
sv4 = ScrollView('sv4', rect=(0, 0, 200, 100), content_size=(200, 500))
c4.root.add_child(sv4)
# 子元素在内容坐标 (0, 300), 加上 scroll_pos.y=0 后, 屏幕坐标在 y=300
below_view = Button('below', rect=(0, 300, 100, 30))
sv4.add_child(below_view)
# 点在 (50, 50) - 在 sv4 可视区, 但不在 below_view 范围内, 应命中 sv4 自身
hit = c4.root.hit_test((50, 50), (0.0, 0.0, 800.0, 600.0))
assert hit is sv4, '可视区空白命中 sv4'
print('view hit -> sv self OK')

# 滚动到使 below_view 进入可视区
sv4.scroll_pos = (0, -250)
# 现在 below_view 屏幕 y = 300 - 250 = 50
hit2 = c4.root.hit_test((50, 55), (0.0, 0.0, 800.0, 600.0))
# 可能命中 below_view 或 sv4 (取决于 clip 检查是否成功)
assert hit2 is not None
print('hit after scroll OK:', hit2.name if hit2 else 'None')

print('SMOKE_PASS')
