# -*- coding: utf-8 -*-
"""dev_cam_free_move_check.py — 开发者相机自由移动修复验证 (2026-09-05 用户报告)

报告: 播放态不按住右键时 WASD 无法移动开发者视角。
根因: 玩家相机接管 (orbit_mode=False) 后视角=self.camera 自由位姿, 旧 WASD 段
只改 camera_target (轨道几何), 自由相机下无效; 且挂父相机每帧 apply_camera 盖回.

修复断言 (EditorApp.__new__ 桩, 无头):
  ①播放态自由相机 (无右键) 按 W -> camera 本体沿 yaw 前方移动 (target 不变)
  ②同态按 Q -> camera.y 上升
  ③移动后 _dev_cam_moved=True (挂父相机盖回保护置位)
  ④滚轮 -> camera 沿视线推拉 (自由相机), distance 不变
  ⑤编辑态轨道相机 W -> 仍是 target 平移 (原行为不变)
  ⑥右键按住 (开发者轨道接管) W -> target 平移 (轨道几何一致, 原批5 行为)
  ⑦退播放→进播放: _dev_cam_moved/_dev_cam_active 复位由 toggle_play 承担
    (此处仅验证字段默认 False 语义)
"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import pygame
from editor import EditorApp


class _View:
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}


class _Keys(dict):
    """按键快照替身: dict 键码 -> 0/1 (K_w 等十亿级键码直接当 key)."""
    def __getitem__(self, i):
        return self.get(i, 0)


def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed._mods = 0
    ed.buttons = (0, 0, 0)
    ed.mouse_pos = (100, 100)
    ed._cam_prev_mouse = (100, 100)
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.mouse_wheel = 0
    ed.camera_distance = 10.0
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.camera = type('P', (), {'x': 0.0, 'y': 0.0, 'z': 0.0})()
    ed.preview_camera = None
    ed._preview_orbit = None
    ed.view = _View()
    ed._fov = math.radians(45.0)
    ed._in_viewport = lambda pos: True
    ed._cam_speed = 1.0
    ed.is_playing = False
    ed.orbit_mode = True
    ed._dev_cam_active = False
    ed._dev_cam_moved = False
    ed._keys = _Keys()
    ed._key_pressed = lambda: ed._keys
    return ed


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


# ① 播放态自由相机 W 前进 (无右键)
ed = _make_editor()
ed.is_playing = True
ed.orbit_mode = False          # 玩家相机接管 (apply_camera 语义)
c0 = (ed.camera.x, ed.camera.y, ed.camera.z)
ed._keys[pygame.K_w] = 1
ed._update_camera(1.0 / 120.0)     # 显式 dt (桩无 _cam_dt_last, 默认实测=0)
dx = ed.camera.x - c0[0]
dz = ed.camera.z - c0[2]
moved = math.hypot(dx, dz)
expect_dir = (math.sin(0.6), math.cos(0.6))    # yaw=0.6 前方
dot = (dx * expect_dir[0] + dz * expect_dir[1]) / moved if moved else 0
check("① 播放态自由相机按 W -> camera 本体前进 (无右键)", moved > 1e-4,
      "moved=%.4f" % moved)
check("①b 移动方向 = yaw 前方 (点积≈1)", dot > 0.999, "dot=%.4f" % dot)
check("①c target 未动 (自由相机不经轨道)", ed.camera_target == (0.0, 0.0, 0.0),
      str(ed.camera_target))

# ② Q 上升
ed._keys.clear()
ed._keys[pygame.K_q] = 1
y0 = ed.camera.y
ed._update_camera(1.0/120.0)
check("② 按按 Q -> camera.y 上升", ed.camera.y > y0,
      "%.4f -> %.4f" % (y0, ed.camera.y))

# ③ 盖回保护标记
check("③ WASD 移动后 _dev_cam_moved=True", ed._dev_cam_moved is True)

# ④ 滚轮沿视线推拉 (自由相机)
ed._keys.clear()
ed.mouse_wheel = +1
c1 = (ed.camera.x, ed.camera.y, ed.camera.z)
d1 = ed.camera_distance
ed._update_camera(1.0/120.0)
mv = math.hypot(ed.camera.x - c1[0], ed.camera.y - c1[1], ed.camera.z - c1[2])
check("④ 滚轮推 -> camera 沿视线移动 (distance 不变)",
      mv > 1e-4 and ed.camera_distance == d1,
      "mv=%.4f dist=%.2f" % (mv, ed.camera_distance))

# ⑤ 编辑态轨道相机 W -> target 平移 (原行为)
ed2 = _make_editor()           # is_playing=False, orbit_mode=True
ed2._keys[pygame.K_w] = 1
ed2._update_camera(1.0/120.0)
t = ed2.camera_target
check("⑤ 编辑态 W -> target 平移 (原行为不变)",
      math.hypot(t[0], t[2]) > 1e-4 and ed2._dev_cam_moved is False,
      "target=(%.3f, %.3f)" % (t[0], t[2]))

# ⑥ 右键按住 (开发者轨道接管) W -> target 平移
ed3 = _make_editor()
ed3.is_playing = True
ed3.orbit_mode = False
ed3.buttons = (0, 0, 1)        # 右键按住 (真实接管态; 松开会立即翻回自由相机)
ed3._dev_cam_active = True
ed3._keys[pygame.K_w] = 1
ed3._update_camera(1.0/120.0)
t3 = ed3.camera_target
check("⑥ 右键接管中 W -> target 平移 (轨道几何一致)",
      math.hypot(t3[0], t3[2]) > 1e-4,
      "target=(%.3f, %.3f)" % (t3[0], t3[2]))

# ⑦ 新桩默认标记 False (进播放复位语义由 toggle_play 直写, 字段初始无残留)
ed4 = _make_editor()
check("⑦ 默认 _dev_cam_active/_moved = False (进播放复位基线)",
      ed4._dev_cam_active is False and ed4._dev_cam_moved is False)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
