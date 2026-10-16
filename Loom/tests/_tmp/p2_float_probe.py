# -*- coding: utf-8 -*-
"""P2 浮空复现探针: 新体建后 is_active/位形逐帧 (2026-08-30)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import physics_bridge as B
import engine as E
from mesh import create_cube, create_plane, create_sphere

DT = 1.0 / 60.0


def make_obj(mesh, pos, primitive='cube', shape=None, mass=None, use_gravity=True,
             is_kinematic=False, parent=None, **kw):
    m = E.GameObject(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), name=kw.get('name', 'obj'),
                     primitive=primitive)
    if shape is not None:
        m.collider.shape = shape
    if mass is not None:
        m.add_rigidbody(mass=mass, use_gravity=use_gravity,
                        is_kinematic=is_kinematic,
                        friction=kw.get('friction', 0.5),
                        restitution=kw.get('restitution', 0.0))
    if parent is not None:
        m.parent = parent
    return m


def run(name, ground_y, ball_y, frames=45):
    b = B.PhysicsWorldBridge()
    ground = make_obj(create_plane(20, 20), (0, ground_y, 0), primitive='cube',
                      shape='box', name='地面')
    ball = make_obj(create_cube(1.0), (0, ball_y, 0), primitive='cube', shape='box',
                    mass=1.0, name=name)
    b.build([ground, ball])
    print("=== %s: 地面顶 y=%.0f, 球 y=%.0f ===" % (name, ground_y, ball_y))
    for i in range(frames):
        b.pre_step(DT)
        b.step(DT)
        b.post_step()
        ent = next((e for e in b._entries if e['model'] is ball), None)
        act = b._w.is_active(ent['handle']) if (b._w is not None and ent) else None
        if i % 5 == 0 or i <= 12:
            print("帧%02d y=%.4f vy=%.4f active=%s" % (
                i, ball.position.y, ball.rigidbody.velocity.y, act))
    return ball


run('场景同型(离地2m)', -2.0, 0.0)
run('高空球(离地10m)', -0.5, 10.0)
