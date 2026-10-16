# -*- coding: utf-8 -*-
"""loom_camera.py — GLEngine 相机控制子系统 (开发者轨道相机 + 键控移动/旋转)。

从 engine.py 抽出 (作为 CameraMixin 供 GLEngine 继承):
  apply_orbit_camera   (轨道相机: target/yaw/pitch/distance -> 眼睛位置)
  move_camera          (WASD+QE 键控平移)
  rotate_camera        (方向键键控转视角)

依赖宿主 GLEngine 运行时提供:
  self.camera / self.camera_target / self.camera_distance /
  self.camera_yaw / self.camera_pitch / self.camera_roll /
  self.camera_move_speed / self.camera_rotation_speed /
  self.key_state / self._key / self._cam_speed
mixin 只通过 self 按需访问 (语义与拆分前逐位一致)。
"""
import math

import numpy as np

from loom_types import Point3D
from loom_scene_entities import CameraState, wrap_deg
from matlib import view_basis_to_angles


class CameraMixin:

    def apply_orbit_camera(self):
        """轨道相机: 由 target/yaw/pitch/distance 反推眼睛位置, 复用 mat4_view_yaw_pitch.
        ez = (sin yaw cos pitch, sin pitch, cos yaw cos pitch) 为相机前方 (+z_view).
        M41 修复: 开发者轨道相机恒直立 —— 强制 camera_roll=0 (预览倾斜相机/播放还原
        不会把 roll 残留到轨道视角)."""
        self.camera_roll = 0.0       # 不变式: 轨道(开发者)视角 roll 恒 0
        yaw, pitch, dist = self.camera_yaw, self.camera_pitch, self.camera_distance
        ez = (math.sin(yaw) * math.cos(pitch),
              math.sin(pitch),
              math.cos(yaw) * math.cos(pitch))
        t = self.camera_target
        self.camera = Point3D(t[0] - dist * ez[0],
                              t[1] - dist * ez[1],
                              t[2] - dist * ez[2])

    def move_camera(self, delta_time):
        """根据按键状态移动相机"""
        # 2026-08-19: 引擎设置项 cam_speed 倍率 (0.5-2.0, 默认 1.0) ——
        # 编辑器/播放器移速统一受倍率控制 (缓存读取, 设置面板改后更新实例)
        if not hasattr(self, '_cam_speed'):
            try:
                import guiloader
                self._cam_speed = float(guiloader.load_settings('loom').get('cam_speed', 1.0))
            except Exception:
                self._cam_speed = 1.0
        move_speed = self.camera_move_speed * delta_time * self._cam_speed
        sin_yaw = math.sin(self.camera_yaw)
        cos_yaw = math.cos(self.camera_yaw)
        ks = self.key_state
        forward = ks[self._key['CAMERA_FORWARD']]
        backward = ks[self._key['CAMERA_BACKWARD']]
        if forward and not backward:
            self.camera = Point3D(self.camera.x + sin_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z + cos_yaw * move_speed)
        elif backward and not forward:
            self.camera = Point3D(self.camera.x - sin_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z - cos_yaw * move_speed)
        left = ks[self._key['CAMERA_LEFT']]
        right = ks[self._key['CAMERA_RIGHT']]
        if left and not right:
            self.camera = Point3D(self.camera.x - cos_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z + sin_yaw * move_speed)
        elif right and not left:
            self.camera = Point3D(self.camera.x + cos_yaw * move_speed,
                                  self.camera.y,
                                  self.camera.z - sin_yaw * move_speed)
        up = ks[self._key['CAMERA_UP']]
        down = ks[self._key['CAMERA_DOWN']]
        if up and not down:
            self.camera = Point3D(self.camera.x, self.camera.y + move_speed, self.camera.z)
        elif down and not up:
            self.camera = Point3D(self.camera.x, self.camera.y - move_speed, self.camera.z)

    def rotate_camera(self, delta_time):
        """根据按键状态旋转相机视角"""
        rotation_speed = self.camera_rotation_speed * delta_time
        ks = self.key_state
        left = ks[self._key['LOOK_LEFT']]
        right = ks[self._key['LOOK_RIGHT']]
        if left and not right:
            self.camera_yaw -= rotation_speed
        elif right and not left:
            self.camera_yaw += rotation_speed
        up = ks[self._key['LOOK_UP']]
        down = ks[self._key['LOOK_DOWN']]
        if up and not down:
            self.camera_pitch += rotation_speed
        elif down and not up:
            self.camera_pitch -= rotation_speed
        self.camera_pitch = max(-math.pi / 2, min(math.pi / 2, self.camera_pitch))

    # ================ 摄像机实体管理 (多摄像机, Unity Camera 概念) ================
    # ================ 摄像机管理 (多摄像机, Unity Camera 概念) ================
    def add_camera(self, position=None, yaw=0.0, pitch=0.0, roll=0.0, fov=60.0,
                   fov_locked=True, name=None, guid=None,
                   pitch_lock=False, pitch_min=-85.0, pitch_max=85.0):
        """添加场景摄像机实体 (不可见实体, 不渲染网格/不参与拾取). 返回 CameraState.
        M41: 朝向度制 (yaw [0,360) / pitch、roll 环绕) + 俯仰角限制字段."""
        cam = CameraState(position=position, yaw=yaw, pitch=pitch, roll=roll,
                          fov=fov, fov_locked=fov_locked, name=name, guid=guid,
                          pitch_lock=pitch_lock, pitch_min=pitch_min,
                          pitch_max=pitch_max)
        self.cameras.append(cam)
        return cam

    def remove_camera(self, cam):
        """从场景移除摄像机 (先脱父, 同时清 active 指向). 相机物体化 2026-08-16."""
        if cam.parent is not None:
            if cam in cam.parent.camera_children:
                cam.parent.camera_children.remove(cam)
            cam.parent = None
            self._bump_struct()                # 组3: 父链变更失效 (ancestry+SoA)
        if cam in self.cameras:
            self.cameras.remove(cam)
        if self.active_camera == cam.guid:
            self.active_camera = None

    def find_camera(self, guid):
        """按 guid 找摄像机, 找不到返回 None."""
        for cam in self.cameras:
            if cam.guid == guid:
                return cam
        return None


    def active_camera_object(self):
        """返回当前玩家视角摄像机对象 (无则 None)."""
        return self.find_camera(self.active_camera) if self.active_camera else None

    def apply_camera(self, cam):
        """把某摄像机设为玩家视角: 世界位置=摄像机世界位置, 世界朝向=yaw/pitch/roll,
        视角广度=fov, 并关闭轨道相机 (自由相机语义). 返回是否成功.
        M41: CameraState 度制 -> 引擎内部弧度 (camera_yaw/pitch/roll).
        2026-08-16 相机物体化: 无父相机走原路径精确赋值 (零漂移, 后向兼容);
        挂父相机合成世界基再反解世界 yaw/pitch/roll (Unity 父子语义)."""
        if cam is None:
            return False
        self.camera = self.camera_world_position(cam)
        if cam.parent is None:
            self.camera_yaw = math.radians(cam.yaw)
            self.camera_pitch = math.radians(cam.pitch)
            self.camera_roll = math.radians(cam.roll)
        else:
            ex, ey, ez = self.camera_world_basis(cam)
            self.camera_yaw, self.camera_pitch, self.camera_roll = \
                view_basis_to_angles(ex, ey, ez)
        self._fov = math.radians(cam.fov)
        self.orbit_mode = False
        return True

    # ---- 相机物体化: 世界位姿由父链合成 (2026-08-16) ----
    def camera_world_position(self, cam):
        """摄像机世界位置 (父链合成, 与 world_position 同构): 局部 @ 父世界矩阵."""
        p = np.array([cam.position.x, cam.position.y, cam.position.z, 1.0])
        if cam.parent is not None:
            p = p @ self.model_world_matrix(cam.parent)
        return Point3D(float(p[0]), float(p[1]), float(p[2]))

    def camera_world_basis(self, cam):
        """摄像机世界正交基 (ex,ey,ez) 行向量 (R=[ex;ey;ez] = 世界→视图旋转).
        按 mat4_view_yaw_pitch 同 trig/负绕向由 cam.yaw/pitch/roll (度) 建局部基,
        再沿父链合成世界旋转 (world_rotation_matrix 纯旋转 -> 基保持单位正交)."""
        yaw, pitch, roll = math.radians(cam.yaw), math.radians(cam.pitch), math.radians(cam.roll)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        ex = (cy, 0.0, -sy)
        ey = (-sy * sp, cp, -cy * sp)
        ez = (sy * cp, sp, cy * cp)
        if roll:
            cr, sr = math.cos(roll), math.sin(roll)
            sn = -sr
            exn = (ex[0] * cr + ey[0] * sn, ex[1] * cr + ey[1] * sn,
                   ex[2] * cr + ey[2] * sn)
            eyn = (ey[0] * cr - ex[0] * sn, ey[1] * cr - ex[1] * sn,
                   ey[2] * cr - ex[2] * sn)
            ex, ey = exn, eyn
        if cam.parent is None:
            return ex, ey, ez
        R3 = np.asarray(self.world_rotation_matrix(cam.parent))[:3, :3]
        return (tuple(float(v) for v in np.array(ex) @ R3),
                tuple(float(v) for v in np.array(ey) @ R3),
                tuple(float(v) for v in np.array(ez) @ R3))

    def set_camera_parent(self, cam, new_parent, preserve_world=True):
        """把摄像机挂到 new_parent (GameObject) 下 (None=根). 只可挂 GameObject,
        CameraState 无缩放. preserve_world=True (默认, Unity 语义): 换父后局部
        位置/朝向按新父空间重算, 世界位置/朝向不变. 维护 cam.parent 与
        parent.camera_children. 相机物体化 2026-08-16.
        (命名 set_camera_parent 避开编辑器 controller 的 reparent_camera(cam,target),
        引擎内部/撤销命令都走本方法.)"""
        if cam.parent is new_parent:
            return
        if new_parent is not None:
            # 摄像机不是 GameObject 不能当父, 防环防御走链 (正常永不触发)
            cur = new_parent
            while cur is not None:
                if cur is cam:
                    return
                cur = cur.parent
        if preserve_world:
            wp = self.camera_world_position(cam)
            ex, ey, ez = self.camera_world_basis(cam)
            Mw = np.array([ex, ey, ez], dtype=np.float64)                 # 世界基 (行)
            Rp = (np.asarray(self.world_rotation_matrix(new_parent))[:3, :3]
                  if new_parent is not None else np.eye(3))
            Ml = Mw @ np.linalg.inv(Rp)                                   # 新父空间局部基
            yaw, pitch, roll = view_basis_to_angles(Ml[0], Ml[1], Ml[2])
            if new_parent is not None:
                loc = np.array([wp[0], wp[1], wp[2], 1.0]) @ \
                      np.linalg.inv(self.model_world_matrix(new_parent))
                cam.position = Point3D(float(loc[0] / loc[3]),
                                       float(loc[1] / loc[3]),
                                       float(loc[2] / loc[3]))
            else:
                cam.position = Point3D(*wp)                               # 脱父: 局部=世界
            cam.yaw = wrap_deg(math.degrees(yaw), 0.0, 360.0)
            cam.pitch = wrap_deg(math.degrees(pitch), -180.0, 180.0)
            cam.roll = wrap_deg(math.degrees(roll), -180.0, 180.0)
        # 换父 (camera_children 列表维护)
        if cam.parent is not None and cam in cam.parent.camera_children:
            cam.parent.camera_children.remove(cam)
        cam.parent = new_parent
        if new_parent is not None:
            new_parent.camera_children.append(cam)

    def player_pitch_limits(self):
        """玩家俯仰角限制 (弧度): 返回 (min_rad, max_rad); 若没有激活相机或未启用
        俯仰角限制则返回 None. 供玩家控制脚本 (first_person/third_person) 夹俯仰角.
        可调范围 = [pitch_min, pitch_max] 含两端 (M41)."""
        cam = self.active_camera_object()
        if cam is None or not cam.pitch_lock:
            return None
        return (math.radians(cam.pitch_min), math.radians(cam.pitch_max))

