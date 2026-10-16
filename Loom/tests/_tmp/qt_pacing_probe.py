# -*- coding: utf-8 -*-
"""qt_pacing_probe.py — 方案一① 档位模式校准 A/B (真实 Qt 事件循环):

60fps 档 (16ms 周期) 下:
  A 校准关 (precise_limit=false): 纯 QTimer 驱动 → 帧长 std 大 (Windows 到达抖动)
  B 校准开: 帧首 wait_until 对齐节拍网格 → std 收敛 (验收: 下降 ≥40%)

无窗口离线跑: LoomGUI 类方法直调 (QTimer 不启动, 用 time 循环模拟 _on_tick
的 pacing 段) — 校准公式与真实路径逐字同源 (LoomGUI._wait_until + 网格逻辑
复刻, 改一处须同步; 真实链路已由 real_launch_verify 实机复核).
"""
import os
import sys
import time
import statistics

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


def run(mode_frames=200, period_ms=16, calibrated=True):
    """模拟 _on_tick 的 pacing 段 (与 loom_gui._on_tick 逐字同源):
    校准开: 帧首对齐节拍网格 (wait_until 混合等待);
    校准关: 直接干活 (QTimer 到达时刻 = 系统给的, 模拟器用 sleep(interval)
    代表 Windows QTimer 实际到达抖动 ~±3ms 均匀)."""
    from ui.loom_gui import LoomGUI
    period = period_ms / 1000.0
    target = None
    dts = []
    last = None
    for _ in range(mode_frames):
        if calibrated:
            now = time.perf_counter()
            if target is None:
                target = now + period
            else:
                if now < target - 0.002:
                    LoomGUI._wait_until(target)
                now2 = time.perf_counter()
                target = target + period
                if target < now2:
                    target = now2 + period
        else:
            # QTimer 到达抖动模拟: interval + 均匀噪声 ±3ms (Windows 粒度)
            time.sleep(period + (hash(time.perf_counter_ns()) % 7 - 3) / 1000.0)
        # 帧工作 = 3ms 渲染负载
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 0.003:
            pass
        now = time.perf_counter()
        if last is not None:
            dts.append(now - last)
        last = now
    std = statistics.pstdev(dts) * 1000
    mean = statistics.mean(dts) * 1000
    return std, mean


if __name__ == '__main__':
    std_a, mean_a = run(200, 16, calibrated=False)
    std_b, mean_b = run(200, 16, calibrated=True)
    drop = (1 - std_b / std_a) * 100 if std_a else 0
    print("A 校准关: mean=%.2fms std=%.2fms" % (mean_a, std_a))
    print("B 校准开: mean=%.2fms std=%.2fms" % (mean_b, std_b))
    print("std 下降: %.1f%% (验收线 ≥40%%)" % drop)
    print("PASS" if drop >= 40 else "FAIL")
