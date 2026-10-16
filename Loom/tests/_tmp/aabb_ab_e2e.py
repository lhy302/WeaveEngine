# -*- coding: utf-8 -*-
"""aabb_ab_e2e.py — 组装段优化 A/B 端到端交替对拍 (2026-09-07).

同一 worker 进程内交替: OLD = 改前逐行写 (猴子补丁替换 _aabbs_batched
为逐字复刻版), NEW = 当前引擎实现。交错多轮抵消环境漂移, 每轮独立
预热+5s 测量 (与 ckernels_e2e_worker.py 同口径: LOOM_NO_NUMBA=1, C 开,
混合500 播放态)。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'

import numpy as np
import fastpath
import pygame
import editor
import sceneio
from engine import Point3D


def old_aabbs_batched(self, models, fw, visible_only=True, _row_cache=True):
    """改前 _aabbs_batched 逐字复刻 (逐行写 staging)."""
    import threading
    sel = []
    for k, m in enumerate(models):
        M = fw[k] if fw is not None and k < len(fw) else None
        if visible_only and not getattr(m, 'visible', True):
            continue
        sel.append((m, M))
    if not sel:
        return []
    out = [None] * len(sel)
    groups = {}
    for k, (m, M) in enumerate(sel):
        if M is None:
            out[k] = self.get_bounding_box(m, None)
            continue
        vh = self._homogeneous_vertices(m.mesh)
        if vh.shape[1] != 4 or M.shape != (4, 4):
            out[k] = self.get_bounding_box(m, M)
            continue
        groups.setdefault(vh.shape[0], []).append((k, vh, M[:, :3]))
    tlc = getattr(self, '_aabb_staging_old', None)
    if tlc is None:
        tlc = self._aabb_staging_old = threading.local()
    buf_cache = getattr(tlc, 'bufs', None)
    if buf_cache is None:
        buf_cache = tlc.bufs = {}
    for gi, lst in enumerate(groups.values()):
        n = len(lst)
        V = lst[0][1].shape[0]
        ent = buf_cache.get((gi, V))
        if ent is None or ent[0].shape[0] < n:
            cap = n if ent is None else max(n, ent[0].shape[0] * 2)
            vhN = np.empty((cap, V, 4), dtype=np.float64)
            m3N = np.empty((cap, 4, 3), dtype=np.float64)
            mn = np.empty((cap, 3), dtype=np.float64)
            mx = np.empty((cap, 3), dtype=np.float64)
            buf_cache[(gi, V)] = (vhN, m3N, mn, mx)
        else:
            vhN, m3N, mn, mx = ent
        vhN_v = vhN[:n]
        m3N_v = m3N[:n]
        mn_v = mn[:n]
        mx_v = mx[:n]
        for r in range(n):
            vhN_v[r] = lst[r][1]
            m3N_v[r] = lst[r][2]
        if n >= self._AABB_PAR_MIN_MODELS:
            fastpath.aabbs_minmax_par(vhN_v, m3N_v, mn_v, mx_v)
        else:
            fastpath.aabbs_minmax(vhN_v, m3N_v, mn_v, mx_v)
        mn_rows = mn_v.tolist()
        mx_rows = mx_v.tolist()
        for r in range(n):
            a, b = mn_rows[r], mx_rows[r]
            out[lst[r][0]] = (Point3D(a[0], a[1], a[2]),
                              Point3D(b[0], b[1], b[2]))
    return out


NEW = editor.GLEngine._aabbs_batched

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
print(f"models={len(eng.models)} lights={len(eng.lights)}", flush=True)

eng.toggle_play()
clock = pygame.time.Clock()


def measure(label):
    """预热 90 帧 + 5s 稳态, 返回 FPS."""
    for _ in range(90):
        eng._handle_events()
        eng.render(1.0 / 120.0)
    frames = 0
    t0 = time.perf_counter()
    end = time.perf_counter() + 5.0
    while time.perf_counter() < end:
        eng._handle_events()
        eng.render(1.0 / 120.0)
        frames += 1
    wall = time.perf_counter() - t0
    return frames / wall


# 交错 8 轮 (O N x4), 每轮前换实现; 配对比值消漂移
results = {'OLD': [], 'NEW': []}
for rnd in range(4):
    for tag, fn in (('OLD', old_aabbs_batched), ('NEW', NEW)):
        editor.GLEngine._aabbs_batched = fn
        fps = measure(tag)
        results[tag].append(fps)
        print(f"round{rnd+1} {tag}: {fps:.2f} FPS", flush=True)

mo = sum(results['OLD']) / 4
mn = sum(results['NEW']) / 4
print(f"OLD avg={mo:.2f}  NEW avg={mn:.2f}  ratio={mn/mo:.3f}")
print(" ".join(f"OLD={' '.join(f'{v:.1f}' for v in results['OLD'])} "
               f"NEW={' '.join(f'{v:.1f}' for v in results['NEW'])}"))
eng.toggle_play()
eng._stop_parallel()
pygame.quit()
