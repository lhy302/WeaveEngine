# -*- coding: utf-8 -*-

"""
test_events_once_reentry.py — EventBus.once 重入回归 (scan_09 P-07)

背景 (审计 docs/audit/scan_09_scripting.md P-07)
------------------------------------------------
契约: once() 订阅 name 事件, "触发一次后自动取消"。修复前 emit 对 once 的
移除被推迟到最外层 _apply_pending: once 回调里再次 emit 同名事件时, 内层
快照仍看到 alive=True 的同一个 handler, 于是递归重复触发 (审计实测 499 次;
回调若有扣血/发奖励等副作用, 等价重复结算)。根因不是"没移除", 而是"移除
发生在最外层派发结束之后", 对重入派发无效。

修法: once handler 在**调用前**就置 alive=False 消费 (异常也消费, Unity 语义),
内层/重入 emit 的快照虽仍含该 handler 但会被 alive 检查跳过; 移除动作仍走
延迟队列, 不破坏正在遍历的列表 (与 F4 的 clear/off 延迟语义一致)。

本文件断言:
  A: once 回调里重入 emit 同名事件 -> 只触发 1 次, 之后 listener_count=0。
  B: once + 普通订阅者: 重入时 once 不重复, 普通订阅者按事件语义各收一次。
  C: once 回调抛异常 -> 仍只触发一次 (异常不复活 once)。
  D: F4 兼容性: 派发中 clear() 仍延迟生效 (本轮 h2 照收, 计数完整)。
  E: once 与 clear 同帧: once 只触发一次, 本轮其余订阅者仍收到事件。

运行: python tests\test_events_once_reentry.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\

from loom_events import EventBus

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


# ====================================================================
# A: once 回调内重入 emit 同名事件
# ====================================================================
def t_once_reentry_same_event():
    bus = EventBus()
    calls = []

    def cb():
        calls.append(1)
        if len(calls) < 50:          # 旧实现会递归到解释器上限
            bus.emit('e')

    h = bus.once('e', cb)
    n = bus.emit('e')
    check("[A] once 重入只触发 1 次", len(calls) == 1, len(calls))
    check("[A] 外层 emit 计数 1", n == 1, n)
    check("[A] 本轮后监听表已清空",
          bus.listener_count('e') == 0 and not bus.has('e'),
          (bus.listener_count('e'), bus.has('e')))
    check("[A] handler 已消费 (alive=False)", h.alive is False)
    check("[A] 后续 emit 不再触发", bus.emit('e') == 0 and len(calls) == 1)


# ====================================================================
# B: once + 普通订阅者
# ====================================================================
def t_once_with_normal_listener():
    bus = EventBus()
    calls = []

    def once_cb():
        calls.append('once')
        bus.emit('e')                # 重入

    def normal():
        calls.append('normal')

    bus.once('e', once_cb)
    bus.on('e', normal)
    bus.emit('e')
    # 外层快照 [once, normal]: once 消费后重入 -> 内层只调 normal;
    # 外层继续 -> normal 再调一次。once 永远只有 1 次。
    check("[B] once 只触发 1 次", calls.count('once') == 1, calls)
    check("[B] 普通订阅者按每次 emit 各收一次",
          calls == ['once', 'normal', 'normal'], calls)
    check("[B] 普通订阅者仍在监听", bus.listener_count('e') == 1)


# ====================================================================
# C: once 回调抛异常 -> 仍只触发一次
# ====================================================================
def t_once_exception_consumed():
    bus = EventBus()
    calls = []

    def cb():
        calls.append(1)
        raise RuntimeError('boom')

    bus.once('e', cb)
    bus.emit('e')
    bus.emit('e')
    check("[C] once 异常后不再触发", len(calls) == 1, len(calls))
    check("[C] once 异常后监听表清空", bus.listener_count('e') == 0)


# ====================================================================
# D: F4 兼容性 — 派发中 clear() 仍延迟生效
# ====================================================================
def t_clear_deferral_preserved():
    bus = EventBus()
    seen = []

    def h1():
        seen.append('h1')
        bus.clear('e')

    def h2():
        seen.append('h2')

    bus.on('e', h1)
    bus.on('e', h2)
    n = bus.emit('e')
    check("[D] F4: 派发中 clear 不吞本轮剩余回调",
          seen == ['h1', 'h2'], seen)
    check("[D] F4: emit 计数完整 2", n == 2, n)
    check("[D] F4: 本轮结束后清空", bus.listener_count('e') == 0)


# ====================================================================
# E: once 与 clear 同帧
# ====================================================================
def t_once_with_clear_same_frame():
    bus = EventBus()
    seen = []

    def once_cb():
        seen.append('once')
        bus.clear('e')               # 延迟移除 (F4)
        bus.emit('e')                # 重入: once 不得复活

    bus.once('e', once_cb)
    bus.on('e', lambda: seen.append('h2'))
    bus.emit('e')
    check("[E] once 与 clear 同帧仍只触发 1 次",
          seen.count('once') == 1, seen)
    check("[E] 本轮 h2 仍收到事件", 'h2' in seen, seen)
    check("[E] 本轮结束后监听表清空", bus.listener_count('e') == 0)


if __name__ == "__main__":
    print("========== EventBus.once 重入 (scan_09 P-07) ==========")
    t_once_reentry_same_event()
    t_once_with_normal_listener()
    t_once_exception_consumed()
    t_clear_deferral_preserved()
    t_once_with_clear_same_frame()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
