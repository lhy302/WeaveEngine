# -*- coding: utf-8 -*-
"""font_symbol_scan.py — 扫描源码所有会渲染进文本的非中文符号字符 (2026-08-15).

提取 Loom/LoomHub 源码 (排除 tests) 中所有非 ASCII、非 CJK 的字符, 并列出其中
雅黑(msyh)缺的 —— 删掉字体回退后这些会渲染成方框, 必须替换.
"""
import glob
import os

import pygame
import pygame.freetype
pygame.freetype.init()

# 工作区根 = Loom(py源代码)\  (本文件在 ...\Loom\tests\_tmp\, 上溯 4 层)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def is_cjk_or_safe(cp):
    # CJK 基本/扩展 + CJK 标点 + 全角 (都在中文字体里)
    if 0x4E00 <= cp <= 0x9FFF:
        return True
    if 0x3000 <= cp <= 0x303F:      # CJK 标点 、。，！？「」
        return True
    if 0xFF00 <= cp <= 0xFFEF:      # 全角
        return True
    if 0x3400 <= cp <= 0x4DBF:      # CJK 扩展A
        return True
    if 0x2E80 <= cp <= 0x2EFF:      # CJK 部首
        return True
    return False


found = {}
files = []
for base in ("Loom", "LoomHub"):
    for p in glob.glob(os.path.join(ROOT, base, "**", "*.py"), recursive=True):
        if "tests" in p or "_tmp" in p or "\\tests" in p:
            continue
        files.append(p)
for p in files:
    try:
        txt = open(p, encoding='utf-8').read()
    except Exception:
        continue
    for ch in txt:
        cp = ord(ch)
        if cp < 0x7F or is_cjk_or_safe(cp):
            continue
        found.setdefault(ch, set()).add(os.path.relpath(p, ROOT))

f = pygame.freetype.Font("C:/Windows/Fonts/msyh.ttc", 16)
def has_glyph(ch):
    try:
        m = f.get_metrics(ch)
        return m is not None and m[0] is not None
    except Exception:
        return True

print("源码里非中文符号字符 (雅黑缺的=会变方框):")
for ch in sorted(found, key=ord):
    mark = "" if has_glyph(ch) else "  <-- 雅黑缺, 需替换"
    print("  U+%04X %r  出现于 %s%s" % (ord(ch), ch,
          ", ".join(sorted(found[ch])[:3]), mark))
