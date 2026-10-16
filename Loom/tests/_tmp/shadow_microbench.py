# -*- coding: utf-8 -*-
"""shadow_microbench.py — shadow_prep 族微基准 (冻结口径, 改造前后同框)

冻结输入 n=501, LOOM_NO_NUMBA=1 (编译等效口径):
  A. 旧路径: 属性链拆包 + tile/repeat 展开 + matmul (逐位复刻改前实现)
  B. 新路径: row_input 直喂 (复用引擎发布行表 + 真实可见过滤)
  C. 行表产出成本 (out_rows 散写增量)
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'

import numpy as np
import pygame
import editor
import sceneio
from matlib import mat4_view_forward
from engine import GLEngine

eng = editor.EditorApp(1280, 800)
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

lt = eng.lights[0]
aabbs_full = eng._prep_aabbs
n_all = len(aabbs_full)
vis_idx = [i for i, m in enumerate(eng.models) if m.visible]
vis_aabbs = [aabbs_full[i] for i in vis_idx]
n = len(vis_aabbs)

# 行表: 走引擎真发布路径 (dirty-path 稳态)
rows_full = eng._aabb_shadow_rows
gen = eng._aabb_shadow_gen
print(f"models={len(eng.models)} n_all={n_all} n_vis={n} "
      f"rows={'OK' if rows_full is not None else 'MISS'} gen={gen}", flush=True)

D = (lt.direction.x, lt.direction.y, lt.direction.z)
ln = (D[0] * D[0] + D[1] * D[1] + D[2] * D[2]) ** 0.5
D = (D[0] / ln, D[1] / ln, D[2] / ln)
eye = (lt.position.x, lt.position.y, lt.position.z)
up = (lt.up_vector().x, lt.up_vector().y, lt.up_vector().z)
view = mat4_view_forward(np, eye, D, up)

vis_rows = rows_full[vis_idx] if rows_full is not None else None


def bounds_old(view, aabbs):
    """逐位复刻改前实现."""
    n_ = len(aabbs)
    ab = np.empty((n_, 3)); cd = np.empty((n_, 3))
    for i, (a, b) in enumerate(aabbs):
        ab[i] = (a.x, a.y, a.z)
        cd[i] = (b.x, b.y, b.z)
    corners = np.empty((n_ * 8, 4), dtype=np.float64)
    xs = np.empty((n_, 2)); xs[:, 0] = ab[:, 0]; xs[:, 1] = cd[:, 0]
    ys = np.empty((n_, 2)); ys[:, 0] = ab[:, 1]; ys[:, 1] = cd[:, 1]
    zs = np.empty((n_, 2)); zs[:, 0] = ab[:, 2]; zs[:, 1] = cd[:, 2]
    corners[:, 0] = np.tile(xs, (1, 4)).ravel()
    corners[:, 1] = np.tile(np.repeat(ys, 2, axis=1), (1, 2)).ravel()
    corners[:, 2] = np.repeat(zs, 4, axis=1).ravel()
    corners[:, 3] = 1.0
    w = corners @ view
    return (w[:, :3].min(axis=0), w[:, :3].max(axis=0))


N = 2000
# 预热
for _ in range(100):
    bounds_old(view, vis_aabbs)
    GLEngine._scene_light_bounds_par(view, vis_aabbs, row_input=vis_rows)

t0 = time.perf_counter()
for _ in range(N):
    bounds_old(view, vis_aabbs)
t_old = (time.perf_counter() - t0) * 1e6 / N

t0 = time.perf_counter()
for _ in range(N):
    GLEngine._scene_light_bounds_par(view, vis_aabbs, row_input=vis_rows)
t_new = (time.perf_counter() - t0) * 1e6 / N

# 数值对拍 (顺手)
o = bounds_old(view, vis_aabbs)
w = GLEngine._scene_light_bounds_par(view, vis_aabbs, row_input=vis_rows)
same = np.array_equal(o[0], w[0]) and np.array_equal(o[1], w[1])

# 行表过滤成本 (每帧新增)
t0 = time.perf_counter()
for _ in range(N):
    r = rows_full[vis_idx]
t_filter = (time.perf_counter() - t0) * 1e6 / N

# 回退路径 (row_input=None) 现状
t0 = time.perf_counter()
for _ in range(N):
    GLEngine._scene_light_bounds_par(view, vis_aabbs)
t_fb = (time.perf_counter() - t0) * 1e6 / N

print(f"[旧路径 属性链+展开+matmul] = {t_old:.1f}us", flush=True)
print(f"[新 row_input 直喂]        = {t_new:.1f}us  (对拍逐位={'PASS' if same else 'FAIL'})",
      flush=True)
print(f"[回退 row_input=None 现状] = {t_fb:.1f}us", flush=True)
print(f"[行表可见过滤 rows[idx] 新增] = {t_filter:.1f}us", flush=True)
print(f"[shadow_bounds 净变化] {t_old - t_new - t_filter:+.1f}us/帧 "
      f"(旧→新+过滤, n=501 冻结口径)", flush=True)

eng.toggle_play()
eng._stop_parallel()
pygame.quit()
print("完成", flush=True)
