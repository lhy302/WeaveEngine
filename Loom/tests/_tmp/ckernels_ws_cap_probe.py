# -*- coding: utf-8 -*-
"""ckernels_ws_cap_probe.py — 取证: C 内核 loom_collide_pairs 的 ws_cap<K 判定是否
会让合法小场景 (K=2) 触发"容量拒绝"回退.

背景: 读 loom_kernels.c 发现 line248 `if (ws_cap < K) return -2;`,
而 Python 侧 _collide_pairs_c 传入的 ws_cap = cap = K*(K-1)//2.
K=2 时 cap=1 < K=2 → 若判定生效, K=2 合法场景会误触容量拒绝.
本探针直接调 fastpath._collide_pairs_c 取证, 用于 B1 逃生门退役决策.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))   # tests/_tmp -> tests -> 引擎根

import numpy as np
import fastpath


def _mk(K):
    cmn = np.zeros((K, 3)); cmx = np.ones((K, 3))
    for i in range(K):
        cmn[i, 0] = i * 0.5
        cmx[i, 0] = i * 0.5 + 1.0   # 相邻相交
    cand = np.arange(K, dtype=np.int64)
    # ★ 每节点独占 DFS 区间 (tin=2i, tout=2i+1), 彼此非祖先:
    #   原构造全重叠区间会使 C 侧 ancestry 判定把所有对误判为同族 skip.
    tin = (np.arange(K, dtype=np.int64) * 2)
    tout = tin + 1
    bmn = cmn.copy(); bmx = cmx.copy()
    scn = np.zeros((K, 3)); rad = np.zeros(K); kind = np.zeros(K, dtype=np.int64)
    return cmn, cmx, cand, tin, tout, bmn, bmx, scn, rad, kind


def probe(K):
    args = _mk(K)
    r = fastpath._collide_pairs_c(*args, K)
    if r is None:
        return '%d -> None (命中容量拒绝, 回退 numpy)' % K
    return '%d -> OK pairs=%d' % (K, len(r[0]))


if __name__ == '__main__':
    print('[C 内核 ws_cap 取证]')
    for K in (2, 3, 4, 8, 16):
        print('  K=%-3s %s' % ('', probe(K)))
    print('解释: None=回退 numpy; OK=走 C 路. 若 K=2 为 None, 说明 ws_cap<K 判定')
    print('      会拒绝合法小场景, 是真实缺陷而非纯防御.')
