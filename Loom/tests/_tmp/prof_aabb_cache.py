# -*- coding: utf-8 -*-
"""prof_aabb_cache.py — 编辑态AABB缓存失配根因 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import moderngl
import editor as editor_mod
from loom_game_object import GameObject

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

# 冻结编辑态（不播放），连续几帧观察缓存键变化
print("=== 编辑态连续5帧: 缓存键观察 ===", flush=True)
for fr in range(5):
    ed._render_world = None  # 强制重算渲染矩阵? 不, 编辑态不用render_world
    now = time.perf_counter(); d = min(now-ed.last_frame_time,0.1)
    ed.last_frame_time = now
    before = getattr(ed, '_aabb_row_cache', None)
    ed.render(d)
    after = getattr(ed, '_aabb_row_cache', None)
    sg = getattr(ed, '_struct_gen', 0)
    ag = GameObject._appearance_gen
    cache_desc = "None" if after is None else ("stamp=%s n=%d" % (after[1], after[2]))
    print("  帧%d: struct_gen=%d appearance_gen=%d  cache=%s" % (fr, sg, ag, cache_desc), flush=True)

# 直接测 _model_aabbs_par 是否命中
print("\n=== 连续调 _model_aabbs_par (visible_only=False) 计时 ===", flush=True)
fw = ed._frame_world
N=30
t0=time.perf_counter()
for _ in range(N):
    a = ed._model_aabbs_par(ed.models, fw, visible_only=False)
print("  30次平均: %.3f ms/次" % ((time.perf_counter()-t0)/N*1000), flush=True)
# 看缓存键
c = getattr(ed, '_aabb_row_cache', None)
if c:
    print("  cache stamp=%s n=%d, fw is cache[3]? %s" % (c[1], c[2], c[3] is fw), flush=True)
ed._stop_parallel()
import pygame; pygame.quit()
print("完成", flush=True)
