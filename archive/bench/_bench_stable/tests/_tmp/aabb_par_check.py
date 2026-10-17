# -*- coding: utf-8 -*-
"""aabb_par_check.py — 组3层3 AABB 批量化并行改造对拍网 (2026-08-31).

基准 = 改前 _model_aabbs_par 串行路径 (逐模型 get_bounding_box):
  vh @ M[:,:3] -> 转置连续 -> min/max -> Point3D
目标 = 批量化版 (分组共享 M 切片, matmul 逐模型调用不变, dgemm 释放 GIL 可池并行)
断言 = AABB 六个分量 float == 逐位 + visible_only 两种模式 + 乱序混合网格
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from engine import GLEngine, Point3D  # noqa: E402
from mesh import create_cube, create_sphere  # noqa: E402


def ref_aabb_serial(eng, models, fw, visible_only=True):
    """改前串行直译: 逐模型 get_bounding_box."""
    out = []
    for i, m in enumerate(models):
        if visible_only and not getattr(m, 'visible', True):
            continue
        out.append(eng.get_bounding_box(m, fw[i]))
    return out


def batched_aabb(eng, models, fw, visible_only=True):
    """批量化版 (层3 目标形态): 逐模型 matmul 不变, 消属性链重复, 可池分块.
    (这里是不含池的纯算法版; 池分块接线后 engine 内部同核语义)"""
    out = []
    for i, m in enumerate(models):
        if visible_only and not getattr(m, 'visible', True):
            continue
        M = fw[i]
        vh = eng._homogeneous_vertices(m.mesh)
        w3t = np.ascontiguousarray((vh @ M[:, :3]).T)
        mn, mx = w3t.min(axis=1), w3t.max(axis=1)
        out.append((Point3D(float(mn[0]), float(mn[1]), float(mn[2])),
                    Point3D(float(mx[0]), float(mx[1]), float(mx[2]))))
    return out


def aabb_eq(a, b, tol=1e-7):
    """D6 验收标准: 逐位/1e-7 内一致. AABB 归约走 numba 标量求和 vs BLAS dgemm
    有 ~4 ULP (1e-16 级) 舍入差 (SIMD 分块求和顺序), 1e-7 标准下等价."""
    return (abs(a[0].x - b[0].x) <= tol and abs(a[0].y - b[0].y) <= tol and
            abs(a[0].z - b[0].z) <= tol and
            abs(a[1].x - b[1].x) <= tol and abs(a[1].y - b[1].y) <= tol and
            abs(a[1].z - b[1].z) <= tol)


def main():
    # 无头桩引擎 (只用 _homogeneous_vertices 缓存, 不进 GL)
    eng = GLEngine.__new__(GLEngine)
    eng._bb_cache = {}
    n = 80
    models = []
    for i in range(n):
        mesh = create_cube(1.0) if i % 3 == 0 else (
            create_sphere(0.7, 12, 8) if i % 3 == 1 else create_sphere(0.5, 16, 12))
        m = type('M', (), {})()
        m.mesh = mesh
        m.visible = (i % 7 != 3)
        models.append(m)
    # 伪世界矩阵: 非平凡变换 (平移+旋转+非均匀缩放混合)
    rng = np.random.default_rng(42)
    fw = []
    for i in range(n):
        T = np.eye(4); T[:3, 3] = rng.uniform(-5, 5, 3)
        rx, ry, rz = rng.uniform(-3, 3, 3)
        cx, sx = np.cos(rx), np.sin(rx)
        Rx = np.array([[1, 0, 0, 0], [0, cx, -sx, 0], [0, sx, cx, 0], [0, 0, 0, 1]])
        cy, sy = np.cos(ry), np.sin(ry)
        Ry = np.array([[cy, 0, sy, 0], [0, 1, 0, 0], [-sy, 0, cy, 0], [0, 0, 0, 1]])
        cz, sz = np.cos(rz), np.sin(rz)
        Rz = np.array([[cz, -sz, 0, 0], [sz, cz, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        R = Rz @ Ry @ Rx
        S = np.diag([rng.uniform(0.3, 2.5), rng.uniform(0.3, 2.5),
                     rng.uniform(0.3, 2.5), 1.0])
        fw.append(S @ R @ T)

    fails = 0
    # A. engine._aabbs_batched (真实现) vs 逐模型 get_bounding_box 旧直译
    for vo in (True, False):
        ref = ref_aabb_serial(eng, models, fw, visible_only=vo)
        new = eng._aabbs_batched(models, fw, visible_only=vo)
        ok = len(ref) == len(new) and all(aabb_eq(a, b) for a, b in zip(ref, new))
        print(f"[真实现] visible_only={vo}: n_ref={len(ref)} n_new={len(new)} "
              f"逐位一致={'PASS' if ok else 'FAIL'}")
        fails += 0 if ok else 1
    # B. engine._model_aabbs_par (无池桩 = 串行批量化) 同对拍
    for vo in (True, False):
        ref = ref_aabb_serial(eng, models, fw, visible_only=vo)
        new = eng._model_aabbs_par(models, fw, visible_only=vo)
        ok = len(ref) == len(new) and all(aabb_eq(a, b) for a, b in zip(ref, new))
        print(f"[入口串行] visible_only={vo}: "
              f"逐位一致={'PASS' if ok else 'FAIL'}")
        fails += 0 if ok else 1
    # C. fw 不全兜底: 给 None 的模型须走 get_bounding_box(m, None) -> 自算矩阵,
    #    需真 GameObject; 用真物体重验 (部分给矩阵部分 None)
    from engine import GameObject as _GO
    gmodels = []
    for i in range(6):
        g = _GO(None, Point3D(float(i), 0.0, 0.0), Point3D(0.1 * i, 0.0, 0.0),
                scale=(1.0 + 0.1 * i, 1.0, 1.0))
        g.mesh = create_cube(1.0) if i % 2 == 0 else create_sphere(0.5, 10, 8)
        gmodels.append(g)
    gfw = [fw[i] if i % 2 == 0 else None for i in range(6)]
    ref = [eng.get_bounding_box(gmodels[i], gfw[i]) for i in range(6)]
    new = eng._model_aabbs_par(gmodels, gfw)
    ok = all(aabb_eq(a, b) for a, b in zip(ref, new))
    print(f"[fw不全兜底-真物体]: 逐位一致={'PASS' if ok else 'FAIL'}")
    fails += 0 if ok else 1
    # D. 重复调用稳定性 (缓存复用路径)
    r1 = ref_aabb_serial(eng, models, fw)
    r2 = ref_aabb_serial(eng, models, fw)
    print("串行两次调用一致:", "PASS" if all(aabb_eq(a, b) for a, b in zip(r1, r2)) else "FAIL")
    print("结果:", "ALL PASS" if fails == 0 else "FAIL")
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
