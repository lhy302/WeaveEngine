# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod
from matlib import mat4_view_yaw_pitch, mat4_perspective

ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_综合_小镇.json'))
for _ in range(30):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)

# 引擎剔除结果: 从 _main_bucket_n + _render_buckets 反推每桶主pass实例数
mbn = getattr(ed, '_main_bucket_n', {})
# 独立复算: 用引擎刚用的 _vp + fw 算每个物体可见性
vp = np.asarray(ed._vp, dtype=np.float64).reshape(4,4)
planes = ed._frustum_planes(vp)
fw = ed._frame_world
mr = getattr(ed, '_bucket_radius', {})
# 对每个桶的每个实例, 独立判定
total_main = sum(mbn.values())
# 独立判定可见数
from loom_game_object import GameObject
vis = np.zeros(len(ed.models), dtype=bool)
for i,m in enumerate(ed.models):
    if not m.visible or m.mesh is None: continue
    key = ed._mesh_key(m)
    r = mr.get(key, 1.0)
    c = np.asarray(fw[i], dtype=np.float64)[3,:3]
    vv = True
    for a,b,cc,dd in planes:
        if c[0]*a+c[1]*b+c[2]*cc+dd < -r: vv=False; break
    vis[i]=vv
indep = int(vis.sum())
print("引擎主pass可见=%d  独立复算可见=%d  一致=%s" % (total_main, indep, total_main==indep))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
