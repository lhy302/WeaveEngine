# -*- coding: utf-8 -*-
"""prof_aabb_count.py — 编辑态AABB重算计数 (2026-10-14)"""
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
    ed.view.gui.render = lambda* a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_综合_小镇.json'))
for _ in range(15):
    now = time.perf_counter(); d = min(now-ed.last_frame_time,0.1)
    ed.last_frame_time = now; ed.render(d)

cnt = {'batched': 0, 'par': 0}
_ob = ed._aabbs_batched
_op = ed._model_aabbs_par
def wb(*a, **k):
    cnt['batched'] += 1
    return _ob(*a, **k)
def wp(*a, **k):
    cnt['par'] += 1
    return _op(*a, **k)
ed._aabbs_batched = wb
ed._model_aabbs_par = wp

NF=60
cnt.update(batched=0, par=0)
ed._stage_times.clear(); ed._stage_calls.clear()
t0 = time.perf_counter()
for _ in range(NF):
    now = time.perf_counter(); d = min(now-ed.last_frame_time,0.1)
    ed.last_frame_time = now; ed.render(d)
wall = (time.perf_counter()-t0)/NF*1000
print("编辑态 render: %.2f ms/frame" % wall, flush=True)
print("  _model_aabbs_par 调用: %d 次 (%d 帧, %.2f次/帧)" % (cnt['par'], NF, cnt['par']/NF), flush=True)
print("  _aabbs_batched 调用:   %d 次 (%.2f次/帧)" % (cnt['batched'], cnt['batched']/NF), flush=True)
st = ed._stage_times
for k in ('shadow_prep','aabbs','shadow_bounds','world_matrices','buckets'):
    if k in st:
        print("  %-14s %.3f ms/frame" % (k, st[k]/NF), flush=True)
ed._stop_parallel()
import pygame; pygame.quit()
print("完成", flush=True)
