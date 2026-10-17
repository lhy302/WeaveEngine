# -*- coding: utf-8 -*-
"""C3 异常调查: rolling=0 的球为何越滚越快 (vx ~ μ·g 加速度?)"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import physics_bridge as B
import engine as E
from mesh import create_sphere, create_plane

DT = 1.0 / 60.0

m = E.GameObject(create_sphere(0.5), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                 name='球', primitive='sphere')
m.collider.shape = 'sphere'
m.collider.friction = 0.5
m.add_rigidbody(mass=1.0, use_gravity=True, friction=0.5, restitution=0.0,
                rolling_friction=0.0)
m.rigidbody.velocity = E.Point3D(3.0, 0.0, 0.0)

ground = E.GameObject(create_plane(20, 20), E.Point3D(0, -0.5, 0),
                      E.Point3D(0, 0, 0), name='地面', primitive='cube')
ground.collider.shape = 'box'

b = B.PhysicsWorldBridge()
b.build([ground, m])
ent = b._entries[1]
w = b._w
for i in range(560):
    b.frame(DT)
    if i % 40 == 0:
        r = w.get_body_stats(ent['handle'])
        aw = w.get_angular_velocity(ent['handle'])
        print("帧%03d t=%.2f pos=(%.3f,%.4f,%.3f) v=(%.3f,%.3f,%.3f) w=(%.3f,%.3f,%.3f)" % (
            i, i * DT, r[0][0], r[0][1], r[0][2], r[2][0], r[2][1], r[2][2],
            aw[0], aw[1], aw[2]))
