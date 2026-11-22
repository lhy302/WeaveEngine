# -*- coding: utf-8 -*-
"""test_line_depth_plane.py — 粗线四边形**深度落在原平面**上（Q-B7-53-1 根因门）。

为什么有这个门（2026-11-22，Q-B7-53-1 真窗口取证）：
  `build_line_quads` 把线段扩宽成屏幕空间四边形时，每个角点的 NDC z 必须取自
  **它所在的那个端点**：a/e 在 p0 -> z0，b/d 在 p1 -> z1。旧实现把 b 取了 z0、
  e 取了 z1（两者互换），四边形被“拧”成深度不连续的两块。短线段看不出来（两端
  z 差很小），但网格线是 ±60 世界的长线段：一条线经常一端在相机背后（近平面裁剪
  点 w≈0 -> 屏幕坐标上万像素，z=0），另一端在远处（z≈1）。被拧过的那半个三角形
  在屏幕空间横跨整个视口，插值出的深度（实测 0.648）比地面真实深度（0.993）小得多
  -> 网格线穿过物体（“网格永远在最上层”的真因之一；另一条是 GL 叠加层深度目标
  不是场景深度目标，见 test_grid_occlusion_parity.py）。

本门判据（不依赖任何后端/窗口，纯 CPU）：
  · 取编辑器同款透视 VP + ui.grid.build_grid_lines 的真实网格几何；
  · 对每个扩宽后的三角形，取其重心像素（屏幕内、射线能打到 y=0 平面）：
      quad 插值深度  ≈  该像素射线打到地面的真实 NDC z
    两者偏差 > 1e-3 记一条违规（NDC z，深度缓冲精度 1e-7 量级，1e-3 极宽松）；
  · 违规必须为 0 —— 否则“网格在物体前面”就是几何算错，不是深度开关的问题。

修前必红：旧代码（b/e 的 z 互换）实测违规 55 条、最大偏差 0.345（交付报告留实跑原文）。
"""
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

from mathlib.matlib import mat4_perspective, mat4_view_yaw_pitch
from mathlib.line_geometry import build_line_quads
from ui.grid import build_grid_lines

W, H = 900, 390
EYE = (3.7, 5.0, -2.2)
TARGET = (0.0, 0.0, 0.0)

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


def _vp():
    """编辑器同款（行向量约定 clip = [x,y,z,1] @ VP）：VP = View @ Proj。

    相机姿态与 _compute_view_proj 同一条路径（mat4_view_yaw_pitch + mat4_perspective），
    只是 yaw/pitch 由 EYE->TARGET 方向反算（等价于轨道相机看向原点）。
    """
    d = np.array(TARGET, dtype=np.float64) - np.array(EYE, dtype=np.float64)
    d /= np.linalg.norm(d)
    yaw = float(np.arctan2(d[0], d[2]))
    pitch = float(np.arcsin(max(-1.0, min(1.0, d[1]))))
    view = mat4_view_yaw_pitch(np, EYE, yaw, pitch, 0.0)
    proj = mat4_perspective(np, np.radians(60.0), W / float(H), 0.1, 500.0)
    return np.asarray(view, dtype=np.float64) @ np.asarray(proj, dtype=np.float64)


def _ray_ground_z(px, py, VP):
    """屏幕像素 -> 射线与 y=0 平面的交点 -> 该点的 NDC z（打不到返回 None）。"""
    inv = np.linalg.inv(VP)

    def unproj(z):
        v = np.array([2.0 * px / W - 1.0, 1.0 - 2.0 * py / H, z, 1.0]) @ inv
        return v[:3] / v[3]

    a, b = unproj(0.0), unproj(1.0)
    dy = b[1] - a[1]
    if abs(dy) < 1e-12:
        return None
    t = -a[1] / dy
    if not (0.0 <= t <= 1.0):
        return None
    p = a + t * (b - a)
    clip = np.array([p[0], p[1], p[2], 1.0]) @ VP
    if clip[3] <= 0:
        return None
    return float(clip[2] / clip[3])


def _screen(v):
    return ((v[0] * 0.5 + 0.5) * W, (0.5 - v[1] * 0.5) * H)


def _bary(tri, px, py):
    (x0, y0), (x1, y1), (x2, y2) = [(t[0], t[1]) for t in tri]
    d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(d) < 1e-12:
        return None
    a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d
    b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d
    return a, b, 1.0 - a - b


def main():
    VP = _vp()
    verts, cols = build_grid_lines(EYE)
    q, qc, qvp = build_line_quads(verts, cols, VP, width_px=2.0,
                                  viewport_size=(W, H), mode='lines')
    n_tri = len(q) // 3
    check("网格扩宽后有三角形（前置：几何非空）", n_tri > 0, n_tri)
    check("扩宽输出配恒等 VP（顶点已是 NDC）",
          np.allclose(np.asarray(qvp), np.eye(4), atol=1e-6))

    bad = []
    tested = 0
    for t in range(0, len(q), 3):
        tri = np.array([_screen(v) for v in q[t:t + 3]])
        tri3 = np.array(q[t:t + 3], dtype=np.float64)
        x0 = max(0, int(np.floor(tri[:, 0].min())))
        x1 = min(W - 1, int(np.ceil(tri[:, 0].max())))
        y0 = max(0, int(np.floor(tri[:, 1].min())))
        y1 = min(H - 1, int(np.ceil(tri[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue
        # 三角形屏幕包围盒内取 6x6 采样点（重心坐标 >= 0 才算覆盖）——
        # 长条形三角形（近平面裁剪产物）也能被采到。
        for sx in np.linspace(x0, x1, 6):
            for sy in np.linspace(y0, y1, 6):
                bc = _bary(tri, sx, sy)
                if bc is None or min(bc) < 0.0:
                    continue
                z_true = _ray_ground_z(sx, sy, VP)
                if z_true is None:
                    continue
                z_quad = float(bc[0] * tri3[0, 2] + bc[1] * tri3[1, 2] + bc[2] * tri3[2, 2])
                tested += 1
                if abs(z_quad - z_true) > 1e-3:
                    bad.append((round(float(z_quad), 6), round(float(z_true), 6),
                                round(float(z_quad - z_true), 6)))
    check("网格三角形覆盖像素数（前置：真的覆盖到屏幕）", tested >= 8, tested)
    check("每块四边形插值深度 == 地面真实深度（偏差 <= 1e-3）", not bad,
          "违规 %d 条, 示例 %r" % (len(bad), bad[:5]))
    n_znear = int(sum(1 for v in q if abs(float(v[2])) < 1e-9))
    check("近平面裁剪顶点存在（前置：本场景真的触发裁剪）", n_znear > 0, n_znear)

    # 结构锁（防将来把角点 z 又换回去）：每块四边形 6 个顶点 = (a,d,b) + (a,e,d)，
    # a/e 是 p0 端 -> 必须同 z；b/d 是 p1 端 -> 必须同 z。
    # 旧代码 b 取 z0、e 取 z1（互换）：只要两端 z 不同，这两对就必然不等。
    mism = 0
    for k in range(0, len(q), 6):
        z = [float(v[2]) for v in q[k:k + 6]]
        if abs(z[0] - z[4]) > 1e-9 or abs(z[1] - z[2]) > 1e-9:
            mism += 1
    check("结构：四边形同一端点的两个角点 z 相同（a/e 同 z0, b/d 同 z1）",
          mism == 0, "违规四边形 %d / %d" % (mism, len(q) // 6))

    print()
    if not ok:
        print("FAIL: test_line_depth_plane.py")
        sys.exit(1)
    print("ALL PASS (test_line_depth_plane.py)")


main()
