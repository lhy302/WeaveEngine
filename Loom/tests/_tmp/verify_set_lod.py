# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
import engine as E, agent_commands as ac
from mesh import create_sphere
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(320,240,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))
m=ed.add_model(create_sphere(0.5,16,24), E.Point3D(0,0,0), E.Point3D(0,0,0), name='LOD球')
class _Win: editor=ed
print("=== set_lod 自动生成 ===")
r=ac.dispatch('set_lod', {'name':'LOD球','screen':0.1}, _Win())
print("  ->", r.get('result'))
print("  lod_screen_levels:", None if m.renderer.lod_screen_levels is None else [x[0] for x in m.renderer.lod_screen_levels])
print("=== set_lod bias ===")
r2=ac.dispatch('set_lod', {'name':'LOD球','bias':4.0}, _Win())
print("  bias ->", m.renderer.lod_bias)
print("=== set_lod 关闭 ===")
r3=ac.dispatch('set_lod', {'name':'LOD球','on':False}, _Win())
print("  ->", r3.get('result'), " levels=", m.renderer.lod_screen_levels)
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
