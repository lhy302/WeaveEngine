# -*- coding: utf-8 -*-
import os, sys, time
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
for _ in range(30):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
vp = np.asarray(ed._vp, dtype=np.float64).reshape(4,4)
print("vp[0]:", vp[0])
planes = ed._frustum_planes(vp)
print("planes.shape:", planes.shape)
for i,nm in enumerate(('L','R','B','T','N','F')):
    print("  %s: %s" % (nm, planes[i]))
fw = ed._frame_world
print("fw.shape:", fw.shape, "fw[0]:", fw[0])
keep = ed._frustum_keep(fw, planes, 1.0)
print("keep.sum=%d / %d" % (keep.sum(), len(keep)))
# 手动算第一个的中心
c = np.asarray(fw[0],dtype=np.float64)[3,:3]
print("obj0 center:", c)
for a,b,cc,d in planes:
    print("  dist=%.2f (plane a=%.2f b=%.2f c=%.2f d=%.2f)" % (c[0]*a+c[1]*b+c[2]*cc+d, a,b,cc,d))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
