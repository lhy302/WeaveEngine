# -*- coding: utf-8 -*-
"""smoke_trigger_physics.py — Trigger 物理层 is_sensor 生效冒烟 (2026-10-18)

验收标准 §2.7.4 第 7 项：is_sensor 在 Culverin 层生效（动态体穿过不被推开）。

场景 A（trigger 生效）：静态 trigger box + 动态球以 +z 3m/s 冲过去
  -> 球穿过（位置持续前进，不被挡住）
场景 B（对照，非 trigger）：静态普通 box + 动态球同方向同速度
  -> 球被挡住（位置被弹回/停在 box 前）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import numpy as np
import pygame
pygame.init()
pygame.display.set_mode((1, 1), pygame.HIDDEN)

try:
    import culverin  # noqa: F401
except ImportError:
    print('SKIP: culverin 未安装')
    sys.exit(0)

import engine as E
import physics_bridge as B
from mesh import create_cube, create_sphere

DT = 1.0 / 60.0
fails = []


def check(label, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + detail if detail else ''))
    if not cond:
        fails.append(label)


def make_obj(mesh, pos, primitive, shape, mass=None, use_gravity=True,
             is_trigger=False, name='obj'):
    m = E.GameObject(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0),
                     name=name, primitive=primitive)
    m.collider.shape = shape
    m.collider.is_trigger = bool(is_trigger)
    if mass is not None:
        m.add_rigidbody(mass=mass, use_gravity=use_gravity,
                        friction=0.0, restitution=0.0, rolling_friction=0.0)
    return m


def run_scene(is_trigger_on_wall, n_frames=60):
    """跑 60 帧，返回球的末位置和是否穿墙（球初始 z 从 -3 向 +z 走）。"""
    bridge = B.PhysicsWorldBridge()
    # 墙：静态 box，z 范围 5±0.5
    wall = make_obj(create_cube(1.0), (0, 0, 5), 'cube', 'box',
                    is_trigger=is_trigger_on_wall, name='wall')
    wall.scale = (2.0, 4.0, 1.0)
    # 球：半径 0.5，初速度 +z 3m/s，起点 z=2（离墙近，1 秒内必达墙）
    # 墙中心 z=5，半深 0.5，前表面 z=4.5；球半径 0.5 -> 接触点 z=4.0
    ball = make_obj(create_sphere(0.5), (0, 0, 2), 'sphere', 'sphere',
                    mass=1.0, use_gravity=False, name='ball')
    ball.rigidbody.velocity = E.Point3D(0.0, 0.0, 3.0)

    bridge.build([wall, ball])
    # 冲刷查询缓冲
    bridge._w.step(0.0)
    for _ in range(n_frames):
        bridge.frame(DT)
    z_end = ball.position.z
    # 校验 is_sensor 状态（trigger 体在 Culverin 里应 is_sensor=True）
    sensor_states = []
    if bridge._w is not None:
        for e in bridge._entries:
            try:
                # culverin 无直接 is_sensor getter，通过行为验证
                pass
            except Exception:
                pass
    bridge.destroy()
    return z_end


# 场景 A：trigger 墙 -> 球应穿过（末 z > 4.5，即越过墙前表面）
z_trigger = run_scene(is_trigger_on_wall=True)
# 起点 z=2，1s 后理论终位置 z=5（不阻挡）或 z=4.0（被挡住）
check('A) trigger 墙: 球穿过（末 z > 4.5, 越过墙前表面）',
      z_trigger > 4.5, 'z=%0.3f (期望穿过, 应 > 4.5)' % z_trigger)

# 场景 B：对照非 trigger 墙 -> 球被挡（末 z 应停在约 4.0）
z_normal = run_scene(is_trigger_on_wall=False)
check('B) 非 trigger 墙: 球被挡住（末 z < 4.5, 停在墙前）',
      z_normal < 4.5, 'z=%0.3f (期望被挡, 应 < 4.5)' % z_normal)

# 对比：trigger 场景穿过深度 > 非 trigger 场景
check('C) trigger 场景穿过深度 > 非 trigger 场景',
      z_trigger > z_normal,
      'trigger_z=%0.3f normal_z=%0.3f' % (z_trigger, z_normal))

print()
if fails:
    print('FAILED: %d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('SMOKE_PASS')
