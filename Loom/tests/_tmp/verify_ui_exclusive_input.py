# -*- coding: utf-8 -*-
"""verify_ui_exclusive_input.py — UI 独占输入 (契约 §6.3, 阶段2, 决策3=B)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Button


class _StubEditor:
    """模拟 editor._dispatch_ui_mouse 的决策链."""
    def __init__(self):
        self.ui = UIManager()
        self.ui.add_canvas(Canvas(canvas_type='screen', width=800, height=600))
        self.mouse_pos = (0, 0)
        self.pressed = set()
        self.released = set()
        self.ui_consumed = False
        self.was_picked_3d = False

    def dispatch(self):
        consumed = self.ui.dispatch_mouse(
            self.mouse_pos, set(self.pressed), set(self.released))
        if not consumed:
            self.ui.update_hover_only(self.mouse_pos)
        self.ui_consumed = consumed

    def try_pick_3d(self):
        """模拟 3D 拾取入口 (契约决策: 检查 ui_consumed)."""
        if 1 not in self.pressed:
            return
        if self.ui_consumed:
            return
        self.was_picked_3d = True


e = _StubEditor()
btn = Button('b', rect=(100, 100, 120, 40))
e.ui.canvases[0].root.add_child(btn)

# 1) 在按钮上按下 -> UI 消费 -> 3D 不拾取
e.mouse_pos = (110, 110)
e.pressed = {1}
e.dispatch()
assert e.ui_consumed is True
e.try_pick_3d()
assert e.was_picked_3d is False, 'UI 消费后 3D 不应拾取'
print('hit ui -> 3d blocked OK')

# 2) 空白处按下 -> UI 未消费 -> 3D 可拾取
e.was_picked_3d = False
e.mouse_pos = (700, 500)
e.pressed = {1}
e.dispatch()
assert e.ui_consumed is False
e.try_pick_3d()
assert e.was_picked_3d is True, 'UI 未消费时 3D 应拾取'
print('miss ui -> 3d picks OK')

# 3) 禁用按钮不消费 -> 3D 可拾取
e.was_picked_3d = False
btn.enabled = False
e.mouse_pos = (110, 110)
e.pressed = {1}
e.dispatch()
assert e.ui_consumed is False
e.try_pick_3d()
assert e.was_picked_3d is True
btn.enabled = True
print('disabled ui -> 3d picks OK')

# 4) UI 消耗后 mouse_pos 不变 -> 3D 侧 prev 也应同步（契约隐含：防消费结束突跳）
e.mouse_pos = (110, 110)
e.pressed = {1}
e.dispatch()
assert e.ui_consumed
prev = e.mouse_pos
e.mouse_pos = (500, 500)
e.pressed = set()
e.dispatch()
assert e.ui_consumed is False
print('ui lock release OK')

print('PASS verify_ui_exclusive_input')
