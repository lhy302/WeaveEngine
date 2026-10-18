# -*- coding: utf-8 -*-
"""smoke_coroutine.py — 协程冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from scripts import Script


class _TestScript(Script):
    script_id = 'test_coro'
    name = '测试协程'


def drive(s, dt=1.0, frames=10):
    """手动推进 N 帧（每帧 dt=1.0），返回每帧协程数"""
    counts = []
    for _ in range(frames):
        s._drive_coroutines(dt)
        counts.append(s.coroutine_count())
    return counts


# 1) 基本 wait(秒)
s = _TestScript()
log = []

def co1():
    log.append('start')
    yield s.wait(2.0)    # 等 2 帧
    log.append('after wait 2s')
    yield s.wait(1.0)    # 等 1 帧
    log.append('after wait 1s')

s.start_coroutine(co1())
# 第 1 帧：send 启动，进入 wait(2.0)
counts = drive(s, dt=1.0, frames=5)
assert log == ['start', 'after wait 2s', 'after wait 1s'], log
# 时序跟踪（wait(N) 语义是"从现在起等 N 秒"）：
#   帧1: send 启动，跑到 yield wait(2.0)，wait_t=2.0，count=1
#   帧2: wait_t=2.0-1.0=1.0>0 不 resume，count=1
#   帧3: wait_t=1.0-1.0=0.0<=0 resume，打印 after wait 2s，
#        再 yield wait(1.0)，wait_t=1.0，count=1
#   帧4: wait_t=0.0 resume，打印 after wait 1s，StopIteration 移除，count=0
#   帧5: 无变化，count=0
assert counts == [1, 1, 1, 0, 0], counts
print('1) wait(秒) OK:', log)

# 2) wait_until
s = _TestScript()
log = []
state = {'flag': False}

def co2():
    log.append('start')
    yield s.wait_until(lambda: state['flag'])
    log.append('flag became True')

s.start_coroutine(co2())
drive(s, frames=1)   # 启动，进入 wait_until，flag=False
assert log == ['start']
assert s.coroutine_count() == 1
state['flag'] = True
drive(s, frames=1)   # 谓词变 True -> 恢复
assert log == ['start', 'flag became True']
assert s.coroutine_count() == 0
print('2) wait_until OK:', log)

# 3) wait_while
s = _TestScript()
log = []
state = {'flag': True}

def co3():
    log.append('start')
    yield s.wait_while(lambda: state['flag'])
    log.append('flag became False')

s.start_coroutine(co3())
drive(s, frames=1)   # flag=True 继续等
assert log == ['start']
assert s.coroutine_count() == 1
state['flag'] = False
drive(s, frames=1)   # flag=False -> 继续
assert log == ['start', 'flag became False']
print('3) wait_while OK:', log)

# 4) wait_frame（yield None）
s = _TestScript()
frames_passed = []

def co4():
    for i in range(3):
        frames_passed.append(i)
        yield s.wait_frame()

s.start_coroutine(co4())
drive(s, frames=4)
assert frames_passed == [0, 1, 2], frames_passed
assert s.coroutine_count() == 0
print('4) wait_frame OK:', frames_passed)

# 5) 多个协程并发
s = _TestScript()
log = []

def ca():
    log.append('a-start')
    yield s.wait(1.0)
    log.append('a-done')

def cb():
    log.append('b-start')
    yield s.wait(2.0)
    log.append('b-done')

s.start_coroutine(ca())
s.start_coroutine(cb())
assert s.coroutine_count() == 2
# 逐帧推进
drive(s, frames=1)   # 启动两个，a 等 1 帧，b 等 2 帧
drive(s, frames=1)   # a 恢复打印 done
drive(s, frames=1)   # b 恢复打印 done
assert log == ['a-start', 'b-start', 'a-done', 'b-done'], log
assert s.coroutine_count() == 0
print('5) 多协程并发 OK:', log)

# 6) stop_coroutine 停止指定协程
s = _TestScript()
log = []

def ca():
    log.append('a')
    yield s.wait(10.0)
    log.append('a-should-not-print')

def cb():
    log.append('b')
    yield s.wait(1.0)
    log.append('b-done')

gen_a = s.start_coroutine(ca())
s.start_coroutine(cb())
drive(s, frames=1)   # 启动两者
# 停止 a
ok = s.stop_coroutine(gen_a)
assert ok is True
# 推进剩余帧 -> 只有 b 恢复
drive(s, frames=2)
assert log == ['a', 'b', 'b-done'], log
assert s.coroutine_count() == 0
print('6) stop_coroutine OK:', log)

# 7) stop_all_coroutines
s = _TestScript()
log = []

def co7():
    log.append('run')
    yield s.wait(100.0)
    log.append('should-not-print')

s.start_coroutine(co7())
s.start_coroutine(co7())
drive(s, frames=1)
assert s.coroutine_count() == 2
s.stop_all_coroutines()
assert s.coroutine_count() == 0
drive(s, frames=3)
assert log == ['run', 'run']   # 两次 run，之后不该有输出
print('7) stop_all_coroutines OK:', log)

# 8) 协程异常不影响其他协程/update 主流程
s = _TestScript()
log = []

def crashy():
    log.append('crashy-start')
    yield s.wait(0.0)
    raise RuntimeError('故意崩溃')
    yield

def safe():
    log.append('safe-start')
    yield s.wait(1.0)
    log.append('safe-done')

s.start_coroutine(crashy())
s.start_coroutine(safe())
drive(s, frames=1)   # 启动两者
drive(s, frames=1)   # crashy 抛异常，safe 继续
drive(s, frames=1)   # safe 恢复
assert 'safe-done' in log, log
assert s.coroutine_count() == 0
print('8) 协程异常隔离 OK:', log)

# 9) 非 generator 报错
s = _TestScript()
try:
    s.start_coroutine(lambda: None)
    assert False, '应拒绝非 generator'
except TypeError:
    print('9) 非 generator 拒绝 OK')

print('SMOKE_PASS')
