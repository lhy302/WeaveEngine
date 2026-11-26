# -*- coding: utf-8 -*-
"""editor/core_gizmo.py — gizmo：轴向基与圆环几何、屏幕命中、拖拽平面求交、拖拽应用与起拖、每帧更新、模式切换。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：gizmo：轴向基与圆环几何、屏幕命中、拖拽平面求交、拖拽应用与起拖、每帧更新、模式切换。
我不负责：拾取与选择态（core_selection）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
import math
import numpy as np
import pygame
from engine import (GLEngine, Point3D, LightState, CameraState, wrap_deg,
                    gc_play_enter, gc_play_exit)
from mathlib.matlib import (mat4_perspective, mat4_ortho, mat4_rotation, mat4_scale,
                    mat4_translation, mat4_view_yaw_pitch, decompose_euler)
from editor.undo import (UndoManager, Command, StateCommand, AddObjectCommand,
                  camera_snapshot, apply_camera_snapshot)

class EditorGizmoMixin(object):
    """gizmo：轴向基与圆环几何、屏幕命中、拖拽平面求交、拖拽应用与起拖、每帧更新、模式切换（纯搬迁）。"""

    def _camera_forward(self):
        """相机前方 (+z_view), 从 target 指向 eye 的反方向"""
        yaw, pitch = self.camera_yaw, self.camera_pitch
        return (math.sin(yaw) * math.cos(pitch),
                math.sin(pitch),
                math.cos(yaw) * math.cos(pitch))

    @staticmethod
    def _seg_dist(p, a, b):
        """点 p 到线段 ab 的距离 (屏幕像素空间)"""
        ax, ay = a; bx, by = b; px, py = p
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _gizmo_basis(self, axis):
        """轴 a 法向平面内的正交基 (u, v): u ⊥ a, v = cross(a, u)"""
        a = np.array(self._GIZMO_AXES[axis])
        ref = np.array((0.0, 0.0, 1.0)) if abs(a[2]) < 0.9 else np.array((1.0, 0.0, 0.0))
        u = np.cross(a, ref)
        u = u / np.linalg.norm(u)
        return u, np.cross(a, u)

    def _gizmo_circle_points(self, o, R, u, v):
        """圆环点列 (世界空间, 轴法向平面内)"""
        pts = []
        for i in range(self._GIZMO_SEGS):
            th = 2 * math.pi * i / self._GIZMO_SEGS
            pts.append((o[0] + R * (math.cos(th) * u[0] + math.sin(th) * v[0]),
                        o[1] + R * (math.cos(th) * u[1] + math.sin(th) * v[1]),
                        o[2] + R * (math.cos(th) * u[2] + math.sin(th) * v[2])))
        return pts

    def _gizmo_hit(self, px, py):
        """屏幕点 -> 命中轴 (平移: 轴线段; 旋转: 圆环段) 或 None.
        M21: 点光源可平移不可旋转; 平行光 gizmo 目标为 None."""
        t = self._gizmo_target()
        if t is None:
            return None
        if self.gizmo_mode == 'rotate' and isinstance(t, (LightState, CameraState)):
            return None
        o = self._target_world_pos(self, t)
        best, best_d = None, self._GIZMO_HIT_PX
        if self.gizmo_mode == 'translate':
            L = self._GIZMO_LEN
            oproj = self.project_world(o)
            if oproj is None:
                return None               # 目标在相机背后: gizmo 不可见, 不命中
            ox, oy = oproj
            for axis, (ax, ay, az) in self._GIZMO_AXES.items():
                eproj = self.project_world((o[0] + L * ax, o[1] + L * ay, o[2] + L * az))
                if eproj is None:
                    continue              # 轴端在相机背后: 该轴帽不可见, 不命中
                ex, ey = eproj
                d = self._seg_dist((px, py), (ox, oy), (ex, ey))
                if d < best_d:
                    best_d = d
                    best = axis
        else:
            R = self._GIZMO_RAD
            for axis in self._GIZMO_AXES:
                u, v = self._gizmo_basis(axis)
                pts = self._gizmo_circle_points(o, R, u, v)
                for i in range(self._GIZMO_SEGS):
                    a = self.project_world(pts[i])
                    b = self.project_world(pts[(i + 1) % self._GIZMO_SEGS])
                    if a is None or b is None:
                        continue          # 圆环段在相机背后: 不命中
                    d = self._seg_dist((px, py), a, b)
                    if d < best_d:
                        best_d = d
                        best = axis
        return best

    def _gizmo_ray_plane_hit(self, axis, o, px, py):
        """射线交过 o、法线 = axis 的平面, 返回命中点向量 (或 None)"""
        a = np.array(self._GIZMO_AXES[axis])
        origin, dirv = self._ray_from_mouse(px, py)
        d = np.array(dirv)
        denom = float(np.dot(a, d))
        if abs(denom) < 1e-8:
            return None
        t = float(np.dot(a, np.array(o) - np.array((origin.x, origin.y, origin.z)))) / denom
        return np.array((origin.x, origin.y, origin.z)) + t * d

    def _local_delta(self, m, world_delta):
        """世界增量 -> 局部增量 (除父级旋转+缩放; 根=恒等). 行向量: local = world @ inv(parent3x3)"""
        par3 = self.parent_world_matrix(m)[:3, :3]
        return np.asarray(world_delta, dtype=np.float64) @ np.linalg.inv(par3)

    def _gizmo_drag_apply(self):
        """拖拽中: 平移=世界轴分量转局部增量; 旋转=世界轴增量合成后转局部欧拉.
        M21: 目标可以是点光源 (平移走自身 position, 无父链; 旋转不支持)."""
        t = self._gizmo_target()
        if t is None:
            return
        if self.gizmo_mode == 'translate':
            axis, start_world, start_local = self.gizmo_drag[:3]
            a = np.array(self._GIZMO_AXES[axis])
            origin, dirv = self._ray_from_mouse(*self.view.input_state()['mouse_pos'])
            oo = np.array((origin.x, origin.y, origin.z))
            d = np.array(dirv)
            # 拖拽平面: 过拖拽起点、法线 = 相机视线 (正对相机, 射线几乎垂直穿过, denom 稳定).
            # 旧实现用 cross(axis, view_forward) 当法线 -> 平面永远包含视线方向, 射线与平面近似平行,
            # denom≈0 -> 交点被浮点噪声放大成巨大位移 (视角与轴越接近越严重) -> 物体拖飞.
            n = np.array(self._camera_forward())
            denom = float(np.dot(n, d))
            if abs(denom) < 1e-8:          # 几乎不可能 (射线与视线夹角极小)
                return
            pp = np.array(start_world)
            dist = float(np.dot(n, pp - oo)) / denom
            hit = oo + dist * d
            # 平面命中点投影到拖拽轴: 轴正对相机(∥视线)时 t_axis≈0 拖不动
            # (该轴在屏幕上无投影, 点也是 gizmo 端点小球, 符合直觉; 不再拖飞)
            t_axis = float(np.dot(hit - pp, a))
            new_world = pp + a * t_axis
            # 世界增量 -> 局部增量 (父旋转/缩放逆变换); 光源无父链 = 恒等;
            # 2026-08-16 相机物体化: 摄像机也走 _local_delta (有父时转父空间局部)
            wd = new_world - pp
            ld = wd if isinstance(t, LightState) else self._local_delta(t, wd)
            t.position = Point3D(float(start_local[0] + ld[0]),
                                 float(start_local[1] + ld[1]),
                                 float(start_local[2] + ld[2]))
        else:
            if isinstance(t, (LightState, CameraState)):
                return                       # 光源/摄像机不可旋转 (gizmo_hit 已挡)
            axis, start_world_R, start_local_euler, start_theta = self.gizmo_drag
            u, v = self._gizmo_basis(axis)
            oo = np.array(self.world_position(t))
            hit = self._gizmo_ray_plane_hit(axis, oo, *self.view.input_state()['mouse_pos'])
            if hit is None:
                return
            rel = hit - oo
            theta = math.atan2(float(np.dot(rel, v)), float(np.dot(rel, u)))
            delta_angle = theta - start_theta
            # 世界轴增量旋转矩阵 (行主序)
            a = np.array(self._GIZMO_AXES[axis])
            R_delta = mat4_rotation(np, a[0] * delta_angle, a[1] * delta_angle,
                                    a[2] * delta_angle)
            # 新世界旋转 = 增量 @ 起始世界旋转 (行向量先乘增量)
            new_world_R = R_delta @ np.asarray(start_world_R)
            # 转回局部: 局部旋转 = 新世界旋转 @ inv(父世界旋转)
            par_R = (self.world_rotation_matrix(t.parent)
                     if t.parent is not None else np.eye(4, dtype=np.float64))
            new_local_R = new_world_R @ np.linalg.inv(par_R)
            alpha, beta, gamma = decompose_euler(new_local_R)
            t.rotation = Point3D(alpha, beta, gamma)

    def _gizmo_start_drag(self, axis, px, py):
        """在按下点启动拖拽, 记起点 (世界基准) + 撤销前快照.
        M21: 点光源只走平移; 平行光 gizmo 目标为 None."""
        t = self._gizmo_target()
        if t is None:
            return
        if self.gizmo_mode == 'rotate' and isinstance(t, (LightState, CameraState)):
            return
        self.gizmo_axis = axis
        if self.gizmo_mode == 'translate':
            w = self._target_world_pos(self, t)
            self.gizmo_drag = (axis, w,
                               (t.position.x, t.position.y, t.position.z))
        else:
            oo = np.array(self.world_position(t))
            u, v = self._gizmo_basis(axis)
            hit = self._gizmo_ray_plane_hit(axis, oo, px, py)
            if hit is None:
                return
            rel = hit - oo
            start_theta = math.atan2(float(np.dot(rel, v)), float(np.dot(rel, u)))
            self.gizmo_drag = (axis, np.array(self.world_rotation_matrix(t)),
                               (t.rotation.x, t.rotation.y, t.rotation.z),
                               start_theta)
        self.gizmo_undo_before = (light_snapshot(t) if isinstance(t, LightState)
                                  else camera_snapshot(t) if isinstance(t, CameraState)
                                  else undo_snapshot(t))

    def _update_gizmo(self):
        """视口交互: gizmo 拖拽 > 点选. GUI 未抢点击时处理."""
        # 拖拽中: 每帧重算 (左键松开即结束 -> 压撤销栈)
        if self.gizmo_drag is not None:
            if not self.buttons[0]:
                if self.gizmo_undo_before is not None:
                    t = self._gizmo_target()
                    if t is not None:
                        label = "移动" if self.gizmo_mode == 'translate' else "旋转"
                        if isinstance(t, LightState):
                            after = light_snapshot(t)
                            if after != self.gizmo_undo_before:
                                self.undo.push(LightStateCommand(
                                    label, self, t, self.gizmo_undo_before, after))
                        elif isinstance(t, CameraState):
                            after = camera_snapshot(t)
                            if after != self.gizmo_undo_before:
                                self.undo.push(CameraStateCommand(
                                    label, self, t, self.gizmo_undo_before, after))
                        else:
                            after = undo_snapshot(t)
                            if after != self.gizmo_undo_before:
                                self.undo.push(StateCommand(
                                    label, self, t, self.gizmo_undo_before, after))
                self.gizmo_drag = None
                self.gizmo_axis = None
                self.gizmo_undo_before = None
            else:
                self._gizmo_drag_apply()
            return
        # 无拖拽: 只在左键按下帧处理 (Alt 按下时归相机轨道, 不点选)
        # P-22/F3 (2026-11-07): Qt 宿主 _on_tick 在 _update_camera() 之后清空
        # pressed, 而 _update_gizmo 在随后的 paintGL/render 里跑 —— 只读
        # self.pressed 会永远拿不到点击。用 _update_camera 记下的"代际点击"
        # (gen + 屏幕坐标) 消费一次; 直接调 _update_gizmo 的旧路径仍认 pressed。
        click_gen = getattr(self, '_gizmo_click_gen', 0)
        consumed_gen = getattr(self, '_gizmo_consumed_gen', 0)
        pending = click_gen != consumed_gen
        if pending:
            # 无论本次是否命中 (UI 抢走/点面板/Alt) 都只消费一次, 防陈旧点击重放
            self._gizmo_consumed_gen = click_gen
            pp = getattr(self, '_gizmo_click_pos', None)
            if pp is None:
                pp = self.mouse_press_pos.get(1)
        else:
            if 1 not in getattr(self, 'pressed', ()):
                return
            pp = self.mouse_press_pos.get(1)
            # 若本帧 paintGL 先于 _on_tick (旧 pressed 路径已消费), 记下按下的
            # 坐标对象, 让随后 _update_camera 的代际登记跳过同一次按下 —— 防
            # 两种事件顺序下同一击被拾取两次。
            self._gizmo_consumed_press = pp
        if self.view.input_state()['click_captured']:
            return
        if getattr(self, 'ui_consumed', False):    # 2026-10-18: UI 命中则跳过 3D 拾取
            return
        if self._mods & pygame.KMOD_ALT:
            return
        if pp is None:
            return
        vp = self._layout()[4]
        if not (vp[0] <= pp[0] < vp[0] + vp[2] and
                vp[1] <= pp[1] < vp[1] + vp[3]):
            return
        # gizmo 命中优先于点选
        axis = self._gizmo_hit(pp[0], pp[1])
        if axis is not None:
            self._gizmo_start_drag(axis, pp[0], pp[1])
        else:
            self._pick(pp[0], pp[1])

    # ================ UI 命令层 (2026-08-13: UI 模块化) ================
    # UI (IEditorView) 所有"会改变引擎状态"的写操作都走这里 —— 内部统一处理撤销,
    # 面板不直接 push undo. 三种对象 (物体/光源/摄像机) 各配 edit_*(拖拽)/commit_*(单次)
    # 两个入口 + rename_*(名称失焦提交).
    def set_gizmo_mode(self, mode):
        """切换 gizmo 模式 (translate/rotate)."""
        if self.gizmo_mode != mode:
            self.gizmo_mode = mode
            self.gizmo_drag = None
            self.gizmo_axis = None

    # ================ gizmo 目标 (物体或光源) ================
    def _gizmo_target(self):
        """gizmo 操作目标: 光源/摄像机选中 -> 光源/摄像机 (可平移定位点, 旋转不支持);
        否则物体. 平行光方向走检查器 (3 角度), 位置走 gizmo 平移/检查器 (2026-08-12).
        M41: 摄像机同样可平移 (位置 gizmo), 旋转不支持."""
        light = self._selected_light()
        if light is not None:
            return light
        cam = self._selected_camera()
        if cam is not None:
            return cam
        return self._selected()

    @staticmethod
    def _target_world_pos(engine, t):
        """目标的世界位置: LightState 用自身 position, CameraState 走父链合成
        (相机物体化), ModelState 走父链合成"""
        if isinstance(t, LightState):
            return (t.position.x, t.position.y, t.position.z)
        if isinstance(t, CameraState):
            return engine.camera_world_position(t)
        return engine.world_position(t)

    # ================ gizmo (M9 平移 / M10 旋转) ================
    _GIZMO_AXES = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}

    _GIZMO_COLORS = {'X': (0.9, 0.2, 0.2), 'Y': (0.2, 0.9, 0.2), 'Z': (0.25, 0.4, 0.9)}

    _GIZMO_LEN = 1.5

    _GIZMO_RAD = 1.5

    _GIZMO_SEGS = 48

    _GIZMO_HIT_PX = 10.0
