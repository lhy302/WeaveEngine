# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np, moderngl, editor as editor_mod
import engine as E
from mesh import create_sphere
from loom_texture import Texture
from loom_material import Material

W, H = 512, 384
ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(W, H, ctx=ctx)
# 关键: 自建 FBO + 声明外部上下文, 让引擎渲染到它 (可读)
fbo = ctx.simple_framebuffer((W, H))
ed._external_ctx = True
ed._external_fb = fbo
try:
    _g = ed.view.gui.render; ed.view.gui.render = lambda *a, **k: _g(target=fbo)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_空场景.json'))

# 棋盘贴图
arr = np.zeros((64,64,4), dtype=np.uint8)
for y in range(64):
    for x in range(64):
        arr[y,x] = [255,51,51,255] if ((x//8)+(y//8))%2==0 else [51,51,255,255]
tex = Texture.from_rgba(64,64,arr,name='棋盘')
mat_tex = Material(color=None, name='贴图材质', albedo=tex)
mat_metal = Material(color='#B0B0B0', name='金属', metallic=1.0, roughness=0.2, pbr=True)
mat_rough = Material(color='#B0B0B0', name='粗糙', metallic=0.0, roughness=0.9, pbr=True)
ed.add_model(create_sphere(0.5,20,28), E.Point3D(-1.5,0,0), E.Point3D(0,0,0), name='AlbedoSphere').renderer.material = mat_tex
ed.add_model(create_sphere(0.5,20,28), E.Point3D(0,0,0), E.Point3D(0,0,0), name='MetalSphere').renderer.material = mat_metal
ed.add_model(create_sphere(0.5,20,28), E.Point3D(1.5,0,0), E.Point3D(0,0,0), name='RoughSphere').renderer.material = mat_rough
ed.orbit_mode = True; ed.camera_target=(0.0,0.0,0.0); ed.camera_distance=4.5
ed.camera_yaw=0.0; ed.camera_pitch=0.1
try:
    light = ed.add_light('directional'); light.intensity=1.2; light.direction=(0.5,-0.7,0.3)
except Exception as e: print("加光:", e)

for _ in range(20): ed.render(1/60.0)
ctx.finish()
raw = fbo.read(components=3, alignment=1)
print("read bytes:", len(raw), "期望:", W*H*3)
if len(raw) >= W*H*3:
    img = np.frombuffer(raw, dtype=np.uint8)[:W*H*3].reshape(H, W, 3)
    import pygame
    # 上下翻转 (GL 原点在左下)
    out = os.path.join(BASE, 'tests', '_tmp', 'loom_texture_ref.png')
    pygame.image.save(pygame.image.frombuffer(np.flipud(img).tobytes(), (W,H), 'RGB'), out)
    print("Loom 对照图:", out)
    print("中心像素采样: 左球", img[H//2, W//4].tolist(), " 中球", img[H//2, W//2].tolist(), " 右球", img[H//2, 3*W//4].tolist())
ed._stop_parallel(); pygame.quit()
print("完成")
