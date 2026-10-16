# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
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
m.renderer.lod_levels=[(5.0,hi),(20.0,lo)]
ed.orbit_mode=True
ed.camera_target=(0.0,0.0,0.0)
ed.camera_distance=15.0
for _ in range(6):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
print("orbit_mode=", ed.orbit_mode, " camera_distance=", ed.camera_distance)
print("ed.camera=", ed.camera)
fw=ed._frame_world
import numpy as np
c=fw[0][3][:3]
cam=ed.camera
dist=((c[0]-cam.x)**2+(c[1]-cam.y)**2+(c[2]-cam.z)**2)**0.5
print("物体世界位=", c, " 相机=", (cam.x,cam.y,cam.z), " dist=%.2f" % dist)
print("当前 mesh 顶点=", len(m.renderer.mesh.vertices), " lod_cur=", m.renderer._lod_cur is hi and 'hi' or (m.renderer._lod_cur is lo and 'lo' or '?'))
ed._stop_parallel(); import pygame; pygame.quit()
