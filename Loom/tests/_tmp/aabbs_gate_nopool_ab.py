# -*- coding: utf-8 -*-
r"""aabbs_gate_nopool_ab.py — 批4A 无池环境 (闸门真正生效面) 端到端 A/B (2026-09-07)

LOOM_NO_PARALLEL=1 (pool=None -> _aabbs_batched 单体大组调用形态):
  OLD ≈ W=10^18 (等价旧 n-only 512 闸门: 混合500 最大组 100 行永不触发)
  NEW = W=300000 (工作量闸门: (100,V=3015)=301.5k 触发并行档)
同进程交替 3 轮, 每轮预热 90 帧 + 8s 稳态。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'

import fastpath
import pygame
import editor
import sceneio

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
print(f"models={len(eng.models)} frame_pool={eng._frame_pool}", flush=True)

eng.toggle_play()
for _ in range(90):
    eng._handle_events()
    eng.render(1.0 / 120.0)

W = editor.GLEngine._AABB_PAR_MIN_WORK
results = {}
for rnd in range(3):
    for label, wv in (('OLD', 10 ** 18), ('NEW', W)):
        editor.GLEngine._AABB_PAR_MIN_WORK = wv
        frames = 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 8.0:
            eng._handle_events()
            eng.render(1.0 / 120.0)
            frames += 1
        fps = frames / (time.perf_counter() - t0)
        results.setdefault(label, []).append(fps)
        print(f"round{rnd+1} {label}: {fps:.2f} FPS", flush=True)
editor.GLEngine._AABB_PAR_MIN_WORK = W

mo = sum(results['OLD']) / len(results['OLD'])
mn = sum(results['NEW']) / len(results['NEW'])
print(f"OLD avg={mo:.2f}  NEW avg={mn:.2f}  ratio={mn/mo:.4f}")
eng.toggle_play()
pygame.quit()
