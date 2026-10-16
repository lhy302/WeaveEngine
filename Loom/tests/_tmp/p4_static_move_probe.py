# -*- coding: utf-8 -*-
"""P4 候选③: 静态体被脚本移动 -> pre_step destroy+重建 KINEMATIC —— 反复触发
+ 每次世界销毁/重建, 观察原生崩溃 (0xC0000005 家族) 与 faulthandler 输出."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import physics_bridge as B
import engine as E
from mesh import create_cube, create_sphere, create_plane

DT = 1.0 / 60.0

b = B.PhysicsWorldBridge()
ground = E.GameObject(create_plane(200, 200), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0),
                      name='地面', primitive='cube')
ground.collider.shape = 'box'
plat = E.GameObject(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                    name='平台(静态被转)', primitive='cube')
plat.collider.shape = 'box'
ball = E.GameObject(create_sphere(0.5), E.Point3D(0, 2, 0), E.Point3D(0, 0, 0),
                    name='球', primitive='sphere')
ball.collider.shape = 'sphere'
ball.add_rigidbody(mass=1.0, use_gravity=True)
b.build([ground, plat, ball])

for round_i in range(3):
    print("--- 轮 %d ---" % round_i)
    for i in range(300):
        # 平台每帧被"脚本"转 5° (静态 -> pre_step 升级 KINEMATIC: destroy+重建)
        plat.rotation = E.Point3D(0.0, math.radians(5) * (i + 1), 0.0)
        b.frame(DT)
    print("轮%d 结束: count=%d active=%d ball_y=%.3f" % (
        round_i, b.body_count, b.active_count, ball.position.y))
    b.destroy()                      # 模拟停播销毁
    b = B.PhysicsWorldBridge()       # 再建 (下一轮)
    ground2 = E.GameObject(create_plane(200, 200), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0),
                           name='地面', primitive='cube')
    ground2.collider.shape = 'box'
    plat2 = E.GameObject(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                         name='平台(静态被转)', primitive='cube')
    plat2.collider.shape = 'box'
    ball2 = E.GameObject(create_sphere(0.5), E.Point3D(0, 2, 0), E.Point3D(0, 0, 0),
                         name='球', primitive='sphere')
    ball2.collider.shape = 'sphere'
    ball2.add_rigidbody(mass=1.0, use_gravity=True)
    b.build([ground2, plat2, ball2])
    ground, plat, ball = ground2, plat2, ball2

print("全部轮次完成, 无崩溃")
