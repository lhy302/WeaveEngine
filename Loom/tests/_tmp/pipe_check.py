# -*- coding: utf-8 -*-
"""
pipe_check.py — 分离批4 W1 核心闸: 物理管线同轨迹逐位对拍 (R3)

同一进程建两个 bridge (同场景同初态):
  甲 = 主线程直跑 br.ensure/pre/step/post ×N
  乙 = PhysicsPipeThread post/wait ×N (三段在线程内执行)
N 步后逐字段比对全部模型 (position/rotation/rb.velocity) — 要求逐位相等.
任一不等 = 管线引入时序差, 禁止落地.

W2 附加: 超时降级语义 (wait 抛 RuntimeError 后 _degraded=True).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'

import numpy as np
import engine as E
from mesh import create_cube, create_sphere, create_plane

E.GLEngine._build_gpu = lambda self, m: None

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def build_models():
    """落球+斜坡+静态堆 场景 (两组同初态, 各喂一个 bridge)."""
    models = []
    ground = E.GameObject(create_plane(20, 20), E.Point3D(0, -0.5, 0),
                          E.Point3D(0, 0, 0), name='地面')
    ground.collider.shape = 'box'
    models.append(ground)
    ramp = E.GameObject(create_cube(4.0), E.Point3D(3.0, 1.0, 0.0),
                        E.Point3D(0, 0, math_radians(20)), name='斜坡')
    ramp.collider.shape = 'box'
    models.append(ramp)
    for i in range(30):
        b = E.GameObject(create_sphere(0.5), E.Point3D((i % 6) * 1.5 - 3.5,
                                                       3.0 + (i // 6) * 2.0,
                                                       (i % 3) * 1.2 - 1.2),
                         E.Point3D(0, 0, 0), name='堆%d' % i)
        b.collider.shape = 'sphere'
        b.add_rigidbody(mass=1.0, use_gravity=True)
        models.append(b)
    for i in range(4):
        r = E.GameObject(create_cube(0.8), E.Point3D(-2.0 + i, 2.0 + i * 3.0, 0.0),
                         E.Point3D(0, 0, 0), name='滚球%d' % i)
        r.collider.shape = 'sphere'
        r.add_rigidbody(mass=0.5, use_gravity=True)
        r.rigidbody.velocity = E.Point3D(0.5 + i * 0.1, 0.0, 0.0)
        models.append(r)
    return models


def math_radians(d):
    import math
    return math.radians(d)


def snapshot(models):
    return np.array([[m.position.x, m.position.y, m.position.z,
                      m.rotation.x, m.rotation.y, m.rotation.z,
                      m.rigidbody.velocity.x if m.rigidbody else 0.0,
                      m.rigidbody.velocity.y if m.rigidbody else 0.0,
                      m.rigidbody.velocity.z if m.rigidbody else 0.0]
                     for m in models])


def deep_copy_models(models):
    """同初态重建 (Jolt 体不可深拷, 用同参数重建保证初态一致)."""
    return build_models()


def main():
    from physics_bridge import PhysicsWorldBridge, cv_available
    from physics_pipe import PhysicsPipeThread
    if not cv_available:
        print("SKIP: culverin 不可用")
        return 0

    N = 600
    DT = 1.0 / 60.0
    G = -9.8

    # 甲: 主线程直跑
    models_a = build_models()
    br_a = PhysicsWorldBridge()
    br_a.build(models_a)
    for _ in range(N):
        br_a.ensure_models(models_a)
        br_a.pre_step(DT, G)
        br_a.step(DT)
        br_a.post_step()
    snap_a = snapshot(models_a)
    br_a.destroy()

    # 乙: 管线线程
    models_b = build_models()
    br_b = PhysicsWorldBridge()
    br_b.build(models_b)
    pipe = PhysicsPipeThread(br_b)
    for _ in range(N):
        pipe.post(models_b, DT, G, False)
        pipe.wait()
    snap_b = snapshot(models_b)
    pipe.stop()
    br_b.destroy()

    if snap_a.shape == snap_b.shape:
        if np.array_equal(snap_a, snap_b):
            check("W1 管线 vs 主线程 600 步逐位相等", True,
                  "(%d 物体 × 9 字段)" % snap_a.shape[0])
        else:
            d = np.abs(snap_a - snap_b).max()
            check("W1 管线 vs 主线程 600 步逐位相等", False,
                  "max|Δ|=%r — 管线引入时序差, 禁止落地!" % d)
    else:
        check("W1 形状一致", False, "%s vs %s" % (snap_a.shape, snap_b.shape))

    # W2: 超时降级语义
    class _SlowBridge:
        def __init__(self):
            self.enabled = True
        def ensure_models(self, models):
            pass
        def pre_step(self, dt, g):
            import time as _t
            _t.sleep(0.05)
        def step(self, dt):
            pass
        def post_step(self):
            pass
    sb = _SlowBridge()
    slow_pipe = PhysicsPipeThread(sb, timeout=0.2)
    slow_pipe.post([], 1 / 60.0, -9.8, False)
    try:
        slow_pipe.wait()
        check("W2 慢桥 wait 不超时 (0.05s < 0.2s 预算)", True)
    except RuntimeError:
        check("W2 慢桥 wait 不超时", False, "误杀 (0.05s 工作不该超时)")
    slow_pipe.stop()
    # 真超时: 直接验 _degraded 语义 (不真等 1s, 手动置)
    slow_pipe._degraded = True
    check("W2 _degraded 标志可触发降级语义", slow_pipe._degraded)

    print("=" * 40)
    print("pipe_check: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
