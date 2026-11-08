# -*- coding: utf-8 -*-

"""test_beta3_batch4_undo_lease.py — 第 4 批（撤销/批次状态机 D10=A+B）回归测试.

人类裁决 D10 = A+B:
  A. 批次**租约 30s** 自动收口 (end_batch, 历史保留可撤销); 批内每条写命令续租;
     用户的编辑不得被吸进批里、也不得续租。
  B. 租约未到期时 undo/redo 拒绝并**出声**（"Agent 批次进行中（剩余 Xs），暂不可撤销"），
     不得静默弹掉批次之外的历史。

同时覆盖本轮修复（编号来自 docs/audit/scan_beta3_04_editor_agent_visual.md）:
  P-04-05 悬挂批锁死撤销            -> 租约收口后可撤销
  P-04-04 批中 undo 丢批外历史      -> 拒绝 + 历史不动
  P-04-06 批次单条失败丢整批        -> 逐条容错 + 记录保留 + last_error 出声
  P-04-03 cancel_batch 不清 redo    -> 与 _append 口径统一
  P-04-07 set_lod {bias} 绕过撤销   -> 走 commit_model; 报错时不再改状态
  P-04-09 agent_batch_begin 键名    -> 契约键 had_stale (+兼容别名)
  P-04-08 key_binding 白名单/透传   -> 未知动作拒绝; 失败不伪装成功
  P-04-10 view_focus 错误文案       -> 播放态 / 无包围盒 分开报
  P-03-11 camera_proj 直写 ed.ortho -> 走 set_camera_projection (进脏判定+撤销)

跑法: cd Loom && python tests/test_beta3_batch4_undo_lease.py
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
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# 用户层/游戏层配置全部指向临时目录（绝不写受跟踪文件）
_TMPCFG = tempfile.mkdtemp(prefix='loom_b4_cfg_')
os.environ['LOOM_USER_ROOT'] = os.path.join(_TMPCFG, 'user')
os.environ['LOOM_GAME_DIR'] = os.path.join(_TMPCFG, 'game')
os.makedirs(os.environ['LOOM_GAME_DIR'], exist_ok=True)

import engine as E
E.GLEngine._build_gpu = lambda self, m: None
import editor
import undo as U
import agent_commands as ac
import sceneio
from mesh import create_cube, create_sphere

_FAILS = []
ED = None          # 真 EditorApp 桩 (下面 _new_app 建)


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


class Rec(U.Command):
    """只记录调用顺序的探测命令."""

    def __init__(self, log, tag, boom_undo=False, boom_do=False):
        self.log = log
        self.tag = tag
        self.label = tag
        self.boom_undo = boom_undo
        self.boom_do = boom_do

    def do(self):
        self.log.append('do' + self.tag)
        if self.boom_do:
            raise RuntimeError('do boom ' + self.tag)

    def undo(self):
        self.log.append('undo' + self.tag)
        if self.boom_undo:
            raise RuntimeError('undo boom ' + self.tag)


def _new_app():
    app = editor.EditorApp.__new__(editor.EditorApp)
    app.models = []
    app.materials = []
    app.lights = []
    app.cameras = []
    app.active_camera = None
    app.current_model_index = 0
    app.undo = U.UndoManager()
    app.selected_index = -1
    app.selected_light_index = -1
    app.selected_camera_index = -1
    app.is_playing = False
    app.camera = E.Point3D(0, 0, -5)
    app.camera_target = (0, 0, 0)
    app.camera_distance = 10.0
    app.camera_yaw = 0.0
    app.camera_pitch = 0.0
    app.camera_roll = 0.0
    app.orbit_mode = True
    app._fov = math.radians(60.0)
    app.preview_camera = None
    app._preview_orbit = None
    app._cam_undo_start = {}
    app._insp_undo_start = {}
    app._light_undo_start = {}
    app.ortho = False
    app.ortho_size = sceneio.ORTHO_SIZE_DEFAULT
    app._focus_anim = None
    app._request_exit_play = False
    app._scene_cam = None
    app.gravity = -9.8
    app.scene_name = 'probe'
    app._scene_path = None
    return app


class FakeWin(object):
    def __init__(self, ed):
        self.editor = ed
        self.notices = []

    def _agent_batch_status(self, remaining):
        self.notices.append(remaining)


# ============================================================================
print("=== A. D10=A 批次租约: 30s 默认 + 到点自动收口 (历史保留) ===")
print("    修前: 悬挂批让 can_undo 恒 False、记录永久丢失 (P-04-05)")
um = U.UndoManager()
check("默认租约 30s", abs(um.BATCH_LEASE_S - 30.0) < 1e-9, um.BATCH_LEASE_S)
um.begin_batch('Agent 批次')
check("begin 后 batch_active 且有剩余秒数",
      um.batch_active and um.batch_remaining() is not None,
      um.batch_remaining())
eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []
eng.current_model_index = 0
log = []
um.push(Rec(log, '1'))
um.push(Rec(log, '2'))
check("租约内 can_undo 仍为 False (批记录不压栈)", um.can_undo is False)
rem = um.batch_remaining()
closed = um.tick_batch(now=time.monotonic() + rem + 0.01)     # 模拟断连 30s
check("到期 tick_batch -> 自动收口成一步", isinstance(closed, U.BatchCommand)
      and len(um.undo_stack) == 1, closed)
check("收口后 batch_active=False", not um.batch_active)
check("收口把历史变成可撤销 (P-04-05)", um.can_undo is True)
log.clear()
um.undo()
check("收口后 undo 一步逆序回退整批", log == ['undo2', 'undo1'], log)
um.redo()
check("redo 正序恢复整批", log[-2:] == ['do1', 'do2'], log)

print()
print("=== B. D10=B 租约内 undo/redo 拒绝并出声 (不弹栈) ===")
log = []
um2 = U.UndoManager()
um2.push(Rec(log, 'old'))               # 批外历史
um2.begin_batch('Agent 批次')
um2.push(Rec(log, 'in1'))
um2.push(Rec(log, 'in2'))
n_before = len(um2.undo_stack)
log.clear()
r = um2.undo()
check("租约内 undo 返回 None", r is None)
check("租约内 undo 不动撤销栈 (批外历史不丢)", len(um2.undo_stack) == n_before, n_before)
check("租约内 undo 不产生 redo 记录", len(um2.redo_stack) == 0)
check("租约内 undo 没有回退任何命令", log == [], log)
reason = um2.last_refusal or ''
check("拒绝原因是 '批次进行中（剩余 Xs）'",
      ('批次进行中' in reason) and ('剩余' in reason) and reason.endswith('暂不可撤销'),
      reason)
r2 = um2.redo()
check("租约内 redo 同样拒绝", r2 is None and um2.last_refusal)

print()
print("=== C. 续租只由批内写命令触发; 用户编辑不进批、不续租 ===")
um3 = U.UndoManager()
um3.begin_batch('Agent 批次', lease_s=10.0, absorb=False)
um3.agent_command_begin()
um3.push(Rec([], 'agent1'))
um3.agent_command_end()
check("Agent 命令被吸进批", um3.batch_size == 1, um3.batch_size)
deadline1 = um3._batch_deadline
check("批内写命令设置了租约截止时刻", deadline1 is not None, deadline1)
time.sleep(0.03)          # Windows time.monotonic 实际粒度 ~15.6ms, 太短会看不出续租
um3.agent_command_begin()
um3.push(Rec([], 'agent1b'))
um3.agent_command_end()
deadline2 = um3._batch_deadline
check("批内写命令续租 (截止时刻被推后)", deadline2 > deadline1, (deadline1, deadline2))
# 用户自己的编辑 (不在 Agent 命令作用域里): 不进批、不续租
um3.push(Rec([], 'user1'))
check("用户编辑不在批里 (批已收口, 新批为空)",
      um3.batch_size == 0, um3.batch_size)
check("用户编辑单独成为一步 (批记录已先收口成 [Agent 批次, user1])",
      len(um3.undo_stack) == 2, len(um3.undo_stack))
check("用户编辑不被标记成 Agent 命令",
      um3.in_agent_command is False, um3.in_agent_command)
_rem = um3.batch_remaining()
check("重开的批次自带完整租约 (用户编辑没有把它'耗掉')",
      _rem is not None and _rem > um3.batch_lease_s - 1.0,
      (_rem, um3.batch_lease_s))
um3.agent_command_begin()
um3.push(Rec([], 'agent2'))
um3.agent_command_end()
check("之后 Agent 命令仍归新批 (不混进用户那步)", um3.batch_size == 1, um3.batch_size)
labels = [getattr(c, 'label', None) for c in um3.undo_stack]
check("撤销栈顺序 = [批(agent1), user1]", labels[0] == 'Agent 批次' and labels[1] == 'user1',
      labels)

print()
print("=== D. P-04-04: 批中 undo 绝不弹掉批外更早命令 ===")
# 修前: undo() 会 pop 批外 'old' 并紧接着被 end_batch 清掉 redo -> 永久丢失
log = []
um4 = U.UndoManager()
um4.push(Rec(log, 'old'))
um4.begin_batch('Agent')
um4.push(Rec(log, 'in'))
log.clear()
um4.undo()
check("批中 undo 未回退任何命令", log == [], log)
check("批外 'old' 仍在撤销栈", len(um4.undo_stack) == 1 and um4.undo_stack[0].label == 'old',
      [c.label for c in um4.undo_stack])
rem = um4.batch_remaining()
um4.tick_batch(now=time.monotonic() + rem + 0.01)
check("租约到期后栈 = [old, 批]",
      [getattr(c, 'label', None) for c in um4.undo_stack] == ['old', 'Agent'],
      [getattr(c, 'label', None) for c in um4.undo_stack])
log.clear()
um4.undo()
check("到期后第一步撤销的是批 (时间序最近)", log == ['undoin'], log)

print()
print("=== E. P-04-06: 批次单条失败不丢整批, 且失败出声 ===")
log = []
um5 = U.UndoManager()
um5.begin_batch('B')
um5.push(Rec(log, '1', boom_undo=True))
um5.push(Rec(log, '2', boom_undo=False))
um5.push(Rec(log, '3', boom_undo=False))
um5.end_batch()
n_undo5 = len(um5.undo_stack)
log.clear()
r = um5.undo()
check("批次部分失败 -> undo 返回 None", r is None)
check("失败不弹栈 (记录保留可重试)", len(um5.undo_stack) == n_undo5, len(um5.undo_stack))
check("失败不写 redo (状态不确定不伪装成功)", len(um5.redo_stack) == 0)
err = um5.last_error or ''
check("失败出声 (last_error 含批次标签与失败数)",
      ('撤销失败' in err) and ('B' in err), err)
check("逐条容错: 另两条也被回退 (不再半途中断)", log == ['undo3', 'undo2', 'undo1'], log)
batch5 = um5.undo_stack[0]
check("BatchCommand 记录了失败清单", len(getattr(batch5, 'failed', [])) == 1,
      [(getattr(c, 'label', c), str(e)) for c, e in batch5.failed])

print()
print("=== F. P-04-03: cancel_batch 与 _append 口径统一 (清 redo) ===")
um6 = U.UndoManager()
um6.push(Rec([], 'a'))
um6.undo()
check("撤销后 redo 有 1 条", len(um6.redo_stack) == 1)
um6.begin_batch('B')
um6.push(Rec([], 'b'))
um6.cancel_batch()
check("cancel 后 redo 被清空 (修前为 1 -> Ctrl+Y 会把旧命令重放到批改动上)",
      len(um6.redo_stack) == 0, len(um6.redo_stack))

print()
print("=== G. P-04-07: set_lod {bias} 走 commit_model + 报错不改状态 ===")
ED = _new_app()
win = FakeWin(ED)
cube = ED.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                    name='立方体')
sph = ED.add_model(create_sphere(1.0), E.Point3D(2, 0, 0), E.Point3D(0, 0, 0),
                   name='球')
ac.dispatch('object_select', {'name': '立方体'}, win)
bias0 = cube.renderer.lod_bias
r = ac.dispatch('set_lod', {'bias': 2.5}, win)
check("cube + bias -> 拒绝", (not r.get('ok')) and ('sphere' in (r.get('error') or '')),
      r.get('error'))
check("报错时 lod_bias 未被改动 (修前会先写再报错)",
      abs(cube.renderer.lod_bias - bias0) < 1e-9, (cube.renderer.lod_bias, bias0))
n0 = len(ED.undo.undo_stack)
r = ac.dispatch('set_lod', {'name': '球', 'bias': 2.5}, win)
check("sphere + bias -> 成功", r.get('ok') and abs(float(r['result']['bias']) - 2.5) < 1e-9,
      r.get('result'))
check("bias 改动进撤销栈 (修前 undo_depth 不变)", len(ED.undo.undo_stack) == n0 + 1,
      (len(ED.undo.undo_stack), n0))
ED.undo.undo()
check("undo 后 bias 回到 1.0", abs(sph.renderer.lod_bias - 1.0) < 1e-9,
      sph.renderer.lod_bias)
check("undo 后 LOD 级别也回退", sph.renderer.lod_screen_levels is None,
      sph.renderer.lod_screen_levels)

print()
print("=== H. P-04-09: agent_batch_begin 返回契约键 had_stale (+兼容别名) ===")
ED2 = _new_app()
win2 = FakeWin(ED2)
r1 = ac.dispatch('agent_batch_begin', {'label': 'L1'}, win2)
res1 = r1.get('result') or {}
check("首次 begin -> had_stale=False", res1.get('had_stale') is False, res1)
check("兼容别名 cancelled_stale 与契约键一致",
      res1.get('cancelled_stale') == res1.get('had_stale'), res1)
check("返回真实租约秒数", abs(float(res1.get('lease_s') or 0) - 30.0) < 1e-6, res1)
check("begin 把批次状态推给 GUI (剩余秒数)", win2.notices and win2.notices[-1] is not None,
      win2.notices)
r2 = ac.dispatch('agent_batch_begin', {'label': 'L2'}, win2)
res2 = r2.get('result') or {}
check("未 end 又 begin (租约内) -> had_stale=True", res2.get('had_stale') is True, res2)
# 已过租约的悬挂批: 下一次 begin 应"收口"而不是丢弃
ED2.undo.begin_batch('过期批', lease_s=0.002)
ED2.undo.push(Rec([], 'x'))
time.sleep(0.05)          # 大于 Windows time.monotonic 粒度 (~15.6ms)
r3 = ac.dispatch('agent_batch_begin', {'label': 'L3'}, win2)
res3 = r3.get('result') or {}
check("到期悬挂批 -> closed_stale 有标签 (收口, 不丢弃)",
      res3.get('closed_stale') == '过期批', res3)
check("到期批已进撤销栈 (历史保留)", len(ED2.undo.undo_stack) == 1,
      len(ED2.undo.undo_stack))
ac.dispatch('agent_batch_end', {}, win2)
check("end 后 GUI 收到 None (清除批次提示)", win2.notices[-1] is None, win2.notices[-3:])

print()
print("=== I. P-04-08: key_binding 动作白名单 + 真实结果透传 ===")


class FakeEd(object):
    def __init__(self, fail=False):
        self.actions = {'解锁鼠标': ['Tab'], '跳跃': ['space']}
        self.fail = fail

    def get_action_bindings(self):
        return {a: list(k) for a, k in self.actions.items()}

    def set_action_binding(self, action, keys):
        if self.fail:
            return {'ok': False, 'action': action, 'keys': keys,
                    'saved': False, 'error': '磁盘写失败 (模拟)'}
        self.actions[action] = list(keys)
        return {'ok': True, 'action': action, 'keys': list(keys),
                'saved': True, 'path': os.path.join(_TMPCFG, 'game', '游戏设置.json')}


w = FakeWin(FakeEd())
r = ac.dispatch('key_binding', {'action': '跳跃', 'keys': 'j,k'}, w)
check("合法动作 -> ok + saved=True 透传", r.get('ok')
      and (r.get('result') or {}).get('saved') is True, r.get('result'))
r = ac.dispatch('key_binding', {'action': '不存在的动作', 'keys': 'j'}, w)
check("未知动作 -> 拒绝 (修前会静默创建幽灵动作并落盘)",
      (not r.get('ok')) and ('未知动作' in (r.get('error') or '')), r.get('error'))
check("未知动作 -> 给出可用动作列表",
      '解锁鼠标' in (r.get('result') or {}).get('available', []), r.get('result'))
check("未知动作未被写进 actions", '不存在的动作' not in w.editor.actions)
w2 = FakeWin(FakeEd(fail=True))
r = ac.dispatch('key_binding', {'action': '跳跃', 'keys': 'j'}, w2)
check("引擎报 saved=False -> 命令层 ok=False (不伪装成功)",
      (not r.get('ok')) and ('磁盘写失败' in (r.get('error') or '')), r.get('error'))

print()
print("=== J. P-04-10: view_focus 播放态 / 无包围盒 分开报错 ===")
ED3 = _new_app()
win3 = FakeWin(ED3)
obj = ED3.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                    name='盒')
r = ac.dispatch('view_focus', {'index': 0, 'smooth': False}, win3)
check("编辑态聚焦 -> ok", r.get('ok'), r.get('error'))
ED3.is_playing = True
r = ac.dispatch('view_focus', {'index': 0}, win3)
msg_play = r.get('error') or ''
check("播放态 -> '播放态不能移动编辑器相机'", (not r.get('ok')) and '播放态' in msg_play,
      msg_play)
ED3.is_playing = False
ED3._focus_aabb = lambda index: None          # 模拟"取不到包围盒"
r = ac.dispatch('view_focus', {'index': 0}, win3)
msg_aabb = r.get('error') or ''
check("取不到包围盒 -> 不再说'播放态' (修前同一句话)",
      (not r.get('ok')) and ('播放态' not in msg_aabb) and ('包围盒' in msg_aabb),
      msg_aabb)
check("两种失败文案不同", msg_play != msg_aabb, msg_aabb)

print()
print("=== K. P-03-11: camera_proj 走 set_camera_projection (进脏判定 + 进撤销) ===")
ED4 = _new_app()
win4 = FakeWin(ED4)
ED4.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='x')
ED4.mark_saved()
check("初始 dirty=False", ED4.scene_is_dirty() is False)
n0 = len(ED4.undo.undo_stack)
r = ac.dispatch('camera_proj', {'ortho': True, 'size': 9.5}, win4)
res = r.get('result') or {}
check("camera_proj -> ortho/size 回读", res.get('ortho') is True
      and abs(float(res.get('size') or 0) - 9.5) < 1e-9, res)
check("走 set_camera_projection -> 进撤销栈", len(ED4.undo.undo_stack) == n0 + 1,
      (len(ED4.undo.undo_stack), n0))
check("投影改动进脏判定", ED4.scene_is_dirty() is True)
ED4.undo.undo()
check("undo 后回到透视/默认 size", ED4.ortho is False
      and abs(ED4.ortho_size - sceneio.ORTHO_SIZE_DEFAULT) < 1e-9,
      (ED4.ortho, ED4.ortho_size))

print()
print("=== L. 状态栏文案: Agent 批次进行中（剩余 Xs） ===")
import ui.loom_gui as LG


class _SB(object):
    def __init__(self):
        self.msgs = []

    def showMessage(self, m, *a):
        self.msgs.append(m)

    def clearMessage(self):
        self.msgs.append('')

    def setStyleSheet(self, s):
        pass


class _GuiStub(object):
    def __init__(self):
        self._sb = _SB()
        self._agent_status_active = False
        self._agent_batch_active = False
        self._agent_batch_remaining = None
        self._agent_busy_active = False

    def statusBar(self):
        return self._sb

    def _refresh_status(self):
        self._sb.msgs.append('(refresh)')


g = _GuiStub()
LG.LoomGUI._agent_batch_status(g, 27)
check("批次提示文案含剩余秒数",
      'Agent 批次进行中（剩余 27s）' in g._sb.msgs[-1], g._sb.msgs[-1])
check("批次期间状态栏被占用 (300ms 轮询不覆盖)", g._agent_status_active is True)
g._agent_idle_token = 0
n_msgs = len(g._sb.msgs)
LG.LoomGUI._agent_idle(g, 0)
check("1.5s 空闲不得清掉批次提示 (D10 可视化)",
      len(g._sb.msgs) == n_msgs
      and g._sb.msgs[-1] == 'Agent 批次进行中（剩余 27s）', g._sb.msgs[-2:])
check("1.5s 空闲不得释放批次占用的状态栏", g._agent_status_active is True)
LG.LoomGUI._agent_batch_status(g, None)
check("批次结束 -> 清提示并回落默认文本",
      '' in g._sb.msgs and '(refresh)' in g._sb.msgs[-1], g._sb.msgs[-3:])
check("批次结束 -> 释放状态栏占用", g._agent_status_active is False)

print()
print("=== M. AgentService 每拍维护租约并把剩余秒数推给 GUI (集成) ===")
ED5 = _new_app()
ED5.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='y')
win5 = FakeWin(ED5)
svc = ac.AgentService(win5)
svc._tick_batch()
check("无批次 -> 推 None (不显示批次条)", win5.notices and win5.notices[-1] is None,
      win5.notices)
ac.dispatch('agent_batch_begin', {'label': '集成批'}, win5)
svc._tick_batch()
check("批次进行中 -> 推到 GUI 的剩余秒数为 30",
      win5.notices[-1] == 30, win5.notices[-3:])
check("同一秒内不重复刷状态栏 (节流)",
      (svc._tick_batch() or True) and win5.notices[-1] == 30, win5.notices[-3:])
ac.dispatch('agent_batch_begin', {'label': 'x'}, win5)   # 不 end 再造一条命令进批
ac.dispatch('object_add', {'type': 'cube'}, win5)
n_undo_before_expiry = len(ED5.undo.undo_stack)
ED5.undo._batch_deadline = time.monotonic() - 0.001      # 模拟"断连 30s"
svc._tick_batch()
check("租约到期 -> AgentService 自动收口 (撤销栈 +1)",
      len(ED5.undo.undo_stack) == n_undo_before_expiry + 1,
      (len(ED5.undo.undo_stack), n_undo_before_expiry))
check("收口后 GUI 收到 None (清批次条)", win5.notices[-1] is None, win5.notices[-3:])
check("收口后可撤销 (P-04-05 断连恢复)", ED5.undo.can_undo is True)

print()
if _FAILS:
    print("总结果: FAIL", _FAILS)
    sys.exit(1)
print("总结果: ALL PASS")
