# -*- coding: utf-8 -*-
"""test_frame_pacing.py — 方案一/二验收单测 (2026-09-05, 调研报告 §七守护):

方案一① 限帧器校准: _wait_until 混合等待 (虚拟目标时刻真实墙钟验证)
  - 目标节律 ±1ms 内命中率 >95% (真实墙钟, 60 次采样);
  - 过睡 (target 已过) 立即返回不追;
  - 长等待走 sleep (不忙等全程: 剩余 >min_sleep+undershoot 段 CPU 时间占比低).
方案一② 帧长滑窗: get_frame_jitter std/max (恒定帧长注入 → std≈0;
  双峰注入 → std 大).
方案二 extrapolate: 恒速物体外推误差 = 速度×fdt×(a'-1) (精度 1e-7) /
  封顶 1.5 / 静止帧恒等 / angdiff 外推同式.

纯标准库+numpy, 不依赖 Qt (限帧器被测函数是 staticmethod 可独立导入).
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import numpy as np


def _load_wait_until():
    """导入 loom_gui.LoomGUI._wait_until (Qt 模块 — PySide6 已装则直导;
    失败=环境缺 Qt, 单测复制公式原地跑, 公式同源铁律见注释)."""
    try:
        from ui.loom_gui import LoomGUI
        return LoomGUI._wait_until
    except Exception:
        def _wait_until(target, min_sleep=0.005, undershoot=0.004):
            while True:
                remain = target - time.perf_counter()
                if remain <= 0.0:
                    return
                if remain > min_sleep:
                    time.sleep(remain - undershoot)
                else:
                    end = target
                    while time.perf_counter() < end:
                        pass
                    return
        return _wait_until


_wait_until = _load_wait_until()


class TestWaitUntil(unittest.TestCase):

    def test_rhythm_hit_rate(self):
        """节律命中: 连续 wait_until(上次+16.6ms) 60 次, 实际间隔 16.6±1ms
        命中率 >95% (验收线, 调研 §七方案一)."""
        period = 1.0 / 60.0
        t = time.perf_counter() + period
        errs = []
        for _ in range(60):
            _wait_until(t)
            now = time.perf_counter()
            errs.append(now - t)
            t += period
        hits = sum(1 for e in errs if abs(e) <= 0.001)
        self.assertGreater(hits / len(errs), 0.95,
                           "±1ms 命中率 %d/%d" % (hits, len(errs)))

    def test_past_target_returns(self):
        """过睡: target 已过 → 立即返回 (<2ms, 不追不睡)."""
        t0 = time.perf_counter()
        _wait_until(t0 - 1.0)          # 1 秒前的目标
        dt = time.perf_counter() - t0
        self.assertLess(dt, 0.002)

    def test_long_wait_sleeps(self):
        """长等待省 CPU: 300ms 等待全程忙等会吃满核 — 校准版应在尾段才忙等.
        粗验: 等待期间 time.process_time 增量 << 墙钟 (忙等 ~100% 核)."""
        t0 = time.perf_counter()
        c0 = time.process_time()
        _wait_until(t0 + 0.3)
        wall = time.perf_counter() - t0
        cpu = time.process_time() - c0
        self.assertGreater(wall, 0.29)
        self.assertLess(cpu, wall * 0.5,
                        "300ms 等待 CPU 占用 %.0f%% (应走 sleep)" % (cpu / wall * 100))


class _M:
    """最小 GameObject 替身 (同 test_interp_state)."""
    def __init__(self, p=(0, 0, 0), r=(0, 0, 0)):
        self.position = type('P', (), {'x': p[0], 'y': p[1], 'z': p[2]})()
        self.rotation = type('P', (), {'x': r[0], 'y': r[1], 'z': r[2]})()
        self.scale = (1.0, 1.0, 1.0)


class TestFrameJitter(unittest.TestCase):
    """方案一②: get_frame_jitter 滑窗 (用最小桩 __new__ 绕 __init__)."""

    def _mk(self):
        from engine import GLEngine
        e = GLEngine.__new__(GLEngine)
        from collections import deque
        e._frame_dt = deque(maxlen=120)
        return e

    def test_constant_frames_low_std(self):
        """恒定帧长 16ms 注入 → std ≈ 0 (校准目标态)."""
        e = self._mk()
        for _ in range(60):
            e._frame_dt.append(1.0 / 60.0)
        std, mx, n = e.get_frame_jitter()
        self.assertLess(std, 0.01)
        self.assertLess(abs(mx - 1000.0 / 60.0), 0.01)

    def test_bimodal_frames_high_std(self):
        """双峰 6ms/34ms 交替 → std 显著 (未校准态特征, ~14ms)."""
        e = self._mk()
        for _ in range(60):
            e._frame_dt.append(0.006 if _ % 2 == 0 else 0.034)
        std, mx, _ = e.get_frame_jitter()
        self.assertGreater(std, 10.0)

    def test_insufficient_samples(self):
        """样本 <8 → (0,0,n) 不误导."""
        e = self._mk()
        e._frame_dt.append(0.016)
        std, mx, n = e.get_frame_jitter()
        self.assertEqual((std, mx, n), (0.0, 0.0, 1))


class TestExtrapolate(unittest.TestCase):
    """方案二: 外推模式 (interp_state.INTERP_EXTRAP)."""

    def test_constant_velocity_error(self):
        """恒速物体: 外推输出 - 真实未来 = 速度×fdt×(a'-1) 误差 (验收 1e-7).
        prev=0, curr=30Hz 位移 v×fdt; alpha=0.5 → a'=1.5 → 输出 = v×fdt×1.5,
        真实位置 (渲染时刻=curr+0.5fdt) = v×fdt×1.5 — 零误差 (恒速下外推精确)."""
        from interp_state import InterpState
        v, fdt = 10.0, 1.0 / 30.0
        models = [_M(p=(0.0, 0.0, 0.0))]
        it = InterpState(models)
        it.advance()                                # curr@0
        models[0].position = type('P', (), {
            'x': v * fdt, 'y': 0.0, 'z': 0.0})()    # 逻辑帧末 = v*fdt
        it.advance()
        pos, _, _ = it.render_pose(0.5, models,
                                   mode=InterpState.INTERP_EXTRAP)
        expect = v * fdt * 1.5
        self.assertAlmostEqual(float(pos[0, 0]), expect, delta=1e-7)

    def test_cap_15(self):
        """封顶: alpha→1 时 a' = min(2, 1.5) = 1.5 (输出不越过 curr+0.5 帧)."""
        from interp_state import InterpState
        v, fdt = 10.0, 1.0 / 30.0
        models = [_M(p=(0.0, 0.0, 0.0))]
        it = InterpState(models)
        it.advance()
        models[0].position = type('P', (), {'x': v * fdt, 'y': 0.0, 'z': 0.0})()
        it.advance()
        pos, _, _ = it.render_pose(0.999999, models,
                                   mode=InterpState.INTERP_EXTRAP)
        expect = v * fdt * 1.5
        self.assertLessEqual(float(pos[0, 0]), expect + 1e-9)

    def test_static_frame_identity(self):
        """静止帧: prev==curr → 外推恒等 curr (零风险)."""
        from interp_state import InterpState
        models = [_M(p=(3.0, 4.0, 5.0))]
        it = InterpState(models)
        it.advance()
        it.advance()
        pos, _, _ = it.render_pose(0.7, models,
                                   mode=InterpState.INTERP_EXTRAP)
        self.assertEqual((float(pos[0, 0]), float(pos[0, 1]), float(pos[0, 2])),
                         (3.0, 4.0, 5.0))

    def test_interp_mode_unchanged(self):
        """默认 INTERP_LERP 行为不变 (回归): a=0.5 → 中点, 不受外推改动影响."""
        from interp_state import InterpState
        models = [_M(p=(0.0, 0.0, 0.0))]
        it = InterpState(models)
        it.advance()
        models[0].position = type('P', (), {'x': 10.0, 'y': 0.0, 'z': 0.0})()
        it.advance()
        pos, _, _ = it.render_pose(0.5, models)
        self.assertEqual(float(pos[0, 0]), 5.0)

    def test_angdiff_extrap(self):
        """旋转外推同式: prev=0.1, curr=0.2, alpha=0.5 → a'=1.5 → 0.25 (短弧同源)."""
        from interp_state import InterpState
        models = [_M(r=(0.1, 0, 0))]
        it = InterpState(models)
        it.advance()
        models[0].rotation = type('P', (), {'x': 0.2, 'y': 0.0, 'z': 0.0})()
        it.advance()
        _, rot, _ = it.render_pose(0.5, models,
                                   mode=InterpState.INTERP_EXTRAP)
        self.assertAlmostEqual(float(rot[0, 0]), 0.25, places=12)


if __name__ == '__main__':
    unittest.main(verbosity=2)
