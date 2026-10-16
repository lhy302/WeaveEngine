# -*- coding: utf-8 -*-
"""aabb_assembly_check.py — aabbs 组装段去重 (2026-09-07) 对拍验收.

断言:
 1. 真实场景 压测500混合.json 冻结当帧: 新实现 (唯一行表+gather+身份命中)
    vs 参考旧实现 (逐行写, 改前代码逐字复刻) — staging vhN/m3N 前 n 行
    np.array_equal 逐位一致 + AABB 输出逐位一致; miss 帧/命中帧各测一次
    (命中帧 vhN 内容必须保持 — 缓冲无人改写)。
 2. 随机场景 x3 (同网格多实例+独立网格混合 / n 波动 grow-reuse / 每帧换
    网格对象且换几何值 — id 复用假命中陷阱): 同款断言全过。
 3. 缓冲真复用: 两次调用 staging 缓冲对象身份不变 (零重分配)。
纯 ASCII 输出, exit 0 = 全过。
"""
import os
import sys
import gc

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import fastpath  # noqa: E402
from engine import GLEngine, Point3D  # noqa: E402
from mesh import create_sphere, create_cube, create_plane  # noqa: E402

fails = 0


def check(name, ok, detail=''):
    global fails
    print(('[PASS] ' if ok else '[FAIL] ') + name + (' | ' + detail if detail else ''))
    if not ok:
        fails += 1


# ---- 参考旧实现 (改前 _aabbs_batched 组装段逐字复刻, 独立缓冲) -------------
def old_assembly(eng, models, fw, visible_only=True):
    sel = []
    for k, m in enumerate(models):
        M = fw[k] if fw is not None and k < len(fw) else None
        if visible_only and not getattr(m, 'visible', True):
            continue
        sel.append((m, M))
    if not sel:
        return [], {}
    out = [None] * len(sel)
    groups = {}
    for k, (m, M) in enumerate(sel):
        if M is None:
            out[k] = eng.get_bounding_box(m, None)
            continue
        vh = eng._homogeneous_vertices(m.mesh)
        if vh.shape[1] != 4 or M.shape != (4, 4):
            out[k] = eng.get_bounding_box(m, M)
            continue
        groups.setdefault(vh.shape[0], []).append((k, vh, M[:, :3]))
    bufs = {}
    for gi, lst in enumerate(groups.values()):
        n = len(lst)
        V = lst[0][1].shape[0]
        ent = bufs.get((gi, V))
        if ent is None or ent[0].shape[0] < n:
            cap = n if ent is None else max(n, ent[0].shape[0] * 2)
            vhN = np.empty((cap, V, 4), dtype=np.float64)
            m3N = np.empty((cap, 4, 3), dtype=np.float64)
            mn = np.empty((cap, 3), dtype=np.float64)
            mx = np.empty((cap, 3), dtype=np.float64)
            bufs[(gi, V)] = ent = (vhN, m3N, mn, mx)
        else:
            vhN, m3N, mn, mx = ent
        vhN_v = vhN[:n]
        m3N_v = m3N[:n]
        mn_v = mn[:n]
        mx_v = mx[:n]
        for r in range(n):
            vhN_v[r] = lst[r][1]
            m3N_v[r] = lst[r][2]
        fastpath.aabbs_minmax(vhN_v, m3N_v, mn_v, mx_v)
        mn_rows = mn_v.tolist()
        mx_rows = mx_v.tolist()
        for r in range(n):
            a, b = mn_rows[r], mx_rows[r]
            out[lst[r][0]] = (Point3D(a[0], a[1], a[2]),
                              Point3D(b[0], b[1], b[2]))
    return out, bufs


def aabbs_np(out):
    """AABB 列表 -> (n,6) f64 (逐位比较用)."""
    arr = np.empty((len(out), 6), dtype=np.float64)
    for i, (a, b) in enumerate(out):
        arr[i, 0] = a.x; arr[i, 1] = a.y; arr[i, 2] = a.z
        arr[i, 3] = b.x; arr[i, 4] = b.y; arr[i, 5] = b.z
    return arr


def compare_case(name, eng, models, fw, visible_only, ref_bufs_ref):
    """新实现两连跑 (miss+hit) vs 参考旧实现: staging 行 + AABB 逐位."""
    ref_out, ref_bufs = old_assembly(eng, models, fw, visible_only)
    ref_bufs_ref.clear()
    ref_bufs_ref.update(ref_bufs)

    out1 = eng._aabbs_batched(models, fw, visible_only)
    snap1 = {k: (v[0][:].copy(), v[1][:].copy(), v[0].shape[0])
             for k, v in eng._aabb_staging.bufs.items()}
    ids1 = {k: (id(v[0]), id(v[1]), id(v[4]), id(v[5]))
            for k, v in eng._aabb_staging.bufs.items()}
    out2 = eng._aabbs_batched(models, fw, visible_only)   # 命中帧
    ids2 = {k: (id(v[0]), id(v[1]), id(v[4]), id(v[5]))
            for k, v in eng._aabb_staging.bufs.items()}

    ok_out = (np.array_equal(aabbs_np(ref_out), aabbs_np(out1))
              and np.array_equal(aabbs_np(ref_out), aabbs_np(out2)))
    check(f'{name}: AABB 输出逐位一致 (miss+hit 两帧)', ok_out)

    ok_buf = True
    for key, (vh1, m31, n1) in snap1.items():
        # 新键 = (gi, V, 身份序列); 参考旧实现键 = (gi, V) —— 取前两元映射
        ref_key = (key[0], key[1])
        if ref_key not in ref_bufs:
            ok_buf = False
            print(f'  [detail] 参考缺组 ref_key={ref_key}')
            continue
        vhR, m3R, mnR, mxR = ref_bufs[ref_key]
        n = min(n1, vhR.shape[0])
        if not (np.array_equal(vh1[:n], vhR[:n]) and np.array_equal(m31[:n], m3R[:n])):
            ok_buf = False
            print(f'  [detail] staging 不一致 key={key[:2]} n={n}')
    check(f'{name}: staging vhN/m3N 前 n 行逐位一致 '
          f'({len(snap1)} 组)', ok_buf)

    # 命中帧缓冲身份不变 (零重分配) + 命中帧 staging 行仍与参考一致
    # (snap1 已是 miss 帧行快照; 命中帧不重写 -> 与 snap1 逐位同)
    check(f'{name}: 缓冲对象身份稳定 (真复用非重建)', ids1 == ids2)
    snap2 = {k: (v[0][:].copy(), v[1][:].copy())
             for k, v in eng._aabb_staging.bufs.items()}
    ok_hit = all(np.array_equal(snap1[k][0][:snap1[k][2]], snap2[k][0][:snap1[k][2]])
                 and np.array_equal(snap1[k][1][:snap1[k][2]], snap2[k][1][:snap1[k][2]])
                 for k in snap1)
    check(f'{name}: 命中帧 staging 行与 miss 帧逐位同 (vh 段真跳写)', ok_hit)


# ==== 1. 真实场景: 压测500混合.json 冻结当帧 ================================
import pygame  # noqa: E402
import editor  # noqa: E402
import sceneio  # noqa: E402

eng = editor.EditorApp(1280, 800)
for m in list(eng.models):
    eng.remove_model(m)
eng.lights.clear()
data = sceneio.load_scene_data(os.path.join('压测500混合.json'))
sceneio.scene_from_dict(eng, data)
eng.current_model_index = 0
fw_real = eng.compute_world_matrices(eng.models)
print(f'real scene: models={len(eng.models)} fw={fw_real.shape}')

ref_hold = {}
compare_case('真实混合500 (visible_only=False)', eng, list(eng.models),
             fw_real, False, ref_hold)
compare_case('真实混合500 (visible_only=True)', eng, list(eng.models),
             fw_real, True, ref_hold)

# ==== 2. 随机场景 x3 =======================================================
eng2 = GLEngine.__new__(GLEngine)
eng2._bb_cache = {}
eng2._aabb_staging = None
rng = np.random.default_rng(99)


def stub(mesh, visible=True):
    m = type('M', (), {})()
    m.mesh = mesh
    m.visible = visible
    return m


def rand_fw(n):
    out = []
    for _ in range(n):
        T = np.eye(4); T[:3, 3] = rng.uniform(-9, 9, 3)
        A = rng.uniform(-0.9, 0.9, (3, 3)); A = np.linalg.svd(A)[0]
        M = np.eye(4); M[:3, :3] = A * rng.uniform(0.5, 1.5, 3)
        out.append(T @ M)
    return out


# R1: 同网格多实例 + 独立网格 (同参数不同对象=值同 id 异) + 隐形物体 混合
shared = [create_sphere(0.8, 20, 30), create_cube(1.2), create_plane()]
indep = [create_sphere(0.8, 20, 30) for _ in range(3)]     # 值同 id 异
tiny = type('Mesh', (), {})()
tiny.vertices = [(0.0, 0.0, 0.0)]                          # V=1 边界
models_r1 = ([stub(shared[0])] * 37 + [stub(shared[1])] * 5
             + [stub(shared[2])] * 1 + [stub(m) for m in indep]
             + [stub(tiny), stub(tiny)]
             + [stub(shared[0], visible=False)] * 7)       # 隐形 (过滤路径)
fw_r1 = rand_fw(len(models_r1))
ref_hold = {}
compare_case('R1 混合共享/独立/隐形 (visible=True)', eng2, models_r1, fw_r1,
             True, ref_hold)
compare_case('R1 混合共享/独立/隐形 (visible=False)', eng2, models_r1, fw_r1,
             False, ref_hold)

# R2: n 波动 (grow -> 缩 -> 回涨): 缓冲复用 + 逐位不变
mesh_a = create_sphere(0.6, 16, 24)
mesh_b = create_cube(0.9)
models_big = [stub(mesh_a)] * 90 + [stub(mesh_b)] * 30
fw_big = rand_fw(120)
models_small = models_big[:60]
fw_small = fw_big[:60]
ok_all = True
for tag, ms, fws in (('big120', models_big, fw_big),
                     ('small60', models_small, fw_small),
                     ('big120-again', models_big, fw_big)):
    ref_out, _ = old_assembly(eng2, ms, fws, False)
    got = eng2._aabbs_batched(ms, fws, False)
    if not np.array_equal(aabbs_np(ref_out), aabbs_np(got)):
        ok_all = False
        print(f'  [detail] R2 {tag} AABB 不一致')
    ids3 = {k: id(v[0]) for k, v in eng2._aabb_staging.bufs.items()}
    print(f'  R2 {tag}: staging keys={sorted(ids3)}')
check('R2 n 波动 120->60->120 三帧 AABB 逐位一致', ok_all)

# R3: 每帧重建网格对象且换几何值 (恒 miss + id 复用陷阱: 旧 vh 被 GC,
# 若 seq 假命中会写出过期几何 -> 与参考不一致即现形)
ok_all = True
for it in range(6):
    mesh_x = create_sphere(0.5 + 0.1 * it, 14, 20)         # 值每轮都变
    ms = [stub(mesh_x)] * 40 + [stub(create_cube(0.5 + 0.05 * it))] * 10
    fws = rand_fw(50)
    ref_out, _ = old_assembly(eng2, ms, fws, False)
    got = eng2._aabbs_batched(ms, fws, False)
    if not np.array_equal(aabbs_np(ref_out), aabbs_np(got)):
        ok_all = False
        print(f'  [detail] R3 iter={it} AABB 不一致 (假命中嫌疑)')
    gc.collect()                                           # 挤 id 复用空间
check('R3 每帧换网格对象+换几何值 x6 (恒 miss + id 复用陷阱) 逐位一致', ok_all)

pygame.quit()
print('RESULT:', 'ALL PASS' if fails == 0 else 'FAIL (%d)' % fails)
sys.exit(0 if fails == 0 else 1)
