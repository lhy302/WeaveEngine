# -*- coding: utf-8 -*-
"""editor_edit_probe.py — 编辑模式帧时间分解 (50球压测场景) (2026-08-15).

加载 保存\压测50球.json 到编辑器, LOOM_PROFILE 出阶段耗时, 看主线程开销分布在哪.
用法: py -3.12 tests\_tmp\editor_edit_probe.py [serial]
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_PROFILE'] = '1'
if len(sys.argv) > 1 and sys.argv[1] == 'serial':
    os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame
import editor
import sceneio

eng = editor.EditorApp(1280, 800)
# 清默认 + 加载压测场景
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('Loom', '保存', '压测50球.json'))
sceneio.scene_from_dict(eng, data)

def measure(label, frames=150):
    eng._stage_times.clear()
    t0 = time.perf_counter()
    for _ in range(frames):
        eng.render(1.0 / 120.0)
    wall = time.perf_counter() - t0
    st = eng._stage_times
    parts = "  ".join("%s=%.2f" % (k, st.get(k, 0) / frames) for k in
                      ('physics', 'world_matrices', 'shadow_prep'))
    print("%-16s FPS=%6.1f 帧=%.2fms [%s]" %
          (label, frames / wall, wall / frames * 1000, parts))

for _ in range(20):
    eng.render(1.0 / 120.0)
measure("编辑模式")
eng.toggle_play()
measure("播放模式")
eng.toggle_play()
eng._stop_parallel()
pygame.quit()
