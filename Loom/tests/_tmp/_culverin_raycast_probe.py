# -*- coding: utf-8 -*-
"""_culverin_raycast_probe.py — Culverin raycast 语义探针"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import culverin as cv

settings = {
    'gravity': (0.0, 0.0, 0.0),
    'penetration_slop': 0.005,
    'max_bodies': 100,
    'num_threads': 1,
}
w = cv.PhysicsWorld(settings=settings)
w.set_gravity(0.0, 0.0, 0.0)

# 在 z=5 建一个 box（边长 2，范围 z=4~6）
h = w.create_body(
    pos=(0.0, 0.0, 5.0), rot=(0.0, 0.0, 0.0, 1.0),
    size=(1.0, 1.0, 1.0), shape=cv.SHAPE_BOX,
    motion=cv.MOTION_STATIC, mass=1.0,
    category=0xFFFFFFFF, mask=0xFFFFFFFF,
    user_data=0,
    friction=0.5, restitution=0.0)
w.step(0.0)   # 冲刷查询缓冲
print('静态 box 建好: handle=%d, 位置 (0,0,5), 边长 2' % h)

# 测试 A：方向 + max_dist（我以为的语义）
print()
print('测试 A: raycast((0,0,-10), (0,0,1), max_dist=100)')
try:
    r = w.raycast((0.0, 0.0, -10.0), (0.0, 0.0, 1.0), 100.0, 0)
    print('  返回:', r)
except Exception as e:
    print('  异常:', repr(e))

# 测试 B：起点 + 终点
print()
print('测试 B: raycast((0,0,-10), (0,0,10), max_dist=100)  [把终点当方向]')
try:
    r = w.raycast((0.0, 0.0, -10.0), (0.0, 0.0, 10.0), 100.0, 0)
    print('  返回:', r)
except Exception as e:
    print('  异常:', repr(e))

# 测试 C：归一化方向 + max_dist=20（应覆盖 4~6）
print()
print('测试 C: raycast((0,0,-10), (0,0,1), max_dist=20)')
try:
    r = w.raycast((0.0, 0.0, -10.0), (0.0, 0.0, 1.0), 20.0, 0)
    print('  返回:', r)
except Exception as e:
    print('  异常:', repr(e))

# 测试 D：max_dist=1（很短）
print()
print('测试 D: raycast((0,0,-10), (0,0,1), max_dist=1)  [如果 distance 是比例]')
try:
    r = w.raycast((0.0, 0.0, -10.0), (0.0, 0.0, 1.0), 1.0, 0)
    print('  返回:', r)
except Exception as e:
    print('  异常:', repr(e))

# 测试 E：近一点射（起点 (0,0,3)，方向 +z，到 box 前表面 z=4 距离 1）
print()
print('测试 E: raycast((0,0,3), (0,0,1), max_dist=100)')
try:
    r = w.raycast((0.0, 0.0, 3.0), (0.0, 0.0, 1.0), 100.0, 0)
    print('  返回:', r)
except Exception as e:
    print('  异常:', repr(e))

# 测试 F：从 box 内部向外（起点 (0,0,5)，方向 +z）
print()
print('测试 F: raycast((0,0,5), (0,0,1), max_dist=100)  [从内部]')
try:
    r = w.raycast((0.0, 0.0, 5.0), (0.0, 0.0, 1.0), 100.0, 0)
    print('  返回:', r)
except Exception as e:
    print('  异常:', repr(e))
