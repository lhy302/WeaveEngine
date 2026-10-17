# -*- coding: utf-8 -*-
"""grid_cost_probe.py — 网格性能"成本与相机距离无关"探针 (2026-08-30)

验证两件事:
  1. 新旧语义逐位同源: 旧实现半宽=dist*6 在 dist=10 时 half=60, 与新版固定
     半宽 60 逐位一致 (内容零变化, 只砍成本);
  2. 成本持平: 各 cam_dist 下 build_grid_lines 单次耗时 ~恒定 (常数级),
     旧实现 1.75ms/帧 (距离 32) 的根因已消除。
真实运行时数据口径说明: 本探针测纯几何函数自身 (编辑器每帧调用链 =
grid_geometry → build_grid_lines, 无其他分段); 真实 Qt 画面待用户实测。
"""
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))   # Loom 包根 (tests/_tmp -> Loom)
from ui.grid import build_grid_lines

# ---- 旧实现参考 (回退版, 逐行 Python 生成) ----
_BASE_RGBA = (0.35, 0.37, 0.42, 1.0)
_STEP = 1.0
_MAX_HALF = 250.0
_MIN_HALF = 20.0
_FADE_RATIO = 0.4


def _fade_alpha(dist, fade_start, fade_end):
    if dist <= fade_start:
        return 1.0
    if dist >= fade_end:
        return 0.0
    return (fade_end - dist) / (fade_end - fade_start)


def old_build_grid_lines(eye, cam_dist=None, max_half=_MAX_HALF,
                         fade_start=None, fade_end=None, step=_STEP):
    dist = cam_dist if cam_dist and cam_dist > 0 else max(abs(eye[1]), 8.0)
    half = max(_MIN_HALF, min(max_half, dist * 6.0))
    if fade_end is None:
        fade_end = half
    if fade_start is None:
        fade_start = half * _FADE_RATIO
    ox = math.floor(eye[0] / step) * step
    oz = math.floor(eye[2] / step) * step
    n = int(math.ceil(half / step))
    verts, cols = [], []
    for i in range(-n, n + 1):
        x = ox + i * step
        a = _fade_alpha(abs(x - eye[0]), fade_start, fade_end)
        verts.append((x, 0.0, oz - half))
        verts.append((x, 0.0, oz + half))
        cols.append((_BASE_RGBA[0], _BASE_RGBA[1], _BASE_RGBA[2], a))
        cols.append((_BASE_RGBA[0], _BASE_RGBA[1], _BASE_RGBA[2], a))
        z = oz + i * step
        a = _fade_alpha(abs(z - eye[2]), fade_start, fade_end)
        verts.append((ox - half, 0.0, z))
        verts.append((ox + half, 0.0, z))
        cols.append((_BASE_RGBA[0], _BASE_RGBA[1], _BASE_RGBA[2], a))
        cols.append((_BASE_RGBA[0], _BASE_RGBA[1], _BASE_RGBA[2], a))
    return (np.asarray(verts, dtype='f4'), np.asarray(cols, dtype='f4'))


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


# ---- 1) 逐位同源 (旧实现 dist=10 -> half=60, 与新版任何 cam_dist 同参对比) ----
eye = (0.0, 5.0, -8.0)
old_at10 = old_build_grid_lines(eye, cam_dist=10.0)
new_at10 = build_grid_lines(eye, cam_dist=10.0)
new_far = build_grid_lines(eye, cam_dist=5000.0)
check("旧(dist=10) 与新(dist=10) 顶点逐位一致",
      bool(np.array_equal(old_at10[0], new_at10[0])))
check("旧(dist=10) 与新(dist=10) 颜色逐位一致",
      bool(np.array_equal(old_at10[1], new_at10[1])))
check("新(5000) 与新(10) 逐位一致 (距离无关核心)",
      bool(np.array_equal(new_at10[0], new_far[0])) and bool(np.array_equal(new_at10[1], new_far[1])))

# ---- 2) 成本持平: 各 cam_dist 单次耗时 (~常数级) ----
print("\n-- 单次耗时 (10 次取最小, 时间戳法) --")
times = {}
for cd in (0.5, 10.0, 32.0, 200.0, 5000.0):
    best = 1e9
    for _ in range(50):
        t0 = time.perf_counter_ns()
        build_grid_lines(eye, cam_dist=cd)
        best = min(best, time.perf_counter_ns() - t0)
    times[cd] = best / 1e6
    print("  cam_dist=%6.1f  ->  %.4f ms" % (cd, times[cd]))
vals = list(times.values())
check("各距离耗时差距 < 3 倍 (常数级)", max(vals) / max(min(vals), 1e-9) < 3.0,
      "min=%.4f max=%.4f ms" % (min(vals), max(vals)))
check("单次 < 0.5ms", max(vals) < 0.5, "max=%.4f ms" % max(vals))

# 对照: 旧实现同距离成本 (距离 32 = 用户实测问题帧率点)
old_times = []
for cd in (10.0, 32.0, 200.0):
    best = 1e9
    for _ in range(20):
        t0 = time.perf_counter_ns()
        old_build_grid_lines(eye, cam_dist=cd)
        best = min(best, time.perf_counter_ns() - t0)
    old_times.append(best / 1e6)
print("\n-- 旧实现对照 --")
for cd, t in zip((10.0, 32.0, 200.0), old_times):
    print("  cam_dist=%5.1f -> %.4f ms" % (cd, t))
check("新实现远快于旧实现(32)", times[32.0] < old_times[1] * 0.2,
      "new=%.4f old=%.4f ms" % (times[32.0], old_times[1]))

print("\n总结果: ALL PASS ✅" if ok else "\n总结果: 有 FAIL ❌")
sys.exit(0 if ok else 1)
