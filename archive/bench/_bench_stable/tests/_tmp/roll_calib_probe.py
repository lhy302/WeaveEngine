# -*- coding: utf-8 -*-
"""P1 滚动摩擦标定探针: r=0.5 球 μ=0.5 从 3m/s 起滚 -> 停止时间 (2026-08-30)"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import physics_bridge as B
import engine as E
from mesh import create_sphere, create_plane

DT = 1.0 / 60.0


def make_sphere(pos, friction, rolling, v0, shape='sphere'):
    m = E.GameObject(create_sphere(0.5), E.Point3D(*pos), E.Point3D(0, 0, 0),
                     name='球', primitive='sphere')
    m.collider.shape = shape
    m.collider.friction = friction
    m.add_rigidbody(mass=1.0, use_gravity=True, friction=friction,
                    restitution=0.0, rolling_friction=rolling)
    m.rigidbody.velocity = E.Point3D(v0, 0.0, 0.0)
    return m


def run(label, friction, rolling, v0, ncap=1200):
    b = B.PhysicsWorldBridge()
    ground = E.GameObject(create_plane(20, 20), E.Point3D(0, -0.5, 0),
                          E.Point3D(0, 0, 0), name='地面', primitive='cube')
    ground.collider.shape = 'box'
    ball = make_sphere((0, 0, 0), friction, rolling, v0)
    b.build([ground, ball])
    t_stop = None
    vy_series = []
    for i in range(ncap):
        b.frame(DT)
        sp = math.sqrt(sum(c * c for c in ball.rigidbody.velocity))
        if i % 30 == 0:
            vy_series.append("t=%.2f v=%.3f" % (i * DT, sp))
        if t_stop is None and sp < 0.01:
            t_stop = i * DT
            if i > 200:
                break
    ac = b.active_count
    print("[%s] friction=%.1f rolling=%.1f v0=%.1f -> 停止时间 = %s"
          % (label, friction, rolling, v0,
             ("%.3f s" % t_stop) if t_stop is not None else ">= %.1f s 未停" % (ncap * DT)))
    print("   轨迹尾:", vy_series[-4:])
    print("   active_count(最后) =", ac)
    return t_stop


print("=== 标定: 期望停止 2-4s (μ=0.5, rolling=0.1, v0=3) ===")
run("C1 默认", 0.5, 0.1, 3.0)
run("C2 μ=1.0 (应当更快)", 1.0, 0.1, 3.0)
run("C3 rolling=0 (应当滚不完)", 0.5, 0.0, 3.0)
run("C4 rolling=0.5 (应当更快)", 0.5, 0.5, 3.0)
run("C5 慢速 v0=1", 0.5, 0.1, 1.0)
