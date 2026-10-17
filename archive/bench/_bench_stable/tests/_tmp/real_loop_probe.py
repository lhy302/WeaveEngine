# -*- coding: utf-8 -*-
"""real_loop_probe.py — 真实编辑器运行循环 (clock.tick(120)) 下编辑/播放 FPS (2026-08-15).

测两种场景: [stress] 压测50球(静态+10脚本) / [rigid] 压测球+下落刚体(物理热点).
用法: py -3.12 tests\_tmp\real_loop_probe.py [stress|rigid]
"""
import os
import sys
import time

# 工作区根 = Loom(py源代码)\, 上溯 4 层; 引擎代码在 ...\Loom\ (sys.path)
BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(BASE, 'Loom'))
os.chdir(BASE)
os.environ['LOOM_PROFILE'] = '1'

import pygame
import pygame.freetype
pygame.freetype.init()
pygame.init()
pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)

import editor
import sceneio
from mesh import create_sphere

mode = sys.argv[1] if len(sys.argv) > 1 else 'stress'

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
if mode == 'rigid':
    data = sceneio.load_scene_data(os.path.join('Loom', '保存', '压测50球.json'))
    sceneio.scene_from_dict(eng, data)
    # 给 20 个球加刚体 (下落压物理路径)
    rb_count = 0
    for m in eng.models:
        if m.primitive == 'sphere' and rb_count < 20:
            m.add_rigidbody()
            m.position = type(m.position)(m.position.x, m.position.y + 15.0, m.position.z)
            rb_count += 1
    print("场景: rigid (50球, %d 个带刚体下落)" % rb_count)
else:
    data = sceneio.load_scene_data(os.path.join('Loom', '保存', '压测50球.json'))
    sceneio.scene_from_dict(eng, data)
    print("场景: stress (50球静态+10脚本)")

eng.current_model_index = 0
print("加载后 models=%d lights=%d (应 51/2)" % (len(eng.models), len(eng.lights)))

clock = pygame.time.Clock()
frames = 0
t0 = time.perf_counter()
last = time.time()


def run_loop(seconds, playing):
    """真实运行循环 (事件泵 + camera + render + clock.tick(120))."""
    global frames, t0, last
    frames = 0
    t0 = time.perf_counter()
    last = time.time()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        eng._handle_events()
        now = time.time()
        dt = min(now - last, 0.1)
        last = now
        eng.move_camera(dt)
        eng.rotate_camera(dt)
        eng.render(dt)
        frames += 1
        clock.tick(120)
    wall = time.perf_counter() - t0
    return frames / wall


# 预热 (播放态下落物体要落定)
for _ in range(40):
    eng.render(1.0 / 120.0)
if mode == 'rigid':
    # 先把下落球落定再测稳态
    eng.toggle_play()
    for _ in range(400):
        eng.render(1.0 / 120.0)
    eng.toggle_play()

def _stages(label, frames):
    st = eng._stage_times
    parts = "  ".join("%s=%.2f" % (k, st.get(k, 0) / frames) for k in
                      ('scripts', 'physics', 'world_matrices', 'shadow_prep'))
    print("  [%s] %s" % (label, parts))


f_edit = run_loop(3.0, False)
print("编辑模式 (clock.tick 上限) FPS=%.1f 帧=%.2fms" % (f_edit, 1000 / f_edit))
_stages("编辑", frames)
eng.toggle_play()
f_play = run_loop(3.0, True)
print("播放模式 (clock.tick 上限) FPS=%.1f 帧=%.2fms" % (f_play, 1000 / f_play))
_stages("播放", frames)
eng.toggle_play()
eng._stop_parallel()
pygame.quit()
print("结论: 编辑=%.1f 播放=%.1f" % (f_edit, f_play))
