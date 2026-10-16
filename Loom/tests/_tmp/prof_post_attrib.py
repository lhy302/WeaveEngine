# -*- coding: utf-8 -*-
"""prof_post_attrib.py — post_step主循环归因 (2026-10-14) v2"""
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
for _ in range(20): ed._logic_frame(clk.fixed_dt)
br = ed._phys_bridge; w = br._w

stats = {'angv':[0,0.0], 'linv':[0,0.0], 'p3d':[0,0.0]}
_osa=w.set_angular_velocity; _osl=w.set_linear_velocity
def wsa(*a,**k):
    t=time.perf_counter(); r=_osa(*a,**k); stats['angv'][0]+=1; stats['angv'][1]+=time.perf_counter()-t; return r
def wsl(*a,**k):
    t=time.perf_counter(); r=_osl(*a,**k); stats['linv'][0]+=1; stats['linv'][1]+=time.perf_counter()-t; return r
w.set_angular_velocity=wsa; w.set_linear_velocity=wsl
_OP3=pb.Point3D
def P3wrap(*a,**k):
    stats['p3d'][0]+=1
    return _OP3(*a,**k)
pb.Point3D=P3wrap

N=40
for _ in range(3): br.post_step()
stats['angv']=[0,0.0]; stats['linv']=[0,0.0]; stats['p3d']=[0,0.0]
t0=time.perf_counter()
for _ in range(N): br.post_step()
total=(time.perf_counter()-t0)/N*1000
print("post_step 总: %.3f ms/次" % total)
print("  set_angular_velocity: %6.0f 次, 累计 %.3f ms" % (stats['angv'][0]/N, stats['angv'][1]/N*1000))
print("  set_linear_velocity:  %6.0f 次, 累计 %.3f ms" % (stats['linv'][0]/N, stats['linv'][1]/N*1000))
print("  Point3D 构造:         %6.0f 次, 累计 %.3f ms" % (stats['p3d'][0]/N, stats['p3d'][1]/N*1000))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
