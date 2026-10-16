# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import ast
ast.parse(open(os.path.join(BASE,'loom_lighting.py'),encoding='utf-8').read()); print("loom_lighting parse ok")
os.environ['LOOM_PROFILE'] = '1'
import moderngl
import editor as editor_mod
from loom_types import Point3D
ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda* a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_综合_小镇.json'))
for _ in range(15):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)

cnt={'vp':0}
_cv = ed._compute_light_vps
def wv(*a,**k):
    cnt['vp']+=1; return _cv(*a,**k)
ed._compute_light_vps = wv

# 静止60帧
cnt['vp']=0
ed._stage_times.clear()
t0=time.perf_counter()
for _ in range(60):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
w=(time.perf_counter()-t0)/60*1000
print("编辑态静止 render: %.2f ms/frame  _compute_light_vps 实算 %d/60 帧" % (w, cnt['vp']))
print("  shadow_prep=%.3f ms/frame" % (ed._stage_times.get('shadow_prep',0)/60))

# 移动一个物体后测（应触发重算）
m = ed.models[10]
cnt['vp']=0
t0=time.perf_counter()
for i in range(30):
    m.position = Point3D(m.position.x+0.01, m.position.y, m.position.z)  # 每帧移动
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
print("编辑态移动 render: %.2f ms/frame  _compute_light_vps 实算 %d/30 帧 (应≈30)" % ((time.perf_counter()-t0)/30*1000, cnt['vp']))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
