# -*- coding: utf-8 -*-
"""
相机域撤销命令（原 Loom/undo.py 摄像机快照 (Unity Camera) 段 + 相机命令类；
目录重构 B4 批按域拆分，逐行未动）。

成员: camera_snapshot / apply_camera_snapshot / CameraStateCommand /
AddCameraCommand / DeleteCameraCommand / ReparentCameraCommand。
"""
from engine import Point3D

from editor.undo.registry import Command


# ---------------- 摄像机快照 (Unity Camera) ----------------

def camera_snapshot(cam):
    """摄像机可撤销字段 -> dict (与 apply_camera_snapshot 成对).
    M41: 加 roll/俯仰角限制字段. 2026-08-16 相机物体化: 加 parent (父 guid, 稳定)."""
    return {
        'position': (cam.position.x, cam.position.y, cam.position.z),
        'yaw': cam.yaw,
        'pitch': cam.pitch,
        'roll': cam.roll,
        'fov': cam.fov,
        'fov_locked': cam.fov_locked,
        'name': cam.name,
        'pitch_lock': cam.pitch_lock,
        'pitch_min': cam.pitch_min,
        'pitch_max': cam.pitch_max,
        'parent': cam.parent.guid if cam.parent is not None else None,
    }

def apply_camera_snapshot(cam, snap, engine=None):
    """把快照写回摄像机 (undo/redo 共用); .get 兼容旧快照无新字段.
    engine 传则按 parent guid 解析父 (找不到=父被删 -> 脱父), 维护 camera_children."""
    cam.position = Point3D(*snap['position'])
    cam.yaw = snap['yaw']
    cam.pitch = snap['pitch']
    cam.roll = snap.get('roll', 0.0)
    cam.fov = snap['fov']
    cam.fov_locked = snap['fov_locked']
    cam.name = snap['name']
    cam.pitch_lock = snap.get('pitch_lock', False)
    cam.pitch_min = snap.get('pitch_min', -85.0)
    cam.pitch_max = snap.get('pitch_max', 85.0)
    new_parent = None
    pid = snap.get('parent')
    if engine is not None and pid:
        new_parent = engine.find_model_by_guid(pid)
        if new_parent is None:
            # Q-B7-57-1 (2026-11-22): 相机挂相机后父可以是 CameraState ——
            # guid 按物体表查不到时兜底查相机表 (否则快照 undo 会把相机父链
            # 静默断掉, 撤销=破坏状态).
            new_parent = engine.find_camera(pid)
    if cam.parent is not None and cam in cam.parent.camera_children:
        cam.parent.camera_children.remove(cam)
    cam.parent = new_parent
    if new_parent is not None:
        new_parent.camera_children.append(cam)

# ---------------- 摄像机命令 (Unity Camera 概念) ----------------

class CameraStateCommand(Command):
    """摄像机属性改值: before/after 是 camera_snapshot (检查器/gizmo 拖摄像机)."""

    def __init__(self, label, engine, cam, before, after):
        self.label = label
        self.engine = engine
        self.cam = cam
        self.before = before
        self.after = after

    def do(self):
        apply_camera_snapshot(self.cam, self.after, self.engine)

    def undo(self):
        apply_camera_snapshot(self.cam, self.before, self.engine)

class AddCameraCommand(Command):
    """添加摄像机. do() 首次创建, 撤销移除, 重做重新入列表 (摄像机无 GPU 资源).
    M41: 参数顺序与 engine.add_camera 一致 (含 roll/俯仰角限制)."""

    def __init__(self, label, engine, position=None, yaw=0.0, pitch=0.0,
                 roll=0.0, fov=60.0, fov_locked=True, name=None,
                 pitch_lock=False, pitch_min=-85.0, pitch_max=85.0):
        self.label = label
        self.engine = engine
        # 2026-08-22: args 与 engine.add_camera 签名逐槽对齐 —— add_camera 在
        # name 后加了 guid=None 槽, 旧 args 无占位 → 位置错位: pitch_min=-85.0
        # 落进 pitch_lock 槽 → 新相机 bool(-85.0)=True 自带"俯仰限制已启用"
        # (diag 实锤, 用户加相机即"已启用"的根因)
        self.args = (position, yaw, pitch, roll, fov, fov_locked, name, None,
                     pitch_lock, pitch_min, pitch_max)
        self.cam = None

    def do(self):
        if self.cam is None:
            self.cam = self.engine.add_camera(*self.args)
        else:
            self.engine.cameras.append(self.cam)
        return self.cam

    def undo(self):
        self.engine.remove_camera(self.cam)

class DeleteCameraCommand(Command):
    """删除摄像机. 撤销插回原位 (active_camera 若指向它已被 remove_camera 清空, 属预期).
    2026-08-16 相机物体化: 记录父 guid, 撤销按 guid 重连父."""

    def __init__(self, label, engine, cam):
        self.label = label
        self.engine = engine
        self.cam = cam
        self.index = engine.cameras.index(cam)
        self.parent_guid = cam.parent.guid if cam.parent is not None else None

    def do(self):
        self.engine.remove_camera(self.cam)

    def undo(self):
        if self.cam not in self.engine.cameras:
            self.engine.cameras.insert(min(self.index, len(self.engine.cameras)), self.cam)
        if self.parent_guid:
            par = self.engine.find_model_by_guid(self.parent_guid)
            if par is None:
                # Q-B7-57-1 (2026-11-22): 父可以是相机 (camera→camera), 兜底查相机表.
                par = self.engine.find_camera(self.parent_guid)
            if par is not None and self.cam.parent is not par:
                self.cam.parent = par
                par.camera_children.append(self.cam)

class ReparentCameraCommand(Command):
    """把摄像机从 old_parent 挂到 new_parent (None=根). 摄像机只可挂 GameObject.
    相机物体化 2026-08-16."""

    def __init__(self, label, engine, cam, old_parent, new_parent):
        self.label = label
        self.engine = engine
        self.cam = cam
        self.old_parent = old_parent
        self.new_parent = new_parent

    def do(self):
        self.engine.set_camera_parent(self.cam, self.new_parent)

    def undo(self):
        self.engine.set_camera_parent(self.cam, self.old_parent)
