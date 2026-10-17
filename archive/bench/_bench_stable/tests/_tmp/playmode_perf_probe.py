# -*- coding: utf-8 -*-
"""playmode_perf_probe.py — 对比编辑/播放模式帧时间分解 (2026-08-15).

用编辑器跑同场景: 编辑模式 vs 播放模式 (含脚本/物理/碰撞事件), LOOM_PROFILE 出阶段耗时.
用法: py -3.12 tests\_tmp\playmode_perf_probe.py [with_scripts]
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_PROFILE'] = '1'
# 并行默认开 (用户真实场景); 'serial' 参数强制 LOOM_NO_PARALLEL
if len(sys.argv) > 2 and sys.argv[2] == 'serial':
    os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame
import editor

W, H = 1280, 800
with_scripts = len(sys.argv) > 1 and sys.argv[1] == 'with_scripts'

eng = editor.EditorApp(W, H)
# 加 20 个球 + 地面, 部分挂 rotate 脚本 (模拟播放负载)
from mesh import create_sphere, create_plane
if with_scripts:
    for i in range(20):
        m = eng.add_model(create_sphere(0.5, 10, 16),
                          (i % 5 * 1.2 - 2.4, 0.6, i // 5 * 1.2 - 1.2), (0, 0, 0), name="球%d" % i)
        m.add_script('rotate', {'sx': 90.0})
else:
    for i in range(20):
        eng.add_model(create_sphere(0.5, 10, 16),
                      (i % 5 * 1.2 - 2.4, 0.6, i // 5 * 1.2 - 1.2), (0, 0, 0), name="球%d" % i)
eng.add_model(create_plane(12, 12), (0, -0.5, 0), (0, 0, 0), name="地面")
# 阴影平行光 (匹配真实场景负载)
eng.add_light('directional', position=(4, 8, 4), azimuth=30, elevation=-55, shadow=True)


def measure(label, frames=150):
    eng._stage_times.clear()
    t0 = time.perf_counter()
    for _ in range(frames):
        eng.render(1.0 / 120.0)
    wall = time.perf_counter() - t0
    fps = frames / wall
    st = eng._stage_times
    parts = "  ".join("%s=%.2f" % (k, st.get(k, 0) / frames) for k in
                      ('physics', 'world_matrices', 'shadow_prep'))
    print("%-16s FPS=%5.1f 帧=%.2fms  [%s] 未插桩=%.2fms" %
          (label, fps, wall / frames * 1000, parts,
           max(0, wall / frames * 1000 - sum(st.values()) / frames)))
    return fps


# 预热
for _ in range(20):
    eng.render(1.0 / 120.0)

measure("编辑模式")
eng.toggle_play()
measure("播放模式")
eng.toggle_play()

eng._stop_parallel()
pygame.quit()
print("脚本=%s" % with_scripts)
