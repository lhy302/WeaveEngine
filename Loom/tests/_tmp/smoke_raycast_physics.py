# -*- coding: utf-8 -*-
"""smoke_raycast_physics.py — 物理后端 Raycast 冒烟 (2026-10-18)

用真 Culverin 桥（Jolt）测 C2 物理精确路径。
场景：
  - 地面（静态 box，y=-0.5，20x20）
  - 墙1（静态 box，z=10，高 4，厚 1）
  - 墙2（静态 box，z=20，高 4，厚 1）
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import numpy as np

try:
    import culverin  # noqa: F401
except ImportError:
    print('SKIP: culverin 未安装')
    sys.exit(0)

import engine as E
import physics_bridge as B
import loom_raycast
from mesh import create_cube


def make_obj(pos, size, name, shape='box'):
    """建静态 box 物体（无 rigidbody = 静态，仍可被 raycast 命中）"""
    m = E.GameObject(create_cube(size), E.Point3D(*pos),
                     E.Point3D(0, 0, 0), name=name, primitive='cube')
    m.scale = (size, size, size) if not isinstance(size, tuple) else size
    m.collider.shape = shape
    return m


class _Eng(loom_raycast.RaycastMixin):
    def __init__(self, models, bridge):
        self.models = models
        self.width = 800
        self.height = 600
        self._phys_bridge = bridge
        self._frame_world = [np.eye(4, dtype='f4') for _ in models]

    def compute_world_matrices(self, models):
        return [np.eye(4, dtype='f4') for _ in models]

    def _model_aabbs_par(self, models, fw):
        """近似 AABB（用于几何 fallback）：返回 [(mn_vec3, mx_vec3), ...]"""
        from physics_bridge import collider_bounds

        class _V:
            def __init__(self, x, y, z):
                self.x, self.y, self.z = x, y, z

        out = []
        for m in models:
            shape, data = collider_bounds(m)
            if shape == 'box':
                mn, mx = data
                out.append((_V(*mn), _V(*mx)))
            else:
                c, r = data
                out.append((_V(c[0] - r, c[1] - r, c[2] - r),
                            _V(c[0] + r, c[1] + r, c[2] + r)))
        return out


# 场景搭建
ground = make_obj((0, -0.5, 0), 20.0, 'ground')
# 注意：ground 用 cube 顶点半径 0.5 * scale 20 = 10 边长 -> 高 20，顶面 y=9.5
# 修正：要用平面，让 ground 落在 y=-0.5 且顶面 y=0
# 更简单：用 scale=1 的 cube + 手动扩展 scale.y
ground_mesh = create_cube(1.0)
g = E.GameObject(ground_mesh, E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0),
                 name='ground', primitive='cube')
g.scale = (20.0, 1.0, 20.0)   # 顶面 y = -0.5 + 0.5 = 0
g.collider.shape = 'box'

wall1 = E.GameObject(create_cube(1.0), E.Point3D(0, 2, 10),
                     E.Point3D(0, 0, 0), name='wall1', primitive='cube')
wall1.scale = (5.0, 4.0, 1.0)   # z 范围 9.5~10.5
wall1.collider.shape = 'box'

wall2 = E.GameObject(create_cube(1.0), E.Point3D(0, 2, 20),
                     E.Point3D(0, 0, 0), name='wall2', primitive='cube')
wall2.scale = (5.0, 4.0, 1.0)   # z 范围 19.5~20.5
wall2.collider.shape = 'box'

models = [g, wall1, wall2]


# 建物理桥
bridge = B.PhysicsWorldBridge()
bridge.build(models)
assert bridge._w is not None, '物理桥世界未创建'
assert len(bridge._entries) == 3, '物理体数应为 3, 实际 %d' % len(bridge._entries)
print('[setup] 物理桥就绪: %d 个物理体' % len(bridge._entries))

eng = _Eng(models, bridge)

# ---- 1) 物理 raycast 命中地面（从高空向 -y）----
r = eng.raycast((0, 5, 0), (0, -1, 0), max_dist=100, backend='physics')
assert r is not None, '应命中地面'
model, dist, hit_pt = r
assert model.name == 'ground', '命中 %r' % model.name
# 起点 y=5，地面顶面 y=0，距离约 5.0
assert abs(dist - 5.0) < 0.1, dist
assert abs(hit_pt[1] - 0.0) < 0.1, hit_pt
print('1) 物理 raycast 命中地面 OK (dist=%.3f)' % dist)

# ---- 2) 物理 raycast 命中墙1（从 z=-10 向 +z）----
r = eng.raycast((0, 2, -10), (0, 0, 1), max_dist=100, backend='physics')
assert r is not None, '应命中墙1'
model, dist, hit_pt = r
assert model.name == 'wall1', '命中 %r' % model.name
# 墙1 前表面 z=9.5，起点 z=-10，距离约 19.5
assert abs(dist - 19.5) < 0.1, dist
print('2) 物理 raycast 命中墙1 OK (dist=%.3f)' % dist)

# ---- 3) 物理 raycast 未命中（高空向 y+）----
r = eng.raycast((0, 5, 0), (0, 1, 0), max_dist=100, backend='physics')
assert r is None, '应无命中'
print('3) 物理 raycast 未命中 OK')

# ---- 4) 物理 raycast_all 穿两个墙 ----
r = eng.raycast_all((0, 2, -10), (0, 0, 1), max_dist=100, backend='physics')
names = [x[0].name for x in r]
assert 'wall1' in names and 'wall2' in names, names
# 顺序按距离
i1 = names.index('wall1')
i2 = names.index('wall2')
assert i1 < i2, 'wall1 应比 wall2 先命中: %r' % names
print('4) 物理 raycast_all 穿两墙 OK: %r' % names)

# ---- 5) 物理 raycast 忽略地面 ----
r = eng.raycast((0, 5, 0), (0, -1, 0), max_dist=100,
                ignore_model=g, backend='physics')
assert r is None, '忽略地面后应无命中'
print('5) 物理 raycast 忽略物体 OK')

# ---- 6) auto 后端（有桥 -> 物理）----
r = eng.raycast((0, 5, 0), (0, -1, 0), max_dist=100, backend='auto')
assert r is not None and r[0].name == 'ground', 'auto 应走物理'
print('6) auto 后端自动走物理 OK')

# ---- 7) geometry 强制几何 ----
r = eng.raycast((0, 5, 0), (0, -1, 0), max_dist=100, backend='geometry')
assert r is not None, '几何后端也应命中'
# 几何路径下 hit_pt 也是近似位置，不强校精度
print('7) geometry 后端强制几何 OK (%r)' % r[0].name)

# ---- 8) 物理与几何对比（距离应相近，物理更准）----
r_phys = eng.raycast((0, 5, 0), (0, -1, 0), max_dist=100, backend='physics')
r_geom = eng.raycast((0, 5, 0), (0, -1, 0), max_dist=100, backend='geometry')
assert r_phys is not None and r_geom is not None
assert abs(r_phys[1] - r_geom[1]) < 0.2, '物理/几何距离应相近: %.3f vs %.3f' % (r_phys[1], r_geom[1])
print('8) 物理 vs 几何一致性 OK (phys=%.3f geom=%.3f)' % (r_phys[1], r_geom[1]))

bridge.destroy()
print('SMOKE_PASS')
