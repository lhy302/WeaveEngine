# -*- coding: utf-8 -*-
"""
gui/panels/gizmo_mixin.py — 视口叠加绘制（gizmo / 光源相机图标 / 朝向）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：选中对象的 gizmo、光源/相机图标与方向锥/朝向线等视口叠加绘制辅助。
我不负责：draw() 主叠加流程与帧驱动（主窗口）、检查器面板构建（inspector_mixin）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

import math


class GizmoMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    # ---------------- 视口叠加 (与旧版GUI 同路径: draw_lines/draw_screen_rect) ----------------
    def _draw_gizmo(self, ctl):
        from engine import LightState, CameraState   # 仅判类型用 (函数内 import 防环)
        t = ctl._gizmo_target()
        if t is None or (not isinstance(t, (LightState, CameraState))
                         and not t.visible):
            return
        o = ctl._target_world_pos(ctl, t)
        lines, cols = [], []
        if ctl.gizmo_mode == 'translate':
            L = ctl._GIZMO_LEN
            for axis in ('X', 'Y', 'Z'):
                ax = ctl._GIZMO_AXES[axis]
                col = (1.0, 1.0, 1.0) if axis == ctl.gizmo_axis else ctl._GIZMO_COLORS[axis]
                lines += [(o[0], o[1], o[2]),
                          (o[0] + L * ax[0], o[1] + L * ax[1], o[2] + L * ax[2])]
                cols += [col, col]
                # 轴端小方块帽 (屏幕投影)
                cap = ctl.project_world((o[0] + L * ax[0], o[1] + L * ax[1],
                                         o[2] + L * ax[2]))
                if cap is None:
                    continue              # 轴端在相机背后: 不画帽 (背面镜像, 2026-08-21)
                ex, ey = cap
                s = 8
                ctl.draw_screen_rect((ex - s / 2, ey - s / 2, s, s),
                                     tuple(int(c * 255) for c in ctl._GIZMO_COLORS[axis]))
        else:
            R = ctl._GIZMO_RAD
            for axis in ('X', 'Y', 'Z'):
                u, v = ctl._gizmo_basis(axis)
                pts = ctl._gizmo_circle_points(o, R, u, v)
                col = (1.0, 1.0, 1.0) if axis == ctl.gizmo_axis else ctl._GIZMO_COLORS[axis]
                for i in range(ctl._GIZMO_SEGS):
                    lines.append(pts[i])
                    lines.append(pts[(i + 1) % ctl._GIZMO_SEGS])
                    cols += [col, col]
            rot_center = ctl.project_world(o)
            if rot_center is not None:
                cx, cy = rot_center
                ctl.draw_screen_rect((cx - 3, cy - 3, 6, 6), (255, 255, 255))
        if lines:
            # 2026-08-22 A11 修复: gizmo 必须恒可见 (选中框同款逻辑) —— 主 pass
            # 渲染后 GL 残留 DEPTH_TEST=on, 裸调 draw_lines 的棒/圆环线会被身前
            # 物体遮挡 (用户实测"拉条被物体挡住无法拖动"); scope enable_only=0
            # 关全部深度测试. enable_only 破坏 GL_LINE_WIDTH 由 draw_lines 内部
            # 每帧重设 2.0 抵消 (2026-08-18 修复), 选中框已同款实践证明有效.
            with ctl.overlay_scope(framebuffer=ctl._screen_fb(), enable_only=0):
                ctl.draw_lines(lines, cols)

    def _icon_size(self, ctl, p):
        return max(6.0, min(14.0, ctl.camera_distance * 0.35))

    def _direction_cone(self, ax, ay, az, dx, dy, dz, L, col):
        """顶端指向圆锥 (线框): 尖端 (ax,ay,az) 朝向 (dx,dy,dz), 基圆在线后端.
        2026-08-22 从旧版GUI移植 (Qt 版此前为"简化直线", 用户报缺失)."""
        cone_len, cone_r = 0.25 * L, 0.18 * L
        ref = (0, 1, 0) if abs(dy) < 0.9 else (1, 0, 0)
        ux, uy, uz = (dy * ref[2] - dz * ref[1],
                      dz * ref[0] - dx * ref[2],
                      dx * ref[1] - dy * ref[0])
        nl = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
        ux, uy, uz = ux / nl, uy / nl, uz / nl
        vx, vy, vz = (uy * dz - uz * dy, uz * dx - ux * dz, ux * dy - uy * dx)
        bx, by, bz = ax - dx * cone_len, ay - dy * cone_len, az - dz * cone_len
        verts, cols2 = [], []
        nseg = 12
        for i in range(nseg):
            t0 = 2 * math.pi * i / nseg
            t1 = 2 * math.pi * (i + 1) / nseg
            c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
            p0 = (bx + (ux * c0 + vx * s0) * cone_r,
                  by + (uy * c0 + vy * s0) * cone_r,
                  bz + (uz * c0 + vz * s0) * cone_r)
            p1 = (bx + (ux * c1 + vx * s1) * cone_r,
                  by + (uy * c1 + vy * s1) * cone_r,
                  bz + (uz * c1 + vz * s1) * cone_r)
            verts.append((ax, ay, az)); verts.append(p0)
            verts.append(p0); verts.append(p1)
            cols2.extend([col, col, col, col])
        return verts, cols2

    def _draw_light_icons(self, ctl):
        sel = ctl._selected_light()
        for light in ctl.lights:
            p = (light.position.x, light.position.y, light.position.z)
            scr = ctl.project_world(p)
            if scr is None:
                continue                  # 光源在相机背后: 图标/朝向线不画 (2026-08-21)
            sx, sy = scr
            s = self._icon_size(ctl, p)
            col = (230, 200, 90) if light.kind == 'directional' else (240, 150, 70)
            if light is sel:
                ctl.draw_screen_rect((sx - s / 2 - 2, sy - s / 2 - 2, s + 4, s + 4),
                                     (255, 255, 255))
            ctl.draw_screen_rect((sx - s / 2, sy - s / 2, s, s), col)
            if light is sel and light.kind == 'directional':
                self._draw_directional_dir(ctl, light, p)

    def _draw_directional_dir(self, ctl, light, p):
        """选中方向光: 朝向线 + 指向圆锥 + roll 倾斜箭头 + 光束截面 (mode=beam).
        2026-08-22 对齐旧版GUI (原"简化版"缺锥体/roll 箭头/矩形截面, 用户报缺失)."""
        D = (light.direction.x, light.direction.y, light.direction.z)
        ln = math.sqrt(D[0] * D[0] + D[1] * D[1] + D[2] * D[2])
        if ln < 1e-6:
            return
        u = (D[0] / ln, D[1] / ln, D[2] / ln)
        L = 2.2
        col = (0.9, 0.78, 0.35)
        lines = [(p[0], p[1], p[2]),
                 (p[0] + u[0] * L, p[1] + u[1] * L, p[2] + u[2] * L)]
        cols = [col, col]
        # 指向圆锥 (线框, 尖端在光束末端)
        ex, ey, ez = p[0] + u[0] * L, p[1] + u[1] * L, p[2] + u[2] * L
        cone_v, cone_c = self._direction_cone(ex, ey, ez, u[0], u[1], u[2], L, col)
        lines += cone_v
        cols += cone_c
        # roll 倾斜方向箭头 (M30/M41 同款): 朝向线中点 1/4 大小黄色箭头 -> up_vector
        try:
            up = light.up_vector()
            mL = L * 0.25
            mx, my, mz = (p[0] + u[0] * (L / 2),
                          p[1] + u[1] * (L / 2), p[2] + u[2] * (L / 2))
            tx, ty, tz = mx + up.x * mL, my + up.y * mL, mz + up.z * mL
            lines.append((mx, my, mz)); lines.append((tx, ty, tz))
            cols.append((0.95, 0.75, 0.25)); cols.append((0.95, 0.75, 0.25))
            cone2_v, cone2_c = self._direction_cone(tx, ty, tz, up.x, up.y, up.z,
                                                    mL, (0.95, 0.75, 0.25))
            lines += cone2_v
            cols += cone2_c
        except Exception:
            pass
        if getattr(light, 'mode', 'full') == 'beam':
            # 光束截面: 垂直于方向的圆环 (shape=circle) 或矩形 (shape=rect)
            R = getattr(light, 'size', 5.0)
            o = (p[0] + u[0] * L, p[1] + u[1] * L, p[2] + u[2] * L)
            # 截面基 = 光源 up_vector (含方位/俯仰/roll 全部倾斜, 引擎保证恒
            # ⊥ 方向线) + cross(up, direction): 法线严格=光方向, 倾斜随 roll
            # —— 2026-08-22 用户实测原"世界轴参考"只在一个轴面上近似同步且
            # 未应用倾斜, 对齐旧版GUI._draw_beam_cross_section 正确算法
            up = light.up_vector()
            vx = (up.x, up.y, up.z)
            vy = (up.y * u[2] - up.z * u[1], up.z * u[0] - up.x * u[2],
                  up.x * u[1] - up.y * u[0])
            if getattr(light, 'shape', 'circle') == 'circle':
                for i in range(36):
                    a = i / 36 * math.tau
                    b = (i + 1) / 36 * math.tau
                    lines.append((o[0] + R * (math.cos(a) * vx[0] + math.sin(a) * vy[0]),
                                  o[1] + R * (math.cos(a) * vx[1] + math.sin(a) * vy[1]),
                                  o[2] + R * (math.cos(a) * vx[2] + math.sin(a) * vy[2])))
                    lines.append((o[0] + R * (math.cos(b) * vx[0] + math.sin(b) * vy[0]),
                                  o[1] + R * (math.cos(b) * vx[1] + math.sin(b) * vy[1]),
                                  o[2] + R * (math.cos(b) * vx[2] + math.sin(b) * vy[2])))
                    cols += [col, col]
            else:
                corners = [(o[0] + (vx[0] * a + vy[0] * b) * R,
                            o[1] + (vx[1] * a + vy[1] * b) * R,
                            o[2] + (vx[2] * a + vy[2] * b) * R)
                           for a in (-1, 1) for b in (-1, 1)]
                for a, b in ((0, 1), (1, 3), (3, 2), (2, 0)):
                    lines.append(corners[a]); lines.append(corners[b])
                    cols += [col, col]
        # 2026-08-22: 光源指示线/锥/截面恒可见 (同 gizmo A11 修复)
        with ctl.overlay_scope(framebuffer=ctl._screen_fb(), enable_only=0):
            ctl.draw_lines(lines, cols)

    def _draw_camera_icons(self, ctl):
        sel = ctl._selected_camera()
        for cam in ctl.cameras:
            p = (cam.position.x, cam.position.y, cam.position.z)
            scr = ctl.project_world(p)
            if scr is None:
                continue                  # 摄像机在相机背后: 图标不画 (2026-08-21)
            sx, sy = scr
            s = self._icon_size(ctl, p)
            if cam is sel:
                ctl.draw_screen_rect((sx - s / 2 - 2, sy - s / 2 - 2, s + 4, s + 4),
                                     (255, 255, 255))
            ctl.draw_screen_rect((sx - s / 2, sy - s / 2, s, s), (140, 191, 242))
            if cam is sel:
                # 朝向线 + 指向圆锥 + roll 倾斜箭头 (M41, 2026-08-22 对齐旧版GUI)
                yaw, pitch = cam.yaw, cam.pitch
                dx = math.sin(yaw) * math.cos(pitch)
                dy = math.sin(pitch)
                dz = math.cos(yaw) * math.cos(pitch)
                L = 1.2
                lines = [p, (p[0] + dx * L, p[1] + dy * L, p[2] + dz * L)]
                cols = [(0.55, 0.75, 0.95), (0.55, 0.75, 0.95)]
                ex, ey, ez = p[0] + dx * L, p[1] + dy * L, p[2] + dz * L
                cone_v, cone_c = self._direction_cone(ex, ey, ez, dx, dy, dz, L,
                                                      (0.55, 0.75, 0.95))
                lines += cone_v
                cols += cone_c
                # roll 方向标识 (世界基 ey = roll 上): 中线 1/4 黄色箭头 -> up
                try:
                    _exw, _eyw, _ezw = ctl.camera_world_basis(cam)
                    up = (_eyw[0], _eyw[1], _eyw[2])
                    mL = L * 0.25
                    mx, my, mz = p[0] + dx * (L / 2), p[1] + dy * (L / 2), p[2] + dz * (L / 2)
                    tx, ty, tz = mx + up[0] * mL, my + up[1] * mL, mz + up[2] * mL
                    lines.append((mx, my, mz)); lines.append((tx, ty, tz))
                    cols.append((0.95, 0.75, 0.25)); cols.append((0.95, 0.75, 0.25))
                    cone2_v, cone2_c = self._direction_cone(tx, ty, tz, up[0], up[1],
                                                            up[2], mL, (0.95, 0.75, 0.25))
                    lines += cone2_v
                    cols += cone2_c
                except Exception:
                    pass
                # 2026-08-22: 相机朝向线/锥/roll 箭头恒可见 (同 gizmo A11 修复)
                with ctl.overlay_scope(framebuffer=ctl._screen_fb(), enable_only=0):
                    ctl.draw_lines(lines, cols)
