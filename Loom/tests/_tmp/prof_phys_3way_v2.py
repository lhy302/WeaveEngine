# -*- coding: utf-8 -*-
"""prof_phys_3way_v2.py — 严谨三方对拍 (2026-10-14)"""
import os, sys, time, math
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np
import physics_glue as pg

n = 1200
rng = np.random.default_rng(11)
wv0  = rng.uniform(-2, 2, (n, 3))
angw0= rng.uniform(-0.5, 0.5, (n, 3))
ws  = rng.integers(0, 2, n).astype(np.uint8)
isd = np.ones(n, dtype=np.uint8)
ug  = np.ones(n, dtype=np.uint8)
fr  = np.full(n, 0.5); rf = np.full(n, 0.1)
dt = 1.0/60.0; g = -9.8
K=23.0; EPS=0.06; VS=0.03; WS=0.3; VY=1.0

def py_full(wv, angw):
    wv=wv.copy(); angw=angw.copy()
    for k in range(n):
        if not isd[k]: continue
        if ug[k] and ws[k]:
            wv[k,1] += g*dt
        if ws[k]:
            aw=math.sqrt(angw[k,0]**2+angw[k,1]**2+angw[k,2]**2)
            if fr[k]>0 and rf[k]>0 and aw>EPS:
                f=1.0-fr[k]*rf[k]*K*dt
                if f<0: f=0.0
                if f<1.0:
                    angw[k,0]*=f; angw[k,1]*=f; angw[k,2]*=f
                    wv[k,0]*=f; wv[k,2]*=f
            vx,vy,vz=wv[k,0],wv[k,1],wv[k,2]
            vh=math.sqrt(vx*vx+vz*vz)
            if vh<VS and aw<WS and abs(vy)<VY:
                wv[k,0]=0.0; wv[k,2]=0.0
                angw[k,0]=0.0; angw[k,1]=0.0; angw[k,2]=0.0
    return wv, angw

def c_full(wv, angw):
    lv=np.ascontiguousarray(wv,dtype=np.float64).copy()
    av=np.ascontiguousarray(angw,dtype=np.float64).copy()
    pg.pre_step(lv, av, isd, ug, ws, fr, rf, g, dt)
    return lv, av

pv,pa = py_full(wv0, angw0)
cv,ca = c_full(wv0, angw0)
print("py vs C:  lv maxdiff=%.3e  av maxdiff=%.3e" % (np.abs(pv-cv).max(), np.abs(pa-ca).max()))
# 找出最大差异位置
d=np.abs(pv-cv); idx=np.unravel_index(d.argmax(), d.shape)
print("  最大差异行 %s: py=%s C=%s" % (idx, pv[idx[0]], cv[idx[0]]))
print("完成")
