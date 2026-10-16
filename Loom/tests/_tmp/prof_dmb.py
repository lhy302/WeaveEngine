# -*- coding: utf-8 -*-
import os, sys, time, statistics
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np, moderngl, editor as editor_mod, physics_bridge as pb
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_渲染_实例化2000球.json'))
ed.toggle_play(); clk=ed._ensure_split()
for _ in range(20): ed._logic_frame(clk.fixed_dt)
br=ed._phys_bridge
entries=br._entries
N=50
def build_lists():
    ids=[];rows=[];syncs=[];parents=[]
    for e in entries:
        m=e['model']; sync=br._sync_of(m)
        ids.append(id(m)); p=m.position; r=m.rotation
        rows.append((p.x,p.y,p.z,r.x,r.y,r.z)); syncs.append(sync)
        parents.append(id(getattr(m,'parent',None)))
    return ids,rows,syncs,parents
build_lists(); t0=time.perf_counter()
for _ in range(N): build_lists()
print("_dirty_mask_batch 列表构建循环: %.3f ms" % ((time.perf_counter()-t0)/N*1000))
# 缓存命中时, _dirty_mask_batch 总耗时
t0=time.perf_counter()
for _ in range(N): br._dirty_mask_batch(entries)
print("_dirty_mask_batch 总(应缓存命中): %.3f ms" % ((time.perf_counter()-t0)/N*1000))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
