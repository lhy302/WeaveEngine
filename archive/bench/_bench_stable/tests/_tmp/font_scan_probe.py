# -*- coding: utf-8 -*-
"""font_scan_probe.py — 全字体扫描: 找"中文+全部GUI符号"单字体; 并探明雅黑有哪几个几何符号 (2026-08-15)."""
import glob
import os

import pygame
import pygame.freetype
pygame.freetype.init()

NEED = "中A0✓✗☀●◉▣▨◆▶■◀★○·"


def missing(path, chars):
    try:
        f = pygame.freetype.Font(path, 16)
    except Exception:
        return None
    miss = []
    for ch in chars:
        try:
            m = f.get_metrics(ch)
            has = m is not None and m[0] is not None
        except Exception:
            has = True
        if not has:
            miss.append(ch)
    return miss


# 1) 全字体扫描: 谁同时含中文 + 全部符号
print("== 扫描 C:/Windows/Fonts 全部字体: 中文+全部符号 ==")
full = []
fonts = sorted(glob.glob("C:/Windows/Fonts/*.ttf") + glob.glob("C:/Windows/Fonts/*.ttc"))
for p in fonts:
    m = missing(p, NEED)
    if m == []:
        full.append(os.path.basename(p))
print("同时覆盖的字体:", full if full else "(无)")

# 2) 雅黑对候选替换符号的覆盖 (决定符号换什么)
print("\n== 雅黑(msyh.ttc) 对候选符号的覆盖 ==")
cands = "●○□■◆►▷▶◀▲▼√×÷☼⌂◎⚫☁★※·…→←↓↑«»"
m2 = missing("C:/Windows/Fonts/msyh.ttc", cands)
print("雅黑缺:", "".join(m2) if m2 else "(全有)")
print("雅黑有:", "".join(c for c in cands if c not in m2))

# 3) 额外知名宽字符集字体
print("\n== 额外字体 ==")
extra = [("微软正黑", "C:/Windows/Fonts/msjh.ttc"),
         ("MS Gothic", "C:/Windows/Fonts/msgothic.ttc"),
         ("MS UI Gothic", "C:/Windows/Fonts/msuigothic.ttc"),
         ("SimSun-ExtB", "C:/Windows/Fonts/simsunb.ttf")]
for n, p in extra:
    m3 = missing(p, NEED)
    if m3 is None:
        print("  %-12s 不存在" % n)
    else:
        print("  %-12s 缺 %s" % (n, "".join(m3) if m3 else "(全有 ✓)"))
