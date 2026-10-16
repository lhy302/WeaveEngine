# -*- coding: utf-8 -*-
"""loom_logic_thread.py — GLEngine 逻辑帧线程子系统 (异步逻辑线程启停与主循环)。

从 engine.py 抽出 (作为 LogicThreadMixin 供 GLEngine 继承):
  _start_logic_thread / _stop_logic_thread / _logic_loop / _logic_snapshot

★激活条件 (行为红线, 逐位保留): 异步逻辑线程**仅限 Qt 宿主编辑器**
  (_logic_async=True 且 _external_ctx=True)。无头探针/测试直驱 advance_logic
  时不起线程 (否则与调用方双驱逻辑帧 + 物理管线 → 同步超时 + IndexError,
  collide_val_check 回归抓到过)。该门控判定在 advance_logic 内, 不在本文件。

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self._logic_thread / self._logic_stop / self._logic_async / self._logic_gen
  self._logic_steps / self._logic_paused / self._step_requested
  self._prep_pub / self._prep_pairs / self._prep_light_vps
  self._interp / self.is_playing / self._profile
"""
import threading
import time


class LogicThreadMixin:
    def _start_logic_thread(self, clk):
        """★M3-N3: 启动逻辑帧线程 (幂等)。线程只做 clk.advance + 快照发布。"""
        if self._logic_thread is not None:
            return
        self._logic_stop = threading.Event()
        t = threading.Thread(target=self._logic_loop, args=(clk,),
                             name='loom-logic', daemon=True)
        self._logic_thread = t
        t.start()

    def _stop_logic_thread(self):
        """★M3-N3: 停逻辑线程 (幂等; 退出/换场景调)。"""
        ev = self._logic_stop
        t = self._logic_thread
        self._logic_thread = None
        self._logic_stop = None
        if ev is not None:
            ev.set()
        if t is not None and t.is_alive() and t is not threading.current_thread():
            try:
                t.join(timeout=2.0)
            except Exception:
                pass

    def _logic_loop(self, clk):
        """★M3-N3: 逻辑帧线程主循环 —— 与主线程 advance_logic 的分工:
        本线程负责"何时跑逻辑帧"与全部逻辑工作; 主线程只读 clk.alpha 与 _prep_pub。
        节奏: 以 ~2ms 粒度轮询 (逻辑 20Hz, 轮询开销可忽略), clk.advance(dt) 内部
        按 accumulator 决定该跑几帧 (与旧路径同一时钟语义)。"""
        last = time.perf_counter()
        while not (self._logic_stop is not None and self._logic_stop.is_set()):
            try:
                now = time.perf_counter()
                dt = now - last
                last = now
                if not getattr(self, 'is_playing', False):
                    time.sleep(0.002)
                    continue
                if getattr(self, '_logic_paused', False):
                    if getattr(self, '_step_requested', False):
                        self._step_requested = False
                        self._profile('logic_step', lambda: clk.step_once())
                        self._logic_steps = clk.steps
                    time.sleep(0.002)
                    continue
                self._profile('logic_step', lambda: clk.advance(dt))
                self._logic_steps = clk.steps
                it = getattr(self, '_interp', None)
                if it is not None:
                    it.alpha = clk.alpha
                # 单点发布 (原子引用替换): 渲染侧一次读, 不混用新旧半套
                self._prep_pub = (self._logic_gen, self._prep_pairs,
                                  self._prep_light_vps)
                # 让出: 逻辑帧本身耗时 ~16ms, 剩余时间睡觉 (省 CPU)
                time.sleep(0.001)
            except Exception:
                import traceback
                traceback.print_exc()
                time.sleep(0.05)

    def _logic_snapshot(self):
        """★M3-N3: 渲染侧读逻辑帧产物 —— 异步时走单点发布元组, 否则读原字段。
        返回 (logic_gen, prep_pairs, prep_light_vps)。"""
        if self._logic_async:
            pub = self._prep_pub
            if pub is not None:
                return pub
        return (self._logic_gen, self._prep_pairs, self._prep_light_vps)
