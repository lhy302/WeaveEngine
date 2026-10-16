# -*- coding: utf-8 -*-
"""一次性探针: roll 倾斜对矩形光束截面的可见效果.
斜向光束(rect), roll=0 vs roll=45 -> 光束矩形阴影应旋转, 采样点亮度变化.
运行: py -3.12 "Loom\tests\_tmp\diag_roll.py" (子进程+超时)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pygame
import numpy as np
import editor
from mesh import create_cube, create_plane

def frames(e, n=6):
    for _ in range(n):
        e.render(0.016)

def capture(e):
    rb = e.ctx.renderbuffer((e.width, e.height), components=4)
    fbo = e.ctx.framebuffer(color_attachments=[rb])
    e.ctx.copy_framebuffer(fbo, e.ctx.screen)
    data = fbo.read(components=4)
    rb.release(); fbo.release()
    return np.flipud(np.frombuffer(data, dtype='u1').reshape(
        e.height, e.width, 4)[:, :, :3].astype(float) / 255.0)

def build(roll):
    e = editor.EditorApp(640, 480)
    e.clear_scene()
    e.add_model(create_plane(20, 20), editor.Point3D(0, 0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="地面")
    e.add_model(create_cube(1.0), editor.Point3D(0, 1.0, 0), editor.Point3D(0, 0, 0), normal_mode='flat', name="立方体")
    e.add_light('directional', position=(6, 10, 6), direction=(-1, -2, -1),
                shadow=True, mode='beam', shape='rect', size=1.5, roll=roll)
    e.selected_index = -1
    e.camera_target = (0, 1.0, 0); e.camera_distance = 10
    e.camera_yaw = 0.6; e.camera_pitch = -0.35
    e.orbit_mode = True; e.apply_orbit_camera()
    frames(e, 4)
    return e, capture(e)

def samp(e, img, w):
    h = np.array([w[0], w[1], w[2], 1.0]) @ e._vp
    ndc = h[:3] / h[3]
    sx = int((ndc[0] + 1) / 2 * e.width); sy = int((1 - (ndc[1] + 1) / 2) * e.height)
    if not (0 <= sx < e.width and 0 <= sy < e.height):
        return None
    return float(img[max(0, sy-2):sy+3, max(0, sx-2):sx+3].reshape(-1, 3).max())

print("== 矩形光束 roll=0 vs roll=45 (采样光束内若干点) ==")
e0, img0 = build(0)
e45, img45 = build(45)
print("  light.azimuth/elevation/roll:")
for e in (e0, e45):
    lt = e.lights[0]
    print("    az=%.1f el=%.1f roll=%.1f  dir=%s  up=%s" % (
        lt.azimuth, lt.elevation, lt.roll, tuple(round(x,3) for x in lt.direction),
        tuple(round(x,3) for x in lt.up_vector())))
diffs = 0
for name, w in [("光束内(-0.5,-0.5)", (-0.5, 0.02, -0.5)),
                ("光束内(0.5,-0.5)", (0.5, 0.02, -0.5)),
                ("光束内(-0.5,0.5)", (-0.5, 0.02, 0.5)),
                ("光束内(0.5,0.5)", (0.5, 0.02, 0.5)),
                ("立方体顶", (0.0, 1.51, 0.0))]:
    a = samp(e0, img0, w); b = samp(e45, img45, w)
    diff = abs(a - b)
    if diff > 0.02:
        diffs += 1
    print("  %-16s roll0=%.3f roll45=%.3f 差=%.3f" % (name, a, b, diff))
print("== RESULT:", "PASS (roll 旋转光束截面, 边缘点亮度变化)" if diffs >= 1 else "FAIL (roll 无效果)", "==")
pygame.quit()
