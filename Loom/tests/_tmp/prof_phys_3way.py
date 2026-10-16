# -*- coding: utf-8 -*-
"""prof_phys_3way.py — 逐体/numpy/C接口 三方对比+对拍 (2026-10-14)"""
import os, sys, time, math
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np
import physics_glue as pg

n = 1200
rng = np.random.default_rng(7)
# 冻结输入
wv  = rng.uniform(-1, 1, (n, 3))
angw= rng.uniform(-0.5, 0.5, (n, 3))
ws  = rng.integers(0, 2, n).astype(np.uint8)      # is_active
isd = np.ones(n, dtype=np.uint8)                   # is_dynamic
ug  = np.ones(n, dtype=np.uint8)                   # use_gravity
fr  = np.full(n, 0.5)
rf  = np.full(n, 0.1)
dt = 1.0/60.0; g = -9.8
K=23.0; EPS=0.06; VS=0.03; WS=0.3; VY=1.0

def py_math(wv, angw, ws):
    wv=wv.copy(); angw=angw.copy()
    for k in range(n):
        if ws[k]:
            aw = math.sqrt(angw[k,0]**2+angw[k,1]**2+angw[k,2]**2)
            if 0.5>0 and 0.1>0 and aw>EPS:
                f=1.0-0.5*0.1*K*dt
                if f<0: f=0.0
                if f<1.0:
                    wv[k,0]*=f; wv[k,2]*=f; angw[k,:]*=f
            vh=math.sqrt(wv[k,0]**2+wv[k,2]**2)
            if vh<VS and aw<WS and abs(wv[k,1])<VY:
                wv[k,0]=0.0; wv[k,2]=0.0; angw[k,:]=0.0
    return wv, angw

def np_math(wv, angw, ws):
    wv=wv.copy(); angw=angw.copy()
    aw = np.sqrt((angw*angw).sum(1))
    cond=(0.5>0)&(0.1>0)&(aw>EPS)
    f=np.where(cond,1.0-0.5*0.1*K*dt,1.0); f=np.clip(f,0.0,1.0)
    ap=cond&(f<1.0)
    wv[ap,0]*=f[ap]; wv[ap,2]*=f[ap]; angw[ap,:]*=f[ap,None]
    vh=np.sqrt(wv[:,0]**2+wv[:,2]**2)
    st=(vh<VS)&(aw<WS)&(np.abs(wv[:,1])<VY)&(ws.astype(bool))
    wv[st,0]=0.0; wv[st,2]=0.0; angw[st,:]=0.0
    return wv, angw

def c_math(wv, angw, ws):
    # 组装(拷贝) + C 调用: 模拟接线成本
    lv = np.ascontiguousarray(wv, dtype=np.float64)
    av = np.ascontiguousarray(angw, dtype=np.float64)
    rc = pg.pre_step(lv, av, isd, ug, ws, fr, rf, g, dt)
    return lv, av

N=300
def bench(label, fn):
    fn(); t0=time.perf_counter()
    for _ in range(N): fn()
    print("  %-32s %.4f ms" % (label, (time.perf_counter()-t0)/N*1000))

print("n=%d  C可用:" % n, pg.status())
bench("逐体 Python", lambda: py_math(wv, angw, ws))
bench("numpy 批量", lambda: np_math(wv, angw, ws))
bench("C接口(含组装)", lambda: c_math(wv, angw, ws))

# 对拍: 三方结果是否一致
pv, pa = py_math(wv, angw, ws)
nv, na = np_math(wv, angw, ws)
cv_, ca = c_math(wv, angw, ws)
print("\n=== 数值对拍 ===")
print("  py vs numpy  maxdiff lv=%.2e av=%.2e" % (np.abs(pv-nv).max(), np.abs(pa-na).max()))
print("  py vs C      maxdiff lv=%.2e av=%.2e" % (np.abs(pv-cv_).max(), np.abs(pa-ca).max()))
print("完成")
