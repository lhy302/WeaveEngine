# -*- coding: utf-8 -*-
"""shadow_val_check.py — shadow_prep 直通行改造对拍网 (2026-09-07)

基准 = 旧 _scene_light_bounds_par (n×2×3 属性链拆包 ab/cd 填充)
目标 = row_input=(n,6) numpy 直通行版 (零拷贝列视图)
断言 = (min,max) 逐位一致 + None 分支 + 随机/混合500/可见过滤/兜底行场景
       + _aabbs_batched out_rows 行表与 Point3D 列表逐位对拍
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from engine import GLEngine, GameObject, Point3D  # noqa: E402
from mesh import create_cube, create_sphere  # noqa: E402
from matlib import mat4_view_forward  # noqa: E402

fails = 0


def check(name, ok, extra=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}")
    if not ok:
        fails += 1


def ab_cd_old(aabbs):
    """旧路径: 属性链拆包 (参考实现)."""
    n = len(aabbs)
    ab = np.empty((n, 3))
    cd = np.empty((n, 3))
    for i, (a, b) in enumerate(aabbs):
        ab[i] = (a.x, a.y, a.z)
        cd[i] = (b.x, b.y, b.z)
    return ab, cd


def bounds_old(view, aabbs):
    """逐位复刻改前实现 (含 tile/repeat 展开与 matmul)."""
    ab, cd = ab_cd_old(aabbs)
    n = len(aabbs)
    corners = np.empty((n * 8, 4), dtype=np.float64)
    xs = np.empty((n, 2)); xs[:, 0] = ab[:, 0]; xs[:, 1] = cd[:, 0]
    ys = np.empty((n, 2)); ys[:, 0] = ab[:, 1]; ys[:, 1] = cd[:, 1]
    zs = np.empty((n, 2)); zs[:, 0] = ab[:, 2]; zs[:, 1] = cd[:, 2]
    corners[:, 0] = np.tile(xs, (1, 4)).ravel()
    corners[:, 1] = np.tile(np.repeat(ys, 2, axis=1), (1, 2)).ravel()
    corners[:, 2] = np.repeat(zs, 4, axis=1).ravel()
    corners[:, 3] = 1.0
    w = corners @ view
    return (w[:, :3].min(axis=0), w[:, :3].max(axis=0))


def eq(a, b):
    return a[0] is not None and b[0] is not None and \
        np.array_equal(np.asarray(a[0]), np.asarray(b[0])) and \
        np.array_equal(np.asarray(a[1]), np.asarray(b[1]))


def main():
    eng = GLEngine.__new__(GLEngine)
    eng._bb_cache = {}
    eng._aabb_staging = None
    eng._aabb_shadow_rows = None
    eng._aabb_shadow_gen = None
    eng._AABB_PAR_MIN_MODELS = GLEngine._AABB_PAR_MIN_MODELS
    rng = np.random.default_rng(20260907)

    # ---------- 场景 1: 随机 Point3D 列表 (纯数值对拍, n=1/7/501) ----------
    for n in (1, 7, 501):
        aabbs = []
        for _ in range(n):
            a = rng.uniform(-10, 10, 3)
            b = a + rng.uniform(0.1, 3, 3)
            aabbs.append((Point3D(float(a[0]), float(a[1]), float(a[2])),
                          Point3D(float(b[0]), float(b[1]), float(b[2]))))
        view = mat4_view_forward(np, (0.0, 5.0, -12.0), (0.1, -0.2, 0.97),
                                 (0.0, 1.0, 0.0))
        # rows 直喂 (随机值任意 dtype-safe 构造, 无序性无关)
        rows = np.empty((n, 6), dtype=np.float64)
        for i, (a, b) in enumerate(aabbs):
            rows[i, 0:3] = (a.x, a.y, a.z)
            rows[i, 3:6] = (b.x, b.y, b.z)
        old = bounds_old(view, aabbs)
        new = GLEngine._scene_light_bounds_par(view, aabbs, row_input=rows)
        check(f"row_input 直喂 == 旧属性链 (n={n}) 逐位", eq(old, new))
        # row_input=None 必须与旧逐位 (回退路径自对拍)
        new_fb = GLEngine._scene_light_bounds_par(view, aabbs)
        check(f"row_input=None 回退 == 旧 (n={n}) 逐位", eq(old, new_fb))

    # ---------- 场景 2: None 分支 ----------
    view = np.eye(4)
    check("空 aabbs -> None", GLEngine._scene_light_bounds_par(view, []) is None)
    check("空 aabbs + rows -> None",
          GLEngine._scene_light_bounds_par(view, [], row_input=np.empty((0, 6)))
          is None)

    # ---------- 场景 3: _aabbs_batched out_rows 行表 == Point3D 列表 ----------
    n = 80
    models = []
    for i in range(n):
        mesh = create_cube(1.0) if i % 3 == 0 else (
            create_sphere(0.7, 12, 8) if i % 3 == 1 else create_sphere(0.5, 16, 12))
        m = type('M', (), {})()
        m.mesh = mesh
        m.visible = (i % 7 != 3)
        models.append(m)
    fw = []
    for i in range(n):
        T = np.eye(4); T[:3, 3] = rng.uniform(-5, 5, 3)
        rx, ry, rz = rng.uniform(-3, 3, 3)
        cx, sx = np.cos(rx), np.sin(rx)
        R = np.array([[1, 0, 0, 0], [0, cx, -sx, 0], [0, sx, cx, 0], [0, 0, 0, 1]])
        S = np.diag([rng.uniform(0.3, 2.5), rng.uniform(0.3, 2.5),
                     rng.uniform(0.3, 2.5), 1.0])
        fw.append(S @ R @ T)
    for vo in (True, False):
        rows = np.empty((n, 6), dtype=np.float64)
        out = eng._aabbs_batched(models, fw, visible_only=vo, out_rows=rows)
        ok_shape = rows.shape == (n, 6)
        ok = ok_shape
        for i, (a, b) in enumerate(out):
            if rows[i, 0] != a.x or rows[i, 1] != a.y or rows[i, 2] != a.z \
                    or rows[i, 3] != b.x or rows[i, 4] != b.y or rows[i, 5] != b.z:
                ok = False
                break
        check(f"_aabbs_batched out_rows 行序==out 列表 (visible_only={vo})",
              ok, f"shape={rows.shape}")

    # ---------- 场景 4: fw 不全兜底 (None 行回填) ----------
    gmodels = []
    for i in range(6):
        g = GameObject(None, Point3D(float(i), 0.0, 0.0), Point3D(0.1 * i, 0.0, 0.0),
                       scale=(1.0 + 0.1 * i, 1.0, 1.0))
        g.mesh = create_cube(1.0) if i % 2 == 0 else create_sphere(0.5, 10, 8)
        gmodels.append(g)
    gfw = [fw[i] if i % 2 == 0 else None for i in range(6)]
    rows = np.empty((6, 6), dtype=np.float64)
    out = eng._aabbs_batched(gmodels, gfw, visible_only=False, out_rows=rows)
    ok = True
    for i, (a, b) in enumerate(out):
        if rows[i, 0] != a.x or rows[i, 1] != a.y or rows[i, 2] != a.z \
                or rows[i, 3] != b.x or rows[i, 4] != b.y or rows[i, 5] != b.z:
            ok = False
            break
    check("fw 不全兜底行回填 (out==rows 逐位)", ok)

    # ---------- 场景 5: 混合500 端到端 (行表 -> row_input 直喂 vs 旧路) ----------
    n = 501
    meshes = [create_cube(1.0), create_sphere(0.7, 12, 8), create_sphere(0.5, 16, 12),
              create_sphere(1.2, 20, 14)]
    models5 = []
    for i in range(n):
        m = type('M', (), {})()
        m.mesh = meshes[i % 4]
        m.visible = (i % 11 != 5)
        models5.append(m)
    fw5 = []
    for i in range(n):
        T = np.eye(4); T[:3, 3] = rng.uniform(-30, 30, 3)
        rx = rng.uniform(-3, 3)
        cx, sx = np.cos(rx), np.sin(rx)
        R = np.array([[1, 0, 0, 0], [0, cx, -sx, 0], [0, sx, cx, 0], [0, 0, 0, 1]])
        S = np.diag([rng.uniform(0.3, 2.5), rng.uniform(0.3, 2.5),
                     rng.uniform(0.3, 2.5), 1.0])
        fw5.append(S @ R @ T)
    rows5 = np.empty((n, 6), dtype=np.float64)
    out5 = eng._aabbs_batched(models5, fw5, visible_only=False, out_rows=rows5)
    vis_aabbs = [out5[i] for i, m in enumerate(models5) if m.visible]
    vis_rows = rows5[[i for i, m in enumerate(models5) if m.visible]]
    view5 = mat4_view_forward(np, (0.0, 20.0, -40.0), (0.3, -0.4, 0.85),
                              (0.0, 1.0, 0.0))
    old5 = bounds_old(view5, vis_aabbs)
    new5 = GLEngine._scene_light_bounds_par(view5, vis_aabbs, row_input=vis_rows)
    check("混合500 全链 (batched行表->可见过滤->row_input) == 旧 逐位", eq(old5, new5))

    print("结果:", "ALL PASS" if fails == 0 else f"FAIL x{fails}")
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
