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
ed.orbit_mode=True; ed.camera_target=(0.0,0.0,0.0); ed.camera_distance=15.0
# 先渲染几帧让 _frame_world 就位
for _ in range(6):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
print("renderer.lod_levels=%r" % (m.renderer.lod_levels,))
print("renderer._lod_cur=%r" % (m.renderer._lod_cur,))
# 手动调一次 _update_lod 看异常
try:
    ed._update_lod()
    print("手动 _update_lod OK, _lod_cur=%r" % (m.renderer._lod_cur,))
    print("mesh 顶点=%d" % len(m.renderer.mesh.vertices))
except Exception as e:
    import traceback; traceback.print_exc()
ed._stop_parallel(); import pygame; pygame.quit()
