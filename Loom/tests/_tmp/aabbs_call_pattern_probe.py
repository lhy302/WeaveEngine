# -*- coding: utf-8 -*-
r"""aabbs_call_pattern_probe.py — 批4A 取证: 播放态 aabbs 内核真实调用形态 (2026-09-07)

背景: 优化作用面差异分析断言 "混合500 单组 n≈400, 卡在 _AABB_PAR_MIN_MODELS=512
闸门外恒走串行"。本探针 monkeypatch fastpath.aabbs_minmax / aabbs_minmax_par
记录真实调用: 每逻辑帧多少次调用、每次 n×V、走串行还是并行。

口径: 无头 headless 播放态 (aabb_ab_e2e.py 同款: EditorApp 直建 + toggle_play +
render 循环), LOOM_NO_NUMBA=1 (模拟编译版软件形态, C 内核同速)。
"""
import os
import sys
import time
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'

import numpy as np
import fastpath
import pygame
import editor
import sceneio

assert fastpath._CK['dll'] is not None, 'C DLL 未加载'

SER = Counter()          # (n, V) -> 次数 (串行档)
PAR = Counter()          # (n, V) -> 次数 (并行档)
_frame_calls = []

_ser_orig = fastpath.aabbs_minmax
_par_orig = fastpath.aabbs_minmax_par


def ser_hook(vh, m3, a, b):
    key = (int(vh.shape[0]), int(vh.shape[1]))
    SER[key] += 1
    _frame_calls.append(('S', key))
    return _ser_orig(vh, m3, a, b)


def par_hook(vh, m3, a, b):
    key = (int(vh.shape[0]), int(vh.shape[1]))
    PAR[key] += 1
    _frame_calls.append(('P', key))
    return _par_orig(vh, m3, a, b)


fastpath.aabbs_minmax = ser_hook
fastpath.aabbs_minmax_par = par_hook

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
print(f"models={len(eng.models)} lights={len(eng.lights)}", flush=True)
print(f"_AABB_PAR_MIN_MODELS={editor.GLEngine._AABB_PAR_MIN_MODELS} "
      f"_AABB_POOL_THRESHOLD={editor.GLEngine._AABB_POOL_THRESHOLD} "
      f"frame_pool={eng._frame_pool} nw={getattr(eng._frame_pool,'n_workers',None)}",
      flush=True)

eng.toggle_play()
clock = pygame.time.Clock()

# 预热 90 帧
for _ in range(90):
    eng._handle_events()
    eng.render(1.0 / 120.0)

# 采样 120 渲染帧 (~TPS20 下 6s)
SER.clear(); PAR.clear()
logic_frames = 0
prev_gen = eng._logic_gen
t0 = time.perf_counter()
frames = 0
while frames < 120:
    eng._handle_events()
    eng.render(1.0 / 120.0)
    if eng._logic_gen != prev_gen:
        logic_frames += 1
        prev_gen = eng._logic_gen
    frames += 1
wall = time.perf_counter() - t0

print(f"\nsampled {frames} render frames / {logic_frames} logic frames / {wall:.2f}s")
print(f"\n== 串行档调用 (n, V) -> 次数/逻辑帧均值 ==")
lf = max(1, logic_frames)
for (n, V), c in sorted(SER.items(), key=lambda kv: -(kv[0][0] * kv[0][1])):
    print(f"  serial n={n:4d} V={V:5d}  calls/frame={c/lf:6.2f}  rowwork={n*V/1e6:.2f}M")
print(f"== 并行档调用 ==")
if not PAR:
    print("  (无 — 并行档从未触发)")
for (n, V), c in sorted(PAR.items(), key=lambda kv: -(kv[0][0] * kv[0][1])):
    print(f"  par    n={n:4d} V={V:5d}  calls/frame={c/lf:6.2f}  rowwork={n*V/1e6:.2f}M")

tot_ser_rows = sum(n * c for (n, V), c in SER.items()) / lf
tot_par_rows = sum(n * c for (n, V), c in PAR.items()) / lf
print(f"\n每逻辑帧串行行数合计={tot_ser_rows:.0f} 并行行数合计={tot_par_rows:.0f}")
print(f"每逻辑帧内核调用次数={(sum(SER.values())+sum(PAR.values()))/lf:.1f}")

eng.toggle_play()
eng._stop_parallel()
pygame.quit()
