# -*- coding: utf-8 -*-
"""verify_ui_scroll_clip.py — ScrollView 裁剪验收 (契约 §12, 阶段3)

验收点（契约原文）：ScrollView 裁剪（超出部分不显示）
测试范围：
  1) 内容溢出时滚动范围钳制
  2) push/pop scissor 配对（每帧恰好一对一，不泄漏）
  3) scissor 矩形与可视区精确一致
  4) 子元素在可视区外时命中测试返回父（ScrollView 本身），不返回子元素
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, ScrollView, Button


class _Eng:
    """桩引擎: 只记录 scissor 与 draw 调用"""
    def __init__(self):
        self.scissor_stack = []
        self.scissor_calls = []
        self.rects = []

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


# 1) 内容溢出滚动范围钳制
m, c = make_ui()
sv = ScrollView('sv', rect=(50, 50, 300, 200), content_size=(300, 800))
c.root.add_child(sv)
# 边界测试: 到顶不越界
sv.scroll_by(0, 100)
assert sv.scroll_pos[1] == 0.0, '顶部滚动应钳制在 0'
# 到底不越界 (max_sy = content_h - view_h = 600)
for _ in range(50):
    sv.scroll_by(0, -100)
assert sv.scroll_pos[1] == -600.0, '底部应钳制在 -(ch-vh)'
# 水平方向溢出: content_w = 300 = view_w, 不溢出 -> 不滚
sv.scroll_by(-100, 0)
assert sv.scroll_pos[0] == 0.0, '不溢出的维度不应滚动'
print('overflow clamp OK')

# 2) push/pop scissor 配对
m, c = make_ui()
sv = ScrollView('sv', rect=(50, 50, 300, 200), content_size=(300, 800))
c.root.add_child(sv)
# 加 3 个子元素（含嵌套 ScrollView 测嵌套 push/pop）
for i in range(3):
    sv.add_child(Button(f'b{i}', rect=(10, 10 + i * 40, 100, 30)))
inner = ScrollView('inner', rect=(200, 10, 80, 100), content_size=(80, 300))
sv.add_child(inner)

e = _Eng()
m.draw_all(e)

pushes = [x for x in e.scissor_calls if x[0] == 'push']
pops = [x for x in e.scissor_calls if x[0] == 'pop']
assert len(pushes) == 2, '两个 ScrollView 各 push 一次 (期望 2, 实际 %d)' % len(pushes)
assert len(pops) == 2, 'pop 次数应与 push 相同 (期望 2, 实际 %d)' % len(pops)
assert len(e.scissor_stack) == 0, 'push/pop 必须配对，栈应为空'
print('push/pop pair OK (2 层嵌套)')

# 3) scissor 矩形与可视区精确一致
m, c = make_ui()
sv = ScrollView('sv', rect=(50, 60, 300, 200), content_size=(300, 800))
c.root.add_child(sv)
e = _Eng()
m.draw_all(e)
pushes = [x for x in e.scissor_calls if x[0] == 'push']
assert pushes[0][1] == (50, 60, 300, 200), 'scissor 矩形应等于可视区 (50,60,300,200), 实际 %r' % (pushes[0][1],)
print('scissor rect accurate OK')

# 4) 子元素在可视区外时命中测试返回父
m, c = make_ui()
sv = ScrollView('sv', rect=(50, 50, 300, 200), content_size=(300, 800))
c.root.add_child(sv)
# 子元素在内容坐标 (0, 300)，scroll_pos=0 时屏幕 y=300+50=350，超出 sv 可视区 (50~250)
below = Button('below', rect=(0, 300, 100, 30))
sv.add_child(below)
hit = c.root.hit_test((100, 100), (0.0, 0.0, 800.0, 600.0))
assert hit is sv, '可视区空白处应命中 sv 自身（供滚轮），实际命中 %r' % (getattr(hit, 'name', None),)
# 滚到使子元素进入可视区: scroll_pos.y = -280，子元素屏幕 y = 300 + 50 - 280 = 70
sv.scroll_pos = (0, -280)
# below 屏幕矩形 = (50, 70, 100, 30); 半开区间不含右/下边界, 取 (100, 85)
hit2 = c.root.hit_test((100, 85), (0.0, 0.0, 800.0, 600.0))
assert hit2 is below, '滚动后子元素进入可视区应命中子元素, 实际 %r' % (getattr(hit2, 'name', None),)
print('clip hit-test OK')

print('PASS verify_ui_scroll_clip')
