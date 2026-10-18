# -*- coding: utf-8 -*-
"""verify_ui_input_focus.py — InputField 焦点与文本输入验收 (契约 §6.4 + §12, 阶段3)

验收点（契约原文）：InputField 焦点切换与文本输入
测试范围：
  1) 焦点唯一性（同一时刻最多一个元素）
  2) 焦点切换时旧元素失焦回调被触发
  3) 文本插入光标位置、退格、Delete、方向键
  4) max_length 边界
  5) on_submit / on_change 回调
  6) 中文（多字节）输入正确插入，不截断
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import UIManager, Canvas, InputField

import pygame


def make_ui():
    m = UIManager()
    c = Canvas(canvas_type='screen', width=800, height=600)
    m.add_canvas(c)
    return m, c


# 1) 焦点唯一性
m, c = make_ui()
f1 = InputField('f1', rect=(0, 0, 200, 32))
f2 = InputField('f2', rect=(0, 50, 200, 32))
c.root.add_child(f1)
c.root.add_child(f2)
m.dispatch_mouse((10, 10), {1}, set())
assert m.focused() is f1 and f1._focused is True
m.dispatch_mouse((10, 60), {1}, set())
assert m.focused() is f2 and f2._focused is True
assert f1._focused is False, 'f1 应已失焦'
print('focus uniqueness OK')

# 2) 焦点切换触发 on_focus/on_blur
class _TrackedField(InputField):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.events = []
    def on_focus(self):
        super().on_focus()
        self.events.append('focus')
    def on_blur(self):
        super().on_blur()
        self.events.append('blur')

m, c = make_ui()
ta = _TrackedField('a', rect=(0, 0, 200, 32))
tb = _TrackedField('b', rect=(0, 50, 200, 32))
c.root.add_child(ta)
c.root.add_child(tb)
m.dispatch_mouse((10, 10), {1}, set())
assert ta.events == ['focus']
m.dispatch_mouse((10, 60), {1}, set())
assert ta.events == ['focus', 'blur']
assert tb.events == ['focus']
print('focus/blur callbacks OK')

# 3) 文本编辑光标
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32))
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('abc')
assert field.text == 'abc'
m.dispatch_key(pygame.K_LEFT)   # cursor=2
m.dispatch_text('X')
assert field.text == 'abXc', field.text
assert field._cursor == 3
# 序列: text='abXc', cursor=3 -> BACKSPACE 删 index 2 的 'X' -> 'abc', cursor=2
m.dispatch_key(pygame.K_BACKSPACE)
assert field.text == 'abc' and field._cursor == 2
# DELETE 删 cursor=2 位置的 'c' -> 'ab'
m.dispatch_key(pygame.K_DELETE)
assert field.text == 'ab'
print('cursor / edit OK')

# 4) max_length 边界
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32), max_length=3)
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('abcdefg')
assert field.text == 'abc'
# 光标在末尾再输入被截断
m.dispatch_text('xyz')
assert field.text == 'abc', '应保持 3 字符'
print('max_length OK')

# 5) on_submit / on_change
m, c = make_ui()
changed, submitted = [], []
field = InputField('f', rect=(0, 0, 200, 32),
                   on_change=lambda t: changed.append(t),
                   on_submit=lambda t: submitted.append(t))
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('h')
m.dispatch_text('i')
assert changed == ['h', 'hi']
m.dispatch_key(pygame.K_RETURN)
assert submitted == ['hi']
# 空文本提交回调也能触发（用户主动按回车）
submitted.clear()
field.text = ''
field._cursor = 0
m.dispatch_key(pygame.K_RETURN)
assert submitted == ['']
print('on_submit / on_change OK')

# 6) 中文（多字节）输入不截断
m, c = make_ui()
field = InputField('f', rect=(0, 0, 200, 32), max_length=10)
c.root.add_child(field)
m.dispatch_mouse((10, 10), {1}, set())
m.dispatch_text('你好世界')
assert field.text == '你好世界'
assert len(field.text) == 4    # 每个中文字符 Python 计为 1 字符
print('unicode multi-byte OK')

print('PASS verify_ui_input_focus')
