# -*- coding: utf-8 -*-
"""临时探针: 新网格 (相机为中心) 顶点投影到视图空间, 确认始终在相机前方 + 落在屏幕."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import pygame

import editor
from matlib import mat4_view_yaw_pitch, mat4_perspective

app = editor.EditorApp(480, 320)


def analyze(pitch_deg):
    app.camera_pitch = math.radians(pitch_deg)
    app.apply_orbit_camera()
    eye = (app.camera.x, app.camera.y, app.camera.z)
    out = app.grid_geometry()
    if out is None:
        return "无网格"
    verts, cols = out
    V = mat4_view_yaw_pitch(np, eye, app.camera_yaw, app.camera_pitch)
    P = mat4_perspective(np, app._fov, app.width / app.height, app.near, app.far)
    h = np.concatenate([verts, np.ones((len(verts), 1))], axis=1)
    view = h @ V                       # z_view>0 = 相机前方
    ndc = h @ (V @ P)
    w = ndc[:, 3]
    in_front = view[:, 2] > 0
    on_screen = (np.abs(ndc[:, 0]) < w) & (np.abs(ndc[:, 1]) < w) & (ndc[:, 2] >= 0) & (ndc[:, 2] <= w)
    n = len(verts)
    return ("顶点%d | 前方%d(%.0f%%) | 屏幕内%d(%.0f%%)" %
            (n, int(in_front.sum()), in_front.mean() * 100,
             int(on_screen.sum()), on_screen.mean() * 100))


for pitch_deg in (-60, -30, 0, 30, 60):
    print("pitch=%+4d° eye.y=%+6.2f -> %s" %
          (pitch_deg, app.camera.y, analyze(pitch_deg)))
app._stop_parallel()
pygame.quit()
print("VIEWSPACE PROBE DONE ✅")
