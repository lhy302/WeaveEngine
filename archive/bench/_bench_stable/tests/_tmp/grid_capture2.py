# -*- coding: utf-8 -*-
"""临时探针: 比较两种读回方式, 确认能否读到渲染帧 (找纯黑根因)."""
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


def grab_copy():
    rb = app.ctx.renderbuffer((W, H), components=4)
    fbo = app.ctx.framebuffer(color_attachments=[rb])
    app.ctx.copy_framebuffer(fbo, app.ctx.screen)
    data = fbo.read(components=4)
    fbo.release()
    rb.release()
    return np.frombuffer(data, dtype='u1').reshape(H, W, 4)


def grab_read():
    data = app.ctx.screen.read(components=4, viewport=(0, 0, W, H))
    return np.frombuffer(data, dtype='u1').reshape(H, W, 4)


app.camera_pitch = math.radians(-45)
app.apply_orbit_camera()
for i in range(4):
    app.render(0.016)          # 多渲几帧 (着色器/上下文预热, 首帧可能黑)

for name, arr in (("copy_framebuffer", grab_copy()), ("screen.read", grab_read())):
    mean = arr[:, :, :3].mean()
    mx = arr[:, :, :3].max()
    nonblack = int((arr[:, :, :3].sum(axis=2) > 30).sum())
    print("%s: 平均%.1f 最大%d 非黑像素%d" % (name, mean, mx, nonblack))
app._stop_parallel()
pygame.quit()
print("CAPTURE2 DONE ✅")
