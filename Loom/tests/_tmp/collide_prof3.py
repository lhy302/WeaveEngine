# -*- coding: utf-8 -*-
"""collide_prof3.py — 新路径内拆: cand/extract/C-kernel/list 各段耗时 (冻结输入)"""
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
print('ckernels=%s' % bool(fastpath._CKERNELS), flush=True)

import pygame
import editor
import sceneio


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
        cand = [i for i, m in enumerate(models)
                if m.collider is not None and m.collider.enabled
                and m.collider.shape != 'none']
        shapes = [models[i].collider.shape for i in cand]
        tin, tout = eng._ancestry_ranges(models, getattr(eng, '_struct_gen',
                                                         None))

        m_cand, _ = _timed(lambda: [i for i, m in enumerate(models)
                                    if m.collider is not None
                                    and m.collider.enabled
                                    and m.collider.shape != 'none'], 200)
        m_ext, _ = _timed(lambda: fastpath.collide_extract(
            cand, [aabbs[i] for i in cand],
            [models[i].collider.shape for i in cand], n), 200)
        c_cmn, c_cmx, c_kind, c_cand = fastpath.collide_extract(
            cand, [aabbs[i] for i in cand], shapes, n)

        # 真正的 C kernel 计时 (需 bmn/bmx/scn/rad/kind 全量 — 从旧提取拿)
        bmn = np.zeros((n, 3))
        bmx = np.zeros((n, 3))
        scn = np.zeros((n, 3))
        rad = np.zeros(n)
        kind = np.zeros(n, dtype=np.int64)
        for i in cand:
            shape, d = eng._collider_from_aabb(models[i].collider.shape,
                                               aabbs[i])
            if shape == 'box':
                mn, mx = d
                bmn[i] = (mn.x, mn.y, mn.z)
                bmx[i] = (mx.x, mx.y, mx.z)
            else:
                c, r = d
                scn[i] = (c.x, c.y, c.z)
                rad[i] = r
                kind[i] = 1
        m_ck, b_ck = _timed(lambda: fastpath._collide_pairs_c(
            c_cmn, c_cmx, c_cand, tin, tout, bmn, bmx, scn, rad, kind, n),
            300)

        def whole():
            cand2 = [i for i, m in enumerate(models)
                     if m.collider is not None and m.collider.enabled
                     and m.collider.shape != 'none']
            ex = fastpath.collide_extract(
                cand2, [aabbs[i] for i in cand2],
                [models[i].collider.shape for i in cand2], n)
            if ex[0] is None:
                return None
            return fastpath._collide_pairs_c(ex[0], ex[1], ex[3], tin, tout,
                                             bmn, bmx, scn, rad, kind, n)
        m_w, b_w = _timed(whole, 200)
        mw2, bw2 = _timed(lambda: eng._collision_pairs_parallel(aabbs=aabbs),
                          200)

        print('cand           %7.4f ms' % m_cand, flush=True)
        print('extract        %7.4f ms' % m_ext, flush=True)
        print('C kernel       %7.4f / %7.4f ms' % (m_ck, b_ck), flush=True)
        print('cand+ext+ck    %7.4f / %7.4f ms' % (m_w, b_w), flush=True)
        print('engine whole   %7.4f / %7.4f ms' % (mw2, bw2), flush=True)
        print('[PROF3-DONE]', flush=True)
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


if __name__ == '__main__':
    main()
    print('PROBE OK', flush=True)
