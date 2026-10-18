# -*- coding: utf-8 -*-
"""smoke_ui_step3_ui_consumed.py — ui_consumed 接入冒烟 (2026-10-18)

验证 _dispatch_ui_mouse + ui_consumed 对鼠标的拦截, 不影响键盘段.
用桩 EditorApp 的最小字段, 避开真实 GPU/窗口初始化.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Button


class _StubEditor:
    def __init__(self):
        self.ui = UIManager()
        self.ui.add_canvas(Canvas(canvas_type='screen', width=800, height=600))
        self.mouse_pos = (0, 0)
        self.pressed = set()
        self.released = set()
        self.ui_consumed = False

    # 复制 _dispatch_ui_mouse 的核心逻辑（简化: 只测决策链）
    def dispatch(self):
        consumed = self.ui.dispatch_mouse(
            self.mouse_pos, set(self.pressed), set(self.released))
        if not consumed:
            self.ui.update_hover_only(self.mouse_pos)
        self.ui_consumed = consumed


e = _StubEditor()
btn = Button('b', rect=(100, 100, 120, 40))
e.ui.canvases[0].root.add_child(btn)

# 1) 空点击不消费
e.mouse_pos = (500, 500)
e.pressed = {1}
e.dispatch()
assert e.ui_consumed is False
print('empty click -> not consumed OK')

# 2) 在按钮上按下 -> 消费
e.mouse_pos = (110, 110)
e.pressed = {1}
e.released = set()
e.dispatch()
assert e.ui_consumed is True
print('hit btn down -> consumed OK')

# 3) 松开 -> 消费
e.pressed = set()
e.released = {1}
e.dispatch()
assert e.ui_consumed is True
print('hit btn up -> consumed OK')

# 4) 无命中框 -> 不消费
e.mouse_pos = (10, 10)
e.pressed = set()
e.released = set()
e.dispatch()
assert e.ui_consumed is False
print('move out -> not consumed OK')

# 5) 禁用按钮不消费 (但会 hover)
btn.enabled = False
e.mouse_pos = (110, 110)
e.pressed = {1}
e.dispatch()
assert e.ui_consumed is False
print('disabled btn -> not consumed OK')

print('SMOKE_PASS')
