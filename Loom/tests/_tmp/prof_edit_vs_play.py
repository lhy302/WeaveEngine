# -*- coding: utf-8 -*-
"""prof_edit_vs_play.py — 编辑态 vs 播放态 逐段对比 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import moderngl
import editor as editor_mod

ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_综合_小镇.json'))
print("models:", len(ed.models), flush=True)

# 计数: _model_aabbs_par 调用次数 + _aabbs_batched 调用次数
cnt = {'par': 0, 'batched': 0}
_orig_par = ed._model_aabbs_par
_orig_bat = ed._aabbs_batched
def wrap_par(*a, **k):
    cnt['par'] += 1
    return _orig_par(*a, **k)
def wrap_bat(*a, **k):
    cnt['batched'] += 1
    return _orig_bat(*a, **k)
ed._model_aabbs_par = wrap_par
ed._aabbs_batched = wrap_bat

def report(label, n):
    snap = ed.profile_snapshot()
    print("\n=== %s (%d 帧) ===" % (label, n), flush=True)
    for k in ('shadow_prep', 'world_matrices', 'buckets', 'mt_main_pass',
              'mt_logic_prep', 'aabbs', 'shadow_bounds', 'collide_pairs',
              'mt_scripts', 'pipe_wait'):
        if k in snap['times']:
            print("  %-16s %8.3f ms" % (k, snap['times'][k] / n), flush=True)

# ---- 编辑态 (物体静止) ----
ed.is_playing = False
for _ in range(15):
    now = time.perf_counter(); dt = min(now - ed.last_frame_time, 0.1)
    ed.last_frame_time = now; ed.render(dt)
cnt.update(par=0, batched=0)
ed._stage_times.clear(); ed._stage_calls.clear()
t0 = time.perf_counter()
NF = 60
for _ in range(NF):
    now = time.perf_counter(); dt = min(now - ed.last_frame_time, 0.1)
    ed.last_frame_time = now; ed.render(dt)
wall = (time.perf_counter() - t0) / NF * 1000
print("\n######## 编辑态(静止) render: %.2f ms/frame ########" % wall, flush=True)
print("  _model_aabbs_par 调用: %d/%d帧  _aabbs_batched 调用: %d" % (cnt['par'], NF, cnt['batched']), flush=True)
report("编辑态逐段", NF)

# ---- 播放态 ----
ed.toggle_play()
clk = ed._ensure_split()
for _ in range(20):
    ed._logic_frame(clk.fixed_dt)
cnt.update(par=0, batched=0)
ed._stage_times.clear(); ed._stage_calls.clear()
t0 = time.perf_counter()
for _ in range(NF):
    ed._logic_frame(clk.fixed_dt)
wall = (time.perf_counter() - t0) / NF * 1000
print("\n######## 播放态(物体动) logic_frame: %.2f ms/frame ########" % wall, flush=True)
print("  _model_aabbs_par 调用: %d/%d帧  _aabbs_batched 调用: %d" % (cnt['par'], NF, cnt['batched']), flush=True)
report("播放态逐段", NF)

ed._stop_parallel()
import pygame; pygame.quit()
print("\n完成", flush=True)
