# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


"""test_qt_gizmo_click_order.py — Qt _on_tick → paintGL 点击顺序 (P-22/F3, 2026-11-07).

背景: F3 把 ui/loom_gui.py _on_tick 的 pressed/released 清空移到了
_update_camera() 之后 (UI 分发需要输入)。但 Qt 的 paintGL 在 _on_tick **之后**
执行, editor.render → _update_gizmo 读 self.pressed 时已被清空 → Qt 编辑器里
3D 点选/gizmo 拿不到本帧点击。

修复 (方案 A, 代际标记): _update_camera() 在清空前把"本拍左键按下"记成
_gizmo_click_gen + _gizmo_click_pos, _update_gizmo 消费一次 (无论命中与否);
UI 已消费 (_ui_lock) 则不记 → UI 命中不进 gizmo。

本测试用真实 EditorApp 桩 + 真实 _update_camera/_update_gizmo, 严格模拟
_on_tick → clear → paintGL 顺序。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import undo as U                                          # noqa: E402
from editor import EditorApp                              # noqa: E402
from engine import Point3D                                # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


class _NoKeys:
    def __getitem__(self, key):
        return False


class _View:
    def __init__(self, click_captured=False):
        self._click_captured = click_captured

    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0,
                'click_captured': self._click_captured, 'focus_id': None}

    def reset_interaction(self):
        pass


class _ConsumingUI:
    """UI 命中并消费点击 (模拟 HUD 按钮)。"""
    def dispatch_mouse(self, pos, pressed, released):
        return True

    def update_hover_only(self, pos):
        pass


def _editor(ui=None, click_captured=False):
    ed = EditorApp.__new__(EditorApp)
    ed.width = 800
    ed.height = 600
    ed.panel_left_w = 220
    ed.panel_right_w = 280
    ed.panel_hier_frac = 0.55
    ed.panel_left_collapsed = False
    ed.panel_right_collapsed = False
    ed.hier_list_h = None
    ed.models = []
    ed.cameras = []
    ed.lights = []
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.is_playing = False
    ed.gizmo_mode = 'translate'
    ed.gizmo_axis = None
    ed.gizmo_drag = None
    ed.gizmo_undo_before = None
    ed.ui = ui
    ed.ui_consumed = False
    ed.view = _View(click_captured)
    ed.pressed = set()
    ed.released = set()
    ed.mouse_press_pos = {}
    ed.mouse_pos = (0, 0)
    ed.mouse_wheel = 0
    ed.buttons = (0, 0, 0)
    ed._mods = 0
    ed.preview_camera = None
    ed.camera = Point3D(0.0, 0.0, -10.0)
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.0
    ed.camera_pitch = 0.0
    ed.camera_roll = 0.0
    ed._fov = 0.785
    ed.near = 0.1
    ed.far = 1000.0
    ed._cam_prev_mouse = (0, 0)
    ed._cam_speed = 1.0
    ed._right_drag_view = False
    ed._key_pressed = lambda: _NoKeys()
    ed.undo = U.UndoManager()
    ed.picked = []
    ed._pick = lambda x, y: ed.picked.append((x, y))
    ed._gizmo_hit = lambda x, y: None
    return ed


def _qt_tick_then_paint(ed):
    """严格模拟 Qt 顺序: _on_tick(相机/UI 消费) → clear → paintGL(render)."""
    ed._update_camera(1.0 / 60.0)
    ed.mouse_wheel = 0
    ed.pressed.clear()
    ed.released.clear()
    ed._update_gizmo()


def _press(ed, pos):
    ed.mouse_pos = pos
    ed.mouse_press_pos = {1: pos}
    ed.pressed = {1}
    ed.buttons = (1, 0, 0)


def t_gizmo_gets_click_after_tick_clear():
    ed = _editor()
    vp = ed._layout()[4]
    pos = (vp[0] + vp[2] // 2, vp[1] + vp[3] // 2)
    _press(ed, pos)
    _qt_tick_then_paint(ed)
    check('P-22 清空 pressed 后 gizmo/拾取仍拿到本帧点击',
          ed.picked == [pos], ed.picked)

    # 下一拍无新点击: 不得重放
    _qt_tick_then_paint(ed)
    check('P-22 同一次点击只消费一次 (不重放)', ed.picked == [pos], ed.picked)


def t_ui_consumed_blocks_gizmo():
    ed = _editor(ui=_ConsumingUI())
    vp = ed._layout()[4]
    _press(ed, (vp[0] + vp[2] // 2, vp[1] + vp[3] // 2))
    _qt_tick_then_paint(ed)
    check('P-22 UI 命中时不进 gizmo', ed.picked == [], ed.picked)
    check('P-22 UI 命中标记已置位', ed.ui_consumed is True)


def t_click_outside_viewport_no_pick():
    ed = _editor()
    _press(ed, (10, 10))          # 左侧面板 (视口外)
    _qt_tick_then_paint(ed)
    check('P-22 视口外点击不拾取', ed.picked == [], ed.picked)


def t_click_captured_no_pick():
    ed = _editor(click_captured=True)
    vp = ed._layout()[4]
    _press(ed, (vp[0] + vp[2] // 2, vp[1] + vp[3] // 2))
    _qt_tick_then_paint(ed)
    check('P-22 view.click_captured 时不拾取', ed.picked == [], ed.picked)


def t_gizmo_axis_hit_starts_drag():
    ed = _editor()
    vp = ed._layout()[4]
    pos = (vp[0] + vp[2] // 2, vp[1] + vp[3] // 2)
    started = []
    ed._gizmo_hit = lambda x, y: 'X'
    ed._gizmo_start_drag = lambda axis, x, y: started.append((axis, x, y))
    _press(ed, pos)
    _qt_tick_then_paint(ed)
    check('P-22 命中 gizmo 轴时启动拖拽 (优先于点选)',
          started == [('X', pos[0], pos[1])] and ed.picked == [],
          (started, ed.picked))


def t_paint_before_tick_no_double_pick():
    """反向事件顺序 (paintGL 先于 _on_tick) 也不能把同一击拾取两次。"""
    ed = _editor()
    vp = ed._layout()[4]
    pos = (vp[0] + vp[2] // 2, vp[1] + vp[3] // 2)
    _press(ed, pos)
    ed._update_gizmo()                       # paintGL 先到 (pressed 仍在)
    check('P-22 paintGL 先到 → 本帧拾取一次', ed.picked == [pos], ed.picked)
    ed._update_camera(1.0 / 60.0)            # _on_tick 随后
    ed.mouse_wheel = 0
    ed.pressed.clear()
    ed.released.clear()
    ed._update_gizmo()                       # 下一拍 paintGL
    check('P-22 反向顺序不重复拾取', ed.picked == [pos], ed.picked)


t_gizmo_gets_click_after_tick_clear()
t_paint_before_tick_no_double_pick()
t_ui_consumed_blocks_gizmo()
t_click_outside_viewport_no_pick()
t_click_captured_no_pick()
t_gizmo_axis_hit_starts_drag()
print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
