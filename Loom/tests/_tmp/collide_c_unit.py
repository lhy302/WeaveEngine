# -*- coding: utf-8 -*-
"""collide_c_unit.py — C 内核单元冒烟: 合成数据 C vs 引擎 numpy 段直译 逐位对比

常驻探针 (2026-09-07 collide_pairs C 化守护): 5 组随机形态 (盒/球混合, cand
乱序子集) + K=1 边界. 断言 C 输出与 numpy 参考直译**逐位含顺序一致**.
用法: py -3.12 tests\\_tmp\\collide_c_unit.py
"""
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
import fastpath


def numpy_ref(cmn, cmx, cand, tin, tout, bmn, bmx, scn, rad, kind, n):
    """engine.py numpy 段直译 (回退路径同构): 输出 (i<j, key 升序)"""
    K = len(cand)
    order = np.argsort(cmn[:, 0], kind='stable')
    blk = 64
    pu_l, pv_l = [], []
    for j0 in range(0, K, blk):
        j1 = min(j0 + blk, K)
        t_block = order[:j1]
        u_block = order[j0:j1]
        ok = cmx[t_block, 0][:, None] > cmn[u_block, 0][None, :]
        ii, jj = np.nonzero(ok)
        if ii.size:
            pu_l.append(t_block[ii])
            pv_l.append(u_block[jj])
    if not pu_l:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    pu = np.concatenate(pu_l)
    pv = np.concatenate(pv_l)
    keep = pu != pv
    pu, pv = pu[keep], pv[keep]
    yz_ok = ((cmn[pu, 1] < cmx[pv, 1]) & (cmn[pv, 1] < cmx[pu, 1]) &
             (cmn[pu, 2] < cmx[pv, 2]) & (cmn[pv, 2] < cmx[pu, 2]))
    pu, pv = pu[yz_ok], pv[yz_ok]
    ci = cand
    mi = np.minimum(ci[pu], ci[pv])
    mj = np.maximum(ci[pu], ci[pv])
    key = np.unique(mi * (n + 1) + mj)
    mi, mj = key // (n + 1), key % (n + 1)
    related = ((tin[mi] <= tin[mj]) & (tin[mj] < tout[mi])) | \
              ((tin[mj] <= tin[mi]) & (tin[mi] < tout[mj]))
    ai, bj = mi[~related], mj[~related]
    mask = np.zeros(len(ai), dtype=bool)
    bb = (kind[ai] == 0) & (kind[bj] == 0)
    if bb.any():
        a, b = ai[bb], bj[bb]
        mask[bb] = ((bmn[a, 0] < bmx[b, 0]) & (bmn[b, 0] < bmx[a, 0]) &
                    (bmn[a, 1] < bmx[b, 1]) & (bmn[b, 1] < bmx[a, 1]) &
                    (bmn[a, 2] < bmx[b, 2]) & (bmn[b, 2] < bmx[a, 2]))
    ss = (kind[ai] == 1) & (kind[bj] == 1)
    if ss.any():
        a, b = ai[ss], bj[ss]
        d = scn[a] - scn[b]
        mask[ss] = np.einsum('ij,ij->i', d, d) < (rad[a] + rad[b]) ** 2
    bs = kind[ai] != kind[bj]
    if bs.any():
        a, b = ai[bs], bj[bs]
        sa = np.where(kind[a] == 1, a, b)
        bx = np.where(kind[a] == 1, b, a)
        cx = np.clip(scn[sa][:, 0], bmn[bx][:, 0], bmx[bx][:, 0])
        cy = np.clip(scn[sa][:, 1], bmn[bx][:, 1], bmx[bx][:, 1])
        cz = np.clip(scn[sa][:, 2], bmn[bx][:, 2], bmx[bx][:, 2])
        dx = scn[sa][:, 0] - cx
        dy = scn[sa][:, 1] - cy
        dz = scn[sa][:, 2] - cz
        mask[bs] = (dx * dx + dy * dy + dz * dz) < rad[sa] ** 2
    return ai[mask], bj[mask]


def _main():
    assert fastpath._CKERNELS is not None, 'C DLL 未加载'
    fails = 0
    for seed in (1, 2, 3, 4, 5):
        rng = np.random.default_rng(seed)
        n = 120
        K = 80
        cand = np.sort(rng.choice(n, K, replace=False)).astype(np.int64)
        kind = rng.integers(0, 2, n).astype(np.int64)
        cen = rng.uniform(-5, 5, (n, 3))
        half = np.where((kind == 0)[:, None],
                        rng.uniform(0.2, 1.5, (n, 3)),
                        rng.uniform(0.3, 1.2, (n, 3)))
        bmn_g = np.ascontiguousarray(cen - half)
        bmx_g = np.ascontiguousarray(cen + half)
        scn_g = np.ascontiguousarray(cen)
        rad_g = np.ascontiguousarray(half[:, 0].copy())
        # C 内核吃碰撞体局部行 (K); numpy 参考吃全局行 (n) — 行值相同
        cmn = np.ascontiguousarray((cen - half)[cand])
        cmx = np.ascontiguousarray((cen + half)[cand])
        bmn = np.ascontiguousarray(bmn_g[cand])
        bmx = np.ascontiguousarray(bmx_g[cand])
        scn = np.ascontiguousarray(scn_g[cand])
        rad = np.ascontiguousarray(rad_g[cand])
        kind_l = np.ascontiguousarray(kind[cand])
        tin = np.arange(n, dtype=np.int64)
        tout = tin + rng.integers(1, 4, n).astype(np.int64)
        ai_c, bj_c = fastpath._collide_pairs_c(
            cmn, cmx, cand, tin, tout, bmn, bmx, scn, rad, kind_l, n)
        ai_n, bj_n = numpy_ref(cmn, cmx, cand, tin, tout, bmn_g, bmx_g,
                               scn_g, rad_g, kind, n)
        ok = (len(ai_c) == len(ai_n) and bool((ai_c == ai_n).all())
              and bool((bj_c == bj_n).all()))
        if not ok:
            fails += 1
            print(f'[seed={seed}] C={len(ai_c)} numpy={len(ai_n)} -> FAIL')
            sc = set(zip(ai_c.tolist(), bj_c.tolist()))
            sn = set(zip(ai_n.tolist(), bj_n.tolist()))
            print('  set equal:', sc == sn,
                  'only_C:', list(sc - sn)[:3], 'only_NP:', list(sn - sc)[:3])
        else:
            print(f'[seed={seed}] C={len(ai_c)} == numpy -> PASS')

    # K=1 边界 (早退)
    c0 = np.array([3], dtype=np.int64)
    r0 = fastpath._collide_pairs_c(
        np.zeros((1, 3)), np.zeros((1, 3)), c0,
        np.zeros(10, dtype=np.int64), np.ones(10, dtype=np.int64),
        np.zeros((10, 3)), np.zeros((10, 3)), np.zeros((10, 3)),
        np.zeros(10), np.zeros(10, dtype=np.int64), 10)
    print('[K=1] ->', 'PASS' if r0 is not None and len(r0[0]) == 0 else 'FAIL')
    if r0 is None or len(r0[0]) != 0:
        fails += 1
    print('ALL PASS' if fails == 0 else f'{fails} FAIL')
    sys.exit(0 if fails == 0 else 1)


if __name__ == '__main__':
    _main()
