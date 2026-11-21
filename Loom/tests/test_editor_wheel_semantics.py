# -*- coding: utf-8 -*-
"""B7-28 编辑器「滚轮反语义」回归门 (2026-11-21).

缺陷 (P3 门建设时发现, beta7 立项 B7-28):
  1. editor/core.py _dispatch_ui_mouse 调 ui.dispatch_mouse **不传 wheel** (默认 0)
     -> 编辑器里 ScrollView 滚轮滚不动;
  2. 滚轮缩放按 _ui_lock = ui_consumed (本帧鼠标事件**整体**被消费) 门控
     -> 在滚动列表上滚轮时相机也跟着缩放 (滚轮根本没被拦, UI 也没吃到);
  3. 同帧「点按钮 + 滚轮」: 整帧 consumed=True 把滚轮连坐丢掉
     —— 正是 P-09 (2026-11-07) 明确裁决过的反语义.

修法 (对齐 GL 播放器 P3-1 的同款语义):
  · _dispatch_ui_mouse 把本帧 wheel 传给 ui.dispatch_mouse -> ScrollView 能滚;
  · 滚轮专属判据调 loom_ui_input.wheel_taken_by_scrollview (dispatch **之前**取),
    消费判定调 loom_ui_input.wheel_consumed_by_ui —— 编辑器与 GL/VK 播放器
    **同源唯一实现**, 不另写一份判据 (开发要求 §5.5「同源不同步」反模式);
  · 只有「滚轮本身被 ScrollView 吃掉」才清 self.mouse_wheel; _update_camera
    的滚轮缩放分支不再被 _ui_lock 连坐.

本门三段:
  A. 运行时同源断言: 编辑器 / GL 播放器 / VK 播放器 import 的是**同一个函数对象**;
  B. 源码级结构断言: dispatch 前-后顺序 + 滚轮缩放分支无 _ui_lock;
  C. 行为断言: EditorApp.__new__ 桩 + UIManager 同签名 UI 桩 (不建窗口).
"""

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


import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + detail if detail else ''))
    if not cond:
        ok = False


def _read(rel):
    with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
        return f.read()


def _def_body(src, name):
    """取模块里 `def name(` 到下一个同级 def 之前的源码 (含缩进整体保留)."""
    lines = src.splitlines()
    start = None
    indent = 0
    for i, ln in enumerate(lines):
        m = re.match(r'^(\s*)def\s+' + re.escape(name) + r'\s*\(', ln)
        if m:
            start = i
            indent = len(m.group(1))
            break
    if start is None:
        return None
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            break
        out.append(ln)
    return '\n'.join(out)


# ================= A. 运行时同源断言 (唯一实现, 不许分叉) =================
import loom_ui_input
import runtime                      # GL 播放器 (P3-1 已修好, 行为不许动)
import editor.core as editor_core   # B4 后编辑器本体 (原 editor.py)
check('loom_ui_input.wheel_taken_by_scrollview 存在',
      callable(loom_ui_input.wheel_taken_by_scrollview))
check('loom_ui_input.wheel_consumed_by_ui 存在',
      callable(loom_ui_input.wheel_consumed_by_ui))
check('编辑器 import 的是共享判据本体 (taken)',
      editor_core.wheel_taken_by_scrollview is loom_ui_input.wheel_taken_by_scrollview)
check('编辑器 import 的是共享判据本体 (consumed)',
      editor_core.wheel_consumed_by_ui is loom_ui_input.wheel_consumed_by_ui)
check('GL 播放器 import 的是共享判据本体 (taken) (P3-1 先例, 不许动)',
      runtime.wheel_taken_by_scrollview is loom_ui_input.wheel_taken_by_scrollview)
check('GL 播放器 import 的是共享判据本体 (consumed) (P3-1 先例, 不许动)',
      runtime.wheel_consumed_by_ui is loom_ui_input.wheel_consumed_by_ui)
try:
    import render.vk.ui as vk_ui
    check('VK 播放器 import 的是共享判据本体 (taken)',
          vk_ui.wheel_taken_by_scrollview is loom_ui_input.wheel_taken_by_scrollview)
except Exception as e:   # pragma: no cover
    check('VK 播放器 import 的是共享判据本体 (taken)', False, repr(e))

# ================= B. 源码级结构断言 =================
ed_src = _read(os.path.join('editor', 'core.py'))
disp = _def_body(ed_src, '_dispatch_ui_mouse')
check('editor._dispatch_ui_mouse 存在', disp is not None)
if disp:
    check('_dispatch_ui_mouse dispatch 前取 wheel_taken_by_scrollview',
          disp.find('wheel_taken_by_scrollview(ui, pos)') >= 0
          and disp.find('wheel_taken_by_scrollview(ui, pos)')
              < disp.find('ui.dispatch_mouse('),
          'taken@%d dispatch@%d' % (
              disp.find('wheel_taken_by_scrollview(ui, pos)'),
              disp.find('ui.dispatch_mouse(')))
    check('_dispatch_ui_mouse 把 wheel 传给 dispatch_mouse (第 4 实参)',
          'ui.dispatch_mouse(pos, pressed, released, wheel)' in disp)
    check('_dispatch_ui_mouse 用共享 wheel_consumed_by_ui 结算',
          'wheel_consumed_by_ui(wheel, consumed, wheel_taken)' in disp)
    check('_dispatch_ui_mouse 滚轮被吃时清 self.mouse_wheel',
          'self.mouse_wheel = 0' in disp)
uc = _def_body(ed_src, '_update_camera')
check('editor._update_camera 存在', uc is not None)
if uc:
    check('滚轮缩放分支不再被 _ui_lock (整帧 consumed) 连坐',
          'not _ui_lock and self.mouse_wheel' not in uc)
    check('滚轮缩放分支仍在视口内才生效 (基线不回归)',
          'self._in_viewport(self.mouse_pos)' in uc)

# ================= C. 行为断言 (无头桩) =================
import pygame
from editor import EditorApp


class _SV:
    def __init__(self):
        self.scroll_pos = 0.0

    def can_scroll(self):
        return True

    def on_mouse_wheel(self, d):
        self.scroll_pos += d
        return True


class _StubUI:
    """与 loom_ui.UIManager 的滚轮路径同签名:
    dispatch_mouse(pos, pressed, released, wheel=0) / _hit_scroll_view / on_mouse_wheel."""
    def __init__(self):
        self.sv = _SV()
        self.wheel_seen = []

    def _hit_scroll_view(self, pos):
        return self.sv if pos == (100, 100) else None   # (100,100) = 滚动列表

    def dispatch_mouse(self, pos, pressed, released, wheel=0):
        self.wheel_seen.append(wheel)
        if wheel:
            hit = self._hit_scroll_view(pos)
            if hit is not None:
                if hit.on_mouse_wheel(wheel):
                    return True
        return 1 in pressed       # 点到按钮 = 本帧鼠标事件整体被消费

    def update_hover_only(self, pos):
        pass


class _View:
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}


def make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed._mods = 0
    ed.buttons = (0, 0, 0)
    ed.mouse_pos = (100, 100)
    ed._cam_prev_mouse = (100, 100)
    ed.mouse_press_pos = {}
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.mouse_wheel = 0
    ed.camera_distance = 10.0
    ed.camera_target = (0, 0, 0)
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.preview_camera = None
    ed._preview_orbit = None
    ed.view = _View()
    ed._fov = math.radians(45.0)
    ed._in_viewport = lambda pos: True
    ed.ui = _StubUI()
    return ed


class _NoKeys:
    def __getitem__(self, i):
        return 0


pygame.key.get_pressed = _NoKeys()

# C1: 编辑器里 ScrollView 滚轮能滚 (修前: dispatch 不传 wheel, scroll_pos 恒 0)
ed = make_editor()
ed.mouse_wheel = +1
ed._update_camera()
check('C1 编辑器 ScrollView 滚轮能滚 (dispatch 收到 wheel + scroll_pos=1)',
      ed.ui.wheel_seen[-1] == 1 and ed.ui.sv.scroll_pos == 1.0,
      'wheel_seen=%r scroll_pos=%r' % (ed.ui.wheel_seen, ed.ui.sv.scroll_pos))

# C2: 列表上滚轮 -> 相机不跟着缩放 (修前: distance 10 -> 9.048)
ed = make_editor()
ed.mouse_wheel = +1
d0 = ed.camera_distance
ed._update_camera()
check('C2 列表上滚轮 -> 相机不缩放 (滚轮被 ScrollView 吃掉)',
      abs(ed.camera_distance - d0) < 1e-9,
      'distance %.6f -> %.6f' % (d0, ed.camera_distance))

# C3 (P-09): 同帧「点按钮 + 滚轮」-> 滚轮不丢, 相机照常缩放
#   (修前: 整帧 consumed=True 把滚轮连坐丢掉, distance 不变)
ed = make_editor()
ed.mouse_pos = (500, 500)
ed.pressed = {1}
ed.mouse_wheel = +1
d0 = ed.camera_distance
ed._update_camera()
check('C3 同帧点按钮+滚轮 -> 滚轮不丢 (P-09, 相机照常缩放)',
      abs(ed.camera_distance - d0) > 1e-9,
      'distance %.6f -> %.6f' % (d0, ed.camera_distance))

# C4 基线: 视口内纯滚轮 (无 UI 命中) -> 相机照常缩放 (不许回归)
ed = make_editor()
ed.mouse_pos = (500, 500)
ed.mouse_wheel = +1
d0 = ed.camera_distance
ed._update_camera()
check('C4 视口内纯滚轮 -> 相机照常缩放 (基线)',
      abs(ed.camera_distance - d0) > 1e-9,
      'distance %.6f -> %.6f' % (d0, ed.camera_distance))

# C5 基线: 视口外滚轮不缩放 (test_camera_control 同款, 不许回归)
ed = make_editor()
ed.mouse_pos = (500, 500)
ed.mouse_wheel = +1
ed._in_viewport = lambda pos: False
d0 = ed.camera_distance
ed._update_camera()
check('C5 视口外滚轮不缩放 (基线)',
      abs(ed.camera_distance - d0) < 1e-9,
      'distance %.6f -> %.6f' % (d0, ed.camera_distance))

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
