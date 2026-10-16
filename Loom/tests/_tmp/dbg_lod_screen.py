# -*- coding: utf-8 -*-
import os, sys, time, math
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod
import engine as E
from mesh import create_sphere
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(320,240,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))
hi=create_sphere(0.5,16,24); lo=create_sphere(0.5,6,8)
m=ed.add_model(hi, E.Point3D(0,0,0), E.Point3D(0,0,0), name='LOD球')
m.renderer.lod_screen_levels=[(0.1, hi), (0.0, lo)]
ed.orbit_mode=True; ed.camera_target=(0.0,0.0,0.0)

print("初始 camera_distance=", ed.camera_distance, " _fov=", ed._fov, " tan_half=", math.tan(ed._fov*0.5))
ed.camera_distance=30.0
for f in range(4):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
    cam=ed.camera
    # 手动复算
    fw=ed._frame_world
    c=np.asarray(fw[0],dtype=np.float64)[3,:3]
    dist=((c[0]-cam.x)**2+(c[1]-cam.y)**2+(c[2]-cam.z)**2)**0.5
    rad=0.5
    ratio=(rad/max(dist,1e-3)/math.tan(ed._fov*0.5))*1.0
    cur = "hi" if m.renderer.mesh is hi else ("lo" if m.renderer.mesh is lo else "?")
    print("帧%d: cam=(%.1f,%.1f,%.1f) 物体=%s dist=%.2f ratio=%.3f mesh=%s _lod_cur=%s" % (
        f, cam.x,cam.y,cam.z, tuple(round(x,1) for x in c), dist, ratio, cur,
        "hi" if m.renderer._lod_cur is hi else ("lo" if m.renderer._lod_cur is lo else "?")))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
