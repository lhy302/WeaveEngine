# -*- coding: utf-8 -*-
"""prof_stress_all.py — 压力场景批量 profiling (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import moderngl
import editor as editor_mod

SCENES = [
    ('压力_空场景.json', 120),
    ('压力_渲染_实例化2000球.json', 60),
    ('压力_渲染_多材质1000方块.json', 60),
    ('压力_物理_动态1200刚体.json', 60),
    ('压力_物理_混合600静600动.json', 60),
    ('压力_脚本_自转1000.json', 60),
    ('压力_动画_400关键帧.json', 60),
    ('压力_综合_小镇.json', 40),
]
D = os.path.join(BASE, '保存', '压力测试')

def run_one(name, nframes):
    path = os.path.join(D, name)
    ctx = moderngl.create_standalone_context()
    ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
    ed._external_fb = ctx.detect_framebuffer()
    try:
        _g = ed.view.gui.render
        ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
    except Exception: pass
    ed.load_scene(path)
    for _ in range(10):
        now = time.perf_counter(); dt = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now; ed.render(dt)
    ed.toggle_play()
    clk = ed._ensure_split()
    for _ in range(20):
        ed._logic_frame(clk.fixed_dt)
    ed._stage_times.clear(); ed._stage_calls.clear()
    t0 = time.perf_counter()
    for _ in range(nframes):
        ed._logic_frame(clk.fixed_dt)
    lf_ms = (time.perf_counter() - t0) / nframes * 1000
    snap = ed.profile_snapshot()
    stages = {k: snap['times'][k] / nframes for k in snap['times']}
    n = len(ed.models)
    print("\n=== %s (%d objects) ===" % (name, n), flush=True)
    print("  逻辑帧平均: %.2f ms  (≈%.1f TPS)" % (lf_ms, 1000.0 / lf_ms if lf_ms > 0 else 0), flush=True)
    for k in ('mt_scripts', 'pipe_wait', 'mt_logic_prep', 'collide_pairs',
              'shadow_bounds', 'mt_dispatch', 'mt_audio_anim', 'mt_interp_advance'):
        if k in stages:
            print("    %-18s %7.3f ms  (%4.1f%%)" % (k, stages[k], 100.0 * stages[k] / lf_ms), flush=True)
    ed._stop_parallel()

for nm, nf in SCENES:
    try:
        run_one(nm, nf)
    except Exception as e:
        print("场景失败 %s: %r" % (nm, e), flush=True)
import pygame; pygame.quit()
print("\n完成", flush=True)
