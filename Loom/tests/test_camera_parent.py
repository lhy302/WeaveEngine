# -*- coding: utf-8 -*-
"""2026-08-16 相机物体化: 可挂父相机实体测试.
CameraState 可挂到普通 GameObject (玩家), 世界 = 局部 × 父链合成;
保留 yaw/pitch/roll 度制机制; 撤销/序列化/播放都支持挂父."""
import sys, os, math, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import engine as E
import undo as U
import sceneio as S
from matlib import mat4_view_yaw_pitch, view_basis_to_angles
from mesh import create_cube

E.GLEngine._build_gpu = lambda self, m: None

def _engine():
    e = E.GLEngine.__new__(E.GLEngine)
    e.cameras = []; e.active_camera = None
    e.models = []; e.lights = []; e.materials = []
    e.camera = E.Point3D(0, 0, -5)
    e.camera_yaw = 0.0; e.camera_pitch = 0.0; e.camera_roll = 0.0
    e.orbit_mode = False; e._fov = 0.785
    e.undo = U.UndoManager()
    e.current_model_index = 0
    return e

def mk(name, pos, rot=(0, 0, 0)):
    m = E.GameObject(create_cube(1.5), E.Point3D(*pos), E.Point3D(*rot), name=name)
    m.guid = uuid.uuid4().hex
    return m

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

def v3(t):
    return tuple(round(float(v), 6) for v in t)

# ---- 1) CameraState 默认 ----
e0 = _engine()
cam0 = E.CameraState(position=(0, 0, -5), name="默认")
check("1 CameraState 默认 parent=None", cam0.parent is None)
check("1 CameraState 默认 children=[]", cam0.children == [])

# ---- 2) camera_world_position: 根=position, 挂父=父世界 @ 局部 ----
e = _engine()
obj = mk("父", (10, 0, 0))
e.models = [obj]
cam = E.CameraState(position=(2, 0, 0), name="相机")
e.cameras = [cam]
check("2 根相机世界位置=position", v3(e.camera_world_position(cam)) == (2, 0, 0))
e.set_camera_parent(cam, obj)      # 保世界挂父: 局部被换算, 世界不变
check("2 挂父后世界位置不变 (2,0,0)", v3(e.camera_world_position(cam)) == (2, 0, 0),
      str(v3(e.camera_world_position(cam))))
check("2 挂父后局部换算到父空间 (-8,0,0)",
      v3((cam.position.x, cam.position.y, cam.position.z)) == (-8, 0, 0),
      str(v3((cam.position.x, cam.position.y, cam.position.z))))
check("2 parent.camera_children 维护", obj.camera_children == [cam])

# ---- 3) camera_world_basis: 根=局部基, 挂父=局部 @ 父旋转 ----
e2 = _engine()
obj2 = mk("父2", (0, 0, 0), (0, math.pi / 2, 0))   # 父绕 Y 90°
e2.models = [obj2]
cam2 = E.CameraState(position=(2, 0, 0), yaw=0.0, pitch=0.0, roll=0.0, name="相机2")
e2.cameras = [cam2]
# 指针挂父 (不换算局部), 局部朝向仍 yaw=0 -> 局部前 +z
e2.set_camera_parent(cam2, obj2, preserve_world=False)
ex, ey, ez = e2.camera_world_basis(cam2)
check("3 父转90° 相机世界前 = +x (局部+z @ Ry90)", v3(ez) == (1, 0, 0), str(v3(ez)))
check("3 世界右 (0,0,-1) 世界上 (0,1,0)", v3(ex) == (0, 0, -1) and v3(ey) == (0, 1, 0),
      str((v3(ex), v3(ey))))

# ---- 4) view_basis_to_angles round-trip (mat4_view_yaw_pitch 基是"列") ----
for y, p, r in ((0.7, -0.3, 0.5), (2.5, 0.4, -1.2), (-1.0, 0.8, 0.2), (3.0, -0.6, 2.0)):
    V0 = mat4_view_yaw_pitch(np, (0, 0, 0), y, p, r)
    y2, p2, r2 = view_basis_to_angles(V0[:, 0], V0[:, 1], V0[:, 2])
    V1 = mat4_view_yaw_pitch(np, (0, 0, 0), y2, p2, r2)
    check("4 反解重建基 allclose (y=%.2f p=%.2f r=%.2f)" % (y, p, r),
          np.allclose(V0[:3, :3], V1[:3, :3], atol=1e-9),
          "err=%.2e" % float(np.max(np.abs(V0[:3, :3] - V1[:3, :3]))))

# ---- 5) apply_camera: 根精确 (后向兼容) + 挂父世界合成 ----
e3 = _engine()
cam3 = E.CameraState(position=(1, 2, 3), yaw=30.0, pitch=-20.0, roll=15.0, name="C3")
e3.cameras = [cam3]
e3.apply_camera(cam3)
check("5 根相机 apply 精确 yaw 度->弧度", abs(e3.camera_yaw - math.radians(30.0)) < 1e-9)
check("5 根相机 apply 精确 roll 度->弧度", abs(e3.camera_roll - math.radians(15.0)) < 1e-9)
check("5 根相机 apply 世界位置=position", v3((e3.camera.x, e3.camera.y, e3.camera.z)) == (1, 2, 3))

obj3 = mk("父3", (10, 0, 0), (0, math.pi / 2, 0))
e3.models = [obj3]
cam4 = E.CameraState(position=(2, 0, 0), yaw=0.0, pitch=0.0, roll=0.0, name="C4")
e3.cameras.append(cam4)
e3.set_camera_parent(cam4, obj3, preserve_world=False)
e3.apply_camera(cam4)
# 父在 (10,0,0) 转90°: 局部(2,0,0) 被旋转成 (0,0,-2) 再加父位置 -> (10,0,-2)
check("5 挂父相机 apply 世界位置 (10,0,-2)",
      v3((e3.camera.x, e3.camera.y, e3.camera.z)) == (10, 0, -2),
      str(v3((e3.camera.x, e3.camera.y, e3.camera.z))))
Vw = mat4_view_yaw_pitch(np, (e3.camera.x, e3.camera.y, e3.camera.z),
                         e3.camera_yaw, e3.camera_pitch, e3.camera_roll)
exw, eyw, ezw = e3.camera_world_basis(cam4)
check("5 挂父相机 apply 视图基(列)=世界基(行)",
      np.allclose(Vw[:3, :3], np.array([exw, eyw, ezw]).T, atol=1e-9))

# ---- 6) set_camera_parent: 脱父保世界 / children ----
cam5 = E.CameraState(position=(0, 0, 0), name="C5")
e3.cameras.append(cam5)
e3.set_camera_parent(cam5, obj3, preserve_world=False)   # 局部(0,0,0) 挂父 -> 世界=父位置(10,0,-2)?
# 父原点 (10,0,0) 旋转: 局部(0,0,0) -> 世界 (10,0,0) (父位置)
e3.set_camera_parent(cam5, None, preserve_world=True)
check("6 脱父后局部=世界 (父位置 (10,0,0))",
      v3((cam5.position.x, cam5.position.y, cam5.position.z)) == (10, 0, 0),
      str(v3((cam5.position.x, cam5.position.y, cam5.position.z))))
check("6 脱父后 camera_children 只剩 cam4", obj3.camera_children == [cam4])
e3.set_camera_parent(cam5, obj3, preserve_world=False)

# ---- 7) ReparentCameraCommand do/undo ----
e4 = _engine()
o7 = mk("父7", (5, 0, 0)); e4.models = [o7]
c7 = E.CameraState(position=(1, 0, 0), name="C7"); e4.cameras = [c7]
cmd = U.ReparentCameraCommand("摄像机挂父", e4, c7, None, o7)
e4.undo.push(cmd)
check("7 ReparentCameraCommand do 挂父", c7.parent is o7 and o7.camera_children == [c7])
e4.undo.undo()
check("7 ReparentCameraCommand undo 脱父", c7.parent is None and o7.camera_children == [])
e4.undo.redo()
check("7 ReparentCameraCommand redo 重挂", c7.parent is o7)

# ---- 8) 序列化 parent_id round-trip + 迁移 + 加载顺序 ----
e5 = _engine()
o8 = mk("父8", (5, 0, 0)); e5.models = [o8]
c8 = E.CameraState(position=(1, 0, 0), name="C8"); e5.cameras = [c8]
e5.set_camera_parent(c8, o8, preserve_world=False)
d = S.scene_to_dict(e5)
cammap = {cm["id"]: cm for cm in d["cameras"]}
check("8 序列化 parent_id=父 guid", cammap[c8.guid]["parent_id"] == o8.guid)
e6 = _engine()
S.scene_from_dict(e6, d)
check("8 回读后相机挂回父", e6.cameras[0].parent is e6.models[0])
check("8 回读父.camera_children", e6.models[0].camera_children == [e6.cameras[0]])
# v9 旧文件迁移
old = {"version": 9, "camera": {}, "cameras": [{"id": "c9", "name": "A",
        "position": [0, 0, -5], "yaw": 0.0, "pitch": 0.0, "roll": 0.0,
        "fov": 45.0, "fov_locked": True, "pitch_lock": False,
        "pitch_min": -85.0, "pitch_max": 85.0}],
        "materials": [], "lights": [], "objects": []}
m9 = S.migrate(dict(old))
check("8 v9→v10 补 parent_id=None", m9["cameras"][0].get("parent_id") is None)
check("8 migrate version=当前", m9["version"] == S.SCENE_VERSION)

# ---- 9) DeleteCameraCommand 删挂父相机清 children, undo 重连 ----
e7 = _engine()
o9 = mk("父9", (5, 0, 0)); e7.models = [o9]
c9 = E.CameraState(position=(1, 0, 0), name="C9"); e7.cameras = [c9]
e7.set_camera_parent(c9, o9, preserve_world=False)
dcmd = U.DeleteCameraCommand("删除摄像机", e7, c9)
dcmd.do()
check("9 删挂父相机清 camera_children", o9.camera_children == [])
dcmd.undo()
check("9 DeleteCameraCommand undo 重连父", c9.parent is o9 and o9.camera_children == [c9])

# ---- 10) apply_camera_snapshot 按 guid 恢复父 / 未知 guid->None ----
e8 = _engine()
o10 = mk("父10", (5, 0, 0)); e8.models = [o10]
c10 = E.CameraState(position=(1, 0, 0), name="C10"); e8.cameras = [c10]
snap = U.camera_snapshot(c10)
snap["parent"] = o10.guid
U.apply_camera_snapshot(c10, snap, e8)
check("10 apply_camera_snapshot 按 guid 恢复父", c10.parent is o10)
snap2 = U.camera_snapshot(c10)
snap2["parent"] = "不存在"
U.apply_camera_snapshot(c10, snap2, e8)
check("10 未知 parent guid -> 脱父 None", c10.parent is None)

# ---- 11) 挂父相机 gizmo 世界增量 -> 父空间局部 ----
from editor import EditorApp
class _V:
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}
ed = EditorApp.__new__(EditorApp)
ed.camera_yaw = 0.0; ed.camera_pitch = 0.0; ed.camera_roll = 0.0
ed._vp = np.eye(4, dtype=np.float64); ed.width = 800; ed.height = 600
ed.view = _V(); ed.buttons = (0, 0, 0); ed._mods = 0
o11 = mk("父11", (10, 0, 0), (0, math.pi / 2, 0))
ed.models = [o11]
c11 = E.CameraState(position=(2, 0, 0), name="C11"); ed.cameras = [c11]
ed.set_camera_parent(c11, o11, preserve_world=False)
ld = ed._local_delta(c11, np.array((1.0, 0.0, 0.0)))   # 世界 +x, 父转90° -> 局部
check("11 _local_delta 挂父相机世界增量->父空间局部", abs(float(ld[0])) < 1e-9
      and abs(float(ld[2]) - 1.0) < 1e-9, str(ld))

# ---- 12) 播放: 挂父激活相机 toggle_play 进出还原 + 父移动跟随 ----
def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed.models = []; ed.materials = []; ed.lights = []
    ed.cameras = []; ed.active_camera = None
    ed.current_model_index = 0
    ed.undo = U.UndoManager()
    ed.selected_index = 0; ed.selected_light_index = -1; ed.selected_camera_index = -1
    ed.is_playing = False
    ed.camera = E.Point3D(0, 0, -5)
    ed.camera_target = (0, 0, 0); ed.camera_distance = 10.0
    ed.camera_yaw = 0.6; ed.camera_pitch = -0.35; ed.camera_roll = 0.0
    ed.orbit_mode = True; ed._fov = 0.785
    ed.preview_camera = None; ed._preview_orbit = None
    ed._cam_undo_start = {}
    return ed

ed2 = _make_editor()
opl = mk("玩家", (0, 0, 0)); ed2.models = [opl]
cp = E.CameraState(position=(0, 1.6, 0), yaw=0.0, pitch=0.0, roll=0.0, name="第一人称")
ed2.cameras = [cp]
ed2.set_camera_parent(cp, opl, preserve_world=False)
ed2.active_camera = cp.guid
ed2.toggle_play()
check("12 播放进入挂父激活相机 orbit_mode=False", ed2.orbit_mode is False)
check("12 播放进入相机世界位置=玩家+眼高", v3((ed2.camera.x, ed2.camera.y, ed2.camera.z)) == (0, 1.6, 0))
opl.position = E.Point3D(10, 0, 0)      # 玩家移动
ed2.apply_camera(ed2.active_camera_object())
check("12 父移动后相机世界位置跟随 (10,1.6,0)", v3((ed2.camera.x, ed2.camera.y, ed2.camera.z)) == (10, 1.6, 0),
      str(v3((ed2.camera.x, ed2.camera.y, ed2.camera.z))))
ed2.toggle_play()
check("12 播放退出还原轨道 orbit_mode=True", ed2.orbit_mode is True)
check("12 播放退出相机父链还原", cp.parent is opl and opl.camera_children == [cp])

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
