# -*- coding: utf-8 -*-
"""临时探针: 引擎在小字号 (GUI 实际字号) 下渲染图标, 看是否清晰可辨."""
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import editor

app = editor.EditorApp(800, 300)
for _ in range(3):
    app.render(0.016)

# 模拟 GUI 里的图标+文字组合 (层级行样式)
lines = ["✓ 立方体", "✗ 球体", "☀ 平行光", "● 点光源", "◉ 摄像机", "▣ 网格资产"]
size = 13
for i, s in enumerate(lines):
    app.draw_text_quad(s, 500, 40 + i * 30, (255, 255, 255), size)
app.render(0.016)

rb = app.ctx.renderbuffer((800, 300), components=4)
fbo = app.ctx.framebuffer(color_attachments=[rb])
app.ctx.copy_framebuffer(fbo, app.ctx.screen)
data = fbo.read(components=4)
fbo.release()
rb.release()
arr = np.flipud(np.frombuffer(data, dtype='u1').reshape(300, 800, 4))[:, :, :3].astype(int)

for i, s in enumerate(lines):
    py_ = 40 + i * 30
    patch = (arr[py_:py_ + 30, 500:500 + 60] > 120).any(axis=2)
    # 放大显示 (每像素 x3)
    big = np.kron(patch, np.ones((1, 1), dtype=bool))
    print("=== %r 非零%.0f%% ===" % (s, patch.mean() * 100))
    for r in range(0, patch.shape[0], 1):
        line = "".join("#" if patch[r, c] else "." for c in range(0, patch.shape[1], 1))
        if line.strip():
            print("  " + line)
app._stop_parallel()
pygame.quit()
