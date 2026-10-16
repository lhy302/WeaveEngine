# -*- coding: utf-8 -*-
r"""aabbs_gate_check.py — 批4A 闸门校正对拍网 (2026-09-07)

断言:
  1. C 内核串行 vs 并行 输出**逐位一致** (容差口径 ≤6.9e-14, 实测 0):
     边界含 零矩阵/单位矩阵/多层树状层级矩阵/奇异矩阵/n×V 跨闸门两侧。
  2. 闸门行为: n×V >= _AABB_PAR_MIN_WORK → 并行档; 不足 → 串行档
     (高 V 小 n 组与低 V 大 n 组两侧都不误开, 引擎真实调用路径 hook 验证)。
  3. 引擎 _aabbs_batched 输出: 并行档开启前后逐位一致 (monkeypatch 对照)。
"""
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'      # 走 C 内核 (与编译版同形态)

import numpy as np
import fastpath
from engine import GLEngine
from mesh import create_sphere, create_cube

fails = 0


def check(name, ok):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        fails += 1


W = GLEngine._AABB_PAR_MIN_WORK
print(f"_AABB_PAR_MIN_WORK = {W}  (旧 n-only 闸门 _AABB_PAR_MIN_MODELS = "
      f"{GLEngine._AABB_PAR_MIN_MODELS}, 仅探针兼容保留)")

# ---------- 1. C 内核 串行 vs 并行 逐位 ----------
rng = np.random.default_rng(20260907)
V = 2035

def case_mats(n, mode):
    vh = rng.standard_normal((n, V, 4))
    vh[:, :, 3] = 1.0
    m3 = (rng.standard_normal((n, 4, 3)) * 0.5)
    if mode == 'zero':
        m3[:] = 0.0
    elif mode == 'identity':
        m3[:] = 0.0
        m3[:, 0, 0] = m3[:, 1, 1] = m3[:, 2, 2] = 1.0
    elif mode == 'tree':                       # 多层树: 子=父@局部 (链式合成)
        for i in range(n):
            k = i % 7                          # 深度 1..7 层
            acc = m3[i].copy()                 # (4,3) 切片
            for _ in range(k):
                nxt = np.zeros((4, 3))
                # acc (4,3) 左乘同一局部 (4,3): 线性段复合 + 平移链
                nxt[:3, :3] = acc[:3, :3] @ m3[i, :3, :3]
                nxt[3, :3] = acc[3, :3] @ m3[i, :3, :3] + m3[i, 3, :3]
                acc = nxt
            m3[i] = acc
    elif mode == 'singular':                   # 奇异矩阵 (scale 压扁)
        m3[:, 2, :] = 0.0
    return vh.astype(np.float64), m3.astype(np.float64)

cases = [
    ('随机 n=400 V=2035 (跨闸门下侧)', 400, 'rand'),
    ('随机 n=450 V=2035', 450, 'rand'),
    ('随机 n=500 V=2035 (混合500形态)', 500, 'rand'),
    ('随机 n=100 V=3015 (高V大n)', 100, 'rand'),
    ('零矩阵 n=500', 500, 'zero'),
    ('单位矩阵 n=500', 500, 'identity'),
    ('多层树 1..7 层合成 n=448', 448, 'tree'),
    ('奇异矩阵 n=384', 384, 'singular'),
    ('单模型 n=1 V=2035', 1, 'rand'),
]
for name, n, mode in cases:
    vh, m3 = case_mats(n, mode)
    mn_s, mx_s = np.empty((n, 3)), np.empty((n, 3))
    mn_p, mx_p = np.empty((n, 3)), np.empty((n, 3))
    fastpath._aabbs_minmax_c(vh, m3, mn_s, mx_s)
    fastpath._aabbs_minmax_c(vh, m3, mn_p, mx_p, par=True)
    bit = bool((mn_s == mn_p).all() and (mx_s == mx_p).all())
    d = max(float(np.abs(mn_s - mn_p).max()), float(np.abs(mx_s - mx_p).max()))
    check(f"{name} 串行==并行 逐位 (maxdiff={d:.1e})", bit)

# ---------- 2. 闸门行为 (引擎真实调用路径 hook) ----------
SER = Counter(); PAR = Counter()
_ser_orig = fastpath.aabbs_minmax
_par_orig = fastpath.aabbs_minmax_par

def ser_hook(vh, m3, a, b):
    SER[(int(vh.shape[0]), int(vh.shape[1]))] += 1
    return _ser_orig(vh, m3, a, b)

def par_hook(vh, m3, a, b):
    PAR[(int(vh.shape[0]), int(vh.shape[1]))] += 1
    return _par_orig(vh, m3, a, b)

fastpath.aabbs_minmax = ser_hook
fastpath.aabbs_minmax_par = par_hook

eng = GLEngine.__new__(GLEngine)
eng._bb_cache = {}
eng._aabb_staging = None
try:
    # 高 V 组: 100 模型 V=3015 (n×V=0.30M 达闸) → 必须并行
    sph = create_sphere(0.8, 44, 66)
    models = []
    for _ in range(100):
        m = type('M', (), {})(); m.mesh = sph; m.visible = True
        models.append(m)
    fw = np.stack([np.eye(4) for _ in range(100)])
    SER.clear(); PAR.clear()
    r_hi = eng._aabbs_batched(models, fw)
    hi = (sum(PAR.values()), sum(SER.values()))
    check(f"闸门开启: (100,V=3015) n×V={100*3015} >= {W} → 并行 "
          f"(par={hi[0]} ser={hi[1]})", hi[0] >= 1 and hi[1] == 0)

    # 低 V 组: 512 模型 V=24 cube (n×V=12288 远低于闸) → 必须串行
    cub = create_cube(1.0)
    models_c = []
    for _ in range(512):
        m = type('M', (), {})(); m.mesh = cub; m.visible = True
        models_c.append(m)
    fw_c = np.stack([np.eye(4) for _ in range(512)])
    SER.clear(); PAR.clear()
    r_lo = eng._aabbs_batched(models_c, fw_c)
    lo = (sum(PAR.values()), sum(SER.values()))
    check(f"闸门不误开: (512,V=24) n×V={512*24} < {W} → 串行 "
          f"(par={lo[0]} ser={lo[1]})", lo[0] == 0 and lo[1] >= 1)

    # 闸门边界下侧: n×V 略低于闸 → 串行
    models_b = models[:99]                        # 99×3015 = 298485 < 300000
    fw_b = fw[:99]
    SER.clear(); PAR.clear()
    r_b = eng._aabbs_batched(models_b, fw_b)
    bcnt = (sum(PAR.values()), sum(SER.values()))
    check(f"闸门下侧: (99,V=3015) n×V={99*3015} < {W} → 串行 "
          f"(par={bcnt[0]} ser={bcnt[1]})", bcnt[0] == 0 and bcnt[1] >= 1)

    # ---------- 3. 引擎输出 逐位: 并行档 vs 强制串行 ----------
    fastpath.aabbs_minmax_par = _par_orig         # 恢复后强制整路串行对照
    GLEngine._AABB_PAR_MIN_WORK = 10 ** 18        # 临时: 永不触发并行
    SER.clear(); PAR.clear()
    r_hi_ser = eng._aabbs_batched(models, fw)
    GLEngine._AABB_PAR_MIN_WORK = W
    same = all(
        a[0].x == b[0].x and a[0].y == b[0].y and a[0].z == b[0].z and
        a[1].x == b[1].x and a[1].y == b[1].y and a[1].z == b[1].z
        for a, b in zip(r_hi, r_hi_ser))
    check("引擎输出: (100,V=3015) 并行档 == 强制串行档 逐位", same and len(r_hi) == 100)
finally:
    fastpath.aabbs_minmax = _ser_orig
    fastpath.aabbs_minmax_par = _par_orig
    GLEngine._AABB_PAR_MIN_WORK = W

print("结果:", "ALL PASS" if fails == 0 else "FAIL")
sys.exit(0 if fails == 0 else 1)
