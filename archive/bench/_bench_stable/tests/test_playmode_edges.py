# -*- coding: utf-8 -*-
"""《未测试功能测试方向指南》A8 播放模式在"增删/改参/重复"下的完整性.
用 EditorApp 无头桩测 toggle_play 快照/还原 (不开窗口)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import editor
import undo
from mesh import create_cube

E.GLEngine._build_gpu = lambda self, m: None

def new_app():
    app = editor.EditorApp.__new__(editor.EditorApp)
    app.models = []; app.materials = []; app.lights = []
    app.cameras = []; app.active_camera = None
    app.current_model_index = 0
    app.undo = undo.UndoManager()
    app.selected_index = 0
    app.selected_light_index = -1
    app.selected_camera_index = -1
    app.is_playing = False
    # 相机状态 (toggle_play 播放视角快照/恢复 apply_orbit_camera 用)
    app.camera = E.Point3D(0, 0, -5)
    app.camera_target = (0, 0, 0)
    app.camera_distance = 10.0
    app.camera_yaw = 0.0
    app.camera_pitch = 0.0
    app.camera_roll = 0.0          # M41: _play_edit_cam 快照含 roll
    app.orbit_mode = True
    app._fov = 0.785
    # M41: 用此相机预览状态 (toggle_play 进入分支会 exit_camera_preview)
    app.preview_camera = None
    app._preview_orbit = None
    app._cam_undo_start = {}
    return app

def add(app, mesh, pos):
    return app.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0))

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ---- A8-1 播放期脚本转动 + 手动改位置/颜色 -> 停止全部还原 ----
app = new_app()
m = add(app, create_cube(1.0), (0, 0, 0))
m.add_script('rotate', {'sy': 90})
m.renderer.material.color = (1.0, 0.0, 0.0)          # 编辑态颜色
app.toggle_play()                                     # 进入
check("A8 进入播放 is_playing", app.is_playing)
app.update_scripts(1.0)                               # 脚本转 90°
check("A8 播放期脚本转动生效", m.rotation.y > 0.1, f"y={m.rotation.y:.3f}")
m.position = E.Point3D(5, 0, 0)                       # 播放期手动改位置(模拟拖动)
m.renderer.material.color = (0.0, 0.0, 1.0)          # 播放期改颜色
app.toggle_play()                                     # 退出
check("A8 停止后旋转还原", abs(m.rotation.y) < 1e-6, f"y={m.rotation.y}")
check("A8 停止后位置还原", m.position == E.Point3D(0, 0, 0), str(m.position))
check("A8 停止后物体数不变", len(app.models) == 1)
check("A8 停止后脚本保留", m.scripts[0].script_id == 'rotate')
check("A8 停止后脚本实例缓存已清", m.scripts[0]._script is None)

# ---- A8-2 播放期新增物体 -> 停止被移除 (绕过 guard 也清理) ----
app.toggle_play()
extra = add(app, create_cube(1.0), (9, 0, 0))
check("A8 播放期新增物体存在", extra in app.models and len(app.models) == 2)
app.toggle_play()
check("A8 停止后播放期新增被移除", extra not in app.models and len(app.models) == 1)

# ---- A8-3 播放期改光源参数 -> 停止还原 ----
lt = app.add_light(kind='point', position=(0, 4, 0), intensity=1.0, color=(1, 1, 1))
app.toggle_play()
lt.intensity = 5.0
lt.position = E.Point3D(0, 8, 0)
app.toggle_play()
check("A8 停止后光源参数还原", lt.intensity == 1.0 and lt.position == E.Point3D(0, 4, 0),
      str((lt.intensity, lt.position)))

# ---- A8-4 多次播放 -> 场景一致不叠加 ----
for i in range(3):
    app.toggle_play()
    app.update_scripts(0.5)
    app.toggle_play()
check("A8 三次播放后场景一致",
      len(app.models) == 1 and len(app.lights) == 1
      and abs(m.rotation.y) < 1e-6 and m.position == E.Point3D(0, 0, 0))

# ---- A8-5 多脚本物体播放还原 + 每个脚本实例缓存都清 ----
app.toggle_play()
app.update_scripts(0.5)                               # rotate 转 + bob 浮动
app.toggle_play()
stale = [sc._script for sc in m.scripts]
check("A8 多脚本播放后全部还原且实例缓存清空",
      abs(m.rotation.y) < 1e-6 and abs(m.position.y) < 1e-6
      and all(s is None for s in stale), str((m.rotation, m.position, stale)))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
