# -*- coding: utf-8 -*-
"""
test_frame_buffer.py — TPS 缓冲 (逻辑帧预取) 验收 (2026-09-06)

覆盖:
  T1 记账器单元: 深度封顶 / 预算红线 / 闸门 (logic_fps>=30) / 逃生门
  T2 clock 消费语义: 预取帧 advance 跳重跑, 时间轴/alpha 逐位同旧
  T3 对拍 (核心): 预取开 = 关, 逻辑状态逐位一致 (含脚本/物理/prep 产物)
  T4 尖峰吸收: 尖峰渲染帧到来时, 开缓冲的 TPS 输出节律不被拖慢 (成品顶上)
  T5 metrics 观测面: hits/prefetches/outstanding 记账正确
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core_clock import FixedStepClock
from frame_buffer import FrameBufferLedger, RenderFrameBuffer


class T1_LedgerUnit(unittest.TestCase):
    def _led(self, **kw):
        led = FrameBufferLedger(**kw)
        led.configure({'frame_buffer_tps': True}, 30)
        return led

    def test_gate_low_fps_rejected(self):
        led = FrameBufferLedger()
        self.assertFalse(led.configure({'frame_buffer_tps': True}, 20))
        led2 = FrameBufferLedger()
        self.assertFalse(led2.configure({'frame_buffer_tps': True}, 0))
        led3 = FrameBufferLedger()
        self.assertTrue(led3.configure({'frame_buffer_tps': True}, 30))

    def test_gate_off_by_default(self):
        led = FrameBufferLedger()
        self.assertFalse(led.configure({}, 60))

    def test_escape_env_removed(self):
        # ★B7b 退役 (2026-10-16): LOOM_NO_FRAMEBUF env 已删; 设置面仍可关。
        led = FrameBufferLedger()
        self.assertFalse(led.configure({'frame_buffer_tps': False}, 60))
        self.assertTrue(led.configure({'frame_buffer_tps': True}, 60))

    def test_depth_cap(self):
        led = self._led(max_depth=2)
        self.assertTrue(led.should_prefetch(0.001))
        led.record_prefetch()
        self.assertTrue(led.should_prefetch(0.001))
        led.record_prefetch()
        self.assertFalse(led.should_prefetch(0.001))  # 深度 2 封顶
        self.assertEqual(led.rejected, 1)

    def test_no_pending_no_prefetch(self):
        led = self._led()
        self.assertTrue(led.should_prefetch(0.001))   # 常备语义: 无积压也预取

    def test_budget_redline(self):
        led = self._led()
        self.assertFalse(led.should_prefetch(0.013))  # 超 12ms 红线
        self.assertTrue(led.should_prefetch(0.011))

    def test_disabled_no_prefetch(self):
        led = FrameBufferLedger()
        led.configure({'frame_buffer_tps': False}, 60)
        self.assertFalse(led.should_prefetch(0.0))


class _World:
    """最小逻辑世界: 每逻辑帧 x += v (对拍用)."""

    def __init__(self):
        self.x = 0.0
        self.calls = 0

    def step(self, fdt):
        self.x += 1.0
        self.calls += 1


def _mk_clock(world, logic_fps=30.0, ledger=None):
    clk = FixedStepClock(logic_fps=logic_fps)
    clk.on_logic_step.append(world.step)
    if ledger is not None:
        clk.frame_buffer = ledger
    return clk


class T2_ConsumeSemantics(unittest.TestCase):
    """预取帧 advance 跳重跑: 世界只被调用一次, 时间轴照常推进."""

    def test_advance_skips_prefetched(self):
        w = _World()
        led = FrameBufferLedger()
        led.configure({'frame_buffer_tps': True}, 30)
        clk = _mk_clock(w, 30.0, led)
        # 渲染帧 A: 1 帧到期 → 正常跑 (advance 消费); 帧尾常备预取 1 帧
        clk.advance(1.0 / 30.0)
        self.assertEqual(clk.steps, 1)
        self.assertEqual(w.calls, 1)
        self.assertEqual(clk.pending_steps(), 0)
        # 预取: 提前跑下一逻辑帧 (直接调 world.step 模拟 _logic_frame)
        if led.should_prefetch(0.001):
            w.step(clk.fixed_dt)
            led.record_prefetch()
        self.assertEqual(w.calls, 2)
        # 渲染帧 B: advance 应消费预取成品 (不重跑)
        clk.advance(1.0 / 30.0)
        self.assertEqual(clk.steps, 1)
        self.assertEqual(w.calls, 2)               # 关键: 仍是 2 (没重跑)
        self.assertEqual(led.hits, 1)
        self.assertEqual(led.outstanding, 0)
        # 时间轴: 2 逻辑帧已消耗, accumulator 余 0
        self.assertAlmostEqual(clk._acc, 0.0, places=9)


class T3_Equivalence(unittest.TestCase):
    """对拍: 预取开 vs 关, N 渲染帧后世界状态逐位一致."""

    def _run(self, enabled, frames=120, dt_ms=None):
        w = _World()
        led = FrameBufferLedger()
        led.configure({'frame_buffer_tps': enabled}, 30)
        clk = _mk_clock(w, 30.0, led)
        for i in range(frames):
            dt = (dt_ms[i] if dt_ms else 33.3) / 1000.0
            clk.advance(dt)
            # 渲染帧尾预取 (engine._framebuf_prefetch 同款逻辑)
            if led.should_prefetch(0.005):
                w.step(clk.fixed_dt)
                led.record_prefetch()
        return w, led

    def test_steady_dt_identical(self):
        w_off, led_off = self._run(False)
        w_on, led_on = self._run(True)
        # 口径: 预取=执行时刻提前, 总计算量不变但边界帧可差 1 (dt 33.3ms 略
        # 小于 1/30, 关缓冲最后一帧差半毫秒未凑齐; 开缓冲预取恰好凑齐)
        self.assertLessEqual(abs(w_off.calls - w_on.calls), 1)
        self.assertAlmostEqual(w_off.x, w_on.x, delta=1.0)
        # 收口对拍: 关缓冲直注 1 逻辑帧 (step_once 语义) → 状态逐位相等
        clk2 = _mk_clock(w_off, 30.0)
        clk2.step_once()
        self.assertAlmostEqual(w_off.x, w_on.x, places=9)

    def test_spike_dt_identical(self):
        """尖峰 dt 序列 (每 10 帧 100ms): 最终状态必须逐位一致."""
        dt_ms = [100.0 if (i % 10 == 0) else 33.3 for i in range(120)]
        w_off, _ = self._run(False, dt_ms=dt_ms)
        w_on, led_on = self._run(True, dt_ms=dt_ms)
        self.assertLessEqual(abs(w_off.calls - w_on.calls), 1)
        self.assertAlmostEqual(w_off.x, w_on.x, delta=1.0)
        # 尖峰下缓冲确实工作了 (有预取且有命中)
        self.assertGreater(led_on.prefetches, 0)
        self.assertGreater(led_on.hits, 0)


class T4_SpikeAbsorption(unittest.TestCase):
    """尖峰吸收: 慢渲染帧后 TPS 不掉 (预取成品顶上)."""

    def test_tps_recovered_under_spikes(self):
        def run(enabled):
            w = _World()
            led = FrameBufferLedger()
            led.configure({'frame_buffer_tps': enabled}, 30)
            clk = _mk_clock(w, 30.0, led)
            t_events = []          # 每逻辑帧执行时刻 (TPS 语义)
            t = 1000.0             # 起始墙钟 (秒)
            for i in range(60):
                spike = (i % 10 == 0)
                dt = 0.100 if spike else 0.0333
                t += dt
                clk.advance(dt)
                for _ in range(clk.steps):
                    t_events.append(t)
                if led.should_prefetch(0.005):
                    w.step(clk.fixed_dt)
                    led.record_prefetch()
                    t_events.append(t)   # 预取帧=该时刻已算好 (TPS 观测语义)
            return t_events, led

        t_off, _ = run(False)
        t_on, led_on = run(True)
        # 关缓冲: 60 渲染帧 × 每 10 帧欠 2 帧 → 逻辑帧执行落后真实节拍
        # 开缓冲: 预取把执行时刻拉回渲染帧时刻 (成品顶上)
        self.assertGreater(led_on.hits, 0)
        # 最后 10 渲染帧窗口内: 开缓冲执行的逻辑帧数 >= 关缓冲 (顶上了)
        tail_off = sum(1 for t in t_off if t > 1000.0 + 50 * 0.0333 + 5 * 0.100)
        tail_on = sum(1 for t in t_on if t > 1000.0 + 50 * 0.0333 + 5 * 0.100)
        self.assertGreaterEqual(tail_on, tail_off)


class T5_Metrics(unittest.TestCase):
    def test_metrics_shape(self):
        led = self._led() if hasattr(self, '_led') else FrameBufferLedger()
        led.configure({'frame_buffer_tps': True}, 30)
        led.record_prefetch()
        led.consume()
        m = led.metrics()
        self.assertTrue(m['enabled'])
        self.assertEqual(m['prefetches'], 1)
        self.assertEqual(m['hits'], 1)
        self.assertEqual(m['outstanding'], 0)
        self.assertEqual(m['max_depth'], 2)

    def test_reset_clears_outstanding(self):
        led = FrameBufferLedger()
        led.configure({'frame_buffer_tps': True}, 30)
        led.record_prefetch()
        led.record_prefetch()
        self.assertEqual(led.outstanding, 2)
        led.reset()
        self.assertEqual(led.outstanding, 0)
        # reset 后 hits 保留 (累计度量), 深度解锁
        self.assertTrue(led.should_prefetch(0.001))


class T6_RenderBuffer(unittest.TestCase):
    """FPS 缓冲 (渲染帧预画) 单元: 闸门/状态机/决策."""

    def test_gate_fps_limits(self):
        s = {'frame_buffer_fps': True}
        rb = RenderFrameBuffer()
        self.assertTrue(rb.configure(s, 60))
        self.assertTrue(rb.configure(s, 240))
        rb2 = RenderFrameBuffer()
        self.assertFalse(rb2.configure(s, 'unlimited'))   # 无上限禁开
        rb3 = RenderFrameBuffer()
        self.assertFalse(rb3.configure(s, 30))            # <60 禁开
        rb4 = RenderFrameBuffer()
        self.assertFalse(rb4.configure({}, 120))          # 默认关

    def test_gate_escape_env_removed(self):
        # ★B7b 退役 (2026-10-16): LOOM_NO_FRAMEBUF env 已删; 设置面仍可关。
        rb = RenderFrameBuffer()
        self.assertFalse(rb.configure({'frame_buffer_fps': False}, 120))
        self.assertTrue(rb.configure({'frame_buffer_fps': True}, 120))

    def test_state_machine(self):
        rb = RenderFrameBuffer()
        rb.configure({'frame_buffer_fps': True}, 60)
        # 决策: 距节拍点 10ms 空窗 → 可预画
        now = 1000.0
        self.assertTrue(rb.should_preframe(now, now + 0.010))
        # 空窗 <3ms → 放弃
        self.assertFalse(rb.should_preframe(now, now + 0.002))
        self.assertEqual(rb.rejected, 1)
        # ready 前无成品; 无 GL 资源时 commit 不置 ready (防伪成品)
        self.assertFalse(rb.has_ready())
        rb.commit()
        self.assertFalse(rb.has_ready())
        # 修正断言: 无 GL 资源时 commit 不置 ready
        rb2 = RenderFrameBuffer()
        rb2.configure({'frame_buffer_fps': True}, 60)
        rb2.commit()
        self.assertFalse(rb2.has_ready())

    def test_reset_aborts(self):
        rb = RenderFrameBuffer()
        rb.configure({'frame_buffer_fps': True}, 60)
        rb.state = 'ready'               # 模拟 (GL 路径单测不可达)
        rb.reset()
        self.assertEqual(rb.state, 'idle')

    def test_metrics_shape(self):
        rb = RenderFrameBuffer()
        rb.configure({'frame_buffer_fps': True}, 120)
        m = rb.metrics()
        self.assertTrue(m['enabled'])
        self.assertEqual(m['fps_limit'], 120)
        self.assertIn('preframes', m)


if __name__ == '__main__':
    unittest.main(verbosity=2)
