# -*- coding: utf-8 -*-

"""test_agent_pacing.py — AgentService 逐条执行/节奏 测试 (2026-11-07 A, 全无头).

覆盖 (契约见 docs/audit/fix_agent_visual_*.md):
  ① LOOM_AGENT_PACE_MS=120 (缺省): 每次 drain 最多执行 1 条, 距上次不足 pace 直接返回;
  ② LOOM_AGENT_PACE_MS=0: 等价旧"一次排空" (批量脚本用);
  ③ GUI 钩子: _agent_progress/_agent_busy/_agent_after_command (缺失时静默跳过);
  ④ progress()/last_info() 契约 (队列空且无在途时归零).
用假 win 桩 + 测试专用命令, 不建 Qt/pygame 窗口.
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
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import agent_commands as ac

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


# ---- 测试专用命令: 只记录执行顺序, 不碰场景 ----
_CALLS = []


@ac.command('_pacing_tick', '测试专用: 记录一次执行')
def _cmd_pacing_tick(win, args):
    _CALLS.append(args.get('i'))
    return {'i': args.get('i')}


class FakeWin:
    """GUI 钩子桩: 记录调用序列; 无 editor (命令不碰场景)."""

    def __init__(self):
        self.events = []

    def _agent_progress(self, cmd, args, done, total):
        self.events.append(('progress', cmd, int(done), int(total)))

    def _agent_busy(self, active):
        self.events.append(('busy', bool(active)))

    def _agent_after_command(self):
        self.events.append(('after',))


class _NoHookWin:
    """完全没有任何钩子的 win: 契约要求 getattr 缺失即跳过 (不能崩 drain)."""


def _service(pace=None):
    """按环境变量构造 AgentService (构造时读 env, 与真机一致). 返回 (svc, win)."""
    old_p = os.environ.get('LOOM_AGENT_PACE_MS')
    try:
        if pace is None:
            os.environ.pop('LOOM_AGENT_PACE_MS', None)
        else:
            os.environ['LOOM_AGENT_PACE_MS'] = str(pace)
        win = FakeWin()
        svc = ac.AgentService(win)
    finally:
        for k, v in (('LOOM_AGENT_PACE_MS', old_p),):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return svc, win


def _enqueue(svc, i):
    ev = threading.Event()
    svc.queue.put(('_pacing_tick', {'i': i}, ev))
    return ev


# ============ ① 缺省 pace=120: 每次 drain 一条 + 间隔受控 ============
def t_pace_120():
    _CALLS.clear()
    svc, win = _service()
    check("缺省 pace_ms=120.0", abs(svc.pace_ms - 120.0) < 1e-9, svc.pace_ms)
    evs = [_enqueue(svc, i) for i in range(5)]

    t0 = time.perf_counter()
    n1 = svc.drain()
    check("第 1 拍立即执行 1 条", n1 == 1 and _CALLS == [0], (_CALLS, n1))
    n2 = svc.drain()
    check("距上次不足 pace -> 本拍不执行", n2 == 0 and _CALLS == [0], (_CALLS, n2))
    n3 = svc.drain()
    check("连续空转也不越过节奏", n3 == 0 and _CALLS == [0])

    for _i in range(4):
        time.sleep(0.13)
        svc.drain()
    elapsed = time.perf_counter() - t0
    check("5 条命令需要 5 次有效 drain", _CALLS == [0, 1, 2, 3, 4], _CALLS)
    check("总耗时≈4*120ms (间隔受控)", 0.45 <= elapsed <= 1.30, "%.3fs" % elapsed)
    check("每条命令的 ev 都已回填", all(ev.is_set() for ev in evs))

    # 进度钩子: done/total 单调, 末条 = (5,5)
    prog = [e for e in win.events if e[0] == 'progress']
    check("_agent_progress 每条一次", len(prog) == 5, len(prog))
    check("_agent_progress total=5 且 done 递增",
          [p[3] for p in prog] == [5] * 5 and [p[2] for p in prog] == [1, 2, 3, 4, 5],
          [(p[2], p[3]) for p in prog])
    check("_agent_after_command 每条一次",
          len([e for e in win.events if e[0] == 'after']) == 5)

    # busy: 空转非空 -> True; 空闲 0.8s 后 -> False
    busy = [e[1] for e in win.events if e[0] == 'busy']
    check("队列空转非空 -> _agent_busy(True)", busy and busy[0] is True, busy)
    time.sleep(0.85)
    svc.drain()
    busy = [e[1] for e in win.events if e[0] == 'busy']
    check("空闲 0.8s 后 -> _agent_busy(False)", busy and busy[-1] is False, busy)

    # progress(): 队列空且无在途 -> 归零; last_info 保留最后一条
    check("progress() 空闲归零", svc.progress() == (0, 0), svc.progress())
    cmd, ok, ms = svc.last_info()
    check("last_info() 记录最后一条", cmd == '_pacing_tick' and ok is True and ms >= 0.0,
          svc.last_info())


# ============ ② pace=0: 一次排空 (向后兼容批量脚本) ============
def t_pace_zero():
    _CALLS.clear()
    svc, _win = _service(pace=0)
    check("LOOM_AGENT_PACE_MS=0 -> pace_ms=0", svc.pace_ms == 0.0, svc.pace_ms)
    for i in range(5):
        _enqueue(svc, i)
    n = svc.drain()
    check("pace=0 一次 drain 排空 5 条", n == 5 and _CALLS == [0, 1, 2, 3, 4],
          (_CALLS, n))


# ============ ④ 钩子缺失: getattr 跳过, drain 不崩 ============
def t_no_hooks():
    _CALLS.clear()
    old_p = os.environ.get('LOOM_AGENT_PACE_MS')
    os.environ['LOOM_AGENT_PACE_MS'] = '0'
    try:
        svc = ac.AgentService(_NoHookWin())
    finally:
        if old_p is None:
            os.environ.pop('LOOM_AGENT_PACE_MS', None)
        else:
            os.environ['LOOM_AGENT_PACE_MS'] = old_p
    _enqueue(svc, 7)
    n = svc.drain()
    check("win 无任何钩子 -> drain 正常执行不崩", n == 1 and _CALLS == [7], (_CALLS, n))


if __name__ == "__main__":
    print("========== AgentService 节奏测试 ==========")
    t_pace_120()
    t_pace_zero()
    t_no_hooks()
    if _FAILS:
        print("总结果: FAIL", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS")
