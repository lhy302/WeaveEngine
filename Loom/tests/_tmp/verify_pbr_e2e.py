# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
import engine as E, sceneio, agent_commands as ac
from mesh import create_cube
from loom_material import Material

ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(320,240,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))
m=ed.add_model(create_cube(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0), name='PBR块')
class _Win: editor=ed

print("=== set_pbr 命令 ===")
r=ac.dispatch('set_pbr', {'name':'PBR块','metallic':0.9,'roughness':0.2}, _Win())
print("  metallic/roughness ->", r.get('result'))
mat=m.renderer.material
print("  材质: metallic=%.2f roughness=%.2f pbr=%s" % (mat.metallic, mat.roughness, mat.pbr))
r2=ac.dispatch('set_pbr', {'name':'PBR块','smoothness':0.8}, _Win())
print("  smoothness=0.8 -> roughness=%.2f (应 0.2)" % mat.roughness)
r3=ac.dispatch('set_pbr', {'name':'PBR块','on':False}, _Win())
print("  关 PBR ->", mat.pbr)

print("=== 桶键含 PBR ===")
mat.pbr=True; mat.metallic=0.5; mat.roughness=0.3
k=ed._mesh_key(m)
print("  键长=%d 末位=%r" % (len(k), k[-1]))

print("=== 序列化 PBR ===")
mat.metallic=0.7; mat.roughness=0.4; mat.pbr=True
d=sceneio._emit_material(mat)
print("  metallic=%.2f roughness=%.2f pbr=%s" % (d['metallic'], d['roughness'], d['pbr']))
ed2=editor_mod.EditorApp(320,240,ctx=ctx); ed2._external_fb=ctx.detect_framebuffer()
sceneio._apply_materials(ed2, [d])
m2=ed2.materials[0]
print("  重建: metallic=%.2f roughness=%.2f pbr=%s" % (m2.metallic, m2.roughness, m2.pbr))

print("=== 场景渲染不崩 (PBR 默认关=向后兼容) ===")
for _ in range(5): ed.render(1/60.0)
print("  渲染 OK, 桶数=%d" % len(ed._render_buckets))
ed._stop_parallel(); ed2._stop_parallel(); import pygame; pygame.quit()
print("完成")
