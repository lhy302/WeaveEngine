# -*- coding: utf-8 -*-
"""物理运行时状态测试 (2026-08-30 用户实测三问题修复):
① 重力加速度可调 (engine.gravity, 场景/设置/面板) ② 快照还原清运行时运动状态
(velocity/_colliding/动画/音频) —— "停止播放清除所有状态" 契约."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import undo as U
from mesh import create_sphere

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def make_eng(gravity=None):
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []
    e.materials = []
    e.lights = []
    e.current_model_index = 0
    if gravity is not None:
        e.gravity = gravity          # 真实 __new__ 桩不含 __init__ 属性
    E.GLEngine._build_gpu = lambda self, m: None
    return e


DT = 1.0 / 60.0

# ---- ① 重力可调 ----
e = make_eng(gravity=-20.0)
b = e.add_model(create_sphere(0.5), E.Point3D(0, 5, 0), E.Point3D(0, 0, 0))
rb = b.add_rigidbody(use_gravity=True)
e.update_physics(DT)
check("gravity=-20 被使用 (vy=-20*dt)", abs(rb.velocity.y - (-20.0 * DT)) < 1e-9,
      "vy=%.5f" % rb.velocity.y)

e2 = make_eng()                      # 无 gravity 属性 -> 桩路径回退 _GRAVITY
b2 = e2.add_model(create_sphere(0.5), E.Point3D(0, 5, 0), E.Point3D(0, 0, 0))
rb2 = b2.add_rigidbody(use_gravity=True)
e2.update_physics(DT)
check("桩无 gravity 回退 _GRAVITY=-9.8", abs(rb2.velocity.y - (-9.8 * DT)) < 1e-9,
      "vy=%.5f" % rb2.velocity.y)

# ---- ② 快照还原清运行时状态 (播放停止契约) ----
e3 = make_eng(gravity=-9.8)
b3 = e3.add_model(create_sphere(0.5), E.Point3D(0, 5, 0), E.Point3D(0, 0, 0))
rb3 = b3.add_rigidbody(use_gravity=True)
snap = U.snapshot(b3)
for _ in range(60):
    e3.update_physics(DT)
check("下落中速度已累积", rb3.velocity.y < -9.0, "vy=%.3f" % rb3.velocity.y)
U.apply_snapshot(b3, snap)
check("快照还原清 velocity", rb3.velocity.y == 0.0 and rb3.velocity.x == 0.0,
      "残留 vy=%.5f" % rb3.velocity.y)
check("快照还原清 _colliding", rb3._colliding == set() and b3._colliding == set())
check("快照还原 position 正常", b3.position == E.Point3D(0, 5, 0))

# 动画/音频运行态 (先加组件→快照→置运行态→还原)
m4 = E.GameObject(create_sphere(0.5), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
an = m4.add_animator(clips={'a': E.AnimationClip([{'time': 0.0, 'position': (0, 0, 0)}])},
                     current='a')
au = m4.add_audio_source(clip='x.wav', loop=True)
snap4 = U.snapshot(m4)
an.playing = True
an.time = 3.0
au.playing = True
au._key = ('x.wav', True)
U.apply_snapshot(m4, snap4)
check("快照还原清动画运行态 (组件保留)", an.playing is False and an.time == 0.0
      and m4.animator is an, "playing=%s time=%s" % (an.playing, an.time))
check("快照还原清音频运行态 (组件保留)", au.playing is False and au._key is None
      and m4.audio_source is au, "playing=%s key=%s" % (au.playing, au._key))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
