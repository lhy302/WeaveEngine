# -*- coding: utf-8 -*-
r"""pack_bucket_check.py — M3: loom_pipeline_pack_bucket_instances 逐位对拍

对拍对象: pipeline_glue.pack_bucket_instances (C) vs engine._prepare_bucket_frame 内现行实现
判据: 全部用例 max|diff| == 0 (逐位一致); 任一不符 -> exit 1。
用法: py -3.12 tests\_tmp\pack_bucket_check.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import pipeline_glue as pg


def ref_pack(fw32, idxs, sat, rgba, k):
    g = np.take(fw32, idxs, axis=0, mode='clip')
    st = np.zeros((k, 24), dtype=np.float32)
    st[:, 0:16] = g.reshape(k, 16)
    if sat is not None:
        st[:, 16] = sat
    else:
        st[:, 16] = 0.0
    if rgba is not None:
        st[:, 20:24] = rgba
    else:
        st[:, 20:24] = 0.0
    sha = g.reshape(k, 16).copy()
    return st, sha


def run_case(name, n_models, k, with_sat, with_rgba):
    np.random.seed(hash(name) % (2**31))
    fw32 = np.random.randn(n_models, 4, 4).astype(np.float32)
    idxs = np.random.choice(n_models, size=k, replace=True).astype(np.int32)
    sat = np.random.randn(k).astype(np.float32) if with_sat else None
    rgba = np.random.randn(k, 4).astype(np.float32) if with_rgba else None

    ref_main, ref_sha = ref_pack(fw32, idxs, sat, rgba, k)

    c_main = np.zeros((k, 24), dtype=np.float32)
    c_sha = np.zeros((k, 16), dtype=np.float32)

    rc = pg.pack_bucket_instances(fw32, n_models, idxs, sat, rgba, c_main, c_sha)
    assert rc == 0, "C pack failed with rc=%r" % rc

    diff_main = float(np.max(np.abs(ref_main - c_main)))
    diff_sha = float(np.max(np.abs(ref_sha - c_sha)))

    pass_ = (diff_main == 0.0 and diff_sha == 0.0)
    status = "PASS" if pass_ else "FAIL"
    print("%-30s %-8s diff_main=%.3e diff_sha=%.3e" % (name, status, diff_main, diff_sha))
    return pass_


def main():
    print("--- pack_bucket 逐位对拍 (C vs Python numpy) ---")
    cases = [
        ("single_instance", 10, 1, True, True),
        ("small_bucket", 50, 5, True, True),
        ("medium_bucket", 501, 64, True, True),
        ("large_bucket", 501, 501, True, True),
        ("no_sat", 200, 30, False, True),
        ("no_rgba", 200, 30, True, False),
        ("no_sat_no_rgba", 200, 30, False, False),
        ("unordered_idxs", 501, 120, True, True),
        ("repeated_idxs", 100, 50, True, True),
    ]

    all_pass = True
    for c in cases:
        ok = run_case(*c)
        if not ok:
            all_pass = False

    if all_pass:
        print("--- 全部 %d 项: PASS %d / FAIL 0 ---" % (len(cases), len(cases)))
        print("ALL PASS")
        return 0
    else:
        print("FAILURES DETECTED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
