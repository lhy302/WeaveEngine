# -*- coding: utf-8 -*-
"""smoke_ui_inputfield.py — InputField 冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, Panel, InputField

import pygame


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# 1) 点击获焦 / 失焦
m, c = make_ui()
field = InputField('f', rect=(100, 100, 200, 32), placeholder='请输入')
c.root.add_child(field)
m.dispatch_mouse((150, 110), {1}, set())
assert m.focused() is field, '点击 InputField 应获焦'
assert field._focused is True
m.dispatch_mouse((700, 500), {1}, set())   # 点击空白 -> 失焦
assert m.focused() is None
assert field._focused is False
print('focus / blur OK')

# 2) 文本输入（中文/英文）
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32))
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('hello')
assert field.text == 'hello'
m.dispatch_text('你好')
assert field.text == 'hello你好'
print('text input (ASCII + 中文) OK, text=%r' % field.text)

# 3) Backspace / Delete / Left / Right / Home / End
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32), text='abcde')
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
# 光标初始在末尾 (on_mouse_down 设 cursor=len)
assert field._cursor == 5
# 按 Left 3 次 -> cursor = 2
m.dispatch_key(pygame.K_LEFT)
m.dispatch_key(pygame.K_LEFT)
m.dispatch_key(pygame.K_LEFT)
assert field._cursor == 2
# Backspace -> 删掉 'b', text='acde', cursor=1
m.dispatch_key(pygame.K_BACKSPACE)
assert field.text == 'acde' and field._cursor == 1, (field.text, field._cursor)
# Delete -> 删掉光标后的 'c', text='ade'
m.dispatch_key(pygame.K_DELETE)
assert field.text == 'ade'
# Home -> cursor=0
m.dispatch_key(pygame.K_HOME)
assert field._cursor == 0
# End -> cursor=3
m.dispatch_key(pygame.K_END)
assert field._cursor == 3
print('text edit (Backspace/Delete/Left/Home/End) OK')

# 4) max_length
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32), max_length=5)
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('abcdefgh')
assert field.text == 'abcde', field.text
print('max_length OK')

# 5) on_change / on_submit 回调
m, c = make_ui()
changes, submits = [], []
field = InputField('f', rect=(0, 0, 200, 32),
                   on_change=lambda t: changes.append(t),
                   on_submit=lambda t: submits.append(t))
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('a')
m.dispatch_text('b')
assert changes == ['a', 'ab']
m.dispatch_key(pygame.K_RETURN)
assert submits == ['ab']
print('on_change / on_submit OK')

# 6) 无焦点时 dispatch_key/dispatch_text 返回 False
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32))
c.root.add_child(field)
# 未点击 -> 无焦点
assert m.dispatch_key(pygame.K_BACKSPACE) is False
assert m.dispatch_text('a') is False
assert field.text == ''
print('no-focus -> no consume OK')

# 7) Escape 不消费（让上层处理）
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32))
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
assert m.dispatch_key(pygame.K_ESCAPE) is False
print('Escape passthrough OK')

print('SMOKE_PASS')
