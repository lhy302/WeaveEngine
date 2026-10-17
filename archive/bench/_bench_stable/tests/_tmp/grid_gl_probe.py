# -*- coding: utf-8 -*-
"""临时探针: GL 读回 (4帧预热), 统计网格色像素屏幕分布, 验证网格渲染位置/方向."""
import math
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import editor

app = editor.EditorApp(640, 480)
W, H = 640, 480
GRID = np.array([89, 94, 107], dtype=int)   # (0.35,0.37,0.42)*255


def grab():
    rb = app.ctx.renderbuffer((W, H), components=4)
    fbo = app.ctx.framebuffer(color_attachments=[rb])
    app.ctx.copy_framebuffer(fbo, app.ctx.screen)
    data = fbo.read(components=4)
    fbo.release()
    rb.release()
    arr = np.frombuffer(data, dtype='u1').reshape(H, W, 4)
    return np.flipud(arr)[:, :, :3]


def analyze(arr):
    ai = arr.astype(int)
    gd = np.abs(ai - GRID).sum(axis=2)
    mask = gd < 20          # 紧容差: 网格线本身 (alpha=1 处应是精确色)
    n = int(mask.sum())
    if n == 0:
        return "无网格像素"
    ys, xs = np.where(mask)
    cy, cx = ys.mean() / H, xs.mean() / W
    top = (ys < H / 2).mean()
    return "网格%dpx 中心(%.2f,%.2f) 上半%.0f%%" % (n, cx, cy, top * 100)


for pitch_deg in (-45, -20, 0, 20, 45):
    app.camera_pitch = math.radians(pitch_deg)
    app.apply_orbit_camera()
    for _ in range(4):
        app.render(0.016)          # 预热 (首帧黑/着色器编译)
    print("pitch=%+4d° eye.y=%+6.2f -> %s" %
          (pitch_deg, app.camera.y, analyze(grab())))
app._stop_parallel()
pygame.quit()
print("GL PROBE DONE ✅")
