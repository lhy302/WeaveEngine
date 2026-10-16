# -*- coding: utf-8 -*-
"""accept1_e2e_check.py — 验收① 端到端: 无用户 DLL 时引擎核心链路完整可用。

口径 (总纲 §六 M1 验收①): registry.json 全官方条目 (无用户注入) →
assemble 全 loaded/0 popped → 经注册表句柄真跑两条热路径 (echo + aabbs)。
"""
import ctypes
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

import numpy as np
import module_loader as ml
import module_registry as mr

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


def main():
    reg = json.load(open('core_components/registry.json', encoding='utf-8'))
    inj = [c for c in reg['components'] if not c['official']]
    check('1a 注册表无用户注入条目', len(inj) == 0, 'injected=%d' % len(inj))

    a = mr.assemble()
    check('1b 全官方组装 loaded=5 / popped=0',
          sorted(a.modules) == ['ckernels', 'module_ref', 'physics', 'pipeline', 'script']
          and not [r for r in a.report if r['action'] == 'popped'],
          'modules=%r actions=%r' % (sorted(a.modules),
                                     [r['action'] for r in a.report]))
    check('1c provides_map 12 项齐全',
          a.provides_map == {'module_ref.echo': 'module_ref',
                             'ckernels.aabbs': 'ckernels',
                             'ckernels.collide': 'ckernels',
                             'pipeline.light_vps': 'pipeline',
                             'pipeline.scene_bounds': 'pipeline',
                             'pipeline.aabbs': 'pipeline',
                             'pipeline.world_matrices': 'pipeline',
                             'script.batch_rotate': 'script',
                             'script.batch_move': 'script',
                             'physics.pre_step': 'physics',
                             'physics.post_step': 'physics',
                             'physics.substep_loop': 'physics'})

    # 热路径 1: ckernels aabbs 经注册表句柄
    h = a.get('ckernels')
    pd = ctypes.POINTER(ctypes.c_double)
    fn = h.get_fn('loom_aabbs_minmax', ctypes.c_int32,
                  [pd, pd, pd, pd, ctypes.c_int64, ctypes.c_int64])
    n, V = 64, 37
    rng = np.random.default_rng(20260908)
    vh = np.ascontiguousarray(rng.standard_normal((n, V, 4)), dtype=np.float64)
    m3 = np.ascontiguousarray(rng.standard_normal((n, 4, 3)), dtype=np.float64)
    mn, mx = np.zeros((n, 3)), np.zeros((n, 3))
    rc1 = int(fn(vh.ctypes.data_as(pd), m3.ctypes.data_as(pd),
                 mn.ctypes.data_as(pd), mx.ctypes.data_as(pd),
                 ctypes.c_int64(n), ctypes.c_int64(V)))
    import fastpath
    pmn, pmx = np.zeros((n, 3)), np.zeros((n, 3))
    # B1 口径调整 (2026-10-16): 基准换 numpy 批量 (_aabbs_minmax_np), 与 ckernels
    # 标量内核 ~4 ULP 级差, 断言改 D6 标准 1e-7 (同 pipeline_val_check / module_contract A11)。
    fastpath._aabbs_minmax_np(vh, m3, pmn, pmx)
    d1 = float(np.max(np.abs(mn - pmn)))
    d2 = float(np.max(np.abs(mx - pmx)))
    check('1d aabbs 经注册表句柄 rc=0 + D6 容差', rc1 == 0 and d1 <= 1e-7 and d2 <= 1e-7,
          'rc=%d dmn=%g dmx=%g' % (rc1, d1, d2))

    # 热路径 2: module_ref echo 经注册表句柄
    hr = a.get('module_ref')
    src = np.arange(12, dtype=np.float64).reshape(3, 4)
    dst = np.zeros_like(src)
    st, _k1 = ml.tensor_from_array(src)
    dt, _k2 = ml.tensor_from_array(dst)
    ef = hr.get_fn('module_ref_echo', ctypes.c_int32,
                   [ctypes.POINTER(ml.LoomTensor), ctypes.POINTER(ml.LoomTensor)])
    rc2 = int(ef(ctypes.byref(st), ctypes.byref(dt)))
    de = float(np.max(np.abs(dst - src)))
    check('1e echo 经注册表句柄 rc=0 + 逐位', rc2 == 0 and de == 0.0,
          'rc=%d maxdiff=%g' % (rc2, de))

    # 逃生门: 全跳后引擎不死 (get 抛 ModuleNotAvailable, 进程正常退出)
    os.environ['LOOM_NO_DLL'] = '*'
    a2 = mr.assemble()
    ok_escape = (a2.modules == {} and _raises(ml.ModuleNotAvailable,
                                              lambda: a2.get('ckernels')))
    os.environ.pop('LOOM_NO_DLL', None)
    check('1f LOOM_NO_DLL=* 全跳且 get 抛 (引擎不死)', ok_escape)
    a.shutdown()
    a2.shutdown()

    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


if __name__ == '__main__':
    sys.exit(main())

