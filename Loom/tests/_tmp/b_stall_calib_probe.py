# -*- coding: utf-8 -*-
"""修复_b ② 残速死带标定 (stall on/off 对比):
  A. 残留滑动体: 盒 μ=0.5 v0=0.3m/s -> 死带无效(stall=0)时尾巴多久; 死带生效时
     到 |v|=0 的时间 (<1s) + 停后 active=0。
  B. 正常推箱 0.5m/s: 死带不影响自然滑距 (开/关 距离差 < 容差)。
  C. 滚动球 3m/s: 停止时间仍在 2-4.5s (10a 用例防回归)。
用法: py -3.12 tests\\_tmp\\b_stall_calib_probe.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import physics_bridge as B          # noqa: E402
import engine as E                 # noqa: E402
from mesh import create_cube, create_sphere, create_plane   # noqa: E402

DT = 1.0 / 60.0


def make_box_ground():
    b = B.PhysicsWorldBridge()
    ground = E.GameObject(create_plane(200, 200), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0),
                          name='地面', primitive='cube')
    ground.collider.shape = 'box'
    ground.collider.friction = 0.5
    box = E.GameObject(create_cube(1.0), E.Point3D(0, 0.0, 0), E.Point3D(0, 0, 0),
                       name='盒', primitive='cube')
    box.collider.shape = 'box'
    box.add_rigidbody(use_gravity=True, friction=0.5, restitution=0.0,
                      rolling_friction=0.1)
    b.build([ground, box])
    return b, box


def slide_case(v0, name, stall_eps):
    B.V_STALL_EPS = stall_eps                      # 0.0 = 死带关闭
    b, box = make_box_ground()
    box.rigidbody.velocity = E.Point3D(v0, 0.0, 0.0)
    x0 = box.position.x
    t_band = t_zero = None
    act_after = None
    for i in range(600):
        b.frame(DT)
        sp = math.sqrt(sum(c * c for c in box.rigidbody.velocity))
        if t_band is None and math.sqrt(box.rigidbody.velocity.x ** 2
                                        + box.rigidbody.velocity.z ** 2) < 0.03:
            t_band = i * DT
        if t_zero is None and sp < 1e-4:
            t_zero = i * DT
            for j in range(120):                   # 停后 2s: 活性
                b.frame(DT)
            act_after = b.active_count
            break
    dx = box.position.x - x0
    print("[%s] v0=%.1f: 带内(0.03) t=%.3fs | 全停 t=%s | 滑距=%.3fm | 停后 active=%s"
          % (name, v0, t_band if t_band is not None else -1,
             ("%.3fs" % t_zero) if t_zero is not None else ">10s(未停)",
             dx, act_after))
    return t_band, t_zero, dx, act_after


if __name__ == '__main__':
    print("=== 残速死带标定 (阈值: V=%.3f W=%.3f VY_GATE=%.1f) ==="
          % (B.V_STALL_EPS, B.W_STALL_EPS, B.VY_STOP_GATE))
    print("--- A. 残留滑动体 0.3 m/s ---")
    t0a = slide_case(0.3, "死带 关", 0.0)
    t0b = slide_case(0.3, "死带 开(0.03)", 0.03)
    B.V_STALL_EPS = 0.05
    t0c = slide_case(0.3, "死带 开(0.05)", 0.05)
    B.V_STALL_EPS = 0.03
    print("--- B. 正常推箱 0.5 m/s ---")
    t1a = slide_case(0.5, "死带 关", 0.0)
    t1b = slide_case(0.5, "死带 开(0.03)", 0.03)
    print("--- C. 滚动球 3m/s (rolling 0.1 μ0.5, 死带开) ---")
    B.V_STALL_EPS = 0.03
    b = B.PhysicsWorldBridge()
    g = E.GameObject(create_plane(200, 200), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0),
                     name='地面', primitive='cube')
    g.collider.shape = 'box'
    ball = E.GameObject(create_sphere(0.5), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                        name='滚球', primitive='sphere')
    ball.collider.shape = 'sphere'
    ball.add_rigidbody(use_gravity=True, friction=0.5, rolling_friction=0.1)
    b.build([g, ball])
    ball.rigidbody.velocity = E.Point3D(3.0, 0.0, 0.0)
    t_stop = None
    for i in range(900):
        b.frame(DT)
        sp = math.sqrt(sum(c * c for c in ball.rigidbody.velocity))
        if sp < 0.01:
            t_stop = i * DT
            break
    print("[滚动 3m/s 死带开] 停止=%.3fs (目标 2-4.5s) | active=%d" %
          (t_stop if t_stop is not None else -1, b.active_count))
    print("=== 标定完成 ===")
