# -*- coding: utf-8 -*-
"""collide_val_check.py — collide_pairs 对拍铁闸 (2026-09-07 任务闸门 a)

新实现 (C 一体内核, 生产默认路径) vs 探针独立 numpy 参考实现:
  1. 混合500 场景真实播放态 ≥100 逻辑帧: **逐帧**碰撞对集合完全一致
     (物理/脚本/动画驱动位形逐帧变, 同一冻结输入下比对两路返回值);
  2. 随机场景 3 组 (含挂父/碰撞器开关混合): 每组 60 逻辑帧逐帧一致;
★B1 退役 (2026-10-16): 原"关 C 走回退段"改为探针内嵌 _numpy_ref_pairs
  (复现 HEAD 版 numpy 段, 独立参考实现做差分测试, 见 AI协作实践指南)。
★B5 退役 (2026-10-16): 删原第 3 条 "LOOM_NO_SAP=1 旧全对生成路" 对拍段
  (B 路逃生门已删); 主线第 1~2 段已覆盖 C 路 vs 探针内嵌 _numpy_ref_pairs。
用法: py -3.12 tests\\_tmp\\collide_val_check.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'
os.environ['LOOM_PROFILE'] = '1'

import numpy as np

import fastpath
CK_ON = fastpath._CKERNELS is not None
print('ckernels=%s' % CK_ON, flush=True)

import pygame
import editor
import sceneio
from engine import GLEngine, Point3D

fails = []


def _numpy_ref_pairs(eng, aabbs):
    """独立 numpy 参考实现 (B1 退役后替代'关 C 走回退段'的对拍基准).

    复现 HEAD 版 loom_physics._collision_pairs_parallel 的 numpy 候选生成 +
    精判段 (L796-876), 与生产 C 路独立对拍. 语义红线: 返回 [(i,j), ...]
    (i<j, 排序). 该实现内嵌本探针, 不依赖被测代码内部细节.
    """
    models = eng.models
    n = len(models)
    cand = [i for i, m in enumerate(models)
            if m.collider is not None and m.collider.enabled
            and m.collider.shape != 'none']
    if len(cand) < 2:
        return []
    bmn = np.zeros((n, 3), dtype=np.float64)
    bmx = np.zeros((n, 3), dtype=np.float64)
    scn = np.zeros((n, 3), dtype=np.float64)
    rad = np.zeros(n, dtype=np.float64)
    kind = np.zeros(n, dtype=np.int64)
    if aabbs is not None:
        for i in cand:
            shape = models[i].collider.shape
            shape, data = eng._collider_from_aabb(shape, aabbs[i])
            if shape == 'box':
                (mn, mx) = data
                bmn[i] = (mn.x, mn.y, mn.z)
                bmx[i] = (mx.x, mx.y, mx.z)
            else:
                (c, r) = data
                scn[i] = (c.x, c.y, c.z)
                rad[i] = r
                kind[i] = 1
    else:
        fw = eng.compute_world_matrices(models)
        for i in cand:
            shape, data = eng.collider_bounds(models[i], fw[i])
            if shape == 'box':
                (mn, mx) = data
                bmn[i] = (mn.x, mn.y, mn.z)
                bmx[i] = (mx.x, mx.y, mx.z)
            else:
                (c, r) = data
                scn[i] = (c.x, c.y, c.z)
                rad[i] = r
                kind[i] = 1
    n_c = len(cand)
    if n_c > eng._PAIR_GEN_NUMPY_MAX:
        roots = [m.parent is None for m in models]
        pairs_i, pairs_j = [], []
        for a in range(n_c):
            i = cand[a]
            for b in range(a + 1, n_c):
                j = cand[b]
                if roots[i] and roots[j]:
                    pairs_i.append(i)
                    pairs_j.append(j)
                    continue
                if not eng._related(models[i], models[j]):
                    pairs_i.append(i)
                    pairs_j.append(j)
        return sorted(zip(pairs_i, pairs_j))
    tin, tout = eng._ancestry_ranges(
        models, getattr(eng, '_struct_gen', None))
    ci = np.asarray(cand, dtype=np.int64)
    cmn = np.where(kind[ci][:, None] == 1,
                   scn[ci] - rad[ci][:, None], bmn[ci])
    cmx = np.where(kind[ci][:, None] == 1,
                   scn[ci] + rad[ci][:, None], bmx[ci])
    order = np.argsort(cmn[:, 0], kind='stable')
    blk = 64
    pu_l = []
    pv_l = []
    for j0 in range(0, n_c, blk):
        j1 = min(j0 + blk, n_c)
        t_block = order[:j1]
        u_block = order[j0:j1]
        tb = cmx[t_block, 0][:, None]
        ub = cmn[u_block, 0][None, :]
        ok = tb > ub
        ii, jj = np.nonzero(ok)
        if ii.size:
            pu_l.append(t_block[ii])
            pv_l.append(u_block[jj])
    if not pu_l:
        return []
    pu = np.concatenate(pu_l)
    pv = np.concatenate(pv_l)
    keep = pu != pv
    pu, pv = pu[keep], pv[keep]
    yz_ok = ((cmn[pu, 1] < cmx[pv, 1]) & (cmn[pv, 1] < cmx[pu, 1]) &
             (cmn[pu, 2] < cmx[pv, 2]) & (cmn[pv, 2] < cmx[pu, 2]))
    pu, pv = pu[yz_ok], pv[yz_ok]
    mi = np.minimum(ci[pu], ci[pv])
    mj = np.maximum(ci[pu], ci[pv])
    key = mi * (n + 1) + mj
    key = np.unique(key)
    mi = key // (n + 1)
    mj = key % (n + 1)
    related = ((tin[mi] <= tin[mj]) & (tin[mj] < tout[mi])) | \
              ((tin[mj] <= tin[mi]) & (tin[mi] < tout[mj]))
    ai = mi[~related]
    bj = mj[~related]
    from loom_physics import PhysicsMixin
    mask = PhysicsMixin._pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind)
    ai = ai[mask]
    bj = bj[mask]
    return sorted(zip(ai.tolist(), bj.tolist()))


def make_frame_recorder(eng, tag, min_logic_frames, deadline):
    """逐帧录制: 在 _logic_prep 后取冻结输入 (aabbs), 跑新 (默认) 与旧
    (numpy 回退) 两路, 逐帧断言集合一致. 返回比较记录数."""
    models = eng.models
    cmp_frames = 0

    # B1 退役 (2026-10-16): numpy 回退段已删, 用探针内嵌 _numpy_ref_pairs 作参考:
    #   新路 = eng._collision_pairs_parallel(aabbs=...)   (C 默认)
    #   旧路 = _numpy_ref_pairs(eng, aabbs)              (独立 numpy 参考实现)
    records = []
    while cmp_frames < min_logic_frames:
        t0 = time.perf_counter()
        if time.perf_counter() > deadline:
            print(f'[{tag}] watchdog: {cmp_frames} 帧后超时收尾', flush=True)
            break
        # 让逻辑帧推进一格 (固定小 dt 直注 — 不依赖墙钟节奏)
        eng._handle_events()
        eng.render(1.0 / 120.0)
        aabbs = eng._prep_aabbs
        if aabbs is None or not eng.is_playing:
            continue
        # 同一冻结输入: C 路 vs 探针独立 numpy 参考实现
        pairs_new = eng._collision_pairs_parallel(aabbs=aabbs)
        pairs_old = _numpy_ref_pairs(eng, aabbs)
        ok = (len(pairs_new) == len(pairs_old)
              and all(a[0] == b[0] and a[1] == b[1]
                      for a, b in zip(pairs_new, pairs_old)))
        records.append((ok, len(pairs_new), len(pairs_old)))
        cmp_frames += 1
        if not ok:
            bad = [(a, b) for a, b in zip(pairs_new, pairs_old)
                   if a[0] != b[0] or a[1] != b[1]]
            fails.append(f'{tag} 逻辑帧{cmp_frames}: 新{len(pairs_new)}对 '
                         f'旧{len(pairs_old)}对 首差异 {bad[:3]}')
            print('[FAIL]', fails[-1], flush=True)
            break
    n_ok = sum(1 for ok, _, _ in records if ok)
    print(f'[{tag}] 逐帧对拍 {n_ok}/{len(records)} 帧一致', flush=True)
    return cmp_frames


def run_scene(eng, scene_path, tag, min_logic, deadline):
    for m in list(eng.models):
        eng.remove_model(m)
    eng.lights.clear()
    if scene_path is None:
        _build_random_scene(eng, tag)
    else:
        data = sceneio.load_scene_data(scene_path)
        sceneio.scene_from_dict(eng, data)
    eng.current_model_index = 0
    eng.toggle_play()
    try:
        n = make_frame_recorder(eng, tag, min_logic, deadline)
    finally:
        eng.toggle_play()
    return n


def _build_random_scene(eng, tag):
    """随机场景: 混合盒/球 + 挂父链 + 碰撞器开/关 (含 none/enabled=False)."""
    from mesh import create_cube, create_sphere
    rng = np.random.default_rng(hash(tag) & 0xffff)
    for m in list(eng.models):
        eng.remove_model(m)
    eng.lights.clear()
    prev = None
    for i in range(120):
        if i % 3 == 0:
            mesh = create_sphere(float(rng.uniform(0.4, 1.2)), stacks=8,
                                 slices=14)
        else:
            mesh = create_cube(float(rng.uniform(0.5, 2.0)))
        m = eng.add_model(
            mesh,
            Point3D(float(rng.uniform(-6, 6)), float(rng.uniform(-2, 4)),
                    float(rng.uniform(-6, 6))),
            Point3D(float(rng.uniform(-1, 1)), float(rng.uniform(-1, 1)),
                    float(rng.uniform(-1, 1))),
            scale=(float(rng.uniform(0.5, 2.0)),) * 3)
        # 挂父 (每 5 个挂到前一非父物体)
        if prev is not None and i % 5 == 0:
            eng.set_parent(m, prev)
            m.position = Point3D(float(rng.uniform(-1, 1)),
                                 float(rng.uniform(-1, 1)),
                                 float(rng.uniform(-1, 1)))
        # 碰撞器混合: 1/6 关闭, 1/6 none
        col = m.collider
        r = rng.random()
        if r < 0.16:
            col.enabled = False
        elif r < 0.33:
            col.shape = 'none'
        # 刚体让场景动起来 (带碰撞位移驱动逐帧位形变化)
        if i % 2 == 0:
            rb = eng.add_rigidbody(m)
            if rb is not None:
                rb.velocity = Point3D(float(rng.uniform(-2, 2)),
                                      float(rng.uniform(-2, 2)),
                                      float(rng.uniform(-2, 2)))
        prev = m if i % 7 != 0 else prev


def main():
    deadline = time.perf_counter() + 420.0
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    eng = editor.EditorApp(1280, 800)
    try:
        # 1) 混合500 真实播放态 ≥100 逻辑帧
        n1 = run_scene(eng, os.path.join('保存', '压测500混合.json'),
                       '混合500', 100, deadline)
        # 2) 随机场景 3 组
        n2 = run_scene(eng, None, '随机A(挂父+开关)', 60, deadline)
        n3 = run_scene(eng, None, '随机B', 60, deadline)
        n4 = run_scene(eng, None, '随机C', 60, deadline)

        # ★B5 退役 (2026-10-16): 删原第 3 段 "LOOM_NO_SAP=1 旧全对生成路" 对拍
        #   (B 路逃生门已删); 主线第 1~2 段已覆盖 C 路 vs 探针内嵌 _numpy_ref_pairs。
    finally:
        try:
            if eng.is_playing:
                eng.toggle_play()
        except Exception:
            pass
        try:
            eng._stop_parallel()
        except Exception:
            pass
        pygame.quit()

    print('帧数: 混合500=%d 随机A=%d 随机B=%d 随机C=%d' % (n1, n2, n3, n4),
          flush=True)
    if fails or n1 < 100 or min(n2, n3, n4) < 60:
        print('VAL FAIL:', *fails, sep='\n  ')
        sys.exit(1)
    print('VAL ALL PASS', flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
