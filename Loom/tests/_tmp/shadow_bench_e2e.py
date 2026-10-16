# -*- coding: utf-8 -*-
"""shadow_bench_e2e.py — shadow_prep 族端到端账目 (LOOM_PROFILE=1 播放态, 前后对比用)

用法: py -3.12 tests/_tmp/shadow_bench_e2e.py [秒=8]
输出: 全阶段 ms/帧 + FPS (带 profile 口径, 前后同口径对比)
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'          # 模拟冻结 (编译版口径)
os.environ['LOOM_PROFILE'] = '1'           # 阶段账目

import pygame
import editor
import sceneio

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('保存', '压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
print(f"models={len(eng.models)} lights={len(eng.lights)}", flush=True)

eng.toggle_play()
for _ in range(60):
    eng._handle_events()
    eng.render(1.0 / 120.0)

frames = 0
t0 = time.perf_counter()
eng._stage_times.clear()
end = time.perf_counter() + float(sys.argv[1] if len(sys.argv) > 1 else 8.0)
while time.perf_counter() < end:
    eng._handle_events()
    eng.render(1.0 / 120.0)
    frames += 1
wall = time.perf_counter() - t0
fps = frames / wall
st = eng._stage_times
print(f"[带profile播放态] FPS={fps:.1f} 帧={1000/fps:.2f}ms", flush=True)
for k in sorted(st, key=lambda k: -st[k]):
    print(f"  {k:24s} {st[k]/frames:8.3f} ms/帧", flush=True)
prep = sum(st.get(k, 0) for k in ('shadow_prep', 'buckets', 'interp'))
print(f"  shadow_prep+buckets+interp 合计 {prep/frames:.3f} ms/帧", flush=True)
eng.toggle_play()
eng._stop_parallel()
pygame.quit()
print("完成", flush=True)
