# -*- coding: utf-8 -*-
"""loom_events.py — 全局事件总线 (2026-10-18)

用途：跨脚本/跨系统的解耦通信。例：
    # 脚本 A 播报
    self.engine.events.emit('player_died', {'cause': 'fall'})

    # 脚本 B 订阅
    def on_start(self):
        self._h = self.engine.events.on('player_died', self._on_death)

    def _on_death(self, data):
        print('玩家死了:', data['cause'])

设计要点：
  - 极简发布-订阅，无优先级，无异步（全部同步派发）
  - 单线程（主循环）使用；不保证线程安全
  - 订阅句柄：on() 返回一个 handler 对象，可传给 off() 取消
  - once() 只触发一次，自动取消（2026-11-07 审计 scan_09 P-07 收口：
    首次派发**调用前**即置 alive=False 消费，回调里重入 emit 同名事件也只
    触发一次；移除动作仍走延迟队列，不破坏正在遍历的快照）
  - emit() 派发期间的订阅/取消进入延迟队列，派发结束后统一应用（避免遍历中途改字典）
    —— on/once/off/clear **同此语义**（2026-11-07 审计 scan_09 P-06 收口：
    clear 修复前是立即生效的旁路，会吞掉本轮剩余回调）
  - 异常隔离：单个回调抛异常不影响其他回调（打印后继续）
"""
import sys


class EventHandler:
    """订阅句柄，可传给 EventBus.off()."""
    __slots__ = ('name', 'callback', 'once', 'alive')

    def __init__(self, name, callback, once=False):
        self.name = name
        self.callback = callback
        self.once = once
        self.alive = True

    def cancel(self):
        """等效于 bus.off(handler)，方便链式调用."""
        self.alive = False


class EventBus:
    """极简发布-订阅事件总线.

    线程模型: 单线程（主循环）。不保证线程安全。
    """

    def __init__(self):
        # name -> [EventHandler, ...]
        self._handlers = {}
        # 派发期间增删的延迟队列（避免遍历时改列表）
        self._pending_add = []
        self._pending_remove = []
        self._dispatching = 0

    # ---------- 订阅 ----------
    def on(self, name, callback):
        """订阅 name 事件。返回 EventHandler 句柄（可用于 off）。"""
        if not callable(callback):
            raise TypeError('callback 必须可调用: %r' % type(callback))
        h = EventHandler(str(name), callback, once=False)
        if self._dispatching:
            self._pending_add.append(h)
        else:
            self._handlers.setdefault(h.name, []).append(h)
        return h

    def once(self, name, callback):
        """订阅 name 事件，触发一次后自动取消。返回 EventHandler。"""
        if not callable(callback):
            raise TypeError('callback 必须可调用: %r' % type(callback))
        h = EventHandler(str(name), callback, once=True)
        if self._dispatching:
            self._pending_add.append(h)
        else:
            self._handlers.setdefault(h.name, []).append(h)
        return h

    def off(self, handle_or_name, callback=None):
        """取消订阅。三种用法：
          - off(handler)          : 按句柄取消（推荐）
          - off('name')           : 取消该事件全部订阅
          - off('name', callback) : 取消该事件的指定 callback
        """
        if isinstance(handle_or_name, EventHandler):
            h = handle_or_name
            if self._dispatching:
                # 派发期间: 延迟到本轮结束移除（Unity C# 快照语义:
                # 当前轮仍会调用, 下一轮起不再调用）
                self._pending_remove.append(h)
            else:
                h.alive = False
                self._remove_one(h)
            return

        name = str(handle_or_name)
        lst = self._handlers.get(name, [])
        if callback is None:
            # 取消全部
            if self._dispatching:
                self._pending_remove.extend(lst)
            else:
                for h in lst:
                    h.alive = False
                self._handlers.pop(name, None)
        else:
            matches = [h for h in lst if h.callback == callback]
            if self._dispatching:
                self._pending_remove.extend(matches)
            else:
                for h in matches:
                    h.alive = False
                    self._remove_one(h)

    def _remove_one(self, h):
        lst = self._handlers.get(h.name)
        if lst is None:
            return
        try:
            lst.remove(h)
        except ValueError:
            pass
        if not lst:
            self._handlers.pop(h.name, None)

    # ---------- 派发 ----------
    def emit(self, name, *args, **kwargs):
        """同步派发 name 事件给所有订阅者。返回被调用的回调数.

        单个回调抛异常 -> 打印后继续派发（异常隔离）。
        派发期间新增/移除的订阅进入延迟队列，本次派发结束后统一应用。
        """
        name = str(name)
        lst = list(self._handlers.get(name, []))
        if not lst:
            return 0
        self._dispatching += 1
        called = 0
        try:
            for h in lst:
                if not h.alive:
                    continue
                if h.once:
                    # scan_09 P-07: once 必须在**调用前**消费（先 alive=False）。
                    # 旧实现把移除推迟到最外层 _apply_pending, 于是 once 回调里
                    # 重入 emit 同名事件时, 内层快照仍看到 alive=True 的同一个
                    # handler, 递归重复触发（审计实测 499 次）。这里先消费再调用:
                    # 内层快照虽仍含本 handler, 但 alive=False 会被跳过; 派发中
                    # 不改正在遍历的表, 移除动作照旧走延迟队列, 本轮结束统一摘除。
                    h.alive = False
                    if self._dispatching:
                        self._pending_remove.append(h)
                    else:
                        self._remove_one(h)
                try:
                    h.callback(*args, **kwargs)
                    called += 1
                except Exception as e:
                    print('[事件] %s 回调异常: %r' % (name, e),
                          file=sys.stderr)
                    # 异常隔离：继续派发
                    # （once 已在调用前消费, 异常也只会触发这一次, Unity 语义）
        finally:
            self._dispatching -= 1
            self._apply_pending()

        return called

    def _apply_pending(self):
        """派发结束后应用延迟的增删队列."""
        if self._dispatching:
            return
        adds, removes = self._pending_add, self._pending_remove
        self._pending_add, self._pending_remove = [], []
        for h in removes:
            h.alive = False
            self._remove_one(h)
        for h in adds:
            if h.alive:
                self._handlers.setdefault(h.name, []).append(h)

    # ---------- 诊断 ----------
    def has(self, name):
        """该事件是否有订阅者."""
        return bool(self._handlers.get(str(name)))

    def listener_count(self, name):
        """该事件的订阅者数."""
        return len(self._handlers.get(str(name), []))

    def clear(self, name=None):
        """清空订阅。name=None 全部清空，否则只清空该事件。

        2026-11-07 (审计 scan_09 P-06 修复): 派发期调用与 off() 同语义 ——
        进入延迟移除队列, 本轮快照内的订阅者**仍会收到**本次事件, 本轮结束
        (emit 的 finally) 才统一摘除。修复前 clear 直接改 _handlers 并置
        alive=False, 派发中调用会把本轮尚未执行的回调静默丢掉 (emit 的返回
        计数也少 1), 与文档"派发期间的订阅/取消进入延迟队列"和 off() 的
        延迟语义分叉。
        语义边界: 延迟的是"调用 clear 那一刻已存在的订阅"; 本轮内之后新增的
        订阅走 _pending_add, 在本轮结束后才生效 (因此不会被本次 clear 抹掉)。"""
        if self._dispatching:
            if name is None:
                targets = [h for lst in self._handlers.values() for h in lst]
            else:
                targets = list(self._handlers.get(str(name), []))
            # 只入队, 不动 alive / _handlers —— 当前轮照常派发完整快照
            self._pending_remove.extend(targets)
            return
        if name is None:
            for lst in self._handlers.values():
                for h in lst:
                    h.alive = False
            self._handlers.clear()
        else:
            lst = self._handlers.pop(str(name), [])
            for h in lst:
                h.alive = False


# 引擎级默认实例（engine.py 会 import 并在 __init__ 里创建新实例；
# 这个单例主要用于极简脚本/工具场景）
default_bus = EventBus()
