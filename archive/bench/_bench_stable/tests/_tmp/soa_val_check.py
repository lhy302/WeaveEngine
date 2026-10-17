# -*- coding: utf-8 -*-
"""soa_val_check.py — 组3层1 SoA 独立验证 (主线程接管版, 2026-08-31).

验证目标: compute_world_matrices 新路径 (快照平面 + fastpath.depths) 与
旧算法 (逐物体属性链 + 逐物体深度 while) 数值逐位一致。

只新建本文件, 不改引擎任何代码。矩阵组装段 (S@R@T + 层级批量 matmul)
新旧同款 (该段 2026-08-14 起未变), 故共享同一组装函数, 隔离比较的
就是组3层1 换掉的两段: 数据采集 与 深度 DP。
"""
import os
import sys

import numpy as np

# 脚本在 tests/_tmp/ 下, 比既有 tests/*.py 深一层: 三重 dirname 到 Loom 根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from engine import GLEngine, GameObject, Point3D   # noqa: E402
import fastpath                                    # noqa: E402


# ---------- 旧路径直译 (改前 engine.compute_world_matrices 的采集段) ----------
def old_collect(models):
    """旧: 9 次属性链列取 (3 物体 × pos/rot/scl)。"""
    pos = np.array([(m.position.x, m.position.y, m.position.z) for m in models],
                   dtype=np.float64)
    rot = np.array([(m.rotation.x, m.rotation.y, m.rotation.z) for m in models],
                   dtype=np.float64)
    scl = np.array([(m.scale[0], m.scale[1], m.scale[2]) for m in models],
                   dtype=np.float64)
    return pos, rot, scl


def old_parent_depth(models):
    """旧: id2i + parent 索引 + 逐物体深度 while 循环 (d<n 防环截断)。"""
    n = len(models)
    id2i = {id(m): i for i, m in enumerate(models)}
    parent = np.full(n, -1, dtype=np.int64)
    for i, m in enumerate(models):
        if m.parent is not None:
            parent[i] = id2i.get(id(m.parent), -1)
    depth = np.zeros(n, dtype=np.int64)
    for i in range(n):
        d, cur = 0, i
        while parent[cur] >= 0 and d < n:
            cur = int(parent[cur])
            d += 1
        depth[i] = d
    return parent, depth


# ---------- 共享组装段 (新旧同款, 不在比较范围) ----------
def assemble(models, pos, rot, scl, parent, depth):
    n = len(models)
    S = np.zeros((n, 4, 4), dtype=np.float64)
    S[:, 0, 0] = scl[:, 0]
    S[:, 1, 1] = scl[:, 1]
    S[:, 2, 2] = scl[:, 2]
    S[:, 3, 3] = 1.0
    T = np.zeros((n, 4, 4), dtype=np.float64)
    T[:, 0, 0] = T[:, 1, 1] = T[:, 2, 2] = T[:, 3, 3] = 1.0
    T[:, 3, 0] = pos[:, 0]
    T[:, 3, 1] = pos[:, 1]
    T[:, 3, 2] = pos[:, 2]
    R = GLEngine._batch_rotations(models, rot=rot)
    local = S @ R @ T
    world = np.empty_like(local)
    for d in range(int(depth.max()) + 1):
        idx = np.where(depth == d)[0]
        if d == 0:
            world[idx] = local[idx]
        else:
            world[idx] = local[idx] @ world[parent[idx]]
    return world


def new_collect(engine_stub, models):
    """新: _transform_snapshot 平面 + fastpath.depths。"""
    _, pos, rot, scl = engine_stub._transform_snapshot(models)
    id2i = {id(m): i for i, m in enumerate(models)}
    parent = np.full(len(models), -1, dtype=np.int64)
    for i, m in enumerate(models):
        if m.parent is not None:
            parent[i] = id2i.get(id(m.parent), -1)
    depth = fastpath.depths(parent)
    return pos, rot, scl, parent, depth


# ---------- 场景构造 (无头, 不进 GL: 直接建 GameObject, 不调 add_model) ----------
def _mk(pos, rot, scl):
    return GameObject(None, Point3D(*pos), Point3D(*rot), scale=scl)


def scene_chain10():
    ms = [_mk((float(i), 0.0, 0.0), (0.01 * i, 0.0, 0.0), (1.0, 1.0, 1.0))
          for i in range(10)]
    for i in range(1, 10):
        ms[i].parent = ms[i - 1]
    return ms


def scene_star33():
    root = _mk((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    kids = [_mk((1.0 * k, 2.0, 0.5 * k), (0.1 * k, 0.2, 0.0), (1.0, 2.0, 1.0))
            for k in range(32)]
    for k in kids:
        k.parent = root
    return [root] + kids


def scene_forest3():
    out = []
    for t in range(3):
        a = _mk((t * 10.0, 0.0, 0.0), (0.0, 0.1 * t, 0.0), (1.0, 1.0, 1.0))
        b = _mk((t * 10.0, 1.0, 0.0), (0.2, 0.0, 0.3 * t), (2.0, 1.0, 1.0))
        c = _mk((t * 10.0, 2.0, 1.0), (0.0, 0.4, 0.0), (1.0, 1.0, 3.0))
        b.parent = a
        c.parent = b
        out += [a, b, c]
    return out


def scene_root_leaf():
    a = _mk((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    b = _mk((1.0, 1.0, 1.0), (0.3, 0.2, 0.1), (0.5, 0.5, 0.5))
    b.parent = a
    return [a, b]


def scene_euler():
    """浮点欧拉角 (非对称值) 小树。"""
    a = _mk((0.1, -2.3, 3.45), (0.123, -2.567, 1.3), (1.1, 0.9, 1.2))
    b = _mk((-1.0, 5.5, 0.01), (2.5, -1.3, 0.777), (0.8, 1.3, 0.7))
    c = _mk((4.2, 0.0, -0.9), (-0.9, 0.45, 3.01), (1.4, 2.2, 0.6))
    b.parent = a
    c.parent = a
    return [a, b, c]


def scene_shared_parent():
    p1 = _mk((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    p2 = _mk((5.0, 0.0, 0.0), (0.3, 0.0, 0.0), (2.0, 2.0, 2.0))
    kids = []
    for k in range(3):
        c = _mk((1.0 * k, 1.0, 0.0), (0.1, 0.2, 0.3), (1.0, 1.0, 1.0))
        c.parent = p1
        kids.append(c)
    g = _mk((0.0, 2.0, 0.0), (0.0, 0.7, 0.0), (0.9, 0.9, 0.9))
    g.parent = kids[0]
    return [p1, p2] + kids + [g]


SCENES = [
    ("①线性链10层", scene_chain10),
    ("②宽扇出1父32子", scene_star33),
    ("③三棵独立森林", scene_forest3),
    ("④单根单叶", scene_root_leaf),
    ("⑤浮点欧拉角", scene_euler),
    ("⑥重复父共享", scene_shared_parent),
]


def main():
    # 无头桩: __new__ 跳过 GL/SDL 初始化; _transform_snapshot 全程 getattr
    # 防御 (_struct_gen 默认 0), 桩安全 (见其 docstring)。
    e = GLEngine.__new__(GLEngine)
    all_pass = True
    print("soa_val_check: 新路径 (_transform_snapshot + fastpath.depths) vs "
          "旧算法直译 (属性链 + 深度while), np.array_equal 逐位")
    for name, fn in SCENES:
        models = fn()
        # 旧路径
        o_pos, o_rot, o_scl = old_collect(models)
        o_par, o_dep = old_parent_depth(models)
        w_old = assemble(models, o_pos, o_rot, o_scl, o_par, o_dep)
        # 新路径 (两次调用: 第二次走 _soa_snap 缓存命中, 顺带验缓存稳定性)
        n_pos, n_rot, n_scl, n_par, n_dep = new_collect(e, models)
        w_new1 = assemble(models, n_pos, n_rot, n_scl, n_par, n_dep)
        n_pos2, n_rot2, n_scl2, n_par2, n_dep2 = new_collect(e, models)
        w_new2 = assemble(models, n_pos2, n_rot2, n_scl2, n_par2, n_dep2)
        ok_mat = bool(np.array_equal(w_old, w_new1) and np.array_equal(w_old, w_new2))
        ok_dep = bool(np.array_equal(o_dep, n_dep))
        ok = ok_mat and ok_dep
        all_pass &= ok
        print(f"{name}: n={len(models)}  depth一致={ok_dep}  世界矩阵逐位一致={ok_mat}  "
              f"{'PASS' if ok else 'FAIL'}")
    print("总结果:", "ALL PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
