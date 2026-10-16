# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod

def render_read(scene, no_frustum):
    ctx=moderngl.create_standalone_context()
    ed=editor_mod.EditorApp(640,480,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
    # ★B7b 退役 (2026-10-16): 改设置项 _frustum_cull (原 LOOM_NO_FRUSTUM env 已退役)
    if no_frustum: ed._frustum_cull = False
    try:
        _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
    except Exception: pass
    ed.load_scene(os.path.join(BASE,'保存','压力测试',scene))
    for _ in range(30):
        now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
    ed.render(1/60)
    fb=ed._screen_fb()
    w,h=fb.size
    ctx.finish()
    raw=fb.read(viewport=(0,0,w,h), components=3, alignment=1)
    arr=np.frombuffer(raw,dtype=np.uint8)
    print("  read bytes=%d  期望=%d  (w=%d h=%d)" % (len(raw), w*h*3, w, h))
    arr=arr[:w*h*3].reshape(h,w,3)
    ed._stop_parallel()
    return arr

a=render_read('压力_综合_小镇.json', False)
b=render_read('压力_综合_小镇.json', True)
h,w,_=a.shape
ca=a[h//4:3*h//4, w//4:3*w//4].astype(int)
cb=b[h//4:3*h//4, w//4:3*w//4].astype(int)
diff=np.abs(ca-cb)
print("中心区 平均差=%.2f 最大差=%d 显著差异占比=%.1f%%" % (
    diff.mean(), diff.max(), (diff>30).any(axis=2).mean()*100))
import pygame; pygame.quit()
print("完成")
