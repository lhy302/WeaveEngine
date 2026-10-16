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
ed.orbit_mode = True
ed.camera_target = (0.0, 0.0, 0.0)
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))

hi = create_sphere(0.5, 16, 24)   # 高精度
lo = create_sphere(0.5, 6, 8)     # 低精度
m = ed.add_model(hi, E.Point3D(0,0,0), E.Point3D(0,0,0), name='LOD球')
m.renderer.lod_levels = [(5.0, hi), (20.0, lo)]
print("高精度顶点=%d 低精度顶点=%d" % (len(hi.vertices), len(lo.vertices)))

def settle(dist):
    ed.camera_distance = dist
    for _ in range(6):
        now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
    return m.renderer.mesh

r1 = settle(3.0)     # 距 3 -> 高精度
print("相机距 3  -> 选中顶点数 %d (应=%d 高精度) %s" % (len(r1.vertices), len(hi.vertices), r1 is hi))
r2 = settle(15.0)    # 距 15 -> 低精度
print("相机距 15 -> 选中顶点数 %d (应=%d 低精度) %s" % (len(r2.vertices), len(lo.vertices), r2 is lo))
r3 = settle(3.0)
print("相机距 3  -> 又回高精度 %s" % (r3 is hi))

# 无 LOD 物体零开销
m2 = ed.add_model(hi, E.Point3D(5,0,0), E.Point3D(0,0,0), name='普通球')
print("无 LOD 物体 lod_levels=%r (应 None)" % m2.renderer.lod_levels)
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
