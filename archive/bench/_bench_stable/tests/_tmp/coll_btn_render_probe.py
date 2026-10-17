# -*- coding: utf-8 -*-
"""临时探针: 收起按钮渲染在面板之上 (有按钮底色 + 白色字形), 且不显示为空白方块."""
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import editor

app = editor.EditorApp(1280, 800)
W, H = 1280, 800
for _ in range(4):
    app.render(0.016)


def grab():
    rb = app.ctx.renderbuffer((W, H), components=4)
    fbo = app.ctx.framebuffer(color_attachments=[rb])
    app.ctx.copy_framebuffer(fbo, app.ctx.screen)
    data = fbo.read(components=4)
    fbo.release()
    rb.release()
    arr = np.frombuffer(data, dtype='u1').reshape(H, W, 4)
    return np.flipud(arr)[:, :, :3].astype(int)


lw = app._layout()[2][2]                 # 220
arr = grab()
# 收起按钮区域: (lw-11, 40, 22, 22)
x0, y0 = lw - 11, 40
patch = arr[y0:y0 + 22, x0:x0 + 22]
btn_bg = np.array([77, 87, 107])         # (0.30,0.34,0.42)*255
bg_match = int((np.abs(patch - btn_bg).sum(axis=2) < 40).sum())
bright = int((patch.sum(axis=2) > 250).sum())   # 字形笔画 (抗锯齿灰色也算)
print("收起按钮区: 底色像素 %d, 字形亮像素 %d, 总面积 %d" %
      (bg_match, bright, 22 * 22))
assert bg_match > 50, "按钮底色未渲染 (被面板遮住?)"
assert bright > 5, "字形未渲染 (空白方块?)"
app._stop_parallel()
pygame.quit()
print("COLL BTN RENDER PROBE OK ✅")
