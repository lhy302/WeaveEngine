# -*- coding: utf-8 -*-

"""
test_events_clear_defer.py — EventBus.clear() 派发期延迟生效回归 (scan_09 P-06)

背景 (审计 docs/audit/scan_09_scripting.md P-06)
------------------------------------------------
loom_events.py 模块 docstring 与 off() 的注释都声明: "emit() 派发期间的订阅/
取消进入延迟队列, 派发结束后统一应用"、"派发期 off 当前轮仍会调用, 下一轮起
不再调用"。修复前 clear() 是唯一绕过延迟队列的取消旁路 —— 派发中的回调一旦
调用 bus.clear()/clear(name), 就直接改 _handlers 并把 alive 置 False, 于是
**本轮快照里尚未执行的回调被静默丢掉**, emit 的返回计数也少 1 (调用方无法区分
"没人订阅"与"被 clear 吃掉")。

本文件断言:
  A: 派发中 clear('name') -> 本轮其余订阅者仍收到事件, 计数完整, 本轮结束后清空。
  B: 派发中 clear() 全体 -> 同上。
  C: 非派发期 clear 仍然是立即生效 (原语义不回归)。
  D: 派发中 clear 后本轮新加的订阅: 走延迟添加队列, 本轮不触发, 下一轮生效
     (文档 20 行的延迟语义)。
  E: 与 off(handler) 的对照: 两者当前轮行为一致 (都收到完整快照)。

运行: python tests\test_events_clear_defer.py   (无头, 无 GPU)
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
# A: 派发中 clear('name')
# ====================================================================
def t_clear_named_during_dispatch():
    bus = EventBus()
    seen = []

    def h1():
        seen.append('h1')
        bus.clear('e')          # 派发中清空本事件

    def h2():
        seen.append('h2')

    bus.on('e', h1)
    bus.on('e', h2)
    n = bus.emit('e')
    check("[A] 派发中 clear('e') 不吞本轮回调", seen == ['h1', 'h2'], seen)
    check("[A] emit 返回完整计数 2", n == 2, n)
    check("[A] 本轮结束后订阅清空 (listener_count=0, has=False)",
          bus.listener_count('e') == 0 and not bus.has('e'),
          (bus.listener_count('e'), bus.has('e')))
    # 下一轮不再触发
    check("[A] 下一轮不再触发", bus.emit('e') == 0)


# ====================================================================
# B: 派发中 clear() 全体
# ====================================================================
def t_clear_all_during_dispatch():
    bus = EventBus()
    seen = []

    def g1():
        seen.append('g1')
        bus.clear()

    def g2():
        seen.append('g2')

    bus.on('x', g1)
    bus.on('x', g2)
    bus.on('other', lambda: seen.append('other'))
    n = bus.emit('x')
    check("[B] 派发中 clear() 不吞本轮回调", seen == ['g1', 'g2'], seen)
    check("[B] emit 返回完整计数 2", n == 2, n)
    check("[B] 本轮结束后全部事件清空",
          not bus.has('x') and not bus.has('other')
          and bus.listener_count('x') == 0)


# ====================================================================
# C: 非派发期 clear 仍立即生效 (原语义不回归)
# ====================================================================
def t_clear_immediate_outside_dispatch():
    bus = EventBus()
    bus.on('k', lambda: None)
    bus.on('k', lambda: None)
    bus.on('k2', lambda: None)
    bus.clear('k')
    check("[C] 非派发期 clear('k') 立即生效",
          bus.listener_count('k') == 0 and bus.has('k2'))
    bus.clear()
    check("[C] 非派发期 clear() 立即清空全部", not bus.has('k2'))


# ====================================================================
# D: 派发中 clear 之后新增的订阅 (延迟添加队列)
# ====================================================================
def t_add_after_clear():
    bus = EventBus()
    order = []

    def a():
        order.append('a')
        bus.clear('ev')                 # 清掉本轮已存在的
        bus.on('ev', lambda: order.append('late'))   # 之后新增 -> 延迟添加

    bus.on('ev', a)
    bus.on('ev', lambda: order.append('b'))
    n1 = bus.emit('ev')
    check("[D] 本轮: 已存在的 b 仍被调用, late 不触发",
          order == ['a', 'b'], order)
    check("[D] 本轮 emit 计数 2", n1 == 2, n1)
    check("[D] clear 只清'调用那一刻已存在'的订阅: late 保留",
          bus.listener_count('ev') == 1, bus.listener_count('ev'))
    order.clear()
    bus.emit('ev')
    check("[D] 下一轮: late 生效", order == ['late'], order)


# ====================================================================
# E: 与 off(handler) 语义对照
# ====================================================================
def t_off_control():
    bus = EventBus()
    seen = []
    h2 = None

    def c1():
        seen.append('c1')
        bus.off(h2)

    def c2():
        seen.append('c2')

    h2 = bus.on('e', c2)
    bus.on('e', c1)
    bus.emit('e')
    check("[E] off(handler) 对照: 当前轮仍收到完整快照",
          seen == ['c2', 'c1'], seen)
    check("[E] off(handler) 对照: 下一轮已移除",
          bus.listener_count('e') == 1)


if __name__ == "__main__":
    print("========== EventBus.clear() 派发期延迟生效 (scan_09 P-06) ==========")
    t_clear_named_during_dispatch()
    t_clear_all_during_dispatch()
    t_clear_immediate_outside_dispatch()
    t_add_after_clear()
    t_off_control()
    print()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
