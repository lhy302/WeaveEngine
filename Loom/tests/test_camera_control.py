# -*- coding: utf-8 -*-
"""编辑器相机控制方向回归 (无头):
  滚轮缩放方向 = 往下滑拉近/视角下压, 往上滑拉远 (2026-08-12 用户反馈方向反了, 已翻正).
  防止符号被无意翻回去. 用 EditorApp.__new__ 桩, 不建真实窗口."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame
from editor import EditorApp

class _View:
    """极简 IEditorView 桩: 无输入框焦点 -> 相机键盘平移不被 UI 抢占."""
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}

def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed._mods = 0
    ed.buttons = (0, 0, 0)               # 无鼠标键按下 (只测滚轮)
    ed.mouse_pos = (100, 100)
    ed._cam_prev_mouse = (100, 100)
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.mouse_wheel = 0
    ed.camera_distance = 10.0
    ed.camera_target = (0, 0, 0)
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.preview_camera = None       # M41: 无预览状态
    ed._preview_orbit = None
    ed.view = _View()
    ed._fov = math.radians(45.0)
    ed._in_viewport = lambda pos: True   # 覆盖: 视为始终在视口内
    return ed

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

class _NoKeys:
    """任意键码都返回 0 (未按下): 键盘平移 block 不干扰滚轮测试.
    (pygame.K_LEFT 等是 10 亿级键码, 用固定长度元组会 IndexError.)"""
    def __getitem__(self, i):
        return 0

_orig_kp = pygame.key.get_pressed
pygame.key.get_pressed = _NoKeys

ed = _make_editor()
d0 = ed.camera_distance
ed.mouse_wheel = +1                          # 往上推
ed._update_camera()
check("滚轮往上推 -> 放大/拉近 (distance 减小)", ed.camera_distance < d0,
      "%.4f -> %.4f" % (d0, ed.camera_distance))

d1 = ed.camera_distance
ed.mouse_wheel = -1                          # 往下滑
ed._update_camera()
check("滚轮往下滑 -> 拉远 (distance 增大)", ed.camera_distance > d1,
      "%.4f -> %.4f" % (d1, ed.camera_distance))

# 下限 clamp (拉近到 0.5)
ed.camera_distance = 0.4
ed.mouse_wheel = +1
ed._update_camera()
check("拉近下限 clamp 0.5", abs(ed.camera_distance - 0.5) < 1e-9, str(ed.camera_distance))

# 上限 clamp (拉远到 200)
ed.camera_distance = 500.0
ed.mouse_wheel = -1
ed._update_camera()
check("拉远上限 clamp 200", abs(ed.camera_distance - 200.0) < 1e-9, str(ed.camera_distance))

# 滚轮不在视口内不缩放
ed.camera_distance = 10.0
ed.mouse_wheel = +1
ed._in_viewport = lambda pos: False
ed._update_camera()
check("视口外滚轮不缩放", abs(ed.camera_distance - 10.0) < 1e-9, str(ed.camera_distance))

# ---- 右键转动视角 (2026-08-12 用户反馈上下反了, 已翻正) ----
# 左右 (yaw): 右键向右拖 -> yaw 增大 (用户确认方向正常, 锁住)
ed = _make_editor()
ed.buttons = (0, 0, 1)                     # 右键按住
ed._cam_prev_mouse = (100, 100)
ed.mouse_pos = (140, 100)                  # 向右移动 dx=+40
y0 = ed.camera_yaw
ed._update_camera()
check("右键向右拖 -> yaw 增大 (水平方向不变)", ed.camera_yaw > y0,
      "%.4f -> %.4f" % (y0, ed.camera_yaw))

# 上下 (pitch): 右键向下拖 -> pitch 减小 (相机上抬看顶); 向上拖 -> pitch 增大
ed._cam_prev_mouse = (100, 100)
ed.mouse_pos = (100, 130)                  # 向下移动 dy=+30
p0 = ed.camera_pitch
ed._update_camera()
check("右键向下拖 -> pitch 减小", ed.camera_pitch < p0,
      "%.4f -> %.4f" % (p0, ed.camera_pitch))

ed._cam_prev_mouse = (100, 130)
ed.mouse_pos = (100, 80)                   # 向上移动 dy=-50
p1 = ed.camera_pitch
ed._update_camera()
check("右键向上拖 -> pitch 增大", ed.camera_pitch > p1,
      "%.4f -> %.4f" % (p1, ed.camera_pitch))

# ---- 右键转视角激活制 (2026-08-12): 视口内按下, 拖出视口仍持续到松开 (Unity 风格) ----
ed = _make_editor()
ed._right_drag_view = False
ed._in_viewport_state = {'val': True}         # 可变: 按下时视口内, 之后拖出
ed._in_viewport = lambda pos: ed._in_viewport_state['val']
ed.buttons = (0, 0, 1)                        # 右键按住
ed.mouse_pos = (100, 100); ed._cam_prev_mouse = (100, 100)
ed._update_camera()                            # 按下帧 (视口内) -> 激活
check("右键视口内按下激活 _right_drag_view", ed._right_drag_view is True)
ed._in_viewport_state['val'] = False           # 拖出视口
ed.mouse_pos = (140, 100); ed._cam_prev_mouse = (100, 100)
y0 = ed.camera_yaw
ed._update_camera()
check("右键拖出视口仍转视角 (yaw 增大)", ed.camera_yaw > y0,
      "yaw=%.4f" % ed.camera_yaw)
ed.buttons = (0, 0, 0)                         # 松开右键
ed.mouse_pos = (100, 100); ed._cam_prev_mouse = (140, 100)
ed._update_camera()
check("松开右键 _right_drag_view 复位", ed._right_drag_view is False)
# 非视口按下右键不激活 (检查器拖条右键走输入模式)
ed._in_viewport_state['val'] = False
ed.buttons = (0, 0, 1)
ed.mouse_pos = (100, 100); ed._cam_prev_mouse = (100, 100)
ed._update_camera()
check("非视口按下右键不激活 (检查器走输入模式)", ed._right_drag_view is False)

# ---- 摄像机方向线顶端指向圆锥 (几何, 2026-08-12 新增) ----
# UI 模块化 (2026-08-13): _direction_cone 几何 (2026-08-28 迁到 ui.loom_gui)
from ui.loom_gui import LoomGUI as _EditorView
_cone = _EditorView.__new__(_EditorView)
apex = (0.0, 1.0, 0.0)
d = (0.0, 0.0, 1.0)                        # +z 方向
L = 1.2
cv, cc = _cone._direction_cone(*apex, *d, L, (0.75, 0.9, 1.0))
check("圆锥线框顶点数 = 48 (12 段*2 线*2 顶点)", len(cv) == 48, "n=%d" % len(cv))
check("每个侧面首顶点 = 尖端 (线端点)", all(cv[i] == apex for i in range(0, len(cv), 4)))
cone_len, cone_r = 0.25 * L, 0.18 * L
bc = (apex[0] - d[0] * cone_len, apex[1] - d[1] * cone_len, apex[2] - d[2] * cone_len)
p = cv[5]                                  # 第 2 段的基圆端点
off = (p[0] - bc[0], p[1] - bc[1], p[2] - bc[2])
d_dot = off[0] * d[0] + off[1] * d[1] + off[2] * d[2]
r2 = math.sqrt(off[0] ** 2 + off[1] ** 2 + off[2] ** 2)
check("基圆点在垂直于方向的平面内", abs(d_dot) < 1e-9, "d_dot=%.3g" % d_dot)
check("基圆点距轴线 = 底半径 0.18L", abs(r2 - cone_r) < 1e-9, "r=%.4f" % r2)

# ---- 光源/物体选中互斥 (2026-08-12 修复: 加光后点不回物体) ----
ed = _make_editor()
ed.selected_light_index = 2              # 模拟选中光源
ed._select_model(0)
check("_select_model 清掉光源选中, 选中物体", ed.selected_light_index == -1
      and ed.selected_index == 0)

pygame.key.get_pressed = _orig_kp
print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
