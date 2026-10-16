# -*- coding: utf-8 -*-
"""prof_post_sections.py — post_step逐段计时 (2026-10-14)"""
import os, sys, time, math
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import numpy as np
import moderngl
import editor as editor_mod
import physics_bridge as pb
from physics_bridge import quat_to_euler_batch, model_world_matrix, world_rotation_3x3, engine_mat3_from_quat

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
for _ in range(40): ed._logic_frame(clk.fixed_dt)
br = ed._phys_bridge; w = br._w

S={}
def T(name, fn):
    t=time.perf_counter(); r=fn(); S[name]=S.get(name,0)+time.perf_counter()-t; return r

N=40
# 预热
for _ in range(3): br.post_step()
S.clear()
for _ in range(N):
    T('a_read', lambda: (np.asarray(w.user_data).reshape(-1).astype(np.int64),
                         np.asarray(w.positions).reshape(-1,4),
                         np.asarray(w.rotations).reshape(-1,4),
                         np.asarray(w.velocities).reshape(-1,4)))
    ud=np.asarray(w.user_data).reshape(-1).astype(np.int64)
    pos=np.asarray(w.positions).reshape(-1,4); rotsq=np.asarray(w.rotations).reshape(-1,4); vel=np.asarray(w.velocities).reshape(-1,4)
    T('b_argsort', lambda: np.argsort(ud))
    order=np.argsort(ud); ids=ud[order]
    T('c_rowmap', lambda: (np.full(max(br._next_id,1),-1,dtype=np.int64)))
    row_full=np.full(max(br._next_id,1),-1,dtype=np.int64); okm=ids<len(row_full); row_full[ids[okm]]=order[okm]
    dyn=[(i,e) for i,e in enumerate(br._entries) if e['motion']==pb.cv.MOTION_DYNAMIC]
    T('d_dynlist', lambda: None)
    T('e_r_all', lambda: np.array([row_full[e['id']] for _,e in dyn], dtype=np.int64))
    r_all=np.array([row_full[e['id']] for _,e in dyn],dtype=np.int64)
    valid=r_all>=0; r_sub=r_all[valid]
    T('f_gather', lambda: (pos[r_sub,:3].astype(np.float64), rotsq[r_sub].astype(np.float64), vel[r_sub,:3].astype(np.float64)))
    wp=pos[r_sub,:3].astype(np.float64); wq=rotsq[r_sub].astype(np.float64); wv=vel[r_sub,:3].astype(np.float64)
    T('g_quateuler', lambda: quat_to_euler_batch(wq))
    lpq=quat_to_euler_batch(wq)
    T('h_activeok', lambda: np.array([br._active_ok(e['handle']) for _,e in dyn])[valid])
    T('i_angw', lambda: np.asarray(w.angular_velocities).reshape(-1,4)[r_sub,:3].astype(np.float64))
    # 主写回循环
    def loop():
        for k,((_,ent),ok) in enumerate(zip(dyn,valid)):
            if not ok: continue
            m=ent['model']; rb=getattr(m,'rigidbody',None); p=getattr(m,'parent',None)
            fr=(float(wv[k,0]),float(wv[k,1]),float(wv[k,2]))
            lp=(float(wp[k,0]),float(wp[k,1]),float(wp[k,2]))
            lrot=lpq[k]
            m.position=pb.Point3D(lp[0],lp[1],lp[2])
            m.rotation=pb.Point3D(float(lrot[0]),float(lrot[1]),float(lrot[2]))
            if rb is not None: rb.velocity=pb.Point3D(fr[0],fr[1],fr[2])
            sync=br._last_sync.get(id(m))
    T('j_writeback', loop)

print("post_step 逐段 (每帧 ms):")
tot=0
for k in sorted(S):
    v=S[k]/N*1000; tot+=v
    print("  %-14s %.4f ms" % (k, v))
print("  %-14s %.4f ms" % ("合计", tot))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
