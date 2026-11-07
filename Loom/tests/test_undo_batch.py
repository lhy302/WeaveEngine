# -*- coding: utf-8 -*-

"""test_undo_batch.py — 批次撤销 (UndoManager.begin/end/cancel_batch) + EAI 命令
agent_batch_begin/end/cancel 测试 (2026-11-07 D, 全无头).

覆盖:
  · 批内 push 正常 do(), 但不单独压栈; end_batch 合成一个 BatchCommand (不再重复执行);
  · undo 一步逆序全部回退, redo 一步正序全部恢复;
  · cancel_batch 丢弃批次 (已执行的 do() 不回滚, 也无可撤销记录);
  · 悬挂批次 (未 end 又 begin) 自动 cancel 并报告;
  · EAI 命令三件套 + 无批次时 end 的拒绝语义.
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


import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import engine as E
from mesh import create_cube
import undo as U
import agent_commands as ac

# 不开窗口的引擎桩: 替换 _build_gpu 为 no-op (同 test_undo.py)
E.GLEngine._build_gpu = lambda self, m: None
eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []
eng.current_model_index = 0

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _names():
    return [m.name for m in eng.models]


def _add(um, name, pos):
    return um.push(U.AddObjectCommand(
        "加" + name, eng, create_cube(1.5), E.Point3D(*pos),
        E.Point3D(0, 0, 0), name=name)).model


class _Rec(U.Command):
    """只记录调用顺序的探针命令 (验证 undo 逆序 / redo 正序)."""

    def __init__(self, log, tag):
        self.log = log
        self.tag = tag
        self.label = tag

    def do(self):
        self.log.append('do' + self.tag)

    def undo(self):
        self.log.append('undo' + self.tag)


# ============ ① 3 条写命令进批 -> undo 一步全退 / redo 一步全恢复 ============
def t_batch_add_undo_redo():
    eng.models = []
    um = U.UndoManager()
    um.begin_batch('Agent 批次')
    check("begin_batch 后 batch_active", um.batch_active is True)
    _add(um, 'A', (0, 0, 0))
    _add(um, 'B', (2, 0, 0))
    _add(um, 'C', (4, 0, 0))
    check("批内 push 仍执行 do()", _names() == ['A', 'B', 'C'], _names())
    check("批内不单独压撤销栈", um.can_undo is False and um.batch_active is True)
    batch = um.end_batch()
    check("end_batch 合成一个 BatchCommand", isinstance(batch, U.BatchCommand)
          and len(um.undo_stack) == 1, type(batch).__name__)
    check("end_batch 不重复执行", _names() == ['A', 'B', 'C'], _names())
    check("end_batch 后 batch_active 复位", um.batch_active is False)
    um.undo()
    check("undo 一步 -> 3 条全部回退", eng.models == [], _names())
    check("undo 后批次进 redo 栈", um.can_redo is True and um.can_undo is False)
    um.redo()
    check("redo 一步 -> 3 条全部恢复", _names() == ['A', 'B', 'C'], _names())
    check("redo 后批次回 undo 栈", um.can_undo is True and um.can_redo is False)


# ============ ② undo 逆序 / redo 正序 ============
def t_batch_order():
    um = U.UndoManager()
    log = []
    um.begin_batch('顺序')
    for tag in ('1', '2', '3'):
        um.push(_Rec(log, tag))
    check("批内按提交顺序 do()", log == ['do1', 'do2', 'do3'], log)
    um.end_batch()
    log.clear()
    um.undo()
    check("undo 逆序 (3,2,1)", log == ['undo3', 'undo2', 'undo1'], log)
    log.clear()
    um.redo()
    check("redo 正序 (1,2,3)", log == ['do1', 'do2', 'do3'], log)


# ============ ③ cancel_batch: 丢弃批次, 不回滚已执行 ============
def t_cancel_batch():
    eng.models = []
    um = U.UndoManager()
    um.begin_batch()
    _add(um, 'X', (0, 0, 0))
    um.cancel_batch()
    check("cancel_batch 后 batch_active=False", um.batch_active is False)
    check("cancel 不压撤销栈", um.can_undo is False and um.can_redo is False)
    check("cancel 不回滚已执行的 do()", _names() == ['X'], _names())


# ============ ④ 悬挂批次: 下一次 begin 自动 cancel 并报告 ============
def t_stale_begin():
    eng.models = []
    um = U.UndoManager()
    um.begin_batch()
    _add(um, 'Y', (0, 0, 0))
    had_stale = um.begin_batch('新批')
    check("未 end 又 begin -> 报告并自动 cancel 旧批", had_stale is True)
    check("新批次是空的", um.batch_active is True and um.batch_size == 0)
    _add(um, 'Z', (0, 0, 0))
    um.end_batch()
    check("新批次只含 Z 一条", len(um.undo_stack) == 1
          and len(um.undo_stack[0].cmds) == 1)
    um.undo()
    check("undo 只回退新批次 (Y 仍是丢弃态)", _names() == ['Y'], _names())


# ============ ⑤ EAI 命令: agent_batch_begin/end/cancel ============
class _FakeEd:
    def __init__(self, um):
        self.undo = um


class _FakeWin:
    def __init__(self, ed=None):
        self.editor = ed


def t_eai_commands():
    eng.models = []
    um = U.UndoManager()
    win = _FakeWin(_FakeEd(um))
    r = ac.dispatch('agent_batch_begin', {'label': 'Agent 批'}, win)
    check("agent_batch_begin -> ok", r['ok'] and r['result']['batch'] is True, r)
    log = []
    um.push(_Rec(log, 'a'))
    um.push(_Rec(log, 'b'))
    r = ac.dispatch('agent_batch_end', {}, win)
    check("agent_batch_end -> 合成 1 步", r['ok'] and r['result']['commands'] == 2
          and len(um.undo_stack) == 1, r)
    check("end 不重复执行", log == ['doa', 'dob'], log)
    um.undo()
    check("EAI 批次 undo 一步全退", log[-2:] == ['undob', 'undoa'], log)

    n_undo, n_redo = len(um.undo_stack), len(um.redo_stack)
    r = ac.dispatch('agent_batch_begin', {}, win)
    um.push(_Rec(log, 'c'))
    r = ac.dispatch('agent_batch_cancel', {}, win)
    check("agent_batch_cancel -> ok 且丢弃", r['ok'] and r['result']['cancelled'] == 1, r)
    check("cancel 后撤销/重做栈长度不变",
          len(um.undo_stack) == n_undo and len(um.redo_stack) == n_redo,
          (len(um.undo_stack), n_undo, len(um.redo_stack), n_redo))

    r = ac.dispatch('agent_batch_end', {}, win)
    check("无批次时 agent_batch_end -> 拒绝", not r['ok']
          and '没有进行中的批次' in r['error'], r)

    win2 = _FakeWin(None)
    r = ac.dispatch('agent_batch_begin', {}, win2)
    check("editor 缺失时 agent_batch_begin -> 拒绝", not r['ok'] and 'undo' in r['error'], r)

    # 悬挂批次: EAI begin 自动 cancel 并告警 (log 环里能查到)
    win3 = _FakeWin(_FakeEd(U.UndoManager()))
    ac.dispatch('agent_batch_begin', {}, win3)
    r = ac.dispatch('agent_batch_begin', {}, win3)
    check("EAI begin 对悬挂批次自动 cancel 并标注",
          r['ok'] and r['result'].get('cancelled_stale') is True, r)


if __name__ == "__main__":
    print("========== 批次撤销 (Batch Undo) 测试 ==========")
    t_batch_add_undo_redo()
    t_batch_order()
    t_cancel_batch()
    t_stale_begin()
    t_eai_commands()
    if _FAILS:
        print("总结果: FAIL", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS")
