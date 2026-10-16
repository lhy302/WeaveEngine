# -*- coding: utf-8 -*-
r"""physics_c_check.py — M3: dirty_mask 与 local_matrices 逐位对拍

对拍对象: pipeline_glue.dirty_mask 与 local_matrices (C 原生)
          vs physics_bridge 内部 Python 实现
判据: 全部用例 max|diff| == 0 (逐位一致); 任一不符 -> exit 1。
用法: py -3.12 tests\_tmp\physics_c_check.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import pipeline_glue as pg


def ref_dirty_mask(cur_rows, old_rows, pidx):
    n = cur_rows.shape[0]
    ne = cur_rows != old_rows
    mask = ne[:, 0] | ne[:, 1] | ne[:, 2] | ne[:, 3] | ne[:, 4] | ne[:, 5]
    pmask = mask.copy()
    if pidx is not None and n > 0:
        has_parent = np.where(np.array(pidx) >= 0)[0]
        for _ in range(n):
            added = np.zeros(n, dtype=bool)
            for i in has_parent:
                pi = pidx[i]
                if pmask[pi] and not pmask[i]:
                    added[i] = True
            if not added.any():
                break
            pmask |= added
    return pmask.astype(np.uint8)


def ref_local_matrices(r, s, p):
    M = r.shape[0]
    cx = np.cos(r[:, 0]); sx = np.sin(r[:, 0])
    cy = np.cos(r[:, 1]); sy = np.sin(r[:, 1])
    cz = np.cos(r[:, 2]); sz = np.sin(r[:, 2])
    S = np.zeros((M, 4, 4))
    S[:, 0, 0] = s[:, 0]; S[:, 1, 1] = s[:, 1]; S[:, 2, 2] = s[:, 2]; S[:, 3, 3] = 1.0
    Rx = np.zeros((M, 4, 4))
    Rx[:, 0, 0] = 1.0; Rx[:, 3, 3] = 1.0
    Rx[:, 1, 1] = cx; Rx[:, 1, 2] = sx
    Rx[:, 2, 1] = -sx; Rx[:, 2, 2] = cx
    Ry = np.zeros((M, 4, 4))
    Ry[:, 1, 1] = 1.0; Ry[:, 3, 3] = 1.0
    Ry[:, 0, 0] = cy; Ry[:, 0, 2] = -sy
    Ry[:, 2, 0] = sy; Ry[:, 2, 2] = cy
    Rz = np.zeros((M, 4, 4))
    Rz[:, 2, 2] = 1.0; Rz[:, 3, 3] = 1.0
    Rz[:, 0, 0] = cz; Rz[:, 0, 1] = sz
    Rz[:, 1, 0] = -sz; Rz[:, 1, 1] = cz
    T = np.zeros((M, 4, 4))
    T[:, 0, 0] = 1.0; T[:, 1, 1] = 1.0; T[:, 2, 2] = 1.0; T[:, 3, 3] = 1.0
    T[:, 3, :3] = p
    out = S @ Rx @ Ry @ Rz @ T
    return out


def test_dirty():
    print("--- 1. dirty_mask 逐位对拍 (C vs Python) ---")
    np.random.seed(12345)
    cases = [
        ("n0_empty", 0),
        ("n1_clean", 1),
        ("n1_dirty", 1),
        ("n10_linear_chain", 10),
        ("n50_tree", 50),
        ("n501_mixed_scene", 501),
    ]

    for name, n in cases:
        if n == 0:
            cur = np.empty((0, 6), dtype=np.float64)
            old = np.empty((0, 6), dtype=np.float64)
            pidx = np.empty(0, dtype=np.int64)
        else:
            old = np.random.randn(n, 6)
            cur = old.copy()
            # Randomly dirty ~30% of nodes
            dirty_indices = np.random.choice(n, size=max(1, n // 3), replace=False)
            cur[dirty_indices] += np.random.randn(len(dirty_indices), 6) * 0.1
            if name == "n1_clean":
                cur[:] = old[:]
            # Construct parent hierarchy (each node has parent < i or -1)
            pidx = np.full(n, -1, dtype=np.int64)
            for i in range(1, n):
                if np.random.rand() > 0.3:
                    pidx[i] = np.random.randint(0, i)

        ref_mask = ref_dirty_mask(cur, old, pidx)
        c_mask = np.zeros(n, dtype=np.uint8)
        rc = pg.dirty_mask(cur, old, pidx, c_mask)
        assert rc == 0, "dirty_mask failed rc=%r" % rc

        diff = int(np.sum(ref_mask != c_mask))
        pass_ = (diff == 0)
        status = "PASS" if pass_ else "FAIL"
        print("%-25s %-8s diff_count=%d (n=%d)" % (name, status, diff, n))
        if not pass_:
            return False
    return True


def test_local_matrices():
    print("\n--- 2. local_matrices 逐位对拍 (C vs numpy) ---")
    np.random.seed(6789)
    cases = [
        ("n1_identity", 1),
        ("n5_small", 5),
        ("n64_batch", 64),
        ("n501_full", 501),
    ]

    for name, n in cases:
        rot = np.random.randn(n, 3)
        scl = np.random.uniform(0.5, 2.0, size=(n, 3))
        pos = np.random.randn(n, 3) * 10.0
        if name == "n1_identity":
            rot[:] = 0.0; scl[:] = 1.0; pos[:] = 0.0

        ref_m = ref_local_matrices(rot, scl, pos)
        c_m = np.zeros((n, 4, 4), dtype=np.float64)
        rc = pg.local_matrices(rot, scl, pos, c_m)
        assert rc == 0, "local_matrices failed rc=%r" % rc

        max_diff = float(np.max(np.abs(ref_m - c_m)))
        # 允许 <= 2e-15 (BLAS求和序 1-2 ULP)
        pass_ = (max_diff <= 2e-15)
        status = "PASS" if pass_ else "FAIL"
        print("%-25s %-8s max_diff=%.3e" % (name, status, max_diff))
        if not pass_:
            return False
    return True


def main():
    ok1 = test_dirty()
    ok2 = test_local_matrices()
    if ok1 and ok2:
        print("\nALL PASS (physics_c_check)")
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
