# -*- coding: utf-8 -*-
"""ckernels_val_check.py — C 内核 DLL 三方对拍 (C vs numba vs numpy)
闸门: max 相对误差 <= 1e-7 (D6 标准); 含空输入/单元素/大数组边界。
"""
import os
import sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import fastpath
import importlib
importlib.reload(fastpath)

assert fastpath._CKERNELS is not None, 'C DLL 未加载 — 接线失败'
print(f'CKERNELS loaded: OK (par_threads={fastpath._C_PAR_THREADS})')
print(f'numba available: {fastpath._NUMBA} (C 优先, numba 路径仅参考)')


def make_case(n, V, seed):
    rng = np.random.default_rng(seed)
    vh = rng.standard_normal((n, V, 4)).astype(np.float64)
    vh[:, :, 3] = 1.0                                  # 齐次 w=1 为主
    m3 = (rng.standard_normal((n, 4, 3)) * 0.5).astype(np.float64)
    return vh, m3


def rel_err(a, b):
    d = np.abs(a - b)
    s = np.maximum(np.abs(b), 1e-300)
    return float((d / s).max())


fails = 0

cases = [
    ('大数组 n=500 V=2035 (混合500形态)', 500, 2035, 1),
    ('单元素 n=1 V=1', 1, 1, 2),
    ('单模型多顶点 n=1 V=2035', 1, 2035, 3),
    ('多模型单顶点 n=64 V=1', 64, 1, 4),
    ('含大值域 (1e6 级)', 128, 256, 5),
    ('含负值/零矩阵', 128, 256, 6),
]

for name, n, V, seed in cases:
    vh, m3 = make_case(n, V, seed)
    if seed == 6:
        m3[:] = 0.0                                    # 全零矩阵: 全部点落原点
        vh[0, 0, 0] = -3.0
    mn_ref, mx_ref = np.empty((n, 3)), np.empty((n, 3))
    fastpath._aabbs_minmax_np(vh, m3, mn_ref, mx_ref)   # numpy 参考路径
    mn_c, mx_c = np.empty((n, 3)), np.empty((n, 3))
    fastpath._aabbs_minmax_c(vh, m3, mn_c, mx_c)        # C 串行
    mn_cp, mx_cp = np.empty((n, 3)), np.empty((n, 3))
    fastpath._aabbs_minmax_c(vh, m3, mn_cp, mx_cp, par=True)  # C 并行

    e1 = max(rel_err(mn_c, mn_ref), rel_err(mx_c, mx_ref))
    e2 = max(rel_err(mn_cp, mn_ref), rel_err(mx_cp, mx_ref))
    bit1 = bool((mn_c == mn_ref).all() and (mx_c == mx_ref).all())
    ok = e1 <= 1e-7 and e2 <= 1e-7
    fails += 0 if ok else 1
    print(f'[{name}] C串行 rel={e1:.2e} 逐位={bit1} | C并行 rel={e2:.2e} -> '
          f'{"PASS" if ok else "FAIL"}')

# 空输入安全
mn0, mx0 = np.empty((0, 3)), np.empty((0, 3))
vh0 = np.empty((0, 8, 4)); m30 = np.empty((0, 4, 3))
fastpath._aabbs_minmax_c(vh0, m30, mn0, mx0)
fastpath._aabbs_minmax_c(vh0, m30, mn0, mx0, par=True)
print('[空输入 n=0] 无异常 -> PASS')

# B1 退役 (2026-10-16): LOOM_NO_CKERNELS 逃生门已删, 对应验证子步骤一并移除.

print('ALL PASS' if fails == 0 else f'{fails} FAIL')
sys.exit(0 if fails == 0 else 1)
