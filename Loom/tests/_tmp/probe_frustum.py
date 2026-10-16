# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod

def run(scene):
    ctx=moderngl.create_standalone_context()
    ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
    try:
        _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
    except Exception: pass
    ed.load_scene(os.path.join(BASE,'保存','压力测试',scene))
    for _ in range(20):
        now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
    vp = np.asarray(ed._vp, dtype=np.float64).reshape(4,4)
    aabbs = ed._model_aabbs_par(ed.models, ed._frame_world, visible_only=True)
    n_vis=len(aabbs); culled=0
    for a in aabbs:
        mn,mx = a[0], a[1]
        xs=(mn.x,mx.x); ys=(mn.y,mx.y); zs=(mn.z,mx.z)
        corners=np.array([[xs[i],ys[j],zs[k],1.0] for i in(0,1) for j in(0,1) for k in(0,1)],
                         dtype=np.float64)
        clip = corners @ vp
        w=clip[:,3:4]; c=clip[:,0:3]
        if np.all(w<=0): culled+=1; continue
        out = (np.all(c[:,0:1]<-w) or np.all(c[:,0:1]>w) or
               np.all(c[:,1:2]<-w) or np.all(c[:,1:2]>w) or
               np.all(c[:,2:3]<-w) or np.all(c[:,2:3]>w))
        if out: culled+=1
    print("%-32s 可见=%d 视锥外=%d (%.0f%%)" % (scene, n_vis, culled, 100.0*culled/max(n_vis,1)))
    ed._stop_parallel()

for s in ('压力_综合_小镇.json','压力_渲染_实例化2000球.json','压力_物理_动态1200刚体.json'):
    try: run(s)
    except Exception as e:
        import traceback; traceback.print_exc()
import pygame; pygame.quit()
print("完成")
