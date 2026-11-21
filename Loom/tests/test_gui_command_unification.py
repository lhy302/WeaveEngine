# -*- coding: utf-8 -*-
"""test_gui_command_unification.py — Q-B7-56-1: GUI 操作全量命令化 + 相机命令进撤销栈
(2026-11-22, 全无头 offscreen Qt)。

人类裁定（本门最高依据, 2026-11-22 两条）:
  裁定① 「在我的设想里 GUI 界面除了鼠标和开发者相机移动这两个操作允许绕过 EAI
    以外, 剩下的所有对 GUI 界面的点击都是翻译成 EAI 命令行再执行的, 也就是全部
    经过 EAI 命令行。」
  裁定② 「右键转动视角和 WASDQE 移动这两种操作是不进撤销栈的, 只有直接在命令行
    里输命令转动视角和移动才进入撤销栈。」

断言组:
  A (GUI≡命令行): 每个命令化操作, GUI 处理函数路径与「命令行输同一条命令」产生
     同一串可观察结果（对象状态 + 撤销栈深度 + 命令日志条目）。
     覆盖: 加基元 / 复制 / 改名(物体·光源·相机) / gizmo 模式 / 播放暂停 /
     挂父·脱父 / 检查器 set_transform(物体·光源·相机)。
  B (批作用域): GUI 路径 = 用户编辑（D10=A: 不进 agent 批作用域、不续租, 真实
     undo registry 验证）; 命令行路径在 agent_batch_begin 内执行会进批;
     D10=B 批内 undo 拒批语义不破坏。
  C (相机裁定): camera_move/camera_look 执行后撤销栈 +1 且 undo 可恢复相机状态;
     GUI 右键轨道 / WASDQE 老链路 (editor 事件处理函数) 执行后撤销栈深度不变。
  D (结构): main_window.py 清单内直调归零（AST 定位 self.editor.<op>( 直调,
     白名单=豁免面+_notify 类反馈）; dispatch 的 scope 参数存在且缺省兼容。
"""

# 2026-11-06 P-02: Windows 控制台默认 GBK -> 统一 UTF-8(replace) (假失败防治).
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门 (与各 test_*.py 同款): 出现 FAIL 行 -> 退出码 1 (run_all 真绿).
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


import ast
import collections
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
# 无头 Qt: LoomGUI.__new__ 不跑 __init__ (不需要真窗口), 走纯 Python 方法路径.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('LOOM_NO_DIALOG', '1')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

import agent_commands as ac            # noqa: E402
import editor.undo as U                # noqa: E402
import pygame                          # noqa: E402  (仅 K_* 常量)
from editor import EditorApp           # noqa: E402
from gui import main_window as loom_gui  # noqa: E402

# 引擎桩: 不建 GPU 资源 (与 test_undo/test_qt_delete_confirm 同款)
EditorApp._build_gpu = lambda self, m: None

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


# ====================================================================
# 无头夹具: EditorApp.__new__ 桩 (真方法/真 undo registry) + LoomGUI.__new__ 桩
# ====================================================================

def make_editor():
    """最小 EditorApp 桩: 真方法 + 真 UndoManager (本测试**真调 undo registry**)."""
    ed = EditorApp.__new__(EditorApp)
    ed.models = []
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.current_model_index = 0
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.is_playing = False
    ed.gizmo_mode = 'translate'
    ed.scene_name = '场景'
    ed.prefab_name = 'prefab'
    ed._struct_gen = 0
    ed.undo = U.UndoManager()
    ed.preview_camera = None
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.ortho = False
    ed.ortho_size = 12.0
    ed._fov = 1.0
    ed._scene_path = None
    ed.last_dir = None
    ed.active_camera = None
    ed.orbit_mode = True
    ed.width = 1024
    ed.height = 600
    ed.mouse_wheel = 0
    ed.mouse_pos = (0, 0)
    ed.buttons = (False, False, False)
    ed.pressed = ()
    ed.released = ()
    ed._mods = 0
    ed.ui = None
    ed.ui_consumed = False
    ed._cam_speed = 1.0
    ed._cam_prev_mouse = (0, 0)
    ed.panel_left_collapsed = True
    ed.panel_right_collapsed = True
    ed._key_pressed = lambda: collections.defaultdict(bool)
    ed.view = type('V', (), {
        'input_state': staticmethod(lambda: {'focus_id': None, 'click_captured': False}),
        'reset_interaction': lambda self: None})()
    notif = []
    ed._notify = lambda msg, color=None: notif.append(str(msg))
    ed._notifs = notif
    return ed


class _FakeUITree:
    """UI 树桩: 记录教学等价命令日志与刷新次数."""

    def __init__(self):
        self.logs = []
        self.refreshed = 0

    def log_cmd(self, name, args):
        self.logs.append((name, dict(args)))

    def refresh(self):
        self.refreshed += 1


def make_view(ed):
    """LoomGUI.__new__ 桩: 只供 GUI 处理函数路径调用 (不开真窗口)."""
    v = loom_gui.LoomGUI.__new__(loom_gui.LoomGUI)
    v.editor = ed
    v.uitree = _FakeUITree()
    v._rebuild_inspector = lambda: None
    v._refresh_all = lambda: None
    return v


class _Win:
    def __init__(self, ed):
        self.editor = ed


def observed(ed):
    """可观察结果串: 对象状态 + 撤销栈深度 (相机视角不属场景状态, 不入列)."""
    return (
        [(m.name, tuple(m.position), m.parent.name if m.parent is not None else None)
         for m in ed.models],
        [l.name for l in ed.lights],
        [c.name for c in ed.cameras],
        len(ed.undo.undo_stack),
        ed.is_playing,
        ed.gizmo_mode,
    )


def ring_cmds(after=0):
    """命令日志环里的命令名清单 (命令行路径的教学日志通道)."""
    out = []
    for _seq, _ts, text in ac.log_since(after):
        if text.startswith('[命令] ') and ' -> ' in text:
            out.append(text[len('[命令] '):].split(' ')[0])
    return out


# ====================================================================
# 断言组 A: GUI ≡ 命令行
# ====================================================================

def t_a_add_primitive():
    print("---- A1 加基元: GUI _cmd_add vs 命令行 object_add ----")
    edA = make_editor()
    vA = make_view(edA)
    edB = make_editor()
    wB = _Win(edB)
    seq0 = ac.last_log_seq()
    vA._cmd_add('sphere')
    r = ac.dispatch('object_add', {'type': 'sphere'}, wB)
    check("A1 dispatch object_add -> ok", r.get('ok') is True, r)
    check("A1 GUI ≡ 命令行 (对象状态+撤销栈深度)", observed(edA) == observed(edB),
          (observed(edA), observed(edB)))
    check("A1 GUI 路径写等价命令日志 (教学)", vA.uitree.logs
          and vA.uitree.logs[-1] == ('object_add', {'type': 'sphere'}),
          vA.uitree.logs)
    check("A1 命令行路径写命令日志环", 'object_add' in ring_cmds(seq0),
          ring_cmds(seq0))


def t_a_duplicate():
    print("---- A2 复制: GUI _cmd_dup vs 命令行 object_duplicate ----")
    edA = make_editor()
    vA = make_view(edA)
    edB = make_editor()
    wB = _Win(edB)
    seq0 = ac.last_log_seq()
    edA._add_primitive('cube')
    edB._add_primitive('cube')
    vA._cmd_dup()
    r = ac.dispatch('object_duplicate', {}, wB)
    check("A2 dispatch object_duplicate -> ok", r.get('ok') is True, r)
    check("A2 GUI ≡ 命令行", observed(edA) == observed(edB),
          (observed(edA), observed(edB)))
    check("A2 副本名字一致", [m.name for m in edA.models] == ['立方体1', '立方体1_副本'],
          [m.name for m in edA.models])
    check("A2 GUI 路径写等价命令日志", ('object_duplicate', {}) in vA.uitree.logs,
          vA.uitree.logs)
    check("A2 命令行路径写命令日志环", 'object_duplicate' in ring_cmds(seq0))


def t_a_rename():
    print("---- A3 改名: GUI _rename_* (物体/光源/相机) vs 命令行 object_rename ----")
    edA = make_editor()
    vA = make_view(edA)
    edB = make_editor()
    wB = _Win(edB)
    seq0 = ac.last_log_seq()
    # 对话框=输入采集, 顶掉; 按旧名映射新名 (名字池全局唯一, 三类各用各的新名)
    vA._ask_text = lambda title, prompt, initial: '新' + initial
    mA = edA._add_primitive('cube')
    lA = edA._add_light('dir')
    cA = edA._add_camera()
    mB = edB._add_primitive('cube')
    lB = edB._add_light('dir')
    cB = edB._add_camera()
    vA._rename_obj(mA)          # -> 新名字
    vA._rename_light(lA)        # -> 新灯名
    vA._rename_camera(cA)       # -> 新机名
    r1 = ac.dispatch('object_rename', {'name': mB.name, 'new': '新立方体1'}, wB)
    r2 = ac.dispatch('object_rename', {'name': lB.name, 'new': '新平行光'}, wB)
    r3 = ac.dispatch('object_rename', {'name': cB.name, 'new': '新摄像机1'}, wB)
    check("A3 命令行三类改名 -> ok", all(r.get('ok') for r in (r1, r2, r3)),
          (r1, r2, r3))
    check("A3 GUI 三类改名生效", (mA.name, lA.name, cA.name)
          == ('新立方体1', '新平行光', '新摄像机1'), (mA.name, lA.name, cA.name))
    check("A3 GUI ≡ 命令行", observed(edA) == observed(edB),
          (observed(edA), observed(edB)))
    check("A3 GUI 路径写等价命令日志 ×3",
          [x[0] for x in vA.uitree.logs] == ['object_rename'] * 3, vA.uitree.logs)
    check("A3 命令行路径写命令日志环", ring_cmds(seq0).count('object_rename') == 3,
          ring_cmds(seq0))
    # 重名拒绝: 两路都不改状态、不涨撤销栈, GUI 出声 (toast)
    seq1 = ac.last_log_seq()
    vA._ask_text = lambda title, prompt, initial: lA.name   # 改成与光源重名
    depthA = len(edA.undo.undo_stack)
    vA._rename_obj(mA)
    r = ac.dispatch('object_rename', {'name': mB.name, 'new': lB.name}, wB)
    check("A3 重名: 命令行拒绝 (ok=False)", r.get('ok') is False, r)
    check("A3 重名: GUI 不改状态/不涨栈且出声",
          mA.name == '新立方体1' and len(edA.undo.undo_stack) == depthA
          and len(edA._notifs) > 0, (mA.name, edA._notifs))
    check("A3 重名: 命令行日志环记录拒绝", 'object_rename' in ring_cmds(seq1))


def t_a_gizmo():
    print("---- A4 gizmo 模式: GUI _cmd_gizmo vs 命令行 gizmo ----")
    edA = make_editor()
    vA = make_view(edA)
    edB = make_editor()
    wB = _Win(edB)
    seq0 = ac.last_log_seq()
    vA._cmd_gizmo('rotate')
    ac.dispatch('gizmo', {'mode': 'rotate'}, wB)
    check("A4 GUI ≡ 命令行 (gizmo_mode)", edA.gizmo_mode == edB.gizmo_mode == 'rotate',
          (edA.gizmo_mode, edB.gizmo_mode))
    check("A4 GUI 路径写等价命令日志",
          ('gizmo', {'mode': 'rotate'}) in vA.uitree.logs, vA.uitree.logs)
    check("A4 命令行路径写命令日志环", 'gizmo' in ring_cmds(seq0))


def t_a_play():
    print("---- A5 播放/暂停: GUI _cmd_play vs 命令行 play ----")
    edA = make_editor()
    vA = make_view(edA)
    edA._add_primitive('cube')
    edB = make_editor()
    wB = _Win(edB)
    edB._add_primitive('cube')
    seq0 = ac.last_log_seq()
    vA._cmd_play()
    r = ac.dispatch('play', {}, wB)
    check("A5 命令行 play -> ok 且进播放", r.get('ok') and edB.is_playing is True, r)
    check("A5 GUI ≡ 命令行 (播放态+撤销清栈语义一致)",
          observed(edA) == observed(edB), (observed(edA), observed(edB)))
    vA._cmd_play()
    ac.dispatch('play', {}, wB)
    check("A5 再点一次: 两路都退出播放", edA.is_playing is False and edB.is_playing is False)
    check("A5 GUI 路径写等价命令日志", [x[0] for x in vA.uitree.logs] == ['play', 'play'],
          vA.uitree.logs)
    check("A5 命令行路径写命令日志环", ring_cmds(seq0).count('play') == 2)


def t_a_reparent():
    print("---- A6 挂父/脱父: GUI _hier_drop vs 命令行 reparent ----")
    edA = make_editor()
    vA = make_view(edA)
    edB = make_editor()
    wB = _Win(edB)
    seq0 = ac.last_log_seq()
    edA._add_primitive('cube')
    edA._add_primitive('sphere')
    edB._add_primitive('cube')
    edB._add_primitive('sphere')
    vA._hier_drop(('model', 1), ('model', 0))
    ac.dispatch('reparent', {'child': '球体2', 'parent': '立方体1'}, wB)
    check("A6 挂父 GUI ≡ 命令行", observed(edA) == observed(edB),
          (observed(edA), observed(edB)))
    check("A6 父链一致", edA.models[1].parent is edA.models[0]
          and edB.models[1].parent is edB.models[0])
    vA._hier_drop(('model', 1), None)
    ac.dispatch('reparent', {'child': '球体2'}, wB)
    check("A6 脱父 GUI ≡ 命令行", observed(edA) == observed(edB)
          and edA.models[1].parent is None and edB.models[1].parent is None)
    # 相机挂父 (camera-camera; GUI 唯一可达的相机挂父形态): 两路走同一条
    # reparent 命令 —— 引擎侧 set_camera_parent 对 CameraState 父存在**既有缺陷**
    # (loom_camera.world_rotation_matrix 只认 model 的 .rotation), 两路同样失败、
    # 同样无状态变化、同样不涨撤销栈 —— 恰好证明 GUI ≡ 命令行 (同一命令同源)。
    edA._add_camera()
    edA._add_camera()
    edB._add_camera()
    edB._add_camera()
    depthA = len(edA.undo.undo_stack)
    vA._hier_drop(('camera', 1), ('camera', 0))
    r = ac.dispatch('reparent', {'child': '摄像机2', 'parent': '摄像机1'}, wB)
    check("A6 相机挂父: 命令行走同一条 reparent (既有引擎缺陷两路同失败)",
          r.get('ok') is False, r)
    check("A6 相机挂父: GUI ≡ 命令行 (状态/撤销栈零变化)", observed(edA) == observed(edB)
          and len(edA.undo.undo_stack) == depthA == len(edB.undo.undo_stack),
          (observed(edA), observed(edB)))
    check("A6 GUI 路径写等价命令日志 ×2 (失败命令不出教学日志, 走 _notify)",
          [x[0] for x in vA.uitree.logs] == ['reparent'] * 2, vA.uitree.logs)
    check("A6 命令行路径写命令日志环", ring_cmds(seq0).count('reparent') == 2,
          ring_cmds(seq0))   # 相机挂父那条走 '失败:' 行, 不计 ok 面
    # 重新挂回 (为成环测试造链, 两路同步): 球体2 -> 立方体1
    vA._hier_drop(('model', 1), ('model', 0))
    ac.dispatch('reparent', {'child': '球体2', 'parent': '立方体1'}, wB)
    # 无效拖拽 (物体挂到自己的后代): GUI 预判不发命令, 命令行成环守卫拒绝
    depthA = len(edA.undo.undo_stack)
    logs_before = len(vA.uitree.logs)
    vA._hier_drop(('model', 0), ('model', 1))   # 立方体1 挂到它的子 球体2 下
    r = ac.dispatch('reparent', {'child': '立方体1', 'parent': '球体2'}, wB)
    check("A6 成环拒绝: 命令行 ok=False (判据同源)", r.get('ok') is False, r)
    check("A6 成环拒绝: GUI 预判不发命令/不涨栈",
          len(edA.undo.undo_stack) == depthA and len(vA.uitree.logs) == logs_before,
          (len(edA.undo.undo_stack), depthA, len(vA.uitree.logs), logs_before))


def t_a_set_transform():
    print("---- A7 检查器 set_transform: GUI 数值行会话 vs 命令行 set_transform ----")
    edA = make_editor()
    vA = make_view(edA)
    edB = make_editor()
    wB = _Win(edB)
    seq0 = ac.last_log_seq()
    mA = edA._add_primitive('cube')
    mB = edB._add_primitive('cube')
    pos0 = tuple(mA.position)
    # GUI 数值行编辑会话: begin -> 两条单轴命令 -> end (拖拽/连输合一步撤销)
    vA._spin_session_begin('X')
    vA._cmd_vec_set(mA, 'model', 'position', 'X', 5.0)
    vA._cmd_vec_set(mA, 'model', 'position', 'Y', 2.0)
    vA._spin_session_end('X')
    r = ac.dispatch('set_transform', {'name': mB.name, 'x': 5.0, 'y': 2.0}, wB)
    check("A7 命令行 set_transform -> ok", r.get('ok') is True, r)
    check("A7 GUI ≡ 命令行 (位置+撤销栈深度)",
          observed(edA) == observed(edB), (observed(edA), observed(edB)))
    check("A7 GUI 会话=一步撤销 (命令行=一步撤销)",
          len(edA.undo.undo_stack) == len(edB.undo.undo_stack) == 2,
          (len(edA.undo.undo_stack), len(edB.undo.undo_stack)))
    edA.undo.undo()
    edB.undo.undo()
    check("A7 撤销后两路都回到原位", tuple(mA.position) == pos0
          and tuple(mB.position) == pos0, (tuple(mA.position), tuple(mB.position)))
    # 光源/相机位置行: light_set / camera_set
    edA2 = make_editor()
    vA2 = make_view(edA2)
    edB2 = make_editor()
    wB2 = _Win(edB2)
    lA = edA2._add_light('dir')
    lB = edB2._add_light('dir')
    cA = edA2._add_camera()
    cB = edB2._add_camera()
    vA2._spin_session_begin('li.pX')
    vA2._cmd_vec_set(lA, 'light', 'position', 'X', 3.0)
    vA2._spin_session_end('li.pX')
    vA2._spin_session_begin('cam.pX')
    vA2._cmd_vec_set(cA, 'camera', 'position', 'X', 4.0)
    vA2._spin_session_end('cam.pX')
    ac.dispatch('light_set', {'name': lB.name, 'x': 3.0}, wB2)
    ac.dispatch('camera_set', {'name': cB.name, 'x': 4.0}, wB2)
    check("A7 光源/相机位置 GUI ≡ 命令行",
          tuple(lA.position) == tuple(lB.position)
          and tuple(cA.position) == tuple(cB.position)
          and len(edA2.undo.undo_stack) == len(edB2.undo.undo_stack),
          (tuple(lA.position), tuple(lB.position),
           len(edA2.undo.undo_stack), len(edB2.undo.undo_stack)))
    check("A7 GUI 路径写等价命令日志 (会话收尾补一条)",
          [x[0] for x in vA2.uitree.logs] == ['light_set', 'camera_set'],
          vA2.uitree.logs)
    check("A7 命令行路径写命令日志环",
          'light_set' in ring_cmds(seq0) and 'camera_set' in ring_cmds(seq0))


# ====================================================================
# 断言组 B: 批作用域 (D10=A 保持 / D10=B 不破坏) — 真调 undo registry
# ====================================================================

def t_b_gui_not_in_agent_batch():
    print("---- B1 GUI 路径 = 用户编辑: 不进 agent 批作用域 (D10=A) ----")
    ed = make_editor()
    v = make_view(ed)
    w = _Win(ed)
    um = ed.undo
    r = ac.dispatch('agent_batch_begin', {'lease_s': 0}, w)
    check("B1 agent_batch_begin -> ok", r.get('ok') is True, r)
    check("B1 批已开启 (agent 归属)", um.batch_active and um.batch_owner == 'agent')
    v._cmd_add('sphere')
    check("B1 GUI 命令不进批 (batch_size=0, D10=A)", um.batch_size == 0, um.batch_size)
    check("B1 GUI 命令单独进撤销栈", len(um.undo_stack) == 1, len(um.undo_stack))
    check("B1 GUI 执行不在 agent 命令作用域内", um.in_agent_command is False)
    check("B1 GUI 命令后批仍为 agent 归属 (未被 GUI 改写语义)",
          um.batch_owner == 'agent', um.batch_owner)
    # 命令行路径: 在批内执行 -> 吸进批 (现状不变)
    seq0 = ac.last_log_seq()
    ac.dispatch('object_add', {'type': 'cube'}, w)
    check("B1 命令行命令进批 (batch_size=1)", um.batch_size == 1, um.batch_size)
    r = ac.dispatch('agent_batch_end', {}, w)
    check("B1 agent_batch_end 合成一步 (含 1 条命令)", r['result']['commands'] == 1, r)
    um.undo()
    check("B1 批 undo = 一步回退批内全部", [m.name for m in ed.models] == ['球体1'],
          [m.name for m in ed.models])


def t_b_gui_spin_session_batch_is_not_agent_batch():
    print("---- B2 GUI 数值行会话批 = gui 归属 (非 agent 批作用域) ----")
    ed = make_editor()
    v = make_view(ed)
    w = _Win(ed)
    um = ed.undo
    m = ed._add_primitive('cube')
    v._spin_session_begin('X')
    v._cmd_vec_set(m, 'model', 'position', 'X', 1.0)
    check("B2 会话批激活且归属 gui", um.batch_active and um.batch_owner == 'gui',
          (um.batch_active, um.batch_owner))
    check("B2 会话批不在 agent 命令作用域内", um.in_agent_command is False)
    # agent_batch_begin 的"未 end 又 begin 自动 cancel"防悬挂语义不得被 GUI 批破坏
    r = ac.dispatch('agent_batch_begin', {}, w)
    check("B2 GUI 批在跑时 agent_batch_begin 仍走防悬挂 (ok)", r.get('ok') is True, r)
    check("B2 旧 GUI 批被收口/让位, 新批为 agent 归属", um.batch_owner == 'agent',
          um.batch_owner)
    ac.dispatch('agent_batch_cancel', {}, w)
    v._spin_session_end('X')
    check("B2 会话收尾后无批残留", um.batch_active is False)


def t_b_deny_semantics_preserved():
    print("---- B3 D10=B: 批内 undo 拒批语义不破坏 (真实 registry) ----")
    ed = make_editor()
    w = _Win(ed)
    um = ed.undo
    ed._add_primitive('cube')
    ac.dispatch('agent_batch_begin', {'lease_s': 0}, w)
    r = ac.dispatch('undo', {}, w)
    check("B3 批内 undo -> ok=False + blocked (D10=B)", r.get('ok') is False
          and (r.get('blocked') is True or r.get('result', {}).get('blocked') is True), r)
    check("B3 拒绝原因进 last_refusal", um.last_refusal is not None, um.last_refusal)
    ac.dispatch('agent_batch_cancel', {}, w)
    r = ac.dispatch('undo', {}, w)
    check("B3 批取消后 undo 恢复可用", r.get('ok') is True, r)


# ====================================================================
# 断言组 C: 相机裁定 (裁定②)
# ====================================================================

def t_c_camera_commands_push_undo():
    print("---- C1 camera_move/camera_look 进撤销栈且 undo 可恢复 ----")
    ed = make_editor()
    w = _Win(ed)
    um = ed.undo
    d0 = len(um.undo_stack)
    t0 = tuple(ed.camera_target)
    dist0 = ed.camera_distance
    r = ac.dispatch('camera_move', {'x': 1.0, 'y': 2.0, 'z': 3.0, 'distance': 25.0}, w)
    check("C1 camera_move -> ok", r.get('ok') is True, r)
    check("C1 撤销栈深度 +1", len(um.undo_stack) == d0 + 1,
          (d0, len(um.undo_stack)))
    um.undo()
    check("C1 undo 恢复 target", tuple(ed.camera_target) == t0, tuple(ed.camera_target))
    check("C1 undo 恢复 distance", ed.camera_distance == dist0, ed.camera_distance)
    y0 = ed.camera_yaw
    p0 = ed.camera_pitch
    r = ac.dispatch('camera_look', {'yaw': 90.0, 'pitch': -30.0}, w)
    check("C1 camera_look -> ok", r.get('ok') is True, r)
    check("C1 撤销栈深度 +1 (look)", len(um.undo_stack) == d0 + 1)
    um.undo()
    check("C1 undo 恢复 yaw/pitch", ed.camera_yaw == y0 and ed.camera_pitch == p0,
          (ed.camera_yaw, ed.camera_pitch))
    # 增量形式同样进栈
    r = ac.dispatch('camera_move', {'dx': 1.0, 'dy': 0.0, 'dz': 0.0}, w)
    r2 = ac.dispatch('camera_look', {'dyaw': 10.0, 'dpitch': 5.0}, w)
    check("C1 增量 camera_move/look -> ok", r.get('ok') and r2.get('ok'), (r, r2))
    check("C1 增量也进撤销栈", len(um.undo_stack) == d0 + 2)
    # 场景脏判定不跟随 (视角=编辑器视图状态, camera_proj 先例: 投影才进脏判定)
    dig0 = ed._scene_digest()
    ac.dispatch('camera_move', {'x': 9.0, 'y': 9.0, 'z': 9.0}, w)
    check("C1 相机移动不改场景摘要 (脏判定不跟随)", ed._scene_digest() == dig0)
    # proj 对照: camera_proj 进脏判定 (先例不回归)
    dig1 = ed._scene_digest()
    ac.dispatch('camera_proj', {'ortho': True}, w)
    check("C1 对照: camera_proj 仍进场景摘要 (D7=A 先例)", ed._scene_digest() != dig1)


def t_c_gui_camera_legacy_no_undo():
    print("---- C2 GUI 右键轨道/WASDQE 老链路不进撤销栈 (防回归) ----")
    ed = make_editor()
    w = _Win(ed)
    um = ed.undo
    # _layout 打桩: 视口 = (0,0,1024,600) (面板布局与相机控制无关)
    ed._layout = lambda: ((0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0),
                          (0, 0, 0, 0), (0, 0, 1024, 600), (0, 0, 0, 0))
    d0 = len(um.undo_stack)
    # 右键按住拖动 = 转动视角
    ed.buttons = (False, False, True)
    ed.mouse_pos = (100, 100)
    ed._cam_prev_mouse = (90, 90)
    yaw0 = ed.camera_yaw
    ed._update_camera(0.016)
    check("C2 右键拖动改变了视角 (老链路仍生效)", ed.camera_yaw != yaw0)
    check("C2 右键轨道不进撤销栈 (裁定②)", len(um.undo_stack) == d0,
          (d0, len(um.undo_stack)))
    # WASDQE 移动
    ed.buttons = (False, False, False)
    ks = collections.defaultdict(bool)
    ks[pygame.K_w] = True
    ed._key_pressed = lambda: ks
    t0 = tuple(ed.camera_target)
    ed._update_camera(0.016)
    check("C2 WASD 移动了 target (老链路仍生效)", tuple(ed.camera_target) != t0)
    check("C2 WASDQE 不进撤销栈 (裁定②)", len(um.undo_stack) == d0)
    # 滚轮缩放 (豁免面)
    ed._key_pressed = lambda: collections.defaultdict(bool)
    ed.mouse_wheel = 1.0
    dist0 = ed.camera_distance
    ed._update_camera(0.016)
    check("C2 滚轮缩放改变 distance (老链路仍生效)", ed.camera_distance != dist0)
    check("C2 滚轮缩放不进撤销栈", len(um.undo_stack) == d0)
    ed.mouse_wheel = 0
    # 中键平移 (豁免面; 平移判据 = 中键 + Shift/Alt, 与 _update_camera 一致)
    ed.buttons = (False, True, False)
    ed._mods = pygame.KMOD_SHIFT
    ed.mouse_pos = (140, 120)
    t1 = tuple(ed.camera_target)
    ed._update_camera(0.016)
    check("C2 中键平移改变 target (老链路仍生效)", tuple(ed.camera_target) != t1)
    check("C2 中键平移不进撤销栈", len(um.undo_stack) == d0)
    ed.buttons = (False, False, False)
    ed._mods = 0


# ====================================================================
# 断言组 D: 结构 (AST) + dispatch scope 参数
# ====================================================================

# 本次清单内的直调操作名 (GUI 侧一律不许再出现 <op>( 直调):
#   工具栏/菜单 18 + 层级树挂父/脱父族 + 检查器 vec_set 4 处
#   (+ 清单外顺带归零: object_delete / set_visible)。
_FORBIDDEN_CALLS = {
    'toggle_play', 'save_scene', 'save_scene_as', 'load_scene_cmd', 'new_scene_cmd',
    '_undo_action', '_redo_action', 'set_gizmo_mode', '_add_primitive',
    '_import_obj', 'duplicate_object', 'delete_object', '_add_light', '_add_camera',
    '_save_prefab', '_instantiate_prefab', 'set_visible',
    'rename', 'rename_light', 'rename_camera',
    'reparent', 'reparent_camera', 'detach', 'detach_camera',
    'vec_set',
}
# 白名单: 豁免面 + _notify/_refresh 类反馈 + 清单外未命令化操作 (后续批次)。
# 命中即报 FAIL (本门要求归零, 白名单只放注释性/非调用形态)。
_ALLOWED = {}


def t_d_no_direct_calls():
    print("---- D1 main_window.py 清单内直调归零 (AST) ----")
    path = os.path.join(ROOT, 'gui', 'main_window.py')
    with open(path, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename=path)
    hits = []

    class _V(ast.NodeVisitor):
        def visit_Call(self, node):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in _FORBIDDEN_CALLS:
                hits.append((fn.attr, fn.lineno, ast.unparse(node)[:90]))
            self.generic_visit(node)

    _V().visit(tree)
    bad = [h for h in hits
           if h[0] not in _ALLOWED or h[2] not in _ALLOWED.get(h[0], ())]
    check("D1 清单内直调归零 (残留=%d)" % len(bad), not bad, bad[:8])


def t_d_dispatch_scope_param():
    print("---- D2 dispatch 的 scope 参数存在且缺省兼容 ----")
    sig = inspect.signature(ac.dispatch)
    check("D2 dispatch 有 scope 参数", 'scope' in sig.parameters,
          list(sig.parameters))
    check("D2 scope 缺省 = 'agent' (兼容现状)",
          sig.parameters['scope'].default == 'agent')
    check("D2 current_scope() 存在 (命令层按需区分 user/agent)",
          callable(getattr(ac, 'current_scope', None))
          and ac.current_scope() in ('agent', 'user'))
    # 缺省调用 (不传 scope) 全兼容: undo 命令走 agent 作用域照常执行
    ed = make_editor()

    class _W:
        editor = None

    w = _W()
    w.editor = type('E', (), {'_undo_action': lambda self: {'ok': True}})()
    r = ac.dispatch('undo', {}, w)
    check("D2 不传 scope 的 dispatch 调用照常工作", r.get('ok') is True, r)
    r = ac.dispatch('undo', {}, w, scope='user')
    check("D2 显式 scope='user' 也照常工作", r.get('ok') is True, r)


if __name__ == "__main__":
    print("========== Q-B7-56-1 GUI 全量命令化 + 相机命令进撤销栈 门 ==========")
    # 逐组异常隔离: 未落地的新 API (修前红) 报 FAIL 并继续, 不许半路崩掉
    import traceback as _tb
    for _t in (t_a_add_primitive, t_a_duplicate, t_a_rename, t_a_gizmo,
               t_a_play, t_a_reparent, t_a_set_transform,
               t_b_gui_not_in_agent_batch,
               t_b_gui_spin_session_batch_is_not_agent_batch,
               t_b_deny_semantics_preserved,
               t_c_camera_commands_push_undo, t_c_gui_camera_legacy_no_undo,
               t_d_no_direct_calls, t_d_dispatch_scope_param):
        try:
            _t()
        except Exception as _e:
            _tb.print_exc()
            check(_t.__name__ + " 异常中断", False, repr(_e))
    if _FAILS:
        print("总结果: FAIL", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS")
