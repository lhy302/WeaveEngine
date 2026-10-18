# -*- coding: utf-8 -*-
"""smoke_ui_step3_elements.py — Panel/Text 冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import Panel, Text


class _Engine:
    """记录绘制调用的桩 engine."""
    def __init__(self):
        self.rect_calls = []
        self.text_calls = []
        self._char_w = 10
        self._line_h = 18

    def draw_screen_rect(self, rect, color):
        self.rect_calls.append((rect, color))

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        self.text_calls.append((text, x, y, color, size))

    def _measure_text(self, text, size=None):
        return (len(text) * self._char_w, self._line_h)


e = _Engine()

# 1) Panel 绘制
p = Panel('p', rect=(10, 10, 100, 50), bg_color=(255, 0, 0, 128))
p.draw(e, (10, 10, 100, 50))
assert len(e.rect_calls) == 1
assert e.rect_calls[0][1] == (255, 0, 0, 128), e.rect_calls[0]
print('Panel OK')

# 2) Text 单行 left 对齐
e.text_calls.clear()
t = Text('t', rect=(0, 0, 200, 30), text='Hello', font_size=16)
t.draw(e, (5, 5, 200, 30))
assert len(e.text_calls) == 1
assert e.text_calls[0][0] == 'Hello'
assert e.text_calls[0][1] == 5          # left -> x = rect.x
print('Text left OK')

# 3) Text center 对齐
e.text_calls.clear()
t.align = 'center'
t.draw(e, (0, 0, 200, 30))
# lw = 5*10 = 50, tx = (200-50)/2 = 75
assert e.text_calls[0][1] == 75, e.text_calls[0]
print('Text center OK')

# 4) Text right 对齐
e.text_calls.clear()
t.align = 'right'
t.draw(e, (0, 0, 200, 30))
# tx = 200 - 50 = 150
assert e.text_calls[0][1] == 150, e.text_calls[0]
print('Text right OK')

# 5) 自动换行
e.text_calls.clear()
tw = Text('tw', rect=(0, 0, 100, 100), text='abcdefghij', wrap_width=30)
# 每字符宽 10, wrap_width=30 -> 每行 3 字符
lines = tw._wrap_lines(e)
assert lines == ['abc', 'def', 'ghi', 'j'], lines
tw.draw(e, (0, 0, 100, 100))
assert len(e.text_calls) == 4
print('Text wrap OK:', lines)

# 6) 换行符
e.text_calls.clear()
tn = Text('tn', rect=(0, 0, 200, 100), text='line1\nline2', wrap_width=1000)
lines = tn._wrap_lines(e)
assert lines == ['line1', 'line2'], lines
print('Text newline OK')

# 7) 空文本不崩
e.text_calls.clear()
te = Text('te', rect=(0, 0, 100, 30), text='')
te.draw(e, (0, 0, 100, 30))
assert len(e.text_calls) == 0
print('Empty text OK')
print('SMOKE_PASS')
