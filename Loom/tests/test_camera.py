# -*- coding: utf-8 -*-
"""test_camera.py — 摄像机实体 (Unity Camera 概念) 测试:
状态(度制+roll+俯仰角限制)/多摄像机/apply/序列化 v9 迁移/undo/方向/roll矩阵/俯仰限制."""
import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # Loom\

import numpy as np

from engine import GLEngine, CameraState, Point3D
import sceneio
from matlib import mat4_view_yaw_pitch
from undo import (AddCameraCommand, CameraStateCommand, DeleteCameraCommand,
                  camera_snapshot, apply_camera_snapshot)

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _engine():
    """GLEngine 桩: 绕过 __init__ (不开窗口), 只补摄像机/序列化相关字段."""
    e = GLEngine.__new__(GLEngine)
    e.cameras = []
    e.active_camera = None
    e.models = []
    e.lights = []
    e.materials = []
    e.camera = Point3D(0, 0, -5)
    e.camera_yaw = 0.0
    e.camera_pitch = 0.0
    e.camera_roll = 0.0
    e.orbit_mode = False
    e._fov = 0.7853981633974483   # 45°
    return e


def t_state():
    e = _engine()
    cam = e.add_camera(position=(1, 2, 3), yaw=30.0, pitch=-20.0, roll=15.0,
                       fov=60.0, fov_locked=False, name="主摄像机")
    check("add_camera 入列表", len(e.cameras) == 1)
    # M41: 朝向度制存储 + roll 倾斜
    check("摄像机字段 (位置/朝向/倾斜/FOV/锁定)",
          (cam.position.x, cam.position.y, cam.position.z) == (1, 2, 3)
          and cam.yaw == 30.0 and cam.pitch == -20.0 and cam.roll == 15.0
          and cam.fov == 60.0 and cam.fov_locked is False and cam.name == "主摄像机")
    cw = e.add_camera(yaw=370.0)
    check("yaw 环绕进 [0,360) (370→10)", cw.yaw == 10.0, cw.yaw)
    e.remove_camera(cw)
    cp = e.add_camera(pitch=190.0)
    check("pitch 环绕进 (-180,180] (190→-170)", cp.pitch == -170.0, cp.pitch)
    e.remove_camera(cp)
    cr = e.add_camera(roll=-200.0)
    check("roll 环绕进 (-180,180] (-200→160)", cr.roll == 160.0, cr.roll)
    e.remove_camera(cr)
    check("俯仰角限制默认字段 (关/±85)",
          cam.pitch_lock is False and cam.pitch_min == -85.0 and cam.pitch_max == 85.0)
    check("摄像机 guid 自动生成", bool(cam.guid))
    check("默认摄像机 FOV 锁定 (开发者决定玩家可否调)", CameraState().fov_locked is True)
    e.remove_camera(cam)
    check("remove_camera 清列表", len(e.cameras) == 0)


def t_active_apply():
    e = _engine()
    c1 = e.add_camera(position=(0, 0, 0), yaw=0.0, pitch=0.0, fov=45.0)
    e.active_camera = c1.guid
    check("active_camera_object 找到", e.active_camera_object() is c1)
    check("find_camera 按 guid", e.find_camera(c1.guid) is c1)
    check("apply_camera 成功", e.apply_camera(c1))
    check("apply_camera 相机位置 = 摄像机位置", (e.camera.x, e.camera.y, e.camera.z) == (0, 0, 0))
    check("apply_camera 关闭轨道 (自由相机语义)", e.orbit_mode is False)
    check("apply_camera 视角广度 45°→弧度", abs(e._fov - 0.7853981633974483) < 1e-6)
    # M41: 度→弧度换算 (含 roll)
    c2 = e.add_camera(position=(0, 0, 0), yaw=30.0, pitch=10.0, roll=90.0)
    e.apply_camera(c2)
    check("apply_camera yaw 度→弧度", abs(e.camera_yaw - math.radians(30.0)) < 1e-9,
          e.camera_yaw)
    check("apply_camera pitch 度→弧度", abs(e.camera_pitch - math.radians(10.0)) < 1e-9)
    check("apply_camera roll 度→弧度", abs(e.camera_roll - math.radians(90.0)) < 1e-9,
          e.camera_roll)
    e.remove_camera(c1)
    check("删 active 摄像机后 active_camera 清空", e.active_camera is None)
    check("无 active 摄像机 active_camera_object=None", e.active_camera_object() is None)
    check("apply_camera(None) 返回 False", e.apply_camera(None) is False)


def t_sceneio_roundtrip():
    e = _engine()
    e.add_camera(position=(5, 0, -2), yaw=40.0, pitch=-30.0, roll=10.0, fov=70.0,
                 fov_locked=False, name="镜头A",
                 pitch_lock=True, pitch_min=-45.0, pitch_max=60.0)
    e.add_camera(position=(0, 3, 4), name="镜头B")
    e.active_camera = e.cameras[0].guid
    data = sceneio.scene_to_dict(e)
    check("v9 输出 cameras 数组", len(data.get('cameras', [])) == 2)
    check("v9 输出 active_camera", data.get('active_camera') == e.cameras[0].guid)
    e2 = _engine()
    sceneio.scene_from_dict(e2, data)
    check("回读摄像机数", len(e2.cameras) == 2)
    check("回读 active_camera", e2.active_camera == e.cameras[0].guid)
    check("回读摄像机字段 (A 位置/朝向/倾斜/FOV/锁定)",
          (e2.cameras[0].position.x, e2.cameras[0].yaw, e2.cameras[0].roll,
           e2.cameras[0].fov, e2.cameras[0].fov_locked) == (5, 40.0, 10.0, 70.0, False))
    check("回读俯仰角限制字段",
          e2.cameras[0].pitch_lock is True and e2.cameras[0].pitch_min == -45.0
          and e2.cameras[0].pitch_max == 60.0)
    check("回读摄像机名 B", e2.cameras[1].name == "镜头B")


def t_migrate_v6():
    old = {"version": 6, "camera": {}, "materials": [], "lights": [], "objects": []}
    m = sceneio.migrate(dict(old))
    check("v6 迁移到 v7 (补 cameras 空 + active_camera 空)",
          m.get('cameras') == [] and m.get('active_camera') is None)
    check("migrate 后 version=当前", m['version'] == sceneio.SCENE_VERSION)
    # 无 version 的旧文件也能加载
    m2 = sceneio.migrate({"objects": []})
    check("无 version 旧文件迁移后 version=当前",
          m2['version'] == sceneio.SCENE_VERSION and m2.get('cameras') == [])


def t_migrate_v8():
    """v8→v9: 摄像机 yaw/pitch 弧度→度 + 补 roll/俯仰角限制; 顶层轨道 camera dict 不碰."""
    old = {"version": 8,
           "camera": {"target": [0, 0, 0], "distance": 10.0, "yaw": 0.6, "pitch": -0.35},
           "cameras": [{"id": "c1", "name": "A", "position": [0, 0, -5],
                        "yaw": 0.7, "pitch": -0.3, "fov": 70.0, "fov_locked": False}],
           "materials": [], "lights": [], "objects": []}
    m = sceneio.migrate(dict(old))
    cam = m["cameras"][0]
    check("v8→v9 摄像机 yaw 弧度→度", abs(cam["yaw"] - math.degrees(0.7)) < 1e-6,
          cam["yaw"])
    check("v8→v9 摄像机 pitch 弧度→度", abs(cam["pitch"] - math.degrees(-0.3)) < 1e-6)
    check("v9 补 roll=0", cam["roll"] == 0.0)
    check("v9 补俯仰角限制默认",
          cam.get("pitch_lock") is False and cam.get("pitch_min") == -85.0
          and cam.get("pitch_max") == 85.0)
    check("顶层轨道 camera dict yaw 仍弧度 (不迁移)", m["camera"]["yaw"] == 0.6)
    check("migrate 后 version=当前", m["version"] == sceneio.SCENE_VERSION)
    check("v10 补 parent_id=None", cam.get("parent_id") is None)


def t_direction():
    """M41: CameraState.direction 度制派生 (yaw/pitch/roll -> 前方向量)."""
    d0 = CameraState(yaw=0, pitch=0).direction
    check("direction yaw=0,pitch=0 -> +z", tuple(round(v, 6) for v in d0) == (0, 0, 1))
    d90 = CameraState(yaw=90, pitch=0).direction
    check("direction yaw=90 -> +x", tuple(round(v, 6) for v in d90) == (1, 0, 0))
    du = CameraState(yaw=0, pitch=90).direction
    check("direction pitch=90 -> +y",
          abs(du.x) < 1e-9 and abs(du.y - 1.0) < 1e-9 and abs(du.z) < 1e-9)


def t_roll_matrix():
    """M41: mat4_view_yaw_pitch roll 参数 —— roll=90° 时 right/up 列位移, 正交 det=1."""
    V0 = mat4_view_yaw_pitch(np, (0, 0, 0), 0.0, 0.0)
    check("roll=0 与老 3 参调用一致",
          np.allclose(V0, mat4_view_yaw_pitch(np, (0, 0, 0), 0.0, 0.0, 0.0)))
    V = mat4_view_yaw_pitch(np, (0, 0, 0), 0.0, 0.0, math.radians(90))
    check("roll=90° right 列 (0,-1,0)", np.allclose(V[:3, 0], (0, -1, 0)),
          str(np.round(V[:3, 0], 3)))
    check("roll=90° up 列 (1,0,0)", np.allclose(V[:3, 1], (1, 0, 0)),
          str(np.round(V[:3, 1], 3)))
    check("roll 矩阵正交 det=1", abs(np.linalg.det(V[:3, :3]) - 1.0) < 1e-9)
    Vn = mat4_view_yaw_pitch(np, (0, 0, 0), 0.0, 0.0, math.radians(-90))
    check("roll=-90° up 列 (-1,0,0) (对称)", np.allclose(Vn[:3, 1], (-1, 0, 0)))


def t_player_pitch_limits():
    """M41: player_pitch_limits —— 无激活/未启用 -> None; 启用 -> 弧度 [min,max]."""
    e = _engine()
    check("无激活相机 -> None", e.player_pitch_limits() is None)
    c = e.add_camera(position=(0, 0, 0), pitch_lock=False)
    e.active_camera = c.guid
    check("激活相机未启用限制 -> None", e.player_pitch_limits() is None)
    c.pitch_lock = True
    c.pitch_min = -45.0
    c.pitch_max = 60.0
    lim = e.player_pitch_limits()
    check("启用限制返回弧度 [min,max]",
          lim is not None and abs(lim[0] - math.radians(-45)) < 1e-9
          and abs(lim[1] - math.radians(60)) < 1e-9, str(lim))
    check("限制含两端 (min 可达)", lim[0] <= lim[0] and lim[1] >= lim[1])


def t_undo():
    e = _engine()
    cmd = AddCameraCommand("添加摄像机", e, position=(1, 1, 1), name="C1")
    cam = cmd.do()
    check("AddCameraCommand do 添加", len(e.cameras) == 1)
    cmd.undo()
    check("AddCameraCommand undo 移除", len(e.cameras) == 0)
    cmd.do()
    check("AddCameraCommand redo 重新添加", len(e.cameras) == 1)

    before = camera_snapshot(cam)
    cam.yaw = 30.0
    cam.fov = 90.0
    cam.roll = 20.0
    after = camera_snapshot(cam)
    scmd = CameraStateCommand("改摄像机", e, cam, before, after)
    scmd.do()
    check("CameraStateCommand do 应用 after",
          cam.yaw == 30.0 and cam.fov == 90.0 and cam.roll == 20.0)
    scmd.undo()
    check("CameraStateCommand undo 还原 before (含 roll)",
          cam.yaw == 0.0 and cam.fov == 60.0 and cam.roll == 0.0)

    dcmd = DeleteCameraCommand("删除摄像机", e, cam)
    dcmd.do()
    check("DeleteCameraCommand do 删除", len(e.cameras) == 0)
    dcmd.undo()
    check("DeleteCameraCommand undo 插回原位", len(e.cameras) == 1 and e.cameras[0] is cam)


if __name__ == "__main__":
    print("========== 摄像机 (Unity Camera) 测试 ==========")
    t_state()
    t_active_apply()
    t_sceneio_roundtrip()
    t_migrate_v6()
    t_migrate_v8()
    t_direction()
    t_roll_matrix()
    t_player_pitch_limits()
    t_undo()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
