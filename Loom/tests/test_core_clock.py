# -*- coding: utf-8 -*-
"""test_core_clock.py — 分离批5: FixedStepClock 单测 (批5 重构后 API)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core_clock import FixedStepClock, clock_from_settings, split_enabled


class TestFixedStepClock(unittest.TestCase):

    def test_steps_basic(self):
        """V1-改写1: 逻辑 30Hz + 子步 1/60 → advance(1/30) == (1,2);
        advance(1/60) == (0,0) (无逻辑步即无子步 — 单 accumulator 语义)."""
        c = FixedStepClock()
        self.assertEqual(c.advance(1.0 / 30.0), (1, 2))
        c2 = FixedStepClock()
        self.assertEqual(c2.advance(1.0 / 60.0), (0, 0))
        # 下帧补步
        self.assertEqual(c2.advance(1.0 / 60.0), (1, 2))

    def test_alpha_continuity(self):
        """V1-保留: alpha ∈ [0,1); 60FPS 渲染 30Hz 逻辑 → 0.5, 0 拍频."""
        c = FixedStepClock()
        alphas = []
        for _ in range(8):
            c.advance(1.0 / 60.0)
            alphas.append(c.alpha)
        for a in alphas:
            self.assertGreaterEqual(a, 0.0)
            self.assertLess(a, 1.0)
        self.assertAlmostEqual(alphas[0], 0.5, places=9)
        self.assertAlmostEqual(alphas[1], 0.0, places=9)

    def test_death_spiral(self):
        """V1-保留: 巨帧步数封顶+积压丢弃; dt 超上限封顶; 自适应步数上限."""
        c0 = FixedStepClock()                 # delta=0.333 → 自适应上限 10
        s, p = c0.advance(10.0)
        self.assertEqual(s, 9)                # 0.333s 实容 9.99 步 → 9 步
        self.assertLess(c0._acc, c0.fixed_dt)  # 余量 < 1 步 (未触发积压丢弃)
        self.assertEqual(c0.max_steps_per_frame, 10)  # round(0.333*30)
        c = FixedStepClock(max_steps_per_frame=4)
        s, p = c.advance(10.0)
        self.assertEqual(s, 4)
        self.assertEqual(c._acc, 0.0)
        # dt 超 maximum_logic_delta → 等效 0.333
        c2 = FixedStepClock()
        s2, _ = c2.advance(1.0)
        c3 = FixedStepClock()
        s3, _ = c3.advance(0.333)
        self.assertEqual(s2, s3)
        self.assertAlmostEqual(c2._acc, c3._acc, places=12)

    def test_time_scale(self):
        """V1-保留: scale=0.5 步数减半; 0 恒 0 步且 alpha 冻结."""
        c = FixedStepClock()
        c.time_scale = 0.5
        s, p = c.advance(1.0 / 30.0)
        self.assertEqual(s, 0)
        s2, _ = c.advance(1.0 / 30.0)
        self.assertEqual(s2, 1)
        c2 = FixedStepClock()
        c2.time_scale = 0.0
        c2.advance(1.0 / 30.0)
        a_first = c2.alpha
        c2.advance(1.0 / 30.0)
        self.assertEqual(c2.steps, 0)
        self.assertEqual(c2.alpha, a_first)

    def test_callback_order(self):
        """V1-改写5: on_physics_step 已删 — 回调只有逻辑帧; 物理在 L 内部."""
        order = []
        c = FixedStepClock()
        c.on_logic_step.append(lambda dt: order.append('L'))
        c.advance(1.0 / 15.0)                # 2 逻辑步
        self.assertEqual(order, ['L', 'L'])
        self.assertFalse(hasattr(c, 'on_physics_step'))

    def test_sub_properties(self):
        """V1-新增: N 换算表 — 20→3, 30→2, 60→1 (拉齐 1/30), 120→1 (拉齐 1/120)."""
        c20 = FixedStepClock(logic_fps=20.0)
        self.assertEqual(c20.sub_steps, 3)
        self.assertAlmostEqual(c20.sub_dt, 1.0 / 60.0, places=15)
        c30 = FixedStepClock()
        self.assertEqual(c30.sub_steps, 2)
        self.assertAlmostEqual(c30.sub_dt, 1.0 / 60.0, places=15)
        c60 = FixedStepClock(logic_fps=60.0)
        self.assertEqual(c60.sub_steps, 1)
        self.assertAlmostEqual(c60.sub_dt, 1.0 / 60.0, places=15)  # N==1 → 拉齐 fixed_dt
        c120 = FixedStepClock(logic_fps=120.0)
        self.assertEqual(c120.sub_steps, 1)
        self.assertAlmostEqual(c120.sub_dt, 1.0 / 120.0, places=15)
        # set_fps 重算
        c30.set_fps(logic_fps=20.0)
        self.assertEqual(c30.sub_steps, 3)

    def test_phys_steps_accum(self):
        """V1-新增: phys_steps 累计 = steps × sub_steps."""
        c = FixedStepClock(logic_fps=20.0)   # N=3
        s, p = c.advance(0.1)
        self.assertEqual(s, 2)
        self.assertEqual(p, 6)

    def test_reset(self):
        """V1-保留: reset 清积压."""
        c = FixedStepClock()
        c.advance(10.0)
        c.reset()
        s, p = c.advance(0.001)
        self.assertEqual((s, p), (0, 0))
        self.assertAlmostEqual(c._acc, 0.001, places=15)
        self.assertAlmostEqual(c.alpha, 0.001 * 30.0, places=9)

    def test_clock_from_settings(self):
        """V1-保留+新增: 逃生门判定 + 子步长来源三档."""
        self.assertIsNone(clock_from_settings({'logic_fps': 0}))
        self.assertIsNone(clock_from_settings({'logic_fps': -1}))
        c = clock_from_settings({'logic_fps': 30, 'physics_fps': 60})
        self.assertIsInstance(c, FixedStepClock)
        self.assertAlmostEqual(c.sub_dt, 1.0 / 60.0, places=15)
        c2 = clock_from_settings({})         # 缺键: 逻辑 30Hz + 子步 60Hz 兜底
        self.assertEqual(c2.logic_fps, 30.0)
        self.assertAlmostEqual(c2.sub_dt, 1.0 / 60.0, places=15)
        # 新键 phys_substep_dt 优先
        c3 = clock_from_settings({'phys_substep_dt': 0.01})
        self.assertAlmostEqual(c3.sub_dt, 0.01, places=15)
        # 旧键 pf>=50 换算
        c4 = clock_from_settings({'physics_fps': 120})
        self.assertAlmostEqual(c4.sub_dt, 1.0 / 120.0, places=15)
        # 旧键 pf<50 忽略 (兜底 60Hz, 防穿透)
        c5 = clock_from_settings({'physics_fps': 30})
        self.assertAlmostEqual(c5.sub_dt, 1.0 / 60.0, places=15)
        # split_enabled: ★B7b 退役 (2026-10-16) 删 LOOM_NO_SPLIT env 用例;
        #   仅保留设置面判定 (logic_fps<=0 = 绑死)。
        self.assertTrue(split_enabled({'logic_fps': 30}))
        self.assertFalse(split_enabled({'logic_fps': 0}))

    def test_negative_dt(self):
        """V1-保留: 负 dt 钳 0."""
        c = FixedStepClock()
        self.assertEqual(c.advance(-0.1), (0, 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
