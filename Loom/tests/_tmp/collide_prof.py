# -*- coding: utf-8 -*-
"""collide_prof.py — collide_pairs 热段取证 (2026-09-07 任务1: 只测不改代码)

真实加载 保存\\压测500混合.json -> 编辑器播放态 (LOOM_NO_NUMBA=1 模拟冻结口径):
  [A] 全调用耗时: LOOM_PROFILE stage_times['collide_pairs'] / 逻辑帧数 (>=300 帧)
  [B] 冻结当帧输入, _collision_pairs_parallel 内部粗粒度拆解:
      相位计时 + 各级对数 (n_c -> P_x -> P_yz -> P_u -> P_a -> P_final)
  [C] 向量化提取原型 (np.array 一次转换) 计时 + 与旧提取消费面逐位一致性
  [D] _ancestry_ranges 缓存命中耗时 + 冷算耗时
用法: py -3.12 tests\\_tmp\\collide_prof.py [目标逻辑帧数=320]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'          # 模拟冻结 (编译版口径)
os.environ['LOOM_PROFILE'] = '1'           # stage_times 插桩 (基线同口径)

TARGET_LOGIC = int(sys.argv[1]) if len(sys.argv) > 1 else 320
DEADLINE = time.perf_counter() + 240.0     # 自看门狗: 超时自行收尾

import numpy as np

import fastpath
print('ckernels=%s numba=%s' % (bool(fastpath._CKERNELS), fastpath._NUMBA),
      flush=True)

import pygame
import editor
import sceneio
from engine import GLEngine


def _timed(fn, R):
    """返回 (mean_ms, min_ms) — 预热 1 次后计时 R 次."""
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
        print('models=%d' % len(eng.models), flush=True)

        eng.toggle_play()
        for _ in range(60):                      # 预热
            eng._handle_events()
            eng.render(1.0 / 120.0)

        # ============ [A] 播放态 stage 计时 (>=300 逻辑帧) ============
        gen0 = eng._logic_gen
        eng._stage_times.clear()
        frames = 0
        t0 = time.perf_counter()
        while (eng._logic_gen - gen0) < TARGET_LOGIC:
            eng._handle_events()
            eng.render(1.0 / 120.0)
            frames += 1
            if time.perf_counter() > DEADLINE:
                print('[watchdog] 测量窗口超时, 提前收尾', flush=True)
                break
        wall = time.perf_counter() - t0
        n_logic = eng._logic_gen - gen0
        st = eng._stage_times
        print('[A] 渲染帧=%d 墙钟=%.2fs FPS=%.1f 逻辑帧=%d'
              % (frames, wall, frames / max(wall, 1e-9), n_logic), flush=True)
        for k in ('logic_step', 'aabbs', 'collide_pairs', 'pipe_wait',
                  'world_matrices', 'shadow_bounds', 'dispatch'):
            v = st.get(k, 0.0)
            print('    %-16s %8.3f ms/逻辑帧' % (k, v / max(n_logic, 1)),
                  flush=True)
        collide_ms = st.get('collide_pairs', 0.0) / max(n_logic, 1)
        print('[A] >>> collide_pairs = %.3f ms/逻辑帧 (n_logic=%d)'
              % (collide_ms, n_logic), flush=True)

        # ============ [B] 冻结当帧输入: 内部相位拆解 ============
        models = list(eng.models)
        aabbs = eng._prep_aabbs
        n = len(models)
        assert aabbs is not None and len(aabbs) == n, 'prep_aabbs 未就绪'
        ph = {}

        def _T(key, fn):
            t0 = time.perf_counter()
            r = fn()
            ph[key] = (time.perf_counter() - t0) * 1000.0
            return r

        # -- 1) 候选收集 (Python 循环对象访问 1/2) --
        def p_cand():
            return [i for i, m in enumerate(models)
                    if m.collider is not None and m.collider.enabled
                    and m.collider.shape != 'none']
        cand = _T('1_cand', p_cand)
        n_c = len(cand)

        # -- 2) 碰撞体提取 (旧: 逐候选 _collider_from_aabb + numpy 行赋值) --
        def p_extract():
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
        bmn, bmx, scn, rad, kind = _T('2_extract_old', p_extract)

        # -- 2n) 提取原型 (list 抓取 + np.array 一次转换 + 批量派生) --
        def p_extract_new():
            rows = [aabbs[i] for i in cand]
            sph_l = [models[i].collider.shape == 'sphere' for i in cand]
            a6 = np.array(rows, dtype=np.float64)
            mn6 = a6[:, 0, :]
            mx6 = a6[:, 1, :]
            ext = mx6 - mn6
            cen = (mn6 + mx6) * 0.5
            r_all = np.maximum(np.maximum(ext[:, 0], ext[:, 1]),
                               ext[:, 2]) * 0.5
            ci_arr = np.asarray(cand, dtype=np.int64)
            bmn2 = np.zeros((n, 3), dtype=np.float64)
            bmx2 = np.zeros((n, 3), dtype=np.float64)
            scn2 = np.zeros((n, 3), dtype=np.float64)
            rad2 = np.zeros(n, dtype=np.float64)
            kind2 = np.zeros(n, dtype=np.int64)
            bmn2[ci_arr] = mn6
            bmx2[ci_arr] = mx6
            scn2[ci_arr] = cen
            rad2[ci_arr] = r_all
            kind2[ci_arr] = np.asarray(sph_l, dtype=np.int64)
            return bmn2, bmx2, scn2, rad2, kind2
        nbmn, nbmx, nscn, nrad, nkind = _T('2_extract_new', p_extract_new)

        # 消费面逐位一致性: kind / box行 bmn·bmx / sphere行 scn·rad / cmn·cmx
        ci = np.asarray(cand, dtype=np.int64)
        cmn_o = np.where(kind[ci][:, None] == 1,
                         scn[ci] - rad[ci][:, None], bmn[ci])
        cmx_o = np.where(kind[ci][:, None] == 1,
                         scn[ci] + rad[ci][:, None], bmx[ci])
        cmn_n = np.where(nkind[ci][:, None] == 1,
                         nscn[ci] - nrad[ci][:, None], nbmn[ci])
        cmx_n = np.where(nkind[ci][:, None] == 1,
                         nscn[ci] + nrad[ci][:, None], nbmx[ci])
        sph_m = kind[ci] == 1
        eq = {
            'kind': bool((nkind[ci] == kind[ci]).all()),
            'box_bmn': bool((nbmn[ci][~sph_m] == bmn[ci][~sph_m]).all()),
            'box_bmx': bool((nbmx[ci][~sph_m] == bmx[ci][~sph_m]).all()),
            'sph_scn': bool((nscn[ci][sph_m] == scn[ci][sph_m]).all()),
            'sph_rad': bool((nrad[ci][sph_m] == rad[ci][sph_m]).all()),
            'cmn': bool((cmn_n == cmn_o).all()),
            'cmx': bool((cmx_n == cmx_o).all()),
        }
        print('[C] 提取原型一致性: %s' % eq, flush=True)

        # -- 3) SAP 排序 (含现有死代码 r_order/pos_in_r 的代价) --
        def p_sort():
            order = np.argsort(cmn_o[:, 0], kind='stable')
            xmns = cmn_o[order, 0]
            r_order = np.argsort(cmx_o[:, 0], kind='stable')
            pos_in_r = np.searchsorted(cmx_o[r_order, 0], xmns, side='right')
            return order, pos_in_r

        def p_sort_clean():
            # 死代码剔除版: 只保留实际消费的 x 序
            return np.argsort(cmn_o[:, 0], kind='stable'), None
        order, _ = _T('3_sort_with_dead', p_sort)
        _ = _T('3_sort_clean', p_sort_clean)

        # -- 4) SAP 块扫描 (x 轴区间配对) --
        def p_scan(order):
            blk = 64
            pu_l = []
            pv_l = []
            for j0 in range(0, n_c, blk):
                j1 = min(j0 + blk, n_c)
                t_block = order[:j1]
                u_block = order[j0:j1]
                tb = cmx_o[t_block, 0][:, None]
                ub = cmn_o[u_block, 0][None, :]
                ok = tb > ub
                ii, jj = np.nonzero(ok)
                if ii.size:
                    pu_l.append(t_block[ii])
                    pv_l.append(u_block[jj])
            if not pu_l:
                return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
            return np.concatenate(pu_l), np.concatenate(pv_l)
        pu, pv = _T('4_scan', lambda: p_scan(order))
        p_x = len(pu)
        keep = pu != pv
        p_noself = int(keep.sum())

        # -- 5) yz 二次过滤 + unique 归一 --
        def p_yz(pu, pv):
            keep = pu != pv
            pu2, pv2 = pu[keep], pv[keep]
            yz_ok = ((cmn_o[pu2, 1] < cmx_o[pv2, 1]) &
                     (cmn_o[pv2, 1] < cmx_o[pu2, 1]) &
                     (cmn_o[pu2, 2] < cmx_o[pv2, 2]) &
                     (cmn_o[pv2, 2] < cmx_o[pu2, 2]))
            pu3, pv3 = pu2[yz_ok], pv2[yz_ok]
            mi = np.minimum(ci[pu3], ci[pv3])
            mj = np.maximum(ci[pu3], ci[pv3])
            key = mi * (n + 1) + mj
            return np.unique(key)
        key = _T('5_yz_unique', lambda: p_yz(pu, pv))
        p_u = len(key)

        # -- 6) ancestry 过滤 --
        tin, tout = eng._ancestry_ranges(models, getattr(eng, '_struct_gen',
                                                         None))

        def p_anc(key):
            mi = key // (n + 1)
            mj = key % (n + 1)
            related = ((tin[mi] <= tin[mj]) & (tin[mj] < tout[mi])) | \
                      ((tin[mj] <= tin[mi]) & (tin[mi] < tout[mj]))
            return mi[~related], mj[~related]
        ai, bj = _T('6_ancestry', lambda: p_anc(key))
        p_a = len(ai)

        # -- 7) 精判 overlap --
        def p_over():
            return GLEngine._pair_overlap_vec(ai, bj, bmn, bmx, scn, rad, kind)
        mask = _T('7_overlap', p_over)
        p_f = int(mask.sum())

        # -- 8) 结果 list 构建 --
        def p_list():
            return [(int(ai[k]), int(bj[k])) for k in np.where(mask)[0]]
        pairs_chain = _T('8_list', p_list)

        # -- 9) cmn/cmx 派生 (where) --
        _ = _T('9_cmn_where', lambda: (np.where(
            kind[ci][:, None] == 1, scn[ci] - rad[ci][:, None], bmn[ci]),
            np.where(kind[ci][:, None] == 1,
                     scn[ci] + rad[ci][:, None], bmx[ci])))

        # 全链自洽: 拆解链结果 == 引擎现实现结果 (冻结输入)
        pairs_engine = eng._collision_pairs_parallel(aabbs=aabbs)
        chain_ok = (sorted(pairs_chain) == sorted(pairs_engine))
        print('[B] 拆解链 == 引擎实现: %s (final=%d 对)'
              % (chain_ok, p_f), flush=True)

        print('[B] 对数漏斗: n_cand=%d -> P_x=%d (去自配=%d) -> P_u=%d -> '
              'P_a=%d -> P_final=%d'
              % (n_c, p_x, p_noself, p_u, p_a, p_f), flush=True)

        # ============ 相位重复计时 (R 次均值/最优) ============
        print('[B] 相位计时 (ms, mean/min):', flush=True)
        R = 200
        m1, b1 = _timed(p_cand, R)
        print('    1_cand          %8.4f / %8.4f' % (m1, b1), flush=True)
        m2, b2 = _timed(p_extract, 100)
        m2n, b2n = _timed(p_extract_new, 100)
        print('    2_extract_old   %8.4f / %8.4f' % (m2, b2), flush=True)
        print('    2_extract_new   %8.4f / %8.4f  (预期收益 %.2f ms)'
              % (m2n, b2n, m2 - m2n), flush=True)
        ms_, bs_ = _timed(p_sort, R)
        msc, bsc = _timed(p_sort_clean, R)
        print('    3_sort_with_dead %7.4f / %7.4f' % (ms_, bs_), flush=True)
        print('    3_sort_clean     %7.4f / %7.4f  (死代码代价 %.4f ms)'
              % (msc, bsc, ms_ - msc), flush=True)
        m4, b4 = _timed(lambda: p_scan(order), R)
        print('    4_scan          %8.4f / %8.4f' % (m4, b4), flush=True)
        m5, b5 = _timed(lambda: p_yz(pu, pv), R)
        print('    5_yz_unique     %8.4f / %8.4f' % (m5, b5), flush=True)
        m6, b6 = _timed(lambda: p_anc(key), R)
        print('    6_ancestry      %8.4f / %8.4f' % (m6, b6), flush=True)
        m7, b7 = _timed(p_over, 100)
        print('    7_overlap       %8.4f / %8.4f' % (m7, b7), flush=True)
        m8, b8 = _timed(p_list, R)
        print('    8_list          %8.4f / %8.4f' % (m8, b8), flush=True)
        m9, b9 = _timed(lambda: (np.where(
            kind[ci][:, None] == 1, scn[ci] - rad[ci][:, None], bmn[ci]),
            np.where(kind[ci][:, None] == 1,
                     scn[ci] + rad[ci][:, None], bmx[ci])), R)
        print('    9_cmn_where     %8.4f / %8.4f' % (m9, b9), flush=True)

        # -- 10) 整调用 (引擎现实现, 冻结输入) --
        mw, bw = _timed(lambda: eng._collision_pairs_parallel(aabbs=aabbs), 100)
        print('    whole(engine)   %8.4f / %8.4f' % (mw, bw), flush=True)

        # ============ [D] ancestry 查询 ============
        mh, bh = _timed(lambda: eng._ancestry_ranges(
            models, getattr(eng, '_struct_gen', None)), 2000)
        mc, bc = _timed(lambda: eng._ancestry_ranges(
            list(models), getattr(eng, '_struct_gen', None)), 50)  # 新列表=冷算
        print('[D] ancestry_ranges: 缓存命中 %.4f/%.4f ms | 冷算(新列表) '
              '%.4f/%.4f ms | 每逻辑帧调用 1 次 (SAP/NO_SAP 路径各 1)'
              % (mh, bh, mc, bc), flush=True)

        # ============ 汇总 ============
        ssum = m1 + m2 + ms_ + m4 + m5 + m6 + m7 + m8 + m9
        print('[SUM] 相位均值合计 %.3f ms | 引擎整调用 %.3f ms | stage口径 %.3f ms'
              % (ssum, mw, collide_ms), flush=True)
        print('[PROF-DONE] collide_ms_per_logic_frame=%.3f' % collide_ms,
              flush=True)
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
