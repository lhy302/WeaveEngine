# -*- coding: utf-8 -*-
"""smoke_raycast.py — 射线检测冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import numpy as np

import loom_raycast
from loom_raycast import RaycastMixin


# ---- 桩模型 ----
class _Vec3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Model:
    def __init__(self, name, pos, size=1.0, visible=True):
        self.name = name
        self.position = _Vec3(*pos)
        self.scale = (size, size, size)
        self.visible = visible
        self.mesh = None
        self.collider = None
        self.rigidbody = None


class _Eng(RaycastMixin):
    """桩引擎：给几何路径需要的 _frame_world / _model_aabbs_par."""
    def __init__(self, models):
        self.models = models
        self.width = 800
        self.height = 600
        self._phys_bridge = None
        self._frame_world = [np.eye(4, dtype='f4') for _ in models]

    def compute_world_matrices(self, models):
        return [np.eye(4, dtype='f4') for _ in models]

    def _model_aabbs_par(self, models, fw):
        """简版 AABB：模型 position ± scale/2（假设无旋转）."""
        out = []
        for m in models:
            p = m.position
            sx, sy, sz = m.scale
            mn = _Vec3(p.x - sx / 2, p.y - sy / 2, p.z - sz / 2)
            mx = _Vec3(p.x + sx / 2, p.y + sy / 2, p.z + sz / 2)
            out.append((mn, mx))
        return out


# ---- 场景：3 个模型 ----
m1 = _Model('A', (0, 0, 0), size=2.0)
m2 = _Model('B', (0, 0, 5), size=2.0)
m3 = _Model('C', (0, 0, 10), size=2.0)
hidden = _Model('Hidden', (0, 0, 3), size=2.0, visible=False)
eng = _Eng([m1, m2, m3, hidden])


# 1) 单个 raycast 命中最近
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100)
assert r is not None
model, dist, hit_pt = r
# 第一个是 A (z=-1 到 z=1)，从 z=-10 出发，t=9.0
assert model.name == 'A', '期望命中 A，实际 %r' % model.name
assert abs(dist - 9.0) < 0.01, dist
assert abs(hit_pt[2] - (-1.0)) < 0.01, hit_pt
print('1) raycast 命中最近 OK:', model.name, 'dist=%.2f' % dist)

# 2) raycast_all 按距离升序返回全部命中（跳过不可见）
r = eng.raycast_all((0, 0, -10), (0, 0, 1), max_dist=100)
names = [x[0].name for x in r]
# A(z=-1), B(z=4), C(z=9)
assert names == ['A', 'B', 'C'], names
dists = [x[1] for x in r]
assert dists == sorted(dists), dists
print('2) raycast_all 按距离升序 OK:', names)

# 3) 忽略指定模型
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100, ignore_model=m1)
assert r is not None and r[0].name == 'B', r[0].name if r else None
print('3) ignore_model OK:', r[0].name)

# 4) max_dist 限制
# 起点 (0,0,-10) 到 A 前表面 z=-1 的距离 = 9.0
# max_dist=10 -> 命中 A（9 < 10）
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=10)
assert r is not None and r[0].name == 'A', 'max_dist=10 应命中 A'
# max_dist=5 -> 不命中（9 > 5）
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=5)
assert r is None, 'max_dist=5 应无命中'
print('4) max_dist 限制 OK')

# 5) 方向相反：从 z=20 向 -z，应命中 C
r = eng.raycast((0, 0, 20), (0, 0, -1), max_dist=100)
assert r is not None and r[0].name == 'C', r[0].name if r else None
print('5) 反向射线命中 C OK')

# 6) 完全避开所有物体（沿 x 轴远处）
r = eng.raycast((100, 100, -10), (0, 0, 1), max_dist=100)
assert r is None
print('6) 避开所有物体 -> None OK')

# 7) 非归一化方向仍然正确
r = eng.raycast((0, 0, -10), (0, 0, 100), max_dist=100)
assert r is not None and r[0].name == 'A'
assert abs(r[1] - 9.0) < 0.01, '方向长度应被归一化: dist=%f' % r[1]
print('7) 非归一化方向 OK')

# 8) 不可见模型被跳过
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100)
assert r[0].name != 'Hidden'
# 直接检查 Hidden 没在 raycast_all 里
r_all = eng.raycast_all((0, 0, -10), (0, 0, 1), max_dist=100)
assert 'Hidden' not in [x[0].name for x in r_all]
print('8) 不可见模型跳过 OK')

# 9) backend='geometry' 强制几何
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100, backend='geometry')
assert r is not None and r[0].name == 'A'
print('9) 强制 geometry 后端 OK')

# 10) backend='physics' 无桥返回 None（不崩）
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100, backend='physics')
assert r is None
print('10) physics 后端无桥降级 OK (返回 None)')

# 11) raycast_screen 无 _vp 返回 None（首帧前场景）
r = eng.raycast_screen(400, 300)
assert r is None
print('11) raycast_screen 无 _vp -> None OK')

# 12) raycast_screen 有 _vp 时可用
# 构造简单 vp（相机在 (0,0,-20)，yaw=0 pitch=0，看向 +z）
# matlib 签名: mat4_view_yaw_pitch(xp, camera, yaw, pitch, roll=0.0)
#               mat4_perspective(xp, fov_y, aspect, near, far)
from matlib import mat4_perspective, mat4_view_yaw_pitch
view = np.array(mat4_view_yaw_pitch(np, (0.0, 0.0, -20.0), 0.0, 0.0), dtype='f4')
proj = np.array(mat4_perspective(np, 60.0, 800.0 / 600.0, 0.1, 1000.0), dtype='f4')
eng._vp = (view @ proj).astype('f4')
r = eng.raycast_screen(400, 300)   # 屏幕中心
assert r is not None, '屏幕中心应命中'
assert r[0].name == 'A', '屏幕中心应命中 A, 实际 %r' % r[0].name
print('12) raycast_screen 正常 OK:', r[0].name)

print('SMOKE_PASS')
