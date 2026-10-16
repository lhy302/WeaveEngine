# -*- coding: utf-8 -*-
"""shadow_prof.py — shadow_prep 族取证探针 (2026-09-07)

冻结当帧输入逐段计时 (参考 ckernels_e2e_worker.py 的冻结口径):
LOOM_NO_NUMBA=1 (模拟编译版冻结环境), ckernels DLL 按系统默认加载.

逐段计时:
  A. cornerfill 的 ab/cd 属性链填充循环 (_scene_light_bounds_par 开头)
  B. corners 展开 (np.tile/np.repeat 链)
  C. matmul + bounds 归约
  D. 整个 _scene_light_bounds_par (新旧对比)
  E. buckets (_prepare_bucket_frame)
  F. interp (compute_render_matrices)
  G. aabbs 属性链快照成本 (若走 numpy 行路径可省多少)

方法: 真 EditorApp + 压测500混合.json + toggle_play, 预热后暂停逻辑推进
(冻结位形), 各段用 perf_counter 累计 N 次重复调用。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_NUMBA'] = '1'          # 模拟冻结 (编译版口径)

import fastpath
print(f"ckernels={'ON' if fastpath._CKERNELS else 'OFF'} numba={fastpath._NUMBA}",
      flush=True)

import numpy as np
import pygame
import editor
import sceneio

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('保存', '压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
print(f"models={len(eng.models)} lights={len(eng.lights)}", flush=True)

eng.toggle_play()
# 预热 60 帧
for _ in range(60):
    eng._handle_events()
    eng.render(1.0 / 120.0)

# 冻结当帧输入: 直接抓 prep 产物 + 重建 view 矩阵 (mat4_view_forward 同款输入)
from matlib import mat4_view_forward
lt = eng.lights[0]   # 太阳 directional full shadow
aabbs_full = eng._prep_aabbs
n_all = len(aabbs_full)
vis_aabbs = [aabbs_full[i] for i, m in enumerate(eng.models) if m.visible]
n = len(vis_aabbs)
D = (lt.direction.x, lt.direction.y, lt.direction.z)
ln = (D[0] * D[0] + D[1] * D[1] + D[2] * D[2]) ** 0.5
D = (D[0] / ln, D[1] / ln, D[2] / ln)
eye = (lt.position.x, lt.position.y, lt.position.z)
up = (lt.up_vector().x, lt.up_vector().y, lt.up_vector().z)
view = mat4_view_forward(np, eye, D, up)

times = {}
N = 2000
print(f"冻结口径: n_all={n_all} n_vis={n} 重复 N={N}", flush=True)

# ---- A+B+C+D: 新 _scene_light_bounds_par 整体 + 内部三段 ----
ab = np.empty((n, 3)); cd = np.empty((n, 3))
t0 = time.perf_counter()
for _ in range(N):
    for i, (a, b) in enumerate(vis_aabbs):
        ab[i] = (a.x, a.y, a.z)
        cd[i] = (b.x, b.y, b.z)
t_attr = (time.perf_counter() - t0) * 1e6 / N

corners = np.empty((n * 8, 4), dtype=np.float64)
t0 = time.perf_counter()
for _ in range(N):
    xs = np.empty((n, 2)); xs[:, 0] = ab[:, 0]; xs[:, 1] = cd[:, 0]
    ys = np.empty((n, 2)); ys[:, 0] = ab[:, 1]; ys[:, 1] = cd[:, 1]
    zs = np.empty((n, 2)); zs[:, 0] = ab[:, 2]; zs[:, 1] = cd[:, 2]
    corners[:, 0] = np.tile(xs, (1, 4)).ravel()
    corners[:, 1] = np.tile(np.repeat(ys, 2, axis=1), (1, 2)).ravel()
    corners[:, 2] = np.repeat(zs, 4, axis=1).ravel()
    corners[:, 3] = 1.0
t_expand = (time.perf_counter() - t0) * 1e6 / N

t0 = time.perf_counter()
for _ in range(N):
    w = corners @ view
    mn = w[:, :3].min(axis=0)
    mx = w[:, :3].max(axis=0)
t_mm = (time.perf_counter() - t0) * 1e6 / N

t0 = time.perf_counter()
for _ in range(N):
    r = eng._scene_light_bounds_par(view, vis_aabbs)
t_whole = (time.perf_counter() - t0) * 1e6 / N

print(f"[shadow_bounds 解构] 属性链ab/cd={t_attr:.1f}us  corners展开={t_expand:.1f}us  "
      f"matmul+minmax={t_mm:.1f}us  整体={t_whole:.1f}us", flush=True)

# ---- 新候选: numpy 行直填 (模拟 _aabbs_batched 产出 (n,6) 行) ----
rows = np.empty((n, 6), dtype=np.float64)
for i, (a, b) in enumerate(vis_aabbs):
    rows[i, 0] = a.x; rows[i, 1] = a.y; rows[i, 2] = a.z
    rows[i, 3] = b.x; rows[i, 4] = b.y; rows[i, 5] = b.z
mn2 = np.empty((n, 2)); mx2 = np.empty((n, 2))
t0 = time.perf_counter()
for _ in range(N):
    ab2 = rows[:, 0:3]; cd2 = rows[:, 3:6]
    xs = np.empty((n, 2)); xs[:, 0] = ab2[:, 0]; xs[:, 1] = cd2[:, 0]
    ys = np.empty((n, 2)); ys[:, 0] = ab2[:, 1]; ys[:, 1] = cd2[:, 1]
    zs = np.empty((n, 2)); zs[:, 0] = ab2[:, 2]; zs[:, 1] = cd2[:, 2]
    corners[:, 0] = np.tile(xs, (1, 4)).ravel()
    corners[:, 1] = np.tile(np.repeat(ys, 2, axis=1), (1, 2)).ravel()
    corners[:, 2] = np.repeat(zs, 4, axis=1).ravel()
    corners[:, 3] = 1.0
    w = corners @ view
    mn = w[:, :3].min(axis=0)
    mx = w[:, :3].max(axis=0)
t_new = (time.perf_counter() - t0) * 1e6 / N
print(f"[numpy行直填版] 整体={t_new:.1f}us (省属性链+strided读取)", flush=True)

# ---- E: buckets (_prepare_bucket_frame) ----
# 强制重填 (清 sig) 测整段; 再测命中路径
eng._bucket_frame_sig = None
t0 = time.perf_counter()
for _ in range(200):
    eng._bucket_frame_sig = None
    eng._prepare_bucket_frame()
t_bkt_full = (time.perf_counter() - t0) * 1e6 / 200
t0 = time.perf_counter()
for _ in range(2000):
    eng._prepare_bucket_frame()
t_bkt_hit = (time.perf_counter() - t0) * 1e6 / 2000
print(f"[buckets] 重填={t_bkt_full:.1f}us  闸命中={t_bkt_hit:.1f}us", flush=True)

# ---- F: interp (compute_render_matrices) ----
t0 = time.perf_counter()
for _ in range(300):
    eng.compute_render_matrices(eng.models)
t_interp = (time.perf_counter() - t0) * 1e6 / 300
print(f"[interp] compute_render_matrices={t_interp:.1f}us", flush=True)

# ---- G: aabbs 侧 Point3D 构造成本 (回端: mn_v/mx_v tolist + Point3D×2×N) ----
vh = eng._homogeneous_vertices(eng.models[0].mesh)
t0 = time.perf_counter()
for _ in range(200):
    out = eng._aabbs_batched(eng.models, eng._frame_world, False, _row_cache=False)
t_bat = (time.perf_counter() - t0) * 1e6 / 200
mn_rows = None
print(f"[aabbs_batched n=501 全流程]={t_bat:.1f}us", flush=True)

eng.toggle_play()
eng._stop_parallel()
pygame.quit()
print("完成", flush=True)
