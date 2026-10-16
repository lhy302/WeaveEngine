# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod
import engine as E, sceneio, agent_commands as ac
from mesh import create_cube

import pygame
pygame.init()
surf=pygame.Surface((32,32)); surf.fill((200,60,30))
texpath=os.path.join(BASE,'tests','_tmp','_test_albedo.png')
pygame.image.save(surf, texpath)
print("测试贴图:", texpath)

ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(400,400,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))
m=ed.add_model(create_cube(2.0), E.Point3D(0,0,0), E.Point3D(0,0,0), name='测试方块')
class _Win: editor=ed
r=ac.dispatch('set_texture', {'name':'测试方块','path':texpath}, _Win())
print("set_texture ->", r)
mat=m.renderer.material
print("材质 albedo:", mat.albedo.name if mat.albedo else None)

d=sceneio._emit_material(mat)
print("_emit_material albedo:", d.get('albedo'))
ed2=editor_mod.EditorApp(400,400,ctx=ctx); ed2._external_fb=ctx.detect_framebuffer()
sceneio._apply_materials(ed2, [d])
mat2=ed2.materials[0]
print("重建材质 albedo:", mat2.albedo.name if mat2.albedo else None,
      " size=", (mat2.albedo.width, mat2.albedo.height) if mat2.albedo else None,
      " guid一致=", mat2.albedo.guid==mat.albedo.guid if mat2.albedo else None)

r2=ac.dispatch('set_texture', {'name':'测试方块','path':''}, _Win())
print("清除 ->", r2, " albedo=", m.renderer.material.albedo)

# 错误路径
r3=ac.dispatch('set_texture', {'name':'测试方块','path':'不存在.png'}, _Win())
print("错误路径 ->", r3)

os.remove(texpath)
ed._stop_parallel(); ed2._stop_parallel(); pygame.quit()
print("完成")
