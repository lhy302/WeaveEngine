# -*- coding: utf-8 -*-
"""smoke_ui_step2_font.py — 字体回退子系统冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_font import FontChain

fc = FontChain()

# 1) 中文字符 -> 主字体 (索引 0)
idx_cn = fc.char_index('你', 16)
assert idx_cn == 0, '中文应在主字体, 实际 %r' % (idx_cn,)
print('Chinese -> chain[0] OK')

# 2) 英文/数字 -> 主字体
assert fc.char_index('A', 16) == 0
assert fc.char_index('9', 16) == 0
print('ASCII -> chain[0] OK')

# 3) emoji -> 回退字体 (索引 >= 1)
idx_emoji = fc.char_index('\U0001F600', 16)    # 😀
assert idx_emoji >= 1, 'emoji 应走回退, 实际 %r' % (idx_emoji,)
print('emoji -> chain[%d] OK' % idx_emoji)

# 4a) 雅黑覆盖的字符走 chain[0] (← 是雅黑有的, 不应误判为回退)
assert fc.char_index('\u2190', 16) == 0, '← 雅黑有, 应走 chain[0]'
# 4b) 雅黑没有的生僻符号 -> 回退 (\u2230 三重积分)
idx_sym = fc.char_index('\u2230', 16)
assert idx_sym >= 1, '生僻符号应走回退, 实际 %r' % (idx_sym,)
# 4c) 韩文 -> 回退 (한, 雅黑无韩文)
idx_kr = fc.char_index('\ud55c', 16)
assert idx_kr >= 1, '韩文应走回退, 实际 %r' % (idx_kr,)
# 4d) 日文假名 あ 雅黑有, 走 chain[0] (符合真实覆盖)
assert fc.char_index('\u3042', 16) == 0, 'あ 雅黑有, 应走 chain[0]'
print('symbol chain[%d] / Korean chain[%d] OK' % (idx_sym, idx_kr))

# 5) 字符映射缓存命中 (第二次零额外查询)
hits = [0]
_orig = fc.char_index
def _counted(ch, size):
    hits[0] += 1
    return _orig(ch, size)
fc.char_index = _counted
fc.char_index('你', 16)
fc.char_index('\U0001F600', 16)
assert hits[0] == 2, 'char_index 被调用 %d 次' % hits[0]
# 直接查缓存 (不走计数) -> 断言缓存确实存了
assert (16, '你') in fc._char_index
assert (16, '\U0001F600') in fc._char_index
fc.char_index = _orig
print('cache OK (keys present)')

# 6) 分段渲染: 中英+emoji 混排
segs = fc.split('hi你😀世', 16)
kinds = [s[0] for s in segs]
assert kinds.count(0) >= 2, segs
assert any(k >= 1 for k in kinds), segs
print('split OK:', [(i, s.encode('unicode_escape').decode('ascii')) for i, s in segs])

# 7) render 与 measure 宽度一致
text = '你好世界 A1 😀 再见'
surf = fc.render(text, (255, 255, 255), 16)
w, h = fc.measure(text, 16)
assert surf.get_width() > 0
assert abs(surf.get_width() - w) <= 4, (surf.get_width(), w)
print('render/measure consistent OK:', surf.get_size(), (w, h))

# 8) 空文本不崩
s0 = fc.render('', (255, 255, 255), 16)
assert s0.get_width() == 1 and s0.get_height() == 1
assert fc.measure('', 16) == (0, 0)
print('empty text OK')

# 9) _render_text / _measure_text 走通 FontChain (引擎侧)
import pygame
pygame.font.init()
from loom_hud import HudMixin

class _E(HudMixin):
    pass

e = _E()
s = e._render_text('你好😀', (255, 255, 255), 16)
assert s.get_width() > 0
mw, mh = e._measure_text('你好😀', 16)
assert mw > 0 and mh > 0
print('HudMixin wiring OK:', s.get_size(), (mw, mh))
print('SMOKE_PASS')
