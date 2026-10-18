# -*- coding: utf-8 -*-
"""verify_ui_font_fallback.py — 字体回退链 + 缓存 (契约 §2.5, 阶段1)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_font import FontChain

fc = FontChain()

# 回退链: 中/英/日文假名走主字体; emoji/韩文/生僻符号走回退
assert fc.char_index('你', 16) == 0, '中文应主字体'
assert fc.char_index('A', 16) == 0, 'ASCII 应主字体'
assert fc.char_index('\u3042', 16) == 0, '假名 あ 雅黑有, 应主字体'
assert fc.char_index('\U0001F600', 16) >= 1, 'emoji 应回退'
assert fc.char_index('\ud55c', 16) >= 1, '韩文 应回退'
assert fc.char_index('\u2230', 16) >= 1, '三重积分符号 应回退'

# 缓存: 重复查询命中, 不再调 char_index 内部检测
hits = [0]
_orig = fc.char_index
def _counted(ch, size):
    hits[0] += 1
    return _orig(ch, size)
fc.char_index = _counted
fc.char_index('你', 16)
fc.char_index('\U0001F600', 16)
assert hits[0] == 2
assert (16, '你') in fc._char_index
assert (16, '\U0001F600') in fc._char_index
fc.char_index = _orig

# 分段渲染
segs = fc.split('hi你\U0001F600世', 16)
kinds = [s[0] for s in segs]
assert kinds.count(0) >= 2
assert any(k >= 1 for k in kinds)

# render/measure 宽度一致
text = '你好世界 A1 \U0001F600 再见'
surf = fc.render(text, (255, 255, 255), 16)
w, h = fc.measure(text, 16)
assert surf.get_width() > 0
assert abs(surf.get_width() - w) <= 4

# 空文本
s0 = fc.render('', (255, 255, 255), 16)
assert s0.get_size() == (1, 1)
assert fc.measure('', 16) == (0, 0)

print('PASS verify_ui_font_fallback')
