# -*- coding: utf-8 -*-
import os, sys, time, statistics
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod, physics_bridge as pb
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_渲染_实例化2000球.json'))
ed.toggle_play(); clk=ed._ensure_split()
for _ in range(20): ed._logic_frame(clk.fixed_dt)
br=ed._phys_bridge; dt=clk.sub_dt; g=-9.8
ndyn=sum(1 for e in br._entries if e['motion']==pb.cv.MOTION_DYNAMIC)
print("静态场景: entries=%d 动态体=%d" % (len(br._entries), ndyn))
N=40
for label,fn in (('pre_step',lambda:br.pre_step(dt,g)),('step',lambda:br.step(dt)),('post_step',lambda:br.post_step())):
    fn(); t0=time.perf_counter()
    for _ in range(N): fn()
    print("  %-10s %.3f ms" % (label,(time.perf_counter()-t0)/N*1000))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
