# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import ast
for f in ('loom_render.py','loom_model_gpu.py','loom_shaders.py','loom_material.py','loom_texture.py','mesh.py','engine.py'):
    ast.parse(open(os.path.join(BASE,f),encoding='utf-8').read())
print("parse ok")
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(800,600,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_综合_小镇.json'))
for _ in range(30):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
print("渲染 30 帧 OK, 桶数=%d, 白纹理=%s" % (len(ed._render_buckets), ed._white_tex is not None))
alb = getattr(ed, '_bucket_albedo', {})
print("桶 albedo 表: %d 桶, 其中非 None=%d (应全 None=无贴图)" % (len(alb), sum(1 for v in alb.values() if v is not None)))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
