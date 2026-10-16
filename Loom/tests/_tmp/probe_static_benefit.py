# -*- coding: utf-8 -*-
import os, sys, time, statistics
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_综合_小镇.json'))
ed.toggle_play(); clk=ed._ensure_split()
for _ in range(40): ed._logic_frame(clk.fixed_dt)
N=50
def med(fn,R=5):
    fn(); r=[]
    for _ in range(R):
        t0=time.perf_counter()
        for _ in range(N): fn()
        r.append((time.perf_counter()-t0)/N*1000)
    return statistics.median(r)
print("compute_world_matrices (静止,应命中): %.3f ms" % med(lambda: ed.compute_world_matrices(ed.models)))
# 强制一个物体动 -> 缓存失效 -> 整批重算
m=ed.models[100]
from loom_types import Point3D
def move_and_calc():
    m.position=Point3D(m.position.x+0.001, m.position.y, m.position.z)
    return ed.compute_world_matrices(ed.models)
print("compute_world_matrices (一个动->整批重算): %.3f ms" % med(move_and_calc))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
