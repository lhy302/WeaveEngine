# -*- coding: utf-8 -*-
r"""cam_align_probe.py — 相机 VP 对齐探针 (GL vs Vulkan 驱动, 2026-11-06)

验收口径: 同一份场景字典, 一侧走 **GL 引擎真实相机代码路径**
(engine.GLEngine + sceneio.scene_from_dict + loom_camera.apply_camera /
apply_orbit_camera + matlib 组 VP, 即 runtime.PlayerApp 与 loom_render.render
用的那几行), 另一侧走 **Vk 中间层** (scene_driver.SceneDriver.load_from_data +
render_pose). 断言两侧 VP 逐元素 |差| <= 1e-6.

用法: py -3.12 tests\_tmp\cam_align_probe.py
"""
import copy
import math
import os
import sys

try:                                    # Windows 控制台 GBK: 统一 UTF-8, 别让 ✅ 变成崩溃
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

import engine as E                 # noqa: E402
import sceneio as S                # noqa: E402
import scene_driver as SD          # noqa: E402
from loom_camera import clamp_camera_distance   # noqa: E402
from matlib import mat4_view_yaw_pitch, mat4_perspective   # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None      # 无 GL: 只建组件 (同 test_camera_parent)

W, H = 480, 320
ASPECT = W / H
TOL = 1e-6
FAILS = []


# ---------------- GL 侧 (runtime.PlayerApp + loom_render.render 的相机段) ----------------
def gl_reference(data):
    e = E.GLEngine.__new__(E.GLEngine)
    e.cameras = []
    e.active_camera = None
    e.models = []
    e.lights = []
    e.materials = []
    e.camera = E.Point3D(0, 0, -5)
    e.camera_yaw = 0.0
    e.camera_pitch = 0.0
    e.camera_roll = 0.0
    e.orbit_mode = False
    e._fov = math.radians(60.0)
    e.near = 0.1
    e.far = 1000.0
    e.width = W
    e.height = H
    e.gravity = -9.8
    e._skybox = None
    e.undo = None
    cam_out = {}
    S.scene_from_dict(e, copy.deepcopy(data), camera_out=cam_out)
    # —— 以下与 runtime.PlayerApp.__init__ (runtime.py:51-65) 逐行对应 ——
    if cam_out:
        e.camera_target = cam_out['target']
        e.camera_distance = clamp_camera_distance(cam_out['distance'])
        e.camera_yaw = cam_out['yaw']
        e.camera_pitch = cam_out['pitch']
    cam = e.active_camera_object()
    if cam is not None:
        e.apply_camera(cam)
    else:
        e.orbit_mode = True
        e.apply_orbit_camera()
    return e


def gl_vp(e):
    """与 loom_render.render:684-771 同序: 挂父激活相机重应用 -> 轨道合成 -> VP."""
    cam = e.active_camera_object()
    if cam is not None and cam.parent is not None:
        e.apply_camera(cam)
    if e.orbit_mode:
        e.apply_orbit_camera()
    V = mat4_view_yaw_pitch(np, (e.camera.x, e.camera.y, e.camera.z),
                            e.camera_yaw, e.camera_pitch, e.camera_roll)
    P = mat4_perspective(np, e._fov, e.width / e.height, e.near, e.far)
    return V @ P, (e.camera.x, e.camera.y, e.camera.z)


def vk_reference(data):
    d = SD.SceneDriver()
    d._bridge_disabled = True          # 探针不做物理 (只比相机)
    d.load_from_data(copy.deepcopy(data))
    return d


# ---------------- 场景构造 ----------------
def base_scene(camera=None, cameras=None, active=None, objects=None):
    return {
        "version": S.SCENE_VERSION,
        "camera": camera or {"target": [0, 0, 0], "distance": 10.0,
                             "yaw": 0.6, "pitch": -0.35},
        "cameras": cameras or [],
        "active_camera": active,
        "materials": [], "lights": [], "objects": objects or [],
    }


def cam_dict(cid="c1", pos=(2.0, 3.0, -4.0), yaw=35.0, pitch=-12.0, roll=0.0,
             fov=60.0, parent=None, pitch_lock=False, pmin=-85.0, pmax=85.0):
    return {"id": cid, "name": "相机" + cid, "position": list(pos),
            "yaw": yaw, "pitch": pitch, "roll": roll, "fov": fov,
            "fov_locked": True, "pitch_lock": pitch_lock,
            "pitch_min": pmin, "pitch_max": pmax, "parent_id": parent,
            "skybox": None}


CASES = []


def add(name, data, note=""):
    CASES.append((name, data, note))


# A) 无 active_camera -> 轨道相机 (行为必须不变)
for dist, yaw, pitch in ((10.0, 0.6, -0.35), (3.5, -1.2, 0.25),
                         (250.0, 2.8, -0.9), (0.5, 0.0, 0.0)):
    add("A | 无active dist=%.1f yaw=%.2f pitch=%.2f" % (dist, yaw, pitch),
        base_scene(camera={"target": [0, 1, 0], "distance": dist,
                           "yaw": yaw, "pitch": pitch}))

# B) 有 active_camera (根相机, 无父)
for yaw, pitch, fov in ((0.0, 0.0, 60.0), (35.0, -12.0, 48.0),
                        (300.0, 40.0, 90.0), (-120.0, -60.0, 25.0)):
    add("B | active root yaw=%.0f pitch=%.0f fov=%.0f" % (yaw, pitch, fov),
        base_scene(cameras=[cam_dict(yaw=yaw, pitch=pitch, fov=fov)], active="c1"))

# C) 有 active_camera + roll (GL: camera_roll 进 view 矩阵)
for roll in (15.0, 90.0, -33.0):
    add("C | active roll=%.0f" % roll,
        base_scene(cameras=[cam_dict(yaw=25.0, pitch=-8.0, roll=roll, fov=55.0)],
                   active="c1"))

# D) active_camera 挂父 (父带旋转/缩放) —— 走 camera_world_basis + view_basis_to_angles
_parent_scene = base_scene(
    cameras=[cam_dict(pos=(1.0, 1.6, 0.0), yaw=0.0, pitch=0.0, fov=70.0, parent="o1")],
    active="c1",
    objects=[{"id": "o1", "name": "玩家", "type": "cube", "params": {"size": 1.0},
              "position": [5.0, 0.0, -2.0], "rotation": [0.0, 0.7853981633974483, 0.0],
              "scale": [1.0, 1.0, 1.0], "visible": True}])
add("D | active 挂父 (父 yaw=45°, 相机眼高1.6)", _parent_scene)
_parent_scene2 = base_scene(
    cameras=[cam_dict(pos=(0.6, 1.2, 1.8), yaw=20.0, pitch=10.0, roll=5.0,
                      fov=65.0, parent="o2")],
    active="c2",
    objects=[{"id": "o2", "name": "躯干", "type": "cube", "params": {"size": 1.0},
              "position": [-3.0, 2.0, 4.0], "rotation": [0.2, -0.7, 0.35],
              "scale": [1.5, 1.5, 1.5], "visible": True}])
add("D | active 挂父 (父 3 轴旋转 + 缩放 1.5)", _parent_scene2)

# E) 多相机: active 指向第二个 (无父)
add("E | 两相机 active=c2",
    base_scene(cameras=[cam_dict("c1", pos=(0, 5, 0), yaw=180.0),
                        cam_dict("c2", pos=(-6.0, 1.0, 3.0), yaw=95.0, pitch=-20.0,
                                 fov=40.0)], active="c2"))

# F) active_camera 指向不存在 -> 回落轨道 (容错)
add("F | active 指向不存在 -> 轨道",
    base_scene(cameras=[cam_dict()], active="不存在的guid"))


def main():
    print("%-46s %-14s %-14s %-12s %s"
          % ("场景", "GL campos", "VK campos", "|ΔVP|max", "结论"))
    print("-" * 108)
    for name, data, _note in CASES:
        e = gl_reference(data)
        vp_g, pos_g = gl_vp(e)
        d = vk_reference(data)
        vp_v, pos_v = d.render_pose(aspect=ASPECT)
        diff = float(np.max(np.abs(np.asarray(vp_g) - np.asarray(vp_v))))
        pos_diff = max(abs(a - b) for a, b in zip(pos_g, pos_v))
        ok = diff <= TOL and pos_diff <= TOL
        if not ok:
            FAILS.append(name)
        print("%-46s (%6.2f,%6.2f,%6.2f) (%6.2f,%6.2f,%6.2f) %-12.3e %s"
              % (name, pos_g[0], pos_g[1], pos_g[2],
                 pos_v[0], pos_v[1], pos_v[2], diff, "PASS" if ok else "FAIL"))

    # ---- G) 挂父相机: 父移动/旋转后两侧都每帧重应用 -> VP 仍一致 ----
    print()
    for tag, move, drot in (("G | 父位移 +x10", (10.0, 0.0, 0.0), 0.0),
                            ("G | 父位移 +y3 且自转 90°", (0.0, 3.0, 0.0),
                             math.pi / 2)):
        data = copy.deepcopy(_parent_scene)
        e = gl_reference(data)
        obj = e.models[0]
        obj.position = E.Point3D(obj.position.x + move[0], obj.position.y + move[1],
                                 obj.position.z + move[2])
        obj.rotation = E.Point3D(obj.rotation.x, obj.rotation.y + drot,
                                 obj.rotation.z)
        vp_g, pos_g = gl_vp(e)
        d = vk_reference(copy.deepcopy(_parent_scene))
        dv_obj = d.models[0]
        dv_obj.position = E.Point3D(dv_obj.position.x + move[0],
                                    dv_obj.position.y + move[1],
                                    dv_obj.position.z + move[2])
        dv_obj.rotation = E.Point3D(dv_obj.rotation.x, dv_obj.rotation.y + drot,
                                    dv_obj.rotation.z)
        d.advance_logic(1.0 / 60.0)          # 帧首 _refresh_player_camera
        vp_v, pos_v = d.render_pose(aspect=ASPECT)
        diff = float(np.max(np.abs(np.asarray(vp_g) - np.asarray(vp_v))))
        pos_diff = max(abs(a - b) for a, b in zip(pos_g, pos_v))
        ok = diff <= TOL and pos_diff <= TOL
        if not ok:
            FAILS.append(tag)
        print("%-46s (%6.2f,%6.2f,%6.2f) (%6.2f,%6.2f,%6.2f) %-12.3e %s"
              % (tag, pos_g[0], pos_g[1], pos_g[2],
                 pos_v[0], pos_v[1], pos_v[2], diff, "PASS" if ok else "FAIL"))

    print()
    print("总结果:", "ALL PASS ✅" if not FAILS else "有 FAIL ❌ %s" % FAILS)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
