# -*- coding: utf-8 -*-
"""diag_parallel_mismatch.py — 诊断 test_parallel 并行碰撞检测 mismatch."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np
import pygame; pygame.init(); pygame.display.set_mode((1,1), pygame.HIDDEN)
from concurrent.futures import ThreadPoolExecutor
from engine import GLEngine, Point3D

class _FMesh:
    def __init__(self, verts): self.vertices = np.asarray(verts, dtype=np.float64)
class _FCollider:
    def __init__(self, shape, enabled=True): self.shape = shape; self.enabled = enabled
class _FModel:
    def __init__(self, pos, rot, scale, shape, parent=None):
        self.position = Point3D(*pos); self.rotation = Point3D(*rot); self.scale = scale
        self.mesh = _FMesh([(0,0,0),(1,0,0),(0,1,0),(1,1,0),(0,0,1),(1,0,1),(0,1,1),(1,1,1)])
        self.collider = _FCollider(shape); self.parent = parent
        self.scripts = []; self._colliding = set()
        self.name = 'm'; self.children = []

_cube_v = [(0,0,0),(1,0,0),(0,1,0),(1,1,0),(0,0,1),(1,0,1),(0,1,1),(1,1,1)]
_eng2 = GLEngine.__new__(GLEngine)
_rng = np.random.default_rng(99)
_fm = []
for i in range(40):
    _p = _fm[i-1] if i > 0 and _rng.random() < 0.15 else None
    _fm.append(_FModel(tuple(_rng.uniform(-4,4,3)), tuple(_rng.uniform(-0.5,0.5,3)),
                       tuple(_rng.uniform(0.5,2.5,3)),
                       'sphere' if i % 3 == 0 else 'box', _p))
_eng2.models = _fm
_eng2._struct_gen = 0
_eng2._frame_world = _eng2.compute_world_matrices(_fm)
_eng2.parallel = {'policy': {'pool_mask': 0, 'n_logical': 18}}
_eng2.script_cores = 2
_eng2._collision_pool = ThreadPoolExecutor(max_workers=4)
for i in range(0, len(_fm), 5):
    _p = _fm[i].position
    _fm[i].position = Point3D(_p.x + 1.2, _p.y + 0.4, _p.z - 0.8)

_pairs2 = _eng2._collision_pairs_parallel()
print('parallel pairs:', len(_pairs2))

# 用 get_collisions 单独算
detected = set()
for i, m in enumerate(_fm):
    got = _eng2.get_collisions(m)
    for o in got:
        j = _fm.index(o)
        detected.add((min(i,j), max(i,j)))

par_set = set((min(i,j), max(i,j)) for i,j in _pairs2)
print('get_collisions pairs:', len(detected))
print('仅 parallel 有:', sorted(par_set - detected)[:10])
print('仅 get_collisions 有:', sorted(detected - par_set)[:10])
print('差异对数:', len(par_set ^ detected))

# 只统计不一致物体的类型/挂父情况
mismatch_objs = set()
for (a,b) in (par_set ^ detected):
    mismatch_objs.add(a); mismatch_objs.add(b)
print('不一致物体:', len(mismatch_objs))
for i in sorted(mismatch_objs)[:10]:
    m = _fm[i]
    print('  obj[%d] shape=%s parent=%s scale=%s' % (
        i, m.collider.shape, _fm.index(m.parent) if m.parent else None, m.scale))
_eng2._collision_pool.shutdown(wait=False)
