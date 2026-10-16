# -*- coding: utf-8 -*-
r"""aabbs_gate_ab_probe.py — 批4A 闸门 A/B: 播放态 FPS + 内核耗时分解 (2026-09-07)

同进程三档交替 (消环境漂移):
  G512 = 现行闸门 512 (基线)
  G384 = 拟改闸门 384
  G2   = 强制全并行 (上界参照; DLL n<4 自动回退串行)

每档: 预热 90 帧 + 8s 稳态, 记 FPS / 每逻辑帧内核累计 ms / aabbs stage ms /
内核调用直方图。口径: LOOM_NO_NUMBA=1 (模拟编译版软件形态), 无头播放态。
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

SER = Counter()
PAR = Counter()
KER_MS = [0.0]            # 内核本体累计 ms (含在调用线程内计时)
_frame_calls = []

_ser_orig = fastpath.aabbs_minmax
_par_orig = fastpath.aabbs_minmax_par


def ser_hook(vh, m3, a, b):
    key = (int(vh.shape[0]), int(vh.shape[1]))
    SER[key] += 1
    t0 = time.perf_counter()
    r = _ser_orig(vh, m3, a, b)
    KER_MS[0] += (time.perf_counter() - t0) * 1000.0
    return r


def par_hook(vh, m3, a, b):
    key = (int(vh.shape[0]), int(vh.shape[1]))
    PAR[key] += 1
    t0 = time.perf_counter()
    r = _par_orig(vh, m3, a, b)
    KER_MS[0] += (time.perf_counter() - t0) * 1000.0
    return r


eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
print(f"models={len(eng.models)}", flush=True)

eng.toggle_play()
clock = pygame.time.Clock()

# 预热 (行缓存/池/DLL 全部就位)
fastpath.aabbs_minmax = ser_hook
fastpath.aabbs_minmax_par = par_hook
for _ in range(90):
    eng._handle_events()
    eng.render(1.0 / 120.0)


def measure(label, seconds=8.0):
    SER.clear(); PAR.clear()
    KER_MS[0] = 0.0
    st0 = dict(eng._stage_times)
    prev_gen = eng._logic_gen
    logic_frames = 0
    frames = 0
    t0 = time.perf_counter()
    while True:
        eng._handle_events()
        eng.render(1.0 / 120.0)
        if eng._logic_gen != prev_gen:
            logic_frames += 1
            prev_gen = eng._logic_gen
        frames += 1
        wall = time.perf_counter() - t0
        if wall >= seconds:
            break
    st1 = dict(eng._stage_times)
    d_aabbs = (st1.get('aabbs', 0.0) - st0.get('aabbs', 0.0)) / max(1, logic_frames)
    fps = frames / wall
    ker = KER_MS[0] / max(1, logic_frames)
    calls = (sum(SER.values()) + sum(PAR.values())) / max(1, logic_frames)
    rows = (sum(n * c for (n, V), c in SER.items())
            + sum(n * c for (n, V), c in PAR.items())) / max(1, logic_frames)
    print(f"[{label}] FPS={fps:6.1f}  TPS={logic_frames/wall:5.2f}  "
          f"aabbs_stage={d_aabbs:6.2f}ms/logic  kernel={ker:6.3f}ms/logic  "
          f"calls={calls:5.1f}/logic rows={rows:5.0f}/logic  "
          f"par_calls={sum(PAR.values())/max(1,logic_frames):.1f}", flush=True)
    return fps, d_aabbs, ker


G = editor.GLEngine
results = {}
for rnd in range(3):
    for label, gate in (('G512', 512), ('G384', 384), ('G2', 2)):
        G._AABB_PAR_MIN_MODELS = gate
        r = measure(f"round{rnd+1}-{label}")
        results.setdefault(label, []).append(r)

print('\n== 汇总 (3 轮均值) ==')
for label, rs in results.items():
    fps = sum(x[0] for x in rs) / len(rs)
    ab = sum(x[1] for x in rs) / len(rs)
    ker = sum(x[2] for x in rs) / len(rs)
    print(f"  {label}: FPS={fps:6.1f}  aabbs_stage={ab:6.2f}ms  kernel={ker:6.3f}ms")

eng.toggle_play()
eng._stop_parallel()
pygame.quit()
