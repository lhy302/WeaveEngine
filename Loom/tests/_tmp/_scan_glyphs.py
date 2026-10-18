# -*- coding: utf-8 -*-
import pygame.freetype
pygame.freetype.init()
f = pygame.freetype.Font('C:/Windows/Fonts/msyh.ttc', 16)

cands = {
    'arrow': '\u2190',        # ←
    'integral3': '\u2230',    # ∰
    'japanese': '\u3042',     # あ
    'korean': '\ud55c',       # 한
    'emoji': '\U0001F600',    # 😀
    'math_sum': '\u2211',     # ∑
    'star': '\u2605',         # ★
    'lightning': '\u21AF',    # ↯
}
for name, ch in cands.items():
    m = f.get_metrics(ch)
    has = bool(m) and m[0] is not None and float(m[0][4]) > 0.5
    print('%-12s U+%04X  has=%s  %r' % (name, ord(ch), has, m))
