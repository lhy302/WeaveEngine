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
ed.orbit_mode=True; ed.camera_target=(0.0,0.0,0.0)

def pick_name():
    return "hi" if m.renderer.mesh is hi else ("lo" if m.renderer.mesh is lo else "?")
def settle(dist):
    ed.camera_distance=dist
    for _ in range(6):
        now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)

print("=== 屏幕占比模式 (阈值0.1) ===")
m.renderer.lod_screen_levels=[(0.1,hi),(0.0,lo)]; m.renderer.lod_levels=None
settle(2.0);  print("  距 2  ->", pick_name(), "(期望 hi)")
settle(30.0); print("  距 30 ->", pick_name(), "(期望 lo)")
settle(2.0);  print("  回近距 ->", pick_name(), "(期望 hi)")

print("=== lod_bias (Unity: bias大=更高质量=更晚降级) ===")
m.renderer.lod_bias=1.0; settle(12.0); print("  bias=1.0 距12 ->", pick_name())
m.renderer.lod_bias=8.0; settle(12.0); print("  bias=8.0 距12 ->", pick_name(), "(bias大应更可能 hi)")
m.renderer.lod_bias=1.0

print("=== 距离模式向后兼容 ===")
m.renderer.lod_screen_levels=None; m.renderer.lod_levels=[(5.0,hi),(20.0,lo)]
settle(3.0);  print("  距 3  ->", pick_name(), "(期望 hi)")
settle(15.0); print("  距 15 ->", pick_name(), "(期望 lo)")
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
