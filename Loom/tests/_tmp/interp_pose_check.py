# -*- coding: utf-8 -*-
r"""interp_pose_check.py — M3-N4: loom_pipeline_interp_pose 逐位对拍 (只读)

对拍对象: `pipeline_glue.interp_pose` (C) vs 纯 numpy 参考实现
          (= interp_state.InterpState.render_pose 的映射 + lerp 数学)。
判据: 全部用例 max|diff| == 0 (逐位); 任一不符 → exit 1。
用法: py -3.12 tests\_tmp\interp_pose_check.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

import pipeline_glue as pg  # noqa: E402


def ref_render_pose(cur_ids, known, order, known_sorted,
                    prev_pos, curr_pos, prev_rot, curr_rot,
                    prev_scl, curr_scl, a, n):
    """numpy 参考: 与 render_pose 的 numpy 路径同式 (searchsorted + lerp)。"""
    slot = np.minimum(np.searchsorted(known_sorted, cur_ids), known.shape[0] - 1)
    loc = order[slot]
    out_pos = np.empty((n, 3), dtype=np.float64)
    out_rot = np.empty((n, 3), dtype=np.float64)
    out_scl = np.empty((n, 3), dtype=np.float64)
    cg = curr_pos[loc]; pg_ = prev_pos[loc]
    np.subtract(cg, pg_, out=out_pos)
    out_pos *= a
    out_pos += pg_
    d = curr_rot[loc] - prev_rot[loc]
    d = (d + np.pi) % (2.0 * np.pi) - np.pi
    out_rot[:] = prev_rot[loc] + d * a
    np.subtract(curr_scl[loc], prev_scl[loc], out=out_scl)
    out_scl *= a
    out_scl += prev_scl[loc]
    return loc, out_pos, out_rot, out_scl


def run_case(name, cur_ids, known, prev_pos, curr_pos, prev_rot, curr_rot,
             prev_scl, curr_scl, a, results):
    n = cur_ids.shape[0]
    kn = known.shape[0]
    order = np.argsort(known)
    known_sorted = known[order]
    loc_r, op_r, or_r, os_r = ref_render_pose(
        cur_ids, known, order, known_sorted,
        prev_pos, curr_pos, prev_rot, curr_rot, prev_scl, curr_scl, a, n)
    loc_c = np.empty(n, dtype=np.int64)
    op_c = np.zeros((n, 3), dtype=np.float64)
    or_c = np.zeros((n, 3), dtype=np.float64)
    os_c = np.zeros((n, 3), dtype=np.float64)
    r = pg.interp_pose(cur_ids, known_sorted, order,
                       prev_pos, curr_pos, prev_rot, curr_rot,
                       prev_scl, curr_scl, a, loc_c, op_c, or_c, os_c)
    if r is None:
        results.append((name, 'DLL_UNAVAILABLE', None))
        return False
    d_loc = int(np.abs(r[0] - loc_r).max()) if n else 0
    d_pos = float(np.abs(r[1] - op_r).max()) if n else 0.0
    d_rot = float(np.abs(r[2] - or_r).max()) if n else 0.0
    d_scl = float(np.abs(r[3] - os_r).max()) if n else 0.0
    ok = (d_loc == 0) and (d_pos == 0.0) and (d_rot == 0.0) and (d_scl == 0.0)
    results.append((name, 'PASS' if ok else 'FAIL',
                    'loc_diff=%d pos=%.3e rot=%.3e scl=%.3e'
                    % (d_loc, d_pos, d_rot, d_scl)))
    return ok


def run_world_case(name, n, results):
    """★M3-N6: interp_world (合并) vs interp_pose + world_matrices (两步) 逐位对拍。"""
    rng = np.random.default_rng(0x5EED + n)
    ids = (np.arange(n, dtype=np.int64) * 8 + 3)
    prev_pos = rng.normal(size=(n, 3)) * 10
    curr_pos = prev_pos + rng.normal(size=(n, 3))
    prev_rot = rng.uniform(-np.pi, np.pi, size=(n, 3))
    curr_rot = prev_rot + rng.normal(size=(n, 3)) * 0.5
    prev_scl = rng.uniform(0.1, 5.0, size=(n, 3))
    curr_scl = prev_scl * rng.uniform(0.9, 1.1, size=(n, 3))
    parent = np.array([-1 if i == 0 else (i - 1) // 2 for i in range(n)],
                      dtype=np.int64)
    depth = np.array([int(np.floor(np.log2(i + 1))) for i in range(n)],
                     dtype=np.int64)
    max_depth = int(depth.max()) if n else 0
    order = np.argsort(ids)
    ks = ids[order]
    ok_all = True
    for a in (0.0, 0.5, 1.0, 1.5):
        loc1 = np.empty(n, dtype=np.int64)
        op = np.zeros((n, 3)); orr = np.zeros((n, 3)); osl = np.zeros((n, 3))
        r1 = pg.interp_pose(ids, ks, order, prev_pos, curr_pos,
                            prev_rot, curr_rot, prev_scl, curr_scl, a,
                            loc1, op, orr, osl)
        w1 = None
        if r1 is not None:
            w1 = pg.world_matrices(r1[2], r1[3], r1[1], parent, depth)
        loc2 = np.empty(n, dtype=np.int64)
        w2 = np.zeros((n, 4, 4), dtype=np.float64)
        r2 = pg.interp_world(ids, ks, order, prev_pos, curr_pos,
                             prev_rot, curr_rot, prev_scl, curr_scl,
                             parent, depth, max_depth, a, loc2, w2)
        if r1 is None or w1 is None or r2 is None:
            results.append((name + ' n=%d a=%.1f' % (n, a),
                            'DLL_UNAVAILABLE', None))
            ok_all = False
            continue
        d_loc = int(np.abs(r1[0] - r2[0]).max())
        d_w = float(np.abs(w1 - r2[1]).max())
        ok = (d_loc == 0) and (d_w == 0.0)
        ok_all &= ok
        results.append((name + ' n=%d a=%.1f' % (n, a),
                        'PASS' if ok else 'FAIL',
                        'loc_diff=%d world_diff=%.3e' % (d_loc, d_w)))
    return ok_all


def main():
    # ★B2 退役 (2026-10-16): pipeline 是官方件唯一路径, 不可用则硬 raise, 不再 SKIP。
    pg.handle()   # 失败硬抛
    rng = np.random.default_rng(20260909)
    results = []
    ok_all = True

    # ① 基础: 501 行, id 单调 (常规路径)
    for n in (1, 2, 17, 501, 777):
        ids = np.arange(1000, 1000 + n, dtype=np.int64) * 8 + 3
        known = ids.copy()
        prev_pos = rng.normal(size=(n, 3)) * 10
        curr_pos = prev_pos + rng.normal(size=(n, 3))
        prev_rot = rng.uniform(-np.pi, np.pi, size=(n, 3))
        curr_rot = prev_rot + rng.normal(size=(n, 3)) * 0.5
        prev_scl = rng.uniform(0.1, 5.0, size=(n, 3))
        curr_scl = prev_scl * rng.uniform(0.9, 1.1, size=(n, 3))
        for a in (0.0, 0.25, 0.5, 0.999999, 1.0, 1.5):
            ok_all &= run_case('basic n=%d a=%.3f' % (n, a), ids, known,
                               prev_pos, curr_pos, prev_rot, curr_rot,
                               prev_scl, curr_scl, a, results)

    # ② 乱序 cur_ids (searchsorted 命中/未命中/夹取右端)
    n = 200
    known = np.sort(rng.choice(np.arange(10 ** 6), size=n, replace=False)).astype(np.int64)
    order = np.argsort(known)
    ks = known[order]
    cur_ids = np.concatenate([known[:50], known[-3:],
                              np.array([-1, 0, 10 ** 7, 10 ** 7 - 1], dtype=np.int64)])
    prev_pos = rng.normal(size=(n, 3))
    curr_pos = rng.normal(size=(n, 3))
    prev_rot = rng.uniform(-np.pi, np.pi, size=(n, 3))
    curr_rot = rng.uniform(-np.pi, np.pi, size=(n, 3))
    prev_scl = rng.uniform(0.5, 2.0, size=(n, 3))
    curr_scl = rng.uniform(0.5, 2.0, size=(n, 3))
    for a in (0.0, 0.5, 1.0):
        ok_all &= run_case('unordered a=%.2f' % a, cur_ids, known,
                           prev_pos, curr_pos, prev_rot, curr_rot,
                           prev_scl, curr_scl, a, results)

    # ③ 角度边界: 跨 ±π 跳变 (mod 语义最容易错的地方)
    n = 64
    ids = np.arange(n, dtype=np.int64)
    prev_rot = np.full((n, 3), 0.0)
    curr_rot = np.zeros((n, 3))
    edge = np.array([0.0, np.pi, -np.pi, np.pi - 1e-12, -np.pi + 1e-12,
                     2 * np.pi, -2 * np.pi, 3 * np.pi, -3 * np.pi,
                     np.pi / 2, -np.pi / 2, 1e-300, -1e-300,
                     1e10, -1e10, 12345.6789, -12345.6789])
    for i in range(n):
        curr_rot[i, :] = edge[i % edge.size]
    for a in (0.0, 0.3, 0.5, 0.7, 1.0, 1.5):
        ok_all &= run_case('angle-edge a=%.2f' % a, ids, ids,
                           np.zeros((n, 3)), np.zeros((n, 3)),
                           prev_rot, curr_rot,
                           np.ones((n, 3)), np.ones((n, 3)), a, results)

    # ④ 极端量级 (大坐标/小缩放) —— 溢出/精度边界
    n = 32
    ids = np.arange(n, dtype=np.int64)
    big = np.linspace(-1e12, 1e12, n)
    prev_pos = np.stack([big, big * 0.5, -big], axis=1)
    curr_pos = prev_pos + 1e-3
    prev_rot = np.stack([big * 1e-6, -big * 1e-6, big], axis=1)
    curr_rot = prev_rot + 1e-9
    prev_scl = np.full((n, 3), 1e-6)
    curr_scl = np.full((n, 3), 1e6)
    for a in (0.5, 1.0):
        ok_all &= run_case('extreme a=%.1f' % a, ids, ids,
                           prev_pos, curr_pos, prev_rot, curr_rot,
                           prev_scl, curr_scl, a, results)

    # ⑤ M3-N6 合并路径: interp_world vs interp_pose + world_matrices (逐位)
    for n in (1, 17, 501):
        ok_all &= run_world_case('merged', n, results)

    print('--- interp_pose 对拍 (C vs numpy) ---')
    for name, st, detail in results:
        print('%-28s %-16s %s' % (name, st, detail))
    n_pass = sum(1 for _, st, _ in results if st == 'PASS')
    print('--- 共 %d 项: PASS %d / FAIL %d ---'
          % (len(results), n_pass, len(results) - n_pass))
    print('ALL PASS' if ok_all and n_pass == len(results) else 'FAILED')
    return 0 if (ok_all and n_pass == len(results)) else 1


if __name__ == '__main__':
    sys.exit(main())
