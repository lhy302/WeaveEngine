# -*- coding: utf-8 -*-
"""prof_phys_loop.py — 物理循环体逐操作计时 (2026-10-14)"""
import os, sys, time, math
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import numpy as np
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
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_物理_动态1200刚体.json'))
ed.toggle_play()
clk = ed._ensure_split()
for _ in range(20):
    ed._logic_frame(clk.fixed_dt)
br = ed._phys_bridge
dt = clk.sub_dt; g = getattr(ed, 'gravity', -9.8)

# 冻结数据快照
br.pre_step(dt, g)
br.step(dt)
entries = br._entries
dyn = [(i, e) for i, e in enumerate(entries) if e['motion'] == br._w and True]  # placeholder
import physics_bridge as pb
dyn = [(i, e) for i, e in enumerate(entries) if e['motion'] == pb.cv.MOTION_DYNAMIC]
print("entries:", len(entries), " dyn:", len(dyn), flush=True)

N = 200
def bench(label, fn):
    fn()
    t0 = time.perf_counter()
    for _ in range(N): fn()
    print("  %-42s %.4f ms" % (label, (time.perf_counter()-t0)/N*1000), flush=True)

# 候选1: 列表推导 row_full[e['id']]
row_full = np.full(2000, 0, dtype=np.int64)
bench("list comp [row_full[e['id']] for dyn] x1200", lambda: [row_full[e['id']] for _, e in dyn])
# 候选2: np.array 那个列表
bench("np.array([...] for dyn) x1200", lambda: np.array([row_full[e['id']] for _, e in dyn], dtype=np.int64))
# 候选3: Point3D 构造 x1200
p3 = Point3D(1.0,2.0,3.0)
bench("Point3D construct x1200", lambda: [Point3D(1.0,2.0,3.0) for _ in range(1200)])
# 候选4: getattr(rb,'velocity')
bench("getattr(m,'rigidbody') x1200", lambda: [getattr(e['model'],'rigidbody',None) for _,e in dyn])
# 候选5: _t3(velocity)
from physics_bridge import _t3
models=[e['model'] for _,e in dyn]
for m in models:
    if getattr(m,'rigidbody',None): 
        pass
def t3all():
    for m in models:
        rb=getattr(m,'rigidbody',None)
        if rb is not None:
            _t3(rb.velocity)
bench("loop getattr+_t3(velocity) x1200", t3all)
# 候选6: dict get id(m)
lm = br._last_sync
bench("self._last_sync.get(id(m)) x1200", lambda: [lm.get(id(m)) for _,e in dyn for m in [e['model']]])
# 候选7: math.sqrt x1200
bench("math.sqrt x1200", lambda: [math.sqrt(1.5) for _ in range(1200)])
# 候选8: 整段 post_step 的 writeback 循环体 (模拟)
def wb():
    cache=br._tmp_cache
    for k,(_,ent) in enumerate(dyn):
        m=ent['model']
        rb=getattr(m,'rigidbody',None)
        fr=(1.0,2.0,3.0)
        m.position=Point3D(1.0,2.0,3.0)
        m.rotation=Point3D(0.0,0.0,0.0)
        if rb is not None: rb.velocity=Point3D(1.0,2.0,3.0)
        sync=br._last_sync.get(id(m))
bench("模拟 writeback 循环体 x1200", wb)

ed._stop_parallel()
import pygame; pygame.quit()
print("完成", flush=True)
