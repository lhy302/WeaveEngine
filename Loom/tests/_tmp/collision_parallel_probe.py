# -*- coding: utf-8 -*-
"""临时探针: 并行碰撞路径 vs 内联 get_collisions 结果一致性 (用完可删)."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from engine import GLEngine, Point3D

eng = GLEngine.__new__(GLEngine)


class FakeMesh:
    def __init__(self, verts):
        self.vertices = np.asarray(verts, dtype=np.float64)


class FakeCollider:
    def __init__(self, shape='box', enabled=True):
        self.shape = shape
        self.enabled = enabled


class FakeModel:
    def __init__(self, pos, rot, scale, mesh, shape, parent=None):
        self.position = Point3D(*pos)
        self.rotation = Point3D(*rot)
        self.scale = scale
        self.mesh = mesh
        self.collider = FakeCollider(shape)
        self.parent = parent
        self.scripts = []
        self._colliding = set()


# 盒子网格 (单位立方体顶点)
cube = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0),
        (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
sphere = cube  # AABB 兜底

rng = np.random.default_rng(99)
models = []
for i in range(40):
    parent = models[i - 1] if i > 0 and rng.random() < 0.15 else None
    pos = tuple(rng.uniform(-4, 4, 3))
    rot = tuple(rng.uniform(-0.5, 0.5, 3))
    sc = tuple(rng.uniform(0.5, 2.5, 3))
    shape = 'sphere' if i % 3 == 0 else 'box'
    models.append(FakeModel(pos, rot, sc, FakeMesh(sphere if shape == 'sphere' else cube),
                            shape, parent))
eng.models = models
# 模拟"上一帧"的 _frame_world (渲染前算的批量矩阵)
eng._frame_world = eng.compute_world_matrices(models)
eng.parallel = {'policy': {'pool_mask': 0, 'n_logical': 18}}
eng.script_cores = 2
eng._collision_pool = ThreadPoolExecutor(max_workers=4)

# 本帧物理移动物体: _frame_world 已过期, 并行检测必须用当帧当前位形
for i in range(0, len(models), 5):
    p = models[i].position
    models[i].position = Point3D(p.x + 1.2, p.y + 0.4, p.z - 0.8)

# 并行路径
pairs = eng._collision_pairs_parallel()
par = {}
for i, j in pairs:
    par.setdefault(i, set()).add(j)
    par.setdefault(j, set()).add(i)

# 内联路径: 对每个模型 get_collisions
mism = 0
for i, m in enumerate(models):
    inline = {id(x) for x in eng.get_collisions(m)}
    parset = {id(models[j]) for j in par.get(i, ())}
    if inline != parset:
        mism += 1
        print("MISMATCH model", i, "inline", [models.index(o) for o in eng.get_collisions(m)],
              "par", list(par.get(i, ())))

eng._collision_pool.shutdown(wait=False)
print("不一致模型数:", mism)
assert mism == 0, "并行碰撞路径与内联不一致!"
print("PROBE OK ✅")
