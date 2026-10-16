# -*- coding: utf-8 -*-
"""prof_phys_inner.py — 物理胶水内部细分 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import numpy as np
import moderngl
import editor as editor_mod
import physics_bridge as pb

ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda* a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_物理_动态1200刚体.json'))
ed.toggle_play()
clk = ed._ensure_split()
for _ in range(20):
    ed._logic_frame(clk.fixed_dt)

br = ed._phys_bridge
dt = clk.sub_dt; g = getattr(ed, 'gravity', -9.8)
print("models:", len(ed.models), " entries:", len(br._entries), " free:", len(br._free), " sub_steps:", clk.sub_steps, flush=True)

# 计数 _active_ok
cnt = {'active': 0, 'dirty': 0}
_oa = br._active_ok
_od = br._dirty_mask_batch
def wa(*a, **k):
    cnt['active'] += 1; return _oa(*a, **k)
def wd(*a, **k):
    cnt['dirty'] += 1; return _od(*a, **k)
br._active_ok = wa
br._dirty_mask_batch = wd

N = 40
# 三段总计时
for label, fn in (('pre_step', lambda: br.pre_step(dt, g)),
                  ('step', lambda: br.step(dt)),
                  ('post_step', lambda: br.post_step())):
    fn()
    t0 = time.perf_counter()
    for _ in range(N): fn()
    print("  %-12s %.3f ms/次" % (label, (time.perf_counter()-t0)/N*1000), flush=True)

# 单次统计 _active_ok / _dirty 调用次数
cnt.update(active=0, dirty=0)
br.post_step()
print("\npost_step 单次: _active_ok 调用 %d 次 (dynamic体数)" % cnt['active'], flush=True)
cnt.update(active=0, dirty=0)
br.pre_step(dt, g)
print("pre_step 单次: _dirty_mask_batch 调用 %d 次" % cnt['dirty'], flush=True)

# 单独测 _active_ok 单次成本
h = br._entries[0]['handle']
t0 = time.perf_counter()
for _ in range(1000): _oa(h)
print("\n_active_ok 单次: %.4f ms" % ((time.perf_counter()-t0)/1000*1000), flush=True)

# 单独测各数组读取
w = br._w
t0 = time.perf_counter()
for _ in range(N):
    _ = np.asarray(w.positions).reshape(-1,4)
    _ = np.asarray(w.rotations).reshape(-1,4)
    _ = np.asarray(w.velocities).reshape(-1,4)
    _ = np.asarray(w.user_data).reshape(-1)
print("数组读取(4个): %.3f ms" % ((time.perf_counter()-t0)/N*1000), flush=True)

ed._stop_parallel()
import pygame; pygame.quit()
print("完成", flush=True)
