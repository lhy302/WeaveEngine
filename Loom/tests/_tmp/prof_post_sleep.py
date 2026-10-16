# -*- coding: utf-8 -*-
"""prof_post_sleep.py — 睡眠体写回浪费验证 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import numpy as np
import moderngl
import editor as editor_mod
import physics_bridge as pb

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
for _ in range(60): ed._logic_frame(clk.fixed_dt)   # 跑久点让球落定
br = ed._phys_bridge

# 统计睡眠体数
dyn = [(i, e) for i, e in enumerate(br._entries) if e['motion'] == pb.cv.MOTION_DYNAMIC]
active = sum(1 for _, e in dyn if br._active_ok(e['handle']))
print("动态体 %d, 其中活跃(清醒) %d, 睡眠 %d" % (len(dyn), active, len(dyn)-active))

# 测"完整post_step" vs "跳过睡眠体写回" 的时间
N=40
t0=time.perf_counter()
for _ in range(N): br.post_step()
print("完整 post_step: %.3f ms" % ((time.perf_counter()-t0)/N*1000))

# 手动模拟: 只做活跃体写回
def post_skip_sleep():
    w=br._w
    ud=np.asarray(w.user_data).reshape(-1).astype(np.int64)
    pos=np.asarray(w.positions).reshape(-1,4)
    rotsq=np.asarray(w.rotations).reshape(-1,4)
    vel=np.asarray(w.velocities).reshape(-1,4)
    from physics_bridge import quat_to_euler_batch
    order=np.argsort(ud); ids=ud[order]
    row_full=np.full(max(br._next_id,1),-1,dtype=np.int64)
    okm=ids<len(row_full); row_full[ids[okm]]=order[okm]
    cache=br._tmp_cache; cache.clear()
    cnt=0
    for i,e in dyn:
        r=row_full[e['id']]
        if r<0: continue
        if not br._active_ok(e['handle']): continue   # 跳过睡眠体
        m=e['model']
        wp=pos[r,:3].astype(np.float64); wq=rotsq[r].astype(np.float64); wv=vel[r,:3].astype(np.float64)
        from physics_bridge import quat_to_euler_batch
        lpq=quat_to_euler_batch(wq[np.newaxis,:])[0]
        m.position=pb.Point3D(float(wp[0]),float(wp[1]),float(wp[2]))
        m.rotation=pb.Point3D(float(lpq[0]),float(lpq[1]),float(lpq[2]))
        rb=getattr(m,'rigidbody',None)
        if rb is not None: rb.velocity=pb.Point3D(float(wv[0]),float(wv[1]),float(wv[2]))
        cnt+=1
    return cnt
nw=post_skip_sleep()
t0=time.perf_counter()
for _ in range(N): post_skip_sleep()
print("跳过睡眠体写回(仅%d活跃): %.3f ms" % (nw, (time.perf_counter()-t0)/N*1000))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
