# -*- coding: utf-8 -*-
"""smoke_events.py — 事件系统冒烟 (2026-10-18)

Part A: EventBus 核心
  A1 on/emit 基本派发
  A2 once 只触发一次
  A3 off(handler) 按句柄取消
  A4 off('name', cb) 按 callback 取消
  A5 off('name') 清空该事件
  A6 emit 返回被调用的回调数
  A7 异常隔离（单个回调抛异常不影响其他）
  A8 派发期间新增订阅（延迟到本次派发结束）
  A9 派发期间取消订阅（延迟到本次派发结束）
  A10 has / listener_count / clear
  A11 emit 无订阅者返回 0
  A12 on 非 callable 抛 TypeError

Part B: UI pointer 回调
  B1 on_pointer_enter / exit
  B2 on_pointer_down / up
  B3 on_pointer_drag（拖动时）
  B4 回调异常隔离
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from loom_events import EventBus, EventHandler
from loom_ui import UIElement, UIManager, Canvas


# ==================== Part A: EventBus ====================

# A1 on/emit 基本派发
bus = EventBus()
calls = []
h = bus.on('test', lambda x: calls.append(x))
assert isinstance(h, EventHandler)
assert bus.listener_count('test') == 1
n = bus.emit('test', 42)
assert n == 1
assert calls == [42]
print('A1 on/emit OK')

# A2 once 只触发一次
bus = EventBus()
calls = []
bus.once('once_test', lambda: calls.append(1))
bus.emit('once_test')
bus.emit('once_test')
assert calls == [1], calls
assert bus.listener_count('once_test') == 0
print('A2 once OK')

# A3 off(handler)
bus = EventBus()
calls = []
h = bus.on('x', lambda: calls.append(1))
bus.off(h)
bus.emit('x')
assert calls == []
assert bus.listener_count('x') == 0
print('A3 off(handler) OK')

# A4 off('name', cb)
bus = EventBus()
calls = []
def cb1(): calls.append('1')
def cb2(): calls.append('2')
bus.on('y', cb1)
bus.on('y', cb2)
bus.off('y', cb1)
bus.emit('y')
assert calls == ['2'], calls
print('A4 off(name, cb) OK')

# A5 off('name') 清空
bus = EventBus()
bus.on('z', lambda: None)
bus.on('z', lambda: None)
assert bus.listener_count('z') == 2
bus.off('z')
assert bus.listener_count('z') == 0
print('A5 off(name) OK')

# A6 emit 返回计数（含 once 已被移除的情况）
bus = EventBus()
bus.on('m', lambda: None)
bus.on('m', lambda: None)
assert bus.emit('m') == 2
print('A6 emit 计数 OK')

# A7 异常隔离
bus = EventBus()
calls = []
def crash(): raise RuntimeError('崩')
bus.on('err', crash)
bus.on('err', lambda: calls.append('ok'))
n = bus.emit('err')
assert calls == ['ok'], calls
assert n == 1
print('A7 异常隔离 OK')

# A8 派发期间新增订阅（延迟）
bus = EventBus()
order = []
def handler_a():
    order.append('a')
    bus.on('x', lambda: order.append('late'))
bus.on('x', handler_a)
bus.emit('x')
# 第一次派发: 只调 a；late 是延迟添加，下次派发才生效
assert order == ['a'], order
bus.emit('x')
# 第二次派发: a + late
assert order == ['a', 'a', 'late'], order
print('A8 派发期间新增订阅 OK')

# A9 派发期间取消订阅（延迟）
bus = EventBus()
order = []
def handler_c():
    order.append('c')
    bus.off('x', handler_d)
def handler_d():
    order.append('d')
bus.on('x', handler_c)
bus.on('x', handler_d)
bus.emit('x')
# 第一次派发: c 取消 d 是延迟的, 本次 d 还会被调用
assert order == ['c', 'd'], order
order.clear()
bus.emit('x')
# 第二次派发: d 已被移除, 只调 c
assert order == ['c'], order
print('A9 派发期间取消订阅 OK')

# A10 has / listener_count / clear
bus = EventBus()
assert not bus.has('k')
bus.on('k', lambda: None)
assert bus.has('k')
assert bus.listener_count('k') == 1
bus.clear('k')
assert not bus.has('k')
bus.on('k1', lambda: None)
bus.on('k2', lambda: None)
bus.clear()
assert not bus.has('k1') and not bus.has('k2')
print('A10 has/count/clear OK')

# A11 emit 无订阅者
bus = EventBus()
assert bus.emit('none') == 0
print('A11 emit 无订阅者 OK')

# A12 on 非 callable
bus = EventBus()
try:
    bus.on('x', 123)
    assert False
except TypeError:
    pass
try:
    bus.once('x', None)
    assert False
except TypeError:
    pass
print('A12 非 callable 拒绝 OK')


# ==================== Part B: UI pointer 回调 ====================

# 简版 UIManager 场景：1 个 800x600 screen canvas + 1 个 200x100 面板
mgr = UIManager()
c = mgr.add_canvas(Canvas(canvas_type='screen', width=800, height=600))
panel = UIElement('panel', rect=(100, 100, 200, 100))
c.root.add_child(panel)

# B1 enter / exit
log = []
panel.on_pointer_enter = lambda: log.append('enter')
panel.on_pointer_exit = lambda: log.append('exit')

# 移动到 panel 外（鼠标在 50,50）
mgr.dispatch_mouse((50, 50), set(), set())
assert log == [], log
# 移动到 panel 内（150, 150）
mgr.dispatch_mouse((150, 150), set(), set())
assert log == ['enter'], log
# 移动出 panel
mgr.dispatch_mouse((50, 50), set(), set())
assert log == ['enter', 'exit'], log
print('B1 pointer enter/exit OK')

# B2 down / up
# 清掉 B1 遗留的 enter 回调（Python 闭包晚绑定，旧 lambda 会 append 到新 log）
panel.on_pointer_enter = None
panel.on_pointer_exit = None
log = []
panel.on_pointer_down = lambda pos: log.append(('down', tuple(pos)))
panel.on_pointer_up = lambda pos: log.append(('up', tuple(pos)))

# 先 hover 进 panel
mgr.dispatch_mouse((150, 150), set(), set())
# 按下
mgr.dispatch_mouse((150, 150), {1}, set())
assert log == [('down', (150, 150))], log
# 松开（在同一位置）
mgr.dispatch_mouse((150, 150), set(), {1})
assert ('up', (150, 150)) in log
print('B2 pointer down/up OK')

# B3 drag —— 用 Slider 触发（Slider 才走 _dragging_elem 路径）
from loom_ui import Slider
slider = Slider('sld', rect=(300, 300, 200, 20), value=0.0)
c.root.add_child(slider)
drag_log = []
slider.on_pointer_drag = lambda pos: drag_log.append(tuple(pos))
# 按下 slider
mgr.dispatch_mouse((400, 310), {1}, set())
# 拖动
mgr.dispatch_mouse((450, 310), set(), set())
assert drag_log, 'drag 回调未触发: %r' % drag_log
# 松开
mgr.dispatch_mouse((450, 310), set(), {1})
print('B3 pointer drag OK（%d 次）' % len(drag_log))

# B4 回调异常隔离（单个回调崩不影响 UIManager 主循环）
panel2 = UIElement('panel2', rect=(500, 400, 100, 100))
c.root.add_child(panel2)
panel2.on_pointer_enter = lambda: (_ for _ in ()).throw(RuntimeError('崩'))
# 不应抛异常
mgr.dispatch_mouse((550, 450), set(), set())
mgr.dispatch_mouse((10, 10), set(), set())
print('B4 回调异常隔离 OK')

print('SMOKE_PASS')
