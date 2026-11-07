# -*- coding: utf-8 -*-

"""test_editor_focus.py — 相机聚焦 focus_on_object / EAI view_focus / 自动聚焦
(2026-11-07 C, 无头: EditorApp.__new__ 桩, 不建真实窗口/GL).

覆盖:
  · focus_on_object(index, smooth=False): camera_target = 世界 AABB 中心,
    camera_distance = 包围球半径 * FOCUS_DISTANCE_FACTOR, yaw/pitch 不变;
  · smooth=True: _focus_anim 记录 from/to, _advance_focus_anim 做线性插值,
    180ms 后到目标并清状态;
  · 播放态拒绝聚焦 (不动播放相机);
  · EAI view_focus {index?/name?, smooth?} 命令 + 越界/无目标拒绝;
  · 自动聚焦: object_add / object_select 成功后聚焦 (agent_auto_focus 可关).
"""

# 2026-11-06 P-02: Windows 控制台默认 GBK, ✅/❌ 会抛 UnicodeEncodeError 造成假失败.
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门: 出现 "FAIL" 行就在退出时改状态码 1 (run_all 真绿).
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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import engine as E
import undo as U
from mesh import create_cube
from editor import EditorApp
import agent_commands as ac

# 不开窗口的引擎桩: 替换 _build_gpu 为 no-op (同 test_undo.py / test_camera_control.py)
E.GLEngine._build_gpu = lambda self, m: None

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def near(a, b, tol=1e-6):
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


class _View:
    """极简 IEditorView 桩: 无输入框焦点 -> 相机键盘平移不被 UI 抢占."""

    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}


def _make_editor():
    ed = EditorApp.__new__(EditorApp)
    ed.models = []
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.current_model_index = 0
    ed._struct_gen = 0
    ed.is_playing = False
    ed.undo = U.UndoManager()
    ed._mods = 0
    ed.buttons = (0, 0, 0)
    ed.mouse_pos = (100, 100)
    ed._cam_prev_mouse = (100, 100)
    ed.mouse_wheel = 0
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.preview_camera = None
    ed._preview_orbit = None
    ed._fov = math.radians(45.0)
    ed.width = 800
    ed.height = 600
    ed.near = 0.1
    ed.far = 1000.0
    ed.view = _View()
    ed.msg = ''
    ed._msg_until = 0.0
    return ed


def _add_cube(ed, pos=(2.0, 3.0, 4.0), name='盒子'):
    return ed.add_model(create_cube(1.0), E.Point3D(*pos), E.Point3D(0, 0, 0),
                        name=name)


def _center(m):
    ed = _CUR_ED[0]
    mn, mx = ed.get_bounding_box(m)
    return ((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5), \
           (mx.x - mn.x, mx.y - mn.y, mx.z - mn.z)


_CUR_ED = [None]


class _FakeWin:
    def __init__(self, ed):
        self.editor = ed


# ============ ① focus_on_object(smooth=False): 中心 + 包围球距离 ============
def t_focus_immediate():
    ed = _make_editor()
    _CUR_ED[0] = ed
    m = _add_cube(ed)
    fn = getattr(ed, 'focus_on_object', None)
    if fn is None:
        check("editor.focus_on_object 存在", False)
        return
    factor = getattr(EditorApp, 'FOCUS_DISTANCE_FACTOR', None)
    check("EditorApp.FOCUS_DISTANCE_FACTOR 存在", factor is not None, factor)

    ok = fn(0, smooth=False)
    c, d = _center(m)
    radius = 0.5 * math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
    check("focus_on_object 返回 True", ok is True, ok)
    check("camera_target ≈ 世界 AABB 中心", near(ed.camera_target, c),
          "%r vs %r" % (ed.camera_target, c))
    check("camera_distance ≈ 包围球半径 * 系数",
          factor is not None and abs(ed.camera_distance - radius * factor) < 1e-6,
          "%.6f vs %.6f" % (ed.camera_distance,
                            radius * (factor or 0.0)))
    check("focus 保持 yaw/pitch", ed.camera_yaw == 0.6
          and abs(ed.camera_pitch + 0.35) < 1e-12,
          (ed.camera_yaw, ed.camera_pitch))
    check("focus 不残留动画状态", getattr(ed, '_focus_anim', None) is None)


# ============ ② smooth=True: 180ms 线性插值 ============
def t_focus_smooth():
    ed = _make_editor()
    _CUR_ED[0] = ed
    m = _add_cube(ed)
    fn = getattr(ed, 'focus_on_object', None)
    adv = getattr(ed, '_advance_focus_anim', None)
    if fn is None or adv is None:
        check("editor._advance_focus_anim 存在", False)
        return
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    fn(0, smooth=True)
    c, d = _center(m)
    radius = 0.5 * math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
    factor = getattr(EditorApp, 'FOCUS_DISTANCE_FACTOR', 0.0)
    anim = getattr(ed, '_focus_anim', None)
    check("smooth 记录 _focus_anim", isinstance(anim, dict), type(anim).__name__)
    if not isinstance(anim, dict):
        return
    check("动画时长 ~180ms", abs(float(anim.get('dur', 0.0)) - 0.18) < 1e-9,
          anim.get('dur'))
    check("smooth 目标逻辑值已到位 (target=中心)",
          near(ed.camera_target, c), ed.camera_target)
    adv(now=anim['t0'])
    check("动画 0% -> 回到起点", near(ed.camera_target, (0.0, 0.0, 0.0))
          and abs(ed.camera_distance - 10.0) < 1e-9,
          (ed.camera_target, ed.camera_distance))
    adv(now=anim['t0'] + anim['dur'] * 0.5)
    mid = tuple(0.5 * (0.0 + v) for v in c)
    check("动画 50% -> 中点线性插值", near(ed.camera_target, mid),
          "%r vs %r" % (ed.camera_target, mid))
    adv(now=anim['t0'] + anim['dur'] + 0.01)
    check("动画结束 -> 精确落点 + 清状态",
          near(ed.camera_target, c) and getattr(ed, '_focus_anim', None) is None
          and abs(ed.camera_distance - radius * factor) < 1e-6,
          (ed.camera_target, ed.camera_distance))


# ============ ③ 播放态: 不聚焦 ============
def t_focus_playing():
    ed = _make_editor()
    _CUR_ED[0] = ed
    _add_cube(ed)
    fn = getattr(ed, 'focus_on_object', None)
    if fn is None:
        check("editor.focus_on_object 存在 (播放态)", False)
        return
    ed.is_playing = True
    ok = fn(0, smooth=False)
    check("播放态 focus 返回 False 且不动相机",
          ok is False and ed.camera_target == (0.0, 0.0, 0.0)
          and ed.camera_distance == 10.0, (ok, ed.camera_target))


# ============ ④ EAI view_focus ============
def t_view_focus_cmd():
    ed = _make_editor()
    _CUR_ED[0] = ed
    m = _add_cube(ed)
    win = _FakeWin(ed)
    c, d = _center(m)
    r = ac.dispatch('view_focus', {'index': 0, 'smooth': False}, win)
    check("view_focus index -> ok", r['ok'] and r['result'].get('index') == 0, r)
    check("view_focus index -> 相机对准中心", near(ed.camera_target, c),
          ed.camera_target)
    ed.camera_target = (0.0, 0.0, 0.0)
    r = ac.dispatch('view_focus', {'name': '盒子', 'smooth': 'false'}, win)
    check("view_focus name -> ok", r['ok'] and r['result'].get('focused') == '盒子', r)
    check("view_focus name -> 相机对准中心", near(ed.camera_target, c))
    r = ac.dispatch('view_focus', {'index': 99}, win)
    check("view_focus 越界 -> 拒绝", not r['ok'] and '越界' in r['error'], r)
    r = ac.dispatch('view_focus', {'name': '不存在'}, win)
    check("view_focus 找不到 -> 拒绝", not r['ok'] and '找不到' in r['error'], r)
    ed.selected_index = -1
    r = ac.dispatch('view_focus', {}, win)
    check("view_focus 无目标 -> 拒绝", not r['ok'] and '没有选中' in r['error'], r)


# ============ ⑤ 自动聚焦 (object_add / object_select) ============
def t_auto_focus():
    orig = getattr(ac, '_auto_focus_enabled', None)
    if orig is None:
        check("agent_commands._auto_focus_enabled 存在", False)
        return
    ed = _make_editor()
    _CUR_ED[0] = ed
    win = _FakeWin(ed)
    ac._auto_focus_enabled = lambda w: True
    try:
        r = ac.dispatch('object_add', {'type': 'cube'}, win)
        check("object_add ok", r['ok'], r)
        if not ed.models:
            return
        m = ed.models[-1]
        anim = getattr(ed, '_focus_anim', None)
        check("object_add 成功后自动聚焦 (动画已起)", isinstance(anim, dict))
        if isinstance(anim, dict):
            ed._advance_focus_anim(now=anim['t0'] + anim['dur'] + 0.01)
        c, _d = _center(m)
        check("自动聚焦目标 = 新物体中心", near(ed.camera_target, c),
              ed.camera_target)
        ed.camera_target = (0.0, 0.0, 0.0)
        ed._focus_anim = None
        r = ac.dispatch('object_select', {'name': m.name}, win)
        check("object_select ok", r['ok'], r)
        check("object_select 成功后自动聚焦",
              isinstance(getattr(ed, '_focus_anim', None), dict))
        # 显式关闭 agent_auto_focus -> 不聚焦
        ac._auto_focus_enabled = lambda w: False
        ed.camera_target = (0.0, 0.0, 0.0)
        ed._focus_anim = None
        r = ac.dispatch('object_add', {'type': 'sphere'}, win)
        check("agent_auto_focus=false -> 不自动聚焦",
              r['ok'] and getattr(ed, '_focus_anim', None) is None
              and ed.camera_target == (0.0, 0.0, 0.0), r)
    finally:
        ac._auto_focus_enabled = orig


if __name__ == "__main__":
    print("========== 相机聚焦 (Editor Focus) 测试 ==========")
    t_focus_immediate()
    t_focus_smooth()
    t_focus_playing()
    t_view_focus_cmd()
    t_auto_focus()
    if _FAILS:
        print("总结果: FAIL", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS")
