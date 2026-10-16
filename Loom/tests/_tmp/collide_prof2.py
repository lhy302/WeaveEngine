# -*- coding: utf-8 -*-
"""collide_prof2.py — round-2 取证: 提取写法微对比 + 新算法模拟等价性验证 (只读不改产线代码)

1. 提取三写法计时 (真实混合500 aabbs):
   V1 旧: 逐候选 _collider_from_aabb + n 尺寸行赋值 (现状)
   V3 新: flat-list append + np.array 一次转换 + 向量化派生 (cand 局部, 无散射)
   并逐位验证 V3 产物消费面 == V1 (cmn/cmx 粗筛盒 + kind + sphere 精判数据)
2. 新扫描算法模拟 (纯 numpy, 逐 t 循环 + searchsorted, 与拟写 C 同构):
   结果 (排序后 (i,j) 列表) == 引擎现实现输出 (冻结输入, 逐位含顺序)
3. 整链模拟计时 (Python 上界估计, C 预期显著低于此)
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
print('ckernels=%s numba=%s' % (bool(fastpath._CKERNELS), fastpath._NUMBA),
      flush=True)

import pygame
import editor
import sceneio
from engine import GLEngine


def _timed(fn, R):
    fn()
    tot = 0.0
    best = 1e30
    for _ in range(R):
        t0 = time.perf_counter()
        fn()
        dt = (time.perf_counter() - t0) * 1000.0
        tot += dt
        if dt < best:
            best = dt
    return tot / R, best


def main():
    eng = editor.EditorApp(1280, 800)
    try:
        for m in list(eng.models):
            eng.remove_model(m)
        eng.lights.clear()
        data = sceneio.load_scene_data(os.path.join('保存', '压测500混合.json'))
        sceneio.scene_from_dict(eng, data)
        eng.current_model_index = 0

        eng.toggle_play()
        for _ in range(60):
            eng._handle_events()
            eng.render(1.0 / 120.0)

        models = list(eng.models)
        aabbs = eng._prep_aabbs
        n = len(models)
        assert aabbs is not None and len(aabbs) == n
        cand = [i for i, m in enumerate(models)
                if m.collider is not None and m.collider.enabled
                and m.collider.shape != 'none']
        n_c = len(cand)
        ci = np.asarray(cand, dtype=np.int64)

        # ---------- V1 旧提取 (n 尺寸) ----------
        def v1():
            bmn = np.zeros((n, 3), dtype=np.float64)
            bmx = np.zeros((n, 3), dtype=np.float64)
            scn = np.zeros((n, 3), dtype=np.float64)
            rad = np.zeros(n, dtype=np.float64)
            kind = np.zeros(n, dtype=np.int64)
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
            return bmn, bmx, scn, rad, kind
        bmn, bmx, scn, rad, kind = v1()

        # ---------- V3 新提取 (cand 局部) ----------
        def v3():
            flat = []
            ap = flat.append
            kinds_l = []
            kp = kinds_l.append
            for i in cand_idx_list:
                m = models[i]
                mn, mx = aabbs[i]
                ap(mn.x); ap(mn.y); ap(mn.z)
                ap(mx.x); ap(mx.y); ap(mx.z)
                kp(1 if m.collider.shape == 'sphere' else 0)
            a6 = np.array(flat, dtype=np.float64).reshape(n_c, 6)
            mn6 = np.ascontiguousarray(a6[:, 0:3])
            mx6 = np.ascontiguousarray(a6[:, 3:6])
            ext = mx6 - mn6
            cen = (mn6 + mx6) * 0.5
            r_all = np.maximum(np.maximum(ext[:, 0], ext[:, 1]),
                               ext[:, 2]) * 0.5
            return mn6, mx6, cen, r_all, np.array(kinds_l, dtype=np.int64)
        cand_idx_list = cand_idx = [int(x) for x in ci]
        nbmn, nbmx, nscn, nrad, nkind = v3()

        # 消费面逐位验证: 粗筛盒 (C 路径的全部输入) + 精判数据
        cmn_o = np.where(kind[ci][:, None] == 1,
                         scn[ci] - rad[ci][:, None], bmn[ci])
        cmx_o = np.where(kind[ci][:, None] == 1,
                         scn[ci] + rad[ci][:, None], bmx[ci])
        cmn_n = np.where(nkind[:, None] == 1,
                         nscn - nrad[:, None], nbmn)
        cmx_n = np.where(nkind[:, None] == 1,
                         nscn + nrad[:, None], nbmx)
        eq = {
            'kind': bool((nkind == kind[ci]).all()),
            'cmn': bool((cmn_n == cmn_o).all()),
            'cmx': bool((cmx_n == cmx_o).all()),
            # sphere 精判数据 (cen/rad 直接就是 scn/rad)
            'scn_sph': bool((nscn[nkind == 1] == scn[ci][kind[ci] == 1]).all()),
            'rad_sph': bool((nrad[nkind == 1] == rad[ci][kind[ci] == 1]).all()),
            'bmn_box': bool((nbmn[nkind == 0] == bmn[ci][kind[ci] == 0]).all()),
            'bmx_box': bool((nbmx[nkind == 0] == bmx[ci][kind[ci] == 0]).all()),
        }
        print('[EQ] V3 vs V1 消费面:', eq, flush=True)

        m1, b1 = _timed(v1, 150)
        m3, b3 = _timed(v3, 150)
        print('[T] V1 extract  %7.4f / %7.4f ms' % (m1, b1), flush=True)
        print('[T] V3 extract  %7.4f / %7.4f ms  (省 %.3f ms)'
              % (m3, b3, m1 - m3), flush=True)

        # ---------- 新扫描算法模拟 (与拟写 C 同构) ----------
        tin, tout = eng._ancestry_ranges(models, getattr(eng, '_struct_gen',
                                                         None))

        def sim():
            order = np.argsort(cmn_n[:, 0], kind='stable')
            xmns = cmn_n[order, 0]
            out_i = []
            out_j = []
            for t in range(n_c):
                kt = order[t]
                lo = np.searchsorted(xmns, cmx_n[kt, 0], side='left')
                if lo <= t + 1:
                    continue
                us = order[t + 1:lo]
                yz = ((cmn_n[kt, 1] < cmx_n[us, 1]) &
                      (cmn_n[us, 1] < cmx_n[kt, 1]) &
                      (cmn_n[kt, 2] < cmx_n[us, 2]) &
                      (cmn_n[us, 2] < cmx_n[kt, 2]))
                if not yz.any():
                    continue
                for ku in us[yz]:
                    i = int(cand[kt]); j = int(cand[ku])
                    if i > j:
                        i, j = j, i
                    rel = ((tin[i] <= tin[j] and tin[j] < tout[i]) or
                           (tin[j] <= tin[i] and tin[i] < tout[j]))
                    if rel:
                        continue
                    out_i.append(i)
                    out_j.append(j)
            ai = np.array(out_i, dtype=np.int64)
            bj = np.array(out_j, dtype=np.int64)
            mask = GLEngine._pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind)
            ai = ai[mask]
            bj = bj[mask]
            key = ai * (n + 1) + bj
            key = np.unique(key)
            return key // (n + 1), key % (n + 1)
        ai_s, bj_s = sim()

        # 引擎现实现 (冻结输入)
        ref = eng._collision_pairs_parallel(aabbs=aabbs)
        ri = np.array([p[0] for p in ref], dtype=np.int64)
        rj = np.array([p[1] for p in ref], dtype=np.int64)
        same_len = len(ai_s) == len(ri)
        same = same_len and bool((ai_s == ri).all()) and bool((bj_s == rj).all())
        print('[SIM] 模拟链 == 引擎实现 (含顺序): %s (对数 sim=%d ref=%d)'
              % (same, len(ai_s), len(ri)), flush=True)

        ms, bs = _timed(sim, 30)
        print('[T] 模拟整链 (numpy 上界) %7.4f / %7.4f ms' % (ms, bs),
              flush=True)

        mw, bw = _timed(lambda: eng._collision_pairs_parallel(aabbs=aabbs), 150)
        print('[T] 引擎整调用 %7.4f / %7.4f ms' % (mw, bw), flush=True)
        print('[PROF2-DONE]', flush=True)
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
        try:
            pygame.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
    print('PROBE OK', flush=True)
