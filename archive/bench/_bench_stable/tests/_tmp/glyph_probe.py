# -*- coding: utf-8 -*-
"""临时探针: 检测引擎字体 (msyh.ttc) 哪些特殊字形渲染成 tofu 方块 (找"乱码框框"根因)."""
import os
import sys

import pygame

pygame.init()
for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
    if not os.path.exists(path):
        continue
    print("=== 字体:", path)
    f = pygame.font.Font(path, 20)
    glyphs = "◀▶«»🔒🔓☀●◉✓✗▣▨◆■→"
    for ch in glyphs:
        surf = f.render(ch, True, (255, 255, 255))
        w, h = surf.get_size()
        arr = pygame.surfarray.array3d(surf)          # (w,h,3)
        # 中心 5x5 是否有像素 (实心字形有, tofu 空心框无)
        cx0, cy0 = w // 2 - 2, h // 2 - 2
        patch = arr[cx0:cx0 + 5, cy0:cy0 + 5]
        center_filled = bool((patch > 0).any())
        # 边缘 (边框) 是否有像素
        edge = (arr[0, :, :].any() or arr[-1, :, :].any() or
                arr[:, 0, :].any() or arr[:, -1, :].any())
        verdict = "实心字形" if center_filled else ("TOFU框" if edge else "空")
        print("  %r 尺寸(%d,%d) 中心填充=%s 边=%s -> %s" % (ch, w, h, center_filled, edge, verdict))
    break
pygame.quit()
print("GLYPH PROBE DONE ✅")
