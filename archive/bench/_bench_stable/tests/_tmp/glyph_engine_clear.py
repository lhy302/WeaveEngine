# -*- coding: utf-8 -*-
"""临时探针: 引擎 draw_text_quad 在无遮挡位置渲染字形, 验证引擎文字渲染是否真出方块."""
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import editor

app = editor.EditorApp(800, 400)
for _ in range(3):
    app.render(0.016)

glyphs = "✓✗☀●◉▣◆«»"
x0, y0 = 500, 80          # 视口中心附近, 无面板遮挡
size = 40
for i, ch in enumerate(glyphs):
    app.draw_text_quad(ch, x0 + i * 60, y0, (255, 255, 255), size)
app.render(0.016)

rb = app.ctx.renderbuffer((800, 400), components=4)
fbo = app.ctx.framebuffer(color_attachments=[rb])
app.ctx.copy_framebuffer(fbo, app.ctx.screen)
data = fbo.read(components=4)
fbo.release()
rb.release()
arr = np.flipud(np.frombuffer(data, dtype='u1').reshape(400, 800, 4))[:, :, :3].astype(int)

for i, ch in enumerate(glyphs):
    px = x0 + i * 60
    patch = (arr[y0:y0 + 60, px:px + 60] > 120).any(axis=2)
    H, W = patch.shape
    print("=== %r (非零像素 %.0f%%) ===" % (ch, patch.mean() * 100))
    for r in range(0, H, 3):
        line = "".join("#" if patch[r, c] else "." for c in range(0, W, 3))
        if line.strip():
            print("  " + line)
app._stop_parallel()
pygame.quit()
print("ENGINE CLEAR GLYPH DONE ✅")
