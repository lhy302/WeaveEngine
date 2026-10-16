# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl, editor as editor_mod
import engine as E, sceneio
from mesh import create_cube
from loom_texture import Texture
from loom_material import Material

ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(320,240,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))

# 造带 PBR + 贴图 + env 的材质
arr=np.zeros((16,16,4),dtype=np.uint8); arr[:,:,0]=200
tex=Texture.from_rgba(16,16,arr,name='测试贴图')
mat=Material(name='PBR材质', metallic=0.7, roughness=0.25, pbr=True, albedo=tex)
m=ed.add_model(create_cube(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0), name='测试块')
m.renderer.material=mat
print("保存前: metallic=%.2f roughness=%.2f pbr=%s albedo=%s" % (
    mat.metallic, mat.roughness, mat.pbr, mat.albedo.name if mat.albedo else None))

# 完整保存
sp=os.path.join(BASE,'tests','_tmp','_mat_roundtrip.json')
sceneio.save_scene_data(sp, sceneio.scene_to_dict(ed))
print("保存 OK")
# 检查 dict
d=sceneio.scene_to_dict(ed)
print("scene dict materials:", [(mm.get('name'), mm.get('pbr'), mm.get('metallic'), mm.get('albedo') is not None) for mm in d['materials']])

# 重载
ed.load_scene(sp)
print("重载后材质数:", len(ed.materials))
for mm in ed.materials:
    print("  材质 %s: pbr=%s metallic=%s albedo=%s env=%s" % (
        mm.name, getattr(mm,'pbr',None), getattr(mm,'metallic',None),
        mm.albedo.name if getattr(mm,'albedo',None) else None,
        mm.env_map.name if getattr(mm,'env_map',None) else None))
# 物体绑的材质
if ed.models:
    om=ed.models[0].renderer.material
    print("  物体0 材质: %s pbr=%s albedo=%s" % (
        om.name, getattr(om,'pbr',None),
        om.albedo.name if getattr(om,'albedo',None) else None))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
