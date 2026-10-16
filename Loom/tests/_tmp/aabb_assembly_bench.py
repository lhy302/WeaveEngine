# -*- coding: utf-8 -*-
"""aabb_assembly_bench.py — aabbs 组装段方案对比微基准 (2026-09-07).

背景: _aabbs_batched 组装段 `for r: vhN_v[r]=lst[r][1]; m3N_v[r]=lst[r][2]`
逐行 Python 拷贝 ~9ms/逻辑帧 (500x2035x4 f64)。混合500 场景同网格样本共享
同一 vh 数组对象 (_homogeneous_vertices 按 id(mesh) 缓存) -> 去重空间大。

复刻 压测500混合.json 形态 (460 球 30 参数组合 + 40 cube 4 size + 1 plane),
分组逻辑与 staging 缓存复刻 engine._aabbs_batched, 只比组装段:

  0 现状     : 逐行写 vh + 逐行写 m3 (零分配, 解释器循环)
  A 身份命中 : 行身份序列 (id tuple) 命中 -> vh 段整段跳过 (vh 内容不可变);
               miss -> 唯一行逐行写 uniq + np.take(out=vhN_v) 零临时 C 级 gather
  B 每帧gather: 无身份缓存, 每帧唯一行写 uniq + take(out=) (含每帧 seq 构建
               与 inv 重算, 但无命中跳过)
  C fancy临时: vhN_v[...] = uniq[:nu][inv] (每帧建 32MB 临时 —— 第 11 版
               np.stack 32MB 倒退教训同源, 仅取证)

m3N 各方案同款逐行写 (小缓冲 96B/行, 协调者 b 结论: 别动大的)。
另报: 分组段 / 内核 C 串行 参照值。分配差异用 tracemalloc 单独差分 (不混计时)。
纯 ASCII 输出。
"""
import os
import sys
import time
import tracemalloc

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mesh import create_sphere, create_cube, create_plane  # noqa: E402
from engine import GLEngine  # noqa: E402
import fastpath  # noqa: E402

# ---- 场景形态复刻 (压测500混合.json 实测参数分布) --------------------------
SPHERES = [  # (radius, stacks, slices, count)
    (0.6, 44, 66, 20), (0.7, 40, 60, 20), (0.8, 36, 54, 20), (0.9, 32, 48, 20),
    (1.0, 28, 42, 20), (1.1, 44, 66, 20), (0.6, 40, 60, 20), (0.7, 36, 54, 20),
    (0.8, 32, 48, 20), (0.9, 28, 42, 20), (1.0, 44, 66, 20), (1.1, 40, 60, 20),
    (0.6, 36, 54, 20), (0.7, 32, 48, 20), (0.8, 28, 42, 20), (0.9, 44, 66, 20),
    (1.0, 40, 60, 10), (1.1, 36, 54, 10), (0.6, 32, 48, 10), (0.7, 28, 42, 10),
    (0.8, 44, 66, 10), (0.9, 40, 60, 10), (1.0, 36, 54, 10), (1.1, 32, 48, 10),
    (0.6, 28, 42, 10), (0.7, 44, 66, 10), (0.8, 40, 60, 10), (0.9, 36, 54, 10),
    (1.0, 32, 48, 10), (1.1, 28, 42, 10),
]
CUBES = [(1.6, 10), (1.3, 10), (1.1, 10), (0.9, 10)]

eng = GLEngine.__new__(GLEngine)
eng._bb_cache = {}
eng._aabb_staging = None

# 网格池: 同参数组合共享同一 mesh 对象 (同 JSON 加载行为 -> 同 id(mesh) -> 同 vh)
mesh_pool = {}
for r, st, sl, _c in SPHERES:
    mesh_pool.setdefault(('s', r, st, sl), create_sphere(r, st, sl))
for sz, _c in CUBES:
    mesh_pool.setdefault(('c', sz), create_cube(sz))
plane_mesh = create_plane()

models = []
for r, st, sl, cnt in SPHERES:
    m = type('M', (), {})(); m.mesh = mesh_pool[('s', r, st, sl)]
    m.visible = True
    models.extend([m] * cnt)
for sz, cnt in CUBES:
    m = type('M', (), {})(); m.mesh = mesh_pool[('c', sz)]
    m.visible = True
    models.extend([m] * cnt)
m = type('M', (), {})(); m.mesh = plane_mesh; m.visible = True
models.append(m)

N = len(models)
rng = np.random.default_rng(7)
fw = []
for i in range(N):
    T = np.eye(4); T[:3, 3] = rng.uniform(-28, 28, 3)
    A = rng.uniform(-0.9, 0.9, (3, 3)); A = np.linalg.svd(A)[0]
    M = np.eye(4); M[:3, :3] = A * rng.uniform(0.5, 1.5, 3)
    fw.append(T @ M)

# 分组段 (与 engine 同款, 只跑一次取形态账)
t0 = time.perf_counter()
sel = [(k, models[k]) for k in range(N) if getattr(models[k], 'visible', True)]
groups = {}
for k, m in sel:
    M = fw[k]
    vh = eng._homogeneous_vertices(m.mesh)
    groups.setdefault(vh.shape[0], []).append((k, vh, M[:, :3]))
assert len(sel) == N
t_groups = (time.perf_counter() - t0) * 1000

uniq_total = 0
for gi, lst in enumerate(groups.values()):
    V = lst[0][1].shape[0]
    ids = [id(row[1]) for row in lst]
    nu = len(set(ids))
    uniq_total += nu
    print(f"group gi={gi} V={V:5d} rows={len(lst):3d} uniq_vh={nu:2d}")
print(f"groups={len(groups)} total_rows={N} total_uniq={uniq_total}")
print(f"groups build: {t_groups:.2f} ms (参照, 不在组装段账内)")

# staging 复刻 (grow-only, 与 engine 键=(gi,V) 同款)
bufs = {}
for gi, lst in enumerate(groups.values()):
    n = len(lst); V = lst[0][1].shape[0]
    bufs[(gi, V)] = (np.empty((n, V, 4)), np.empty((n, 4, 3)),
                     np.empty((n, 3)), np.empty((n, 3)),
                     np.empty((n, V, 4)), np.empty((n,), np.intp))


def assemble_now(gi, lst):
    """方案0 现状: 逐行写."""
    vhN, m3N, mn, mx, _uniq, _inv = bufs[(gi, lst[0][1].shape[0])]
    n = len(lst)
    vhN_v = vhN[:n]; m3N_v = m3N[:n]
    for r in range(n):
        vhN_v[r] = lst[r][1]
        m3N_v[r] = lst[r][2]


def _gather_write(gi, lst, use_seq_cache):
    """方案 A/B 公共体: 唯一行写 + take(out=) gather.
    use_seq_cache=True (A): 身份序列命中 -> vh 段整段跳过."""
    vhN, m3N, mn, mx, uniq, inv = bufs[(gi, lst[0][1].shape[0])]
    n = len(lst)
    ent = seq_cache.get(gi)
    seq = [id(row[1]) for row in lst]
    if use_seq_cache and ent is not None and ent[0] == n and ent[1] == seq:
        hit[0] += 1
    else:
        seen = {}
        u_rows = []
        for r, row in enumerate(lst):
            k = id(row[1])
            j = seen.get(k, -1)
            if j < 0:
                j = len(u_rows); seen[k] = j; u_rows.append(row[1])
            inv[r] = j
        nu = len(u_rows)
        uniq_v = uniq[:nu]
        for j in range(nu):
            uniq_v[j] = u_rows[j]
        # ★mode='clip': np.take 默认 mode='raise' 时 out= 被强制缓冲
        # (numpy 文档: "out is always buffered if mode='raise'"), 每帧建
        # n*V*4 f64 临时 (实测 B 方案 17.7ms + 9.65MB) —— clip 无此缓冲
        # (inv 值域 [0,nu) 受控, 语义等价)。
        np.take(uniq[:nu], inv[:n], axis=0, out=vhN[:n], mode='clip')
        # 持有 vh 引用防 id 复用假阳性 + 记录序列
        seq_cache[gi] = (n, seq, u_rows)
    vhN_v = vhN[:n]; m3N_v = m3N[:n]
    for r in range(n):
        m3N_v[r] = lst[r][2]


seq_cache = {}
hit = [0]


def assemble_hit(gi, lst):
    """方案 A: 身份命中跳写."""
    _gather_write(gi, lst, True)


def assemble_gather(gi, lst):
    """方案 B: 每帧 gather (seq 每帧重算不命中 — 清缓存模拟)."""
    seq_cache.pop(gi, None)
    _gather_write(gi, lst, True)
    seq_cache.pop(gi, None)          # 下一帧必 miss


def assemble_fancy(gi, lst):
    """方案 C: fancy index 临时分配 gather (取证)."""
    vhN, m3N, mn, mx, uniq, inv = bufs[(gi, lst[0][1].shape[0])]
    n = len(lst)
    seen = {}
    u_rows = []
    for r, row in enumerate(lst):
        k = id(row[1])
        j = seen.get(k, -1)
        if j < 0:
            j = len(u_rows); seen[k] = j; u_rows.append(row[1])
        inv[r] = j
    nu = len(u_rows)
    uniq_v = uniq[:nu]
    for j in range(nu):
        uniq_v[j] = u_rows[j]
    vhN[:n] = uniq[:nu][inv[:n]]     # (n,V,4) 临时 32MB
    m3N_v = m3N[:n]
    for r in range(n):
        m3N_v[r] = lst[r][2]


def run_assembly(asm):
    for gi, lst in enumerate(groups.values()):
        asm(gi, lst)


def bench(asm, rounds=60):
    hit[0] = 0
    run_assembly(asm)                       # 预热 (页/命中态)
    hit[0] = 0                              # 计数只计测量窗
    t0 = time.perf_counter()
    for _ in range(rounds):
        run_assembly(asm)
    dt = (time.perf_counter() - t0) * 1000.0 / rounds
    return dt, hit[0] / (rounds * len(groups))


t_now = bench(assemble_now)[0]
t_hit, hitA = bench(assemble_hit)
t_gather, _h = bench(assemble_gather)
t_fancy = bench(assemble_fancy)[0]

print("--- assembly stage (501 rows, 7 groups) ---")
print(f"0 now   (row-by-row)        {t_now:8.3f} ms/frame")
print(f"A hit   (seq-hit + take clip out=) {t_hit:8.3f} ms/frame  (seq-hit {hitA*100:.0f}%)")
print(f"B gather (take clip out=, no cache) {t_gather:8.3f} ms/frame")
print(f"C fancy (32MB temp)         {t_fancy:8.3f} ms/frame")
print(f"A vs now: {t_now/max(t_hit,1e-9):.2f}x   B vs now: {t_now/max(t_gather,1e-9):.2f}x")

# ---- 分配差分 (tracemalloc, 计时口径外) -----------------------------------
def alloc_frame(asm):
    tracemalloc.start()
    run_assembly(asm)
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


run_assembly(assemble_now)      # 预热
hit[0] = 0
a0 = alloc_frame(assemble_now)
aA = alloc_frame(assemble_hit)
aB = alloc_frame(assemble_gather)
aC = alloc_frame(assemble_fancy)
print("--- tracemalloc peak per frame (delta over idle) ---")
print(f"0 now {a0/1e6:8.2f} MB | A hit {aA/1e6:8.2f} MB | "
      f"B gather {aB/1e6:8.2f} MB | C fancy {aC/1e6:8.2f} MB")

# ---- 内核参照 (C 串行, 含 staging 写后全链路口径对照) ----------------------
gv = list(groups.values())
lst0 = gv[0]
n0, V0 = len(lst0), lst0[0][1].shape[0]
vhN, m3N, mn, mx, _u, _i = bufs[(0, V0)]
mn0 = np.empty((n0, 3)); mx0 = np.empty((n0, 3))
fastpath.aabbs_minmax(vhN[:n0], m3N[:n0], mn0, mx0)   # 预热
t0 = time.perf_counter()
for _ in range(60):
    fastpath.aabbs_minmax(vhN[:n0], m3N[:n0], mn0, mx0)
t_k = (time.perf_counter() - t0) * 1000 / 60
print(f"kernel ref (C serial, largest group n={n0} V={V0}): {t_k:.2f} ms")

# ---- 整机口径: 旧实现 (改前 _aabbs_batched 逐字复刻) vs 新引擎整方法 ------
def old_batched(eng_, models_, fw_):
    sel = []
    for k, m in enumerate(models_):
        M = fw_[k] if fw_ is not None and k < len(fw_) else None
        if not getattr(m, 'visible', True):
            continue
        sel.append((m, M))
    out = [None] * len(sel)
    groups_ = {}
    for k, (m, M) in enumerate(sel):
        if M is None:
            continue
        vh = eng_._homogeneous_vertices(m.mesh)
        groups_.setdefault(vh.shape[0], []).append((k, vh, M[:, :3]))
    ob = {}
    for gi, lst in enumerate(groups_.values()):
        n = len(lst); V = lst[0][1].shape[0]
        ent = ob.get((gi, V))
        if ent is None or ent[0].shape[0] < n:
            cap = n if ent is None else max(n, ent[0].shape[0] * 2)
            ob[(gi, V)] = ent = (np.empty((cap, V, 4)), np.empty((cap, 4, 3)),
                                 np.empty((cap, 3)), np.empty((cap, 3)))
        vhN, m3N, mn, mx = ent
        vhN_v = vhN[:n]; m3N_v = m3N[:n]; mn_v = mn[:n]; mx_v = mx[:n]
        for r in range(n):
            vhN_v[r] = lst[r][1]
            m3N_v[r] = lst[r][2]
        fastpath.aabbs_minmax(vhN_v, m3N_v, mn_v, mx_v)
        mn_rows = mn_v.tolist(); mx_rows = mx_v.tolist()
        for r in range(n):
            a, b = mn_rows[r], mx_rows[r]
            out[lst[r][0]] = (a, b)
    return out


eng2 = GLEngine.__new__(GLEngine)
eng2._bb_cache = {}
eng2._aabb_staging = None
old_batched(eng2, models, fw)            # 预热旧路缓冲
eng2._aabbs_batched(models, fw)          # 预热新路缓冲 (含命中态)
R = 40
t0 = time.perf_counter()
for _ in range(R):
    old_batched(eng2, models, fw)
t_old_full = (time.perf_counter() - t0) * 1000 / R
t0 = time.perf_counter()
for _ in range(R):
    eng2._aabbs_batched(models, fw)
t_new_full = (time.perf_counter() - t0) * 1000 / R
print("--- whole method (501 objs, group+assembly+kernel+tolist) ---")
print(f"old batched (row-by-row):   {t_old_full:8.3f} ms/call")
print(f"new engine (hit path):      {t_new_full:8.3f} ms/call  "
      f"({t_old_full/max(t_new_full,1e-9):.2f}x)")
print('DONE')
