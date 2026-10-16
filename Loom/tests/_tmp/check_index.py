# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod, physics_bridge as pb
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_物理_动态1200刚体.json'))
ed.toggle_play(); clk=ed._ensure_split()
for _ in range(20): ed._logic_frame(clk.fixed_dt)
br=ed._phys_bridge
w=br._w
ud=np.asarray(w.user_data).reshape(-1).astype(np.int64)
order=np.argsort(ud); ids=ud[order]
row_full=np.full(max(br._next_id,1),-1,dtype=np.int64)
okm=ids<len(row_full); row_full[ids[okm]]=order[okm]
dyn=[(i,e) for i,e in enumerate(br._entries) if e['motion']==pb.cv.MOTION_DYNAMIC]
r_all=np.array([row_full[e['id']] for _,e in dyn],dtype=np.int64)
valid=r_all>=0
print("dyn=%d valid全True=%s (True数=%d)" % (len(dyn), valid.all(), valid.sum()))
ws=np.array([br._active_ok(e['handle']) for _,e in dyn])
print("ws dtype=%s  样本=%s" % (ws.dtype, ws[:8]))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
