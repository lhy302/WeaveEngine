# -*- coding: utf-8 -*-
"""M41 摄像机"用此相机预览" + 激活相机测试 (无头 EditorApp.__new__ 桩):
  预览进入/退出/切第二相机不覆盖轨道/预览期轨道操作早退/激活相机/播放应用激活相机."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import undo as U
from engine import CameraState, Point3D
from editor import EditorApp

def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed.models = []; ed.materials = []; ed.lights = []
    ed.cameras = []; ed.active_camera = None
    ed.current_model_index = 0
    ed.undo = U.UndoManager()
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.is_playing = False
    # 相机状态
    ed.camera = Point3D(0, 0, -5)
    ed.camera_target = (0, 0, 0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.orbit_mode = True
    ed._fov = 0.785
    # M41 预览状态
    ed.preview_camera = None
    ed._preview_orbit = None
    ed._cam_undo_start = {}
    return ed

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

ed = _make_editor()
cam1 = CameraState(position=(0, 0, 0), yaw=30.0, pitch=0.0, roll=10.0, name="A")
cam2 = CameraState(position=(0, 5, 0), name="B")
ed.cameras = [cam1, cam2]

# 1) 进入预览
ed.toggle_camera_preview(cam1)
check("进入预览 preview_camera is cam1", ed.preview_camera is cam1)
check("进入预览选中该摄像机", ed.selected_camera_index == 0)
check("首次进入捕获轨道", ed._preview_orbit is not None
      and ed._preview_orbit[2] == 0.6 and ed._preview_orbit[3] == -0.35)
# 模拟 editor.render 预览分支每帧应用
ed.apply_camera(cam1)
check("预览应用后 orbit_mode=False", ed.orbit_mode is False)
check("预览应用 roll 度→弧度", abs(ed.camera_roll - math.radians(10.0)) < 1e-9)

# 2) 预览期 _update_camera 早退 (轨道操作禁用)
ed._mods = 0
ed.buttons = (0, 0, 0)
y0 = ed.camera_yaw
ed._update_camera()
check("预览期 _update_camera 早退 (yaw 不动)", ed.camera_yaw == y0)

# 3) 切到第二相机不覆盖已捕获轨道
ed.toggle_camera_preview(cam2)
check("切第二相机 preview_camera is cam2", ed.preview_camera is cam2)
check("已捕获轨道不被覆盖 (yaw 仍 0.6)", ed._preview_orbit[2] == 0.6)

# 4) 退出预览还原轨道 (M41 修复: 预览过带 roll 的相机, 退出必须清掉倾斜)
ed.exit_camera_preview()
check("退出预览 preview_camera None", ed.preview_camera is None)
check("退出预览还原 orbit_mode=True", ed.orbit_mode is True)
check("退出预览还原 yaw", abs(ed.camera_yaw - 0.6) < 1e-9)
check("退出预览还原 pitch", abs(ed.camera_pitch + 0.35) < 1e-9)
check("退出预览后 camera_roll 归零 (预览倾斜不残留)", ed.camera_roll == 0.0,
      ed.camera_roll)

# 5) 激活相机 (2026-08-17: 激活可取消 = set_active_camera(None))
ed.active_camera = None
ed.set_active_camera(cam1)
check("set_active_camera 设 guid", ed.active_camera == cam1.guid)
ed.set_active_camera(None)
check("set_active_camera(None) 取消激活", ed.active_camera is None)
ed.set_active_camera(cam1)
check("再设为激活", ed.active_camera == cam1.guid)

# 6) 播放应用激活相机 (toggle_play 进入分支 apply_camera)
ed.active_camera = cam1.guid
ed.models = []; ed.lights = []
ed.undo = U.UndoManager()
ed.is_playing = False
ed.toggle_play()
check("播放进入应用激活相机 orbit_mode=False", ed.orbit_mode is False)
check("播放进入相机位置=激活相机", (ed.camera.x, ed.camera.y, ed.camera.z) == (0, 0, 0))
ed.toggle_play()   # 退出
check("播放退出还原轨道 orbit_mode=True", ed.orbit_mode is True)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
