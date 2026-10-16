# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
import engine as E, sceneio, agent_commands as ac
from mesh import create_cube
from loom_cubemap import Cubemap

ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(320,240,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))
m=ed.add_model(create_cube(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0), name='反射块')
class _Win: editor=ed

print("=== set_env 纯色 ===")
r=ac.dispatch('set_env', {'name':'反射块','color':'#FF8800'}, _Win())
print("  ->", r.get('result'))
mat=m.renderer.material
print("  env_map:", mat.env_map.name if mat.env_map else None)

print("=== 桶键含 env ===")
k=ed._mesh_key(m)
print("  键长=%d 末位(env guid)=%s" % (len(k), k[-1][:8] if k[-1] else '(空)'))

print("=== 序列化 env ===")
d=sceneio._emit_material(mat)
print("  env_map 键:", d.get('env_map'))

print("=== 渲染不崩 (有 env + PBR 开启) ===")
mat.pbr=True; mat.metallic=0.8; mat.roughness=0.2
for _ in range(5): ed.render(1/60.0)
print("  渲染 OK, 桶数=%d" % len(ed._render_buckets))

print("=== 清除 env ===")
r2=ac.dispatch('set_env', {'name':'反射块'}, _Win())
print("  ->", r2.get('result'), " env=", m.renderer.material.env_map)
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
