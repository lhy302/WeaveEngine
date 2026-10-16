# -*- coding: utf-8 -*-
"""prof_batch_math.py — 摩擦/残速计算: 逐体Python vs numpy批量 (2026-10-14)"""
import os, sys, time, math
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
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
for _ in range(20): ed._logic_frame(clk.fixed_dt)
br = ed._phys_bridge
dt = clk.sub_dt

# 构造冻结数据 (模拟 post_step 里 dyn 的状态)
dyn = [(i, e) for i, e in enumerate(br._entries) if e['motion'] == pb.cv.MOTION_DYNAMIC]
n = len(dyn)
wv = np.random.rand(n, 3) * 2.0
angw = np.random.rand(n, 3) * 2.0
ws = np.ones(n, dtype=bool)   # 全清醒
roll = np.array([float(e.get('roll', 0.0)) for _, e in dyn])
mu = np.array([float(e.get('mu', 0.5)) for _, e in dyn])
K = pb.ROLLING_K; EPS = pb.ROLLING_ANG_EPS
VS = pb.V_STALL_EPS; WS = pb.W_STALL_EPS; VY = pb.VY_STOP_GATE

def loop_python():
    """现有逐体 Python 数学段 (不含 Jolt 写回)"""
    for k in range(n):
        if ws[k]:
            aw = math.sqrt(angw[k,0]**2 + angw[k,1]**2 + angw[k,2]**2)
            if roll[k] > 0 and mu[k] > 0 and aw > EPS:
                f = 1.0 - mu[k]*roll[k]*K*dt
                if f < 0: f = 0.0
                if f < 1.0:
                    wv[k,0]*=f; wv[k,2]*=f; angw[k,:]*=f
            vh = math.sqrt(wv[k,0]**2 + wv[k,2]**2)
            if vh < VS and aw < WS and abs(wv[k,1]) < VY:
                wv[k,0]=0.0; wv[k,2]=0.0; angw[k,:]=0.0

def loop_numpy():
    """numpy 批量版 (同一数学)"""
    aw = np.sqrt((angw*angw).sum(axis=1))
    cond = (roll > 0) & (mu > 0) & (aw > EPS)
    f = np.where(cond, 1.0 - mu*roll*K*dt, 1.0)
    f = np.clip(f, 0.0, 1.0)
    apply = cond & (f < 1.0)
    wv[apply, 0] *= f[apply]; wv[apply, 2] *= f[apply]
    angw[apply, :] *= f[apply, None]
    vh = np.sqrt(wv[:,0]**2 + wv[:,2]**2)
    stall = (vh < VS) & (aw < WS) & (np.abs(wv[:,1]) < VY) & ws
    wv[stall, 0] = 0.0; wv[stall, 2] = 0.0; angw[stall, :] = 0.0

N = 500
def bench(label, fn):
    fn()
    t0 = time.perf_counter()
    for _ in range(N): fn()
    print("  %-28s %.4f ms" % (label, (time.perf_counter()-t0)/N*1000))

print("dyn bodies:", n, " (1200动态体规模)")
print("\n=== 摩擦/残速纯数学段 ===")
bench("逐体 Python 循环", loop_python)
bench("numpy 批量", loop_numpy)
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
