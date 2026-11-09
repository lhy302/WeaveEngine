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
import sys
import threading
import time


class LogicThreadMixin:
    def _start_logic_thread(self, clk):
        """★M3-N3: 启动逻辑帧线程 (幂等)。线程只做 clk.advance + 快照发布。

        2026-11-09 P1-B (审计缺陷): 旧实现在 _stop 里先把 self._logic_thread 置 None,
        若旧线程仍存活 (见 _stop 的修复) 就会再起一条 → 双线程同时推时钟。
        这里加"同实例重复 start 守卫": 已有存活线程直接复用, 不重复起。
        """
        t0 = self._logic_thread
        if t0 is not None and getattr(t0, 'is_alive', lambda: False)():
            return t0
        self._logic_stop = threading.Event()
        # 2026-11-09 E1 现场取证结论: 逻辑线程被渲染主线程「饿住」—— 默认 GIL 切换
        # 间隔 5ms，而渲染主线程有上百毫秒级的纯 Python 段（501 模型世界矩阵/剔除），
        # 逻辑线程每轮要等 100~400ms 才拿到 GIL，稳态只能跑到 2.5~10 轮/秒，
        # 靠 accumulator 补回大部分时间后 TPS 仍落在 22~25（实测）。
        # 处置: 把切换间隔收到 1ms（逻辑线程能更及时拿到 GIL），停止时恢复原值。
        try:
            self._gil_switch_back = sys.getswitchinterval()
            sys.setswitchinterval(0.001)
        except Exception as e:
            self._gil_switch_back = None
            print('[engine] GIL 切换间隔调整失败 (%r), 逻辑线程可能被渲染线程饥饿' % (e,))
        t = threading.Thread(target=self._logic_loop, args=(clk, self._logic_stop),
                             name='loom-logic', daemon=True)
        self._logic_thread = t
        t.start()
        return t

    def _stop_logic_thread(self):
        """★M3-N3: 停逻辑线程 (幂等; 退出/换场景调)。

        2026-11-09 P1-B (审计缺陷): 旧实现先 `self._logic_stop = None` 再 `ev.set()`,
        而本循环的退出条件读的是 `self._logic_stop` —— 置 None 后条件恒假, 线程
        **永不退出** (实测 join 卡满 2s、stop 后孤儿线程 0.3s 内仍推时钟 178 次、
        再 start 变双线程)。现在: ①先 `ev.set()` 再清引用 ②循环改用**局部 ev**
        ③线程没真正退出时保留 `self._logic_thread` 引用, 让 start 守卫挡住重复起线程。
        返回 True = 已停干净。
        """
        ev = self._logic_stop
        t = self._logic_thread
        if ev is not None:
            ev.set()                      # 先发信号 (循环读的是传进去的局部 ev)
        self._logic_stop = None
        # 2026-11-09 E1: 恢复 GIL 切换间隔 (别把引擎进程的默认值永久改掉)
        _gb = getattr(self, '_gil_switch_back', None)
        if _gb is not None:
            try:
                sys.setswitchinterval(_gb)
            except (ValueError, TypeError) as e:
                print('[engine] 恢复 GIL 切换间隔失败 (%r)' % (e,))
            self._gil_switch_back = None
        if t is not None and t.is_alive() and t is not threading.current_thread():
            try:
                t.join(timeout=2.0)
            except (RuntimeError, ValueError) as e:
                print('[engine] 逻辑线程 join 失败 (%r)' % (e,))
        still = bool(t is not None and getattr(t, 'is_alive', lambda: False)())
        if still:
            # 失败必须可见: 保留引用 (start 守卫据此拒绝再起一条), 并打一条告警
            print('[engine] 警告: 逻辑线程 2s 内未退出 (仍存活), 已保留引用以阻止重复启动')
        else:
            self._logic_thread = None
        return not still

    def _logic_loop(self, clk, stop_ev=None):
        """★M3-N3: 逻辑帧线程主循环 —— 与主线程 advance_logic 的分工:
        本线程负责"何时跑逻辑帧"与全部逻辑工作; 主线程只读 clk.alpha 与 _prep_pub。
        节奏: 以 ~2ms 粒度轮询 (逻辑 20Hz, 轮询开销可忽略), clk.advance(dt) 内部
        按 accumulator 决定该跑几帧 (与旧路径同一时钟语义)。"""
        # 2026-11-09 P1-B: 退出条件用**局部** ev (与 _stop 里 ev.set() 同一对象),
        # 不再每轮读 self._logic_stop —— 后者被置 None 时条件会恒假, 线程永不退出。
        if stop_ev is None:
            stop_ev = getattr(self, '_logic_stop', None)
        if stop_ev is None:
            stop_ev = threading.Event()
        last = time.perf_counter()
        while not stop_ev.is_set():
            try:
                now = time.perf_counter()
                dt = now - last
                last = now
                if not getattr(self, 'is_playing', False):
                    time.sleep(0.002)
                    continue
                if getattr(self, '_logic_paused', False):
                    # 2026-11-09 P1-A: 暂停期清墙钟锚点, 恢复首帧不补欠账
                    self._logic_wall_last = None
                    if getattr(self, '_step_requested', False):
                        self._step_requested = False
                        self._profile('logic_step', lambda: clk.step_once())
                        self._logic_steps = clk.steps
                    time.sleep(0.002)
                    continue
                # 2026-11-09 E1 (beta5): 统一走 _clock_advance (与同步路径同一口径;
                # 这里的 dt 本就是实测间隔, max() 对它是无操作, 但体检记账共用)
                self._profile('logic_step', lambda: self._clock_advance(dt, clk))
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
