# -*- coding: utf-8 -*-
"""loom_profiler.py — GLEngine 性能插桩子系统 (LOOM_PROFILE 阶段耗时统计)。

从 engine.py 抽出 (作为 ProfilerMixin 供 GLEngine 继承):
  _profile / _prof_t0 / _prof_add / profile_snapshot

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self._stage_times / self._stage_calls / self._stage_frames
  self._draw_calls_total / self._render_buckets
"""
import os
import time


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

    def profile_snapshot(self):
        """M3: 一次性导出插桩快照 (累计 ms / 调用数 / 帧数), 供探针做 per-frame 归一化."""
        return {
            'frames': getattr(self, '_stage_frames', 0),
            'times': dict(getattr(self, '_stage_times', {}) or {}),
            'calls': dict(getattr(self, '_stage_calls', {}) or {}),
            # M3-P5: 计数类观测量 (非耗时) —— 主 pass draw 批次数, 用于判断
            # GL 提交开销是"批次多"还是"每批贵"。
            'counts': {'draw_calls': getattr(self, '_draw_calls_total', 0),
                       'buckets': len(getattr(self, '_render_buckets', ()) or ())},
        }
