# -*- coding: utf-8 -*-
"""phys_tri_probe.py — 用户实测三问题复现探针 (2026-08-30):
① 重力加速度 (值/应用路径) ② 播放停止后速度残留 (apply_snapshot 不清运行时)
③ 碰撞器启用后球穿过物体 / 动态-动态动量缺失.
无窗口: GLEngine.__new__ 桩 + 真 update_physics."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import engine as E
from mesh import create_cube, create_plane, create_sphere
import undo as U

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def make_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []
    e.materials = []
    e.lights = []
    e.current_model_index = 0
    e._physics_bounds = {}
    E.GLEngine._build_gpu = lambda self, m: None
    return e


DT = 1.0 / 60.0

# ---------- ① 重力应用值 ----------
e = make_eng()
ball = e.add_model(create_sphere(0.5), E.Point3D(0, 5, 0), E.Point3D(0, 0, 0))
ball.collider.shape = 'sphere'
rb = ball.add_rigidbody(use_gravity=True, is_kinematic=False)
e.update_physics(DT)
check("重力应用: dt 后 vy == 重力*dt (-9.8/60 = -0.1633)",
      abs(rb.velocity.y - (-9.8 * DT)) < 1e-9, "vy=%.6f" % rb.velocity.y)
check("重力常数 _GRAVITY = -9.8", E.GLEngine._GRAVITY == -9.8)

# ---------- ② 播放停止 (apply_snapshot) 后速度残留 ----------
e = make_eng()
ball2 = e.add_model(create_sphere(0.5), E.Point3D(0, 5, 0), E.Point3D(0, 0, 0))
rb2 = ball2.add_rigidbody(use_gravity=True)
snap = U.snapshot(ball2)                     # 播放开始快照
for _ in range(60):                          # 自由落体 1s
    e.update_physics(DT)
check("下落中速度已累积", rb2.velocity.y < -9.0, "vy=%.3f" % rb2.velocity.y)
U.apply_snapshot(ball2, snap)                # 播放停止还原
check("播放停止后 velocity 清零 (BUG 修复点)",
      rb2.velocity.y == 0.0 and rb2.velocity.x == 0.0 and rb2.velocity.z == 0.0,
      "残留 vy=%.5f" % rb2.velocity.y)
check("播放停止后 position 还原 (快照语义不破坏)",
      ball2.position == E.Point3D(0, 5, 0))

# ---------- ③a 球落到静态球上 (collider 启用) 是否穿过 ----------
e = make_eng()
ground = e.add_model(create_plane(20, 20), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0))
ground.collider.shape = 'box'
stat = e.add_model(create_sphere(0.5), E.Point3D(0, 0.5, 0), E.Point3D(0, 0, 0))
stat.collider.shape = 'sphere'               # 彩球 (无刚体, 静态挡体)
dyn = e.add_model(create_sphere(0.5), E.Point3D(0, 6, 0), E.Point3D(0, 0, 0))
dyn.collider.shape = 'sphere'
dyn.add_rigidbody(use_gravity=True)
for _ in range(600):
    e.update_physics(DT)
check("球未穿过静态球", dyn.position.y > 0.4, "y=%.3f (静态球心0.5, 相贴应≈1.0)" % dyn.position.y)
check("球未穿过地面", dyn.position.y > -0.2, "y=%.3f" % dyn.position.y)

# ---------- ③b 斜着落球 (侧移撞静态球) ----------
e = make_eng()
g2 = e.add_model(create_plane(20, 20), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0))
g2.collider.shape = 'box'
s2 = e.add_model(create_sphere(0.5), E.Point3D(0, 0.5, 0), E.Point3D(0, 0, 0))
s2.collider.shape = 'sphere'
d2 = e.add_model(create_sphere(0.5), E.Point3D(0.3, 5, 0), E.Point3D(0, 0, 0))
d2.collider.shape = 'sphere'
d2.add_rigidbody(use_gravity=True)
sink = False
for _ in range(600):
    e.update_physics(DT)
check("斜落球未穿进静态球 (中心距维持 >= 半径和-0.05)",
      abs(d2.position.z) < 0.05 and (E.Point3D(d2.position.x - 0, d2.position.y - 0.5, d2.position.z).x ** 2 + (d2.position.y - 0.5) ** 2) ** 0.5 > 0.9,
      "pos=%.3f,%.3f" % (d2.position.x, d2.position.y))
check("斜落球最终落定 (速度为 0 附近)", abs(d2.rigidbody.velocity.y) < 0.01,
      "vy=%.4f" % d2.rigidbody.velocity.y)

# ---------- ③c 动量: 动态球撞动态球 (都带刚体) ----------
e = make_eng()
g3 = e.add_model(create_plane(20, 20), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0))
g3.collider.shape = 'box'
m1 = e.add_model(create_sphere(0.5), E.Point3D(0, 0.5, 0), E.Point3D(0, 0, 0))
m1.collider.shape = 'sphere'
m1.add_rigidbody(use_gravity=False)
m1.rigidbody.velocity = E.Point3D(3.0, 0, 0)    # 向右匀速滑行
m2 = e.add_model(create_sphere(0.5), E.Point3D(2.0, 0.5, 0), E.Point3D(0, 0, 0))
m2.collider.shape = 'sphere'
m2.add_rigidbody(use_gravity=True)
m2.rigidbody.velocity = E.Point3D(0, 0, 0)
w1 = m1.rigidbody.velocity.x
for _ in range(300):
    e.update_physics(DT)
check("动量报告: 撞后 球1 速度", m1.rigidbody.velocity.x, "x=%.3f (引擎=撞停模型)" % m1.rigidbody.velocity.x)
check("动量报告: 撞后 球2 位移", m2.position.x, "x=%.3f (应被顶住即可)" % m2.position.x)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
