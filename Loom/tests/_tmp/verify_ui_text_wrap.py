# -*- coding: utf-8 -*-
"""verify_ui_text_wrap.py — Text 自动换行 (契约 §3.3, 阶段1)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_ui import Text


class _Engine:
    _char_w = 10
    def _measure_text(self, text, size=None):
        return (len(text) * self._char_w, 18)


e = _Engine()

# 纯英文按宽度切
t = Text('t', rect=(0, 0, 100, 100), text='abcdefghij', wrap_width=30)
assert t._wrap_lines(e) == ['abc', 'def', 'ghi', 'j']

# 换行符优先
t2 = Text('t2', rect=(0, 0, 200, 100), text='line1\nline2\nline3', wrap_width=1000)
assert t2._wrap_lines(e) == ['line1', 'line2', 'line3']

# 手动换行 + 超宽混合
t3 = Text('t3', rect=(0, 0, 200, 100), text='abcdefgh\nxyz', wrap_width=30)
assert t3._wrap_lines(e) == ['abc', 'def', 'gh', 'xyz']

# wrap_width=0 -> 不换行 (只按换行符切)
t4 = Text('t4', rect=(0, 0, 100, 100), text='abcdefghij', wrap_width=0)
assert t4._wrap_lines(e) == ['abcdefghij']

# 空文本
t5 = Text('t5', rect=(0, 0, 100, 100), text='', wrap_width=30)
assert t5._wrap_lines(e) == []

# 中英混排 (中/英同宽 10, 检验边界): '中Ab文' 累计恰 40 (不超), 第5字符超才换
t6 = Text('t6', rect=(0, 0, 100, 100), text='中Ab文Cd', wrap_width=40)
assert t6._wrap_lines(e) == ['中Ab文', 'Cd'], t6._wrap_lines(e)

print('PASS verify_ui_text_wrap')
