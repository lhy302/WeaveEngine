# -*- coding: utf-8 -*-
"""临时探针: 用引擎真实 draw_text_quad 路径渲染各字形, 读回检查是实心还是空心方框."""
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import editor

app = editor.EditorApp(800, 300)
for _ in range(3):
    app.render(0.016)                       # 预热

glyphs = "✓✗☀●◉▣▨◆«»«»▶◀"
x0, y0 = 20, 150
size = 16
for i, ch in enumerate(glyphs):
    app.draw_text_quad(ch, x0 + i * 40, y0, (255, 255, 255), size)
app.render(0.016)

rb = app.ctx.renderbuffer((800, 300), components=4)
fbo = app.ctx.framebuffer(color_attachments=[rb])
app.ctx.copy_framebuffer(fbo, app.ctx.screen)
data = fbo.read(components=4)
fbo.release()
rb.release()
arr = np.flipud(np.frombuffer(data, dtype='u1').reshape(300, 800, 4))[:, :, :3].astype(int)

for i, ch in enumerate(glyphs):
    px, py = x0 + i * 40, y0
    patch = arr[py:py + 26, px:px + 26]
    # 中心 7x7 是否有亮像素 (实心字形有, 空心 tofu 框无)
    cx = patch[9:16, 9:16]
    center_filled = bool((cx > 120).any())
    # 边缘 (边框) 是否有亮像素
    edge = bool((patch[0, :] > 120).any() or (patch[-1, :] > 120).any()
                or (patch[:, 0] > 120).any() or (patch[:, -1] > 120).any())
    verdict = "实心" if center_filled else ("TOFU框" if edge else "空")
    print("%r -> 中心填充=%s 边=%s => %s" % (ch, center_filled, edge, verdict))
app._stop_parallel()
pygame.quit()
print("ENGINE GLYPH PROBE DONE ✅")
