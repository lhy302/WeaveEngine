# -*- coding: utf-8 -*-
"""aabb_rows_probe.py — 播放态稳态 aabbs 组装行数/调用形态探针 (2026-09-07).
猴子补丁包一层 _aabbs_batched: 统计每渲染帧的调用次数/各行数/总行数,
判定稳态组装账走 池分块(小 chunk) 还是 主线程整组 (决定 memo 阈值设计)。
"""
import os
import sys
import time
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'

import fastpath
import pygame
import editor
import sceneio

_orig = editor.GLEngine._aabbs_batched
STATS = {'calls': 0, 'rows': 0, 'sizes': Counter(), 'threads': Counter()}


def patched(self, models, fw, visible_only=True, _row_cache=True):
    import threading
    STATS['calls'] += 1
    STATS['rows'] += len(models)
    STATS['sizes'][len(models)] += 1
    STATS['threads'][threading.get_ident()] += 1
    return _orig(self, models, fw, visible_only, _row_cache)


editor.GLEngine._aabbs_batched = patched

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0

eng.toggle_play()
for _ in range(120):                       # 预热+进稳态
    eng._handle_events()
    eng.render(1.0 / 120.0)

# 采 3 个 1s 窗口
for w in range(3):
    STATS['calls'] = 0; STATS['rows'] = 0; STATS['sizes'].clear()
    STATS['threads'].clear()
    t0 = time.perf_counter()
    frames = 0
    end = time.perf_counter() + 1.0
    while time.perf_counter() < end:
        eng._handle_events()
        eng.render(1.0 / 120.0)
        frames += 1
    dt = time.perf_counter() - t0
    top = ', '.join(f'{k}x{v}' for k, v in STATS['sizes'].most_common(6))
    print(f"win{w}: frames={frames} FPS={frames/dt:.1f} "
          f"calls={STATS['calls']} rows={STATS['rows']} "
          f"rows/frame={STATS['rows']/max(frames,1):.0f} "
          f"threads={len(STATS['threads'])}")
    print(f"   sizes: {top}")

eng.toggle_play()
eng._stop_parallel()
pygame.quit()
