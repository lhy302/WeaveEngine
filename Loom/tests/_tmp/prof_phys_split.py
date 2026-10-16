# -*- coding: utf-8 -*-
"""prof_phys_split.py — post_step 两段拆分 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np
import moderngl
import editor as editor_mod
import physics_bridge as pb
from physics_bridge import quat_to_euler_batch

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
N = 60
# 完整
for _ in range(3): br.post_step()
t0=time.perf_counter()
for _ in range(N): br.post_step()
print("post_step 完整: %.3f ms" % ((time.perf_counter()-t0)/N*1000))

w = br._w
def prep():
    ud = np.asarray(w.user_data).reshape(-1).astype(np.int64)
    pos = np.asarray(w.positions).reshape(-1, 4)
    rotsq = np.asarray(w.rotations).reshape(-1, 4)
    vel = np.asarray(w.velocities).reshape(-1, 4)
    order = np.argsort(ud)
    ids = ud[order]
    row_full = np.full(max(br._next_id, 1), -1, dtype=np.int64)
    okm = ids < len(row_full)
    row_full[ids[okm]] = order[okm]
    dyn = [(i, e) for i, e in enumerate(br._entries) if e['motion'] == pb.cv.MOTION_DYNAMIC]
    r_all = np.array([row_full[e['id']] for _, e in dyn], dtype=np.int64)
    valid = r_all >= 0
    r_sub = r_all[valid]
    wp = pos[r_sub, :3].astype(np.float64)
    wq = rotsq[r_sub].astype(np.float64)
    wv = vel[r_sub, :3].astype(np.float64)
    lpq = quat_to_euler_batch(wq)
    ws = np.array([br._active_ok(e['handle']) for _, e in dyn])[valid]
    return dyn, valid, wp, wq, wv, lpq, ws

prep()
t0=time.perf_counter()
for _ in range(N): prep()
print("准备段: %.3f ms" % ((time.perf_counter()-t0)/N*1000))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成", flush=True)
