# -*- coding: utf-8 -*-
"""loom_profiler.py — GLEngine 性能插桩子系统 (LOOM_PROFILE 阶段耗时统计)。

从 engine.py 抽出 (作为 ProfilerMixin 供 GLEngine 继承):
  _profile / _prof_t0 / _prof_add / profile_snapshot

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self._stage_times / self._stage_calls / self._stage_frames
  self._draw_calls_total / self._render_buckets
"""
import os
import threading
import time

# D2/D3 收尾 (R5-03 P3-05): _prof_counts 懒初始化在双线程首帧竞争 —— 两个线程各自
# 建 dict, 后写者覆盖前者, 实测 3000 次丢 11 次计数。这里用一把模块级小锁把
# "判空 + 建 dict" 做成一次性临界区 (只在首次调用走锁, 稳态零锁开销)。
_PROF_COUNTS_LOCK = threading.Lock()


class ProfilerMixin:
    def _profile(self, name, fn):
        """LOOM_PROFILE=1 时记录 fn 阶段耗时到 self._stage_times (累计 ms; 诊断 8 核均摊).
        未开 profiling 时零开销直接跑.
        ★M3 (2026-09-09): time.time() → time.perf_counter() —— 前者在 Windows 上粒度
        约 15.6ms, 对 ms 级分段不可用 (M2 主线程归因只能"推断"的根因); 另累计调用次数
        (_stage_calls), 供 per-frame 归一化。"""
        if os.environ.get('LOOM_PROFILE') != '1':
            return fn()
        t0 = time.perf_counter()
        r = fn()
        dt = (time.perf_counter() - t0) * 1000.0
        self._stage_times[name] = self._stage_times.get(name, 0.0) + dt
        self._stage_calls[name] = self._stage_calls.get(name, 0) + 1
        return r

    def _prof_t0(self):
        """M3: 多语句块的计时起点 (0.0 = 未开 profiling, _prof_add 会跳过)."""
        return time.perf_counter() if os.environ.get('LOOM_PROFILE') == '1' else 0.0

    def _prof_add(self, name, t0):
        """M3: 与 _prof_t0 配对, 把整段耗时记入 _stage_times/_stage_calls."""
        if not t0:
            return
        dt = (time.perf_counter() - t0) * 1000.0
        self._stage_times[name] = self._stage_times.get(name, 0.0) + dt
        self._stage_calls[name] = self._stage_calls.get(name, 0) + 1

    def _prof_count(self, name, n=1):
        """D1/P0: 交接/事件计数 (非耗时观测量; 仅 LOOM_PROFILE=1).

        口径校正 (R5-03 P3-06): **未开时不是零开销** —— 实测约 1.2 µs/次
        (os.environ.get + 属性读)。当前调用点每帧 ≤3 次 (hm_pipe_post/wait/
        hm_logic_wake), 合计 <0.005 ms/帧; 若将来要加到每次 write 这类高频点,
        必须先改成模块级缓存开关, 否则会吃掉测量收益。

        hm_pipe_post / hm_pipe_wait / hm_logic_wake —— 跨线程交接次数的因果证据
        (3.13 GIL 交接变贵, 见 docs/design/research_beta6_04_python_hotspots.md 附录 E)."""
        if os.environ.get('LOOM_PROFILE') != '1':
            return
        c = getattr(self, '_prof_counts', None)
        if c is None:
            with _PROF_COUNTS_LOCK:          # P3-05: 双线程首帧只建一次
                c = getattr(self, '_prof_counts', None)
                if c is None:
                    c = self._prof_counts = {}
        c[name] = c.get(name, 0) + n

    def profile_snapshot(self):
        """M3: 一次性导出插桩快照 (累计 ms / 调用数 / 帧数), 供探针做 per-frame 归一化."""
        _times = dict(getattr(self, '_stage_times', {}) or {})
        _calls = dict(getattr(self, '_stage_calls', {}) or {})
        # D1/P0: 单次耗时 (µs) 与交接计数 —— 批次 D 的因果证据口径
        _per_call_us = {}
        for _k, _v in _times.items():
            _n = _calls.get(_k)
            if _n:
                _per_call_us[_k] = _v / _n * 1000.0
        return {
            'frames': getattr(self, '_stage_frames', 0),
            'times': _times,
            'calls': _calls,
            'per_call_us': _per_call_us,
            'handoffs': dict(getattr(self, '_prof_counts', {}) or {}),
            # M3-P5: 计数类观测量 (非耗时) —— 主 pass draw 批次数, 用于判断
            # GL 提交开销是"批次多"还是"每批贵"。
            'counts': {'draw_calls': getattr(self, '_draw_calls_total', 0),
                       'buckets': len(getattr(self, '_render_buckets', ()) or ())},
        }
