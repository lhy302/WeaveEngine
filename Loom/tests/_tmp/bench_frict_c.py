# -*- coding: utf-8 -*-
"""bench_frict_c.py — 摩擦段 Python vs C接口 (2026-10-14)"""
import os, sys, time, math, statistics
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import numpy as np
import physics_glue as pg

n=1200
rng=np.random.default_rng(3)
# 稳态数据: 大部分小角速(不触发), 少数触发
wv0=rng.uniform(-0.05,0.05,(n,3))
angw0=rng.uniform(-0.1,0.1,(n,3))
ws=rng.integers(0,2,n).astype(np.uint8)
isd=np.ones(n,dtype=np.uint8); ug=np.ones(n,dtype=np.uint8)
fr=np.full(n,0.5); rf=np.full(n,0.1)
dt=1/60.0
K=23.0; EPS=0.06; VS=0.03; WS=0.3; VY=1.0

def py_frict(wv, angw):
    wv=wv.copy(); angw=angw.copy()
    changed=[]
    for k in range(n):
        if not ws[k]: continue
        a3=angw[k]
        aw=math.sqrt(a3[0]*a3[0]+a3[1]*a3[1]+a3[2]*a3[2])
        wrote=False
        if fr[k]>0 and rf[k]>0 and aw>EPS:
            f=1.0-fr[k]*rf[k]*K*dt
            if f<0: f=0.0
            if f<1.0:
                angw[k,0]*=f; angw[k,1]*=f; angw[k,2]*=f
                wv[k,0]*=f; wv[k,2]*=f
                wrote=True
        vh=math.sqrt(wv[k,0]*wv[k,0]+wv[k,2]*wv[k,2])
        if vh<VS and aw<WS and abs(wv[k,1])<VY:
            wv[k,0]=0.0; wv[k,2]=0.0; angw[k,0]=0.0; angw[k,1]=0.0; angw[k,2]=0.0
            wrote=True
        if wrote: changed.append(k)
    return wv,angw,changed

def c_frict(wv, angw):
    lv=np.ascontiguousarray(wv,dtype=np.float64).copy()
    av=np.ascontiguousarray(angw,dtype=np.float64).copy()
    pg.pre_step(lv,av,isd,ug,ws,fr,rf,0.0,dt)   # gravity_y=0 -> 纯摩擦+残速
    ch=np.where((lv!=wv).any(1)|(av!=angw).any(1))[0]
    return lv,av,ch

N=400; R=7
def med(fn):
    fn(); runs=[]
    for _ in range(R):
        t0=time.perf_counter()
        for _ in range(N): fn()
        runs.append((time.perf_counter()-t0)/N*1000)
    return statistics.median(runs)

pw,pa,pc = py_frict(wv0,angw0)
cw,ca,cc = c_frict(wv0,angw0)
print("逐位: lv maxdiff=%.2e av maxdiff=%.2e  changed集: py=%d c=%d 一致=%s"
      % (np.abs(pw-cw).max(), np.abs(pa-ca).max(), len(pc), len(cc), set(pc)==set(cc)))
print("Python逐体摩擦段: %.4f ms" % med(lambda: py_frict(wv0,angw0)))
print("C接口摩擦段(含copy+找变化): %.4f ms" % med(lambda: c_frict(wv0,angw0)))
print("完成")
