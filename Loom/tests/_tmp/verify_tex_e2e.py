# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod
from loom_texture import Texture
from loom_material import Material
from mesh import create_cube
import engine as E

ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(400,400,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass

# 棋盘纹理 64x64
arr=np.zeros((64,64,4),dtype=np.uint8)
arr[:32,:32]=[255,0,0,255]; arr[:32,32:]=[0,255,0,255]
arr[32:,:32]=[0,0,255,255]; arr[32:,32:]=[255,255,0,255]
tex=Texture.from_rgba(64,64,arr,name='棋盘')

ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_空场景.json'))
# 两个立方体: 一个带贴图 一个不带
mat_tex=Material(color=None, name='贴图材质', albedo=tex)
mat_plain=Material(color='#888888', name='纯色材质')
m1=ed.add_model(create_cube(2.0), E.Point3D(-1.5,0,0), E.Point3D(0,0,0), name='贴图方块')
m1.renderer.material=mat_tex
m2=ed.add_model(create_cube(2.0), E.Point3D(1.5,0,0), E.Point3D(0,0,0), name='纯色方块')
m2.renderer.material=mat_plain
print("m1 tex_guid=%s  m2 tex_guid=%r" % (mat_tex._tex_guid[:8], mat_plain._tex_guid))

for _ in range(15):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)

print("桶数=%d" % len(ed._render_buckets))
for k,idxs in ed._render_buckets:
    tg = k[3] if len(k)>3 else None
    print("  桶 %s tex=%s 实例=%d" % (k[0], (tg[:8] if tg else '(无)'), len(idxs)))
alb=getattr(ed,'_bucket_albedo',{})
print("albedo 非None桶数=%d / %d" % (sum(1 for v in alb.values() if v is not None), len(alb)))

# 读像素尝试
fb=ed._screen_fb()
print("screen_fb.size =", fb.size)
try:
    ctx.finish()
    raw=fb.read(components=3)
    print("fb.read 返回字节:", len(raw), "期望", fb.size[0]*fb.size[1]*3)
except Exception as e:
    print("fb.read 异常:", e)
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
