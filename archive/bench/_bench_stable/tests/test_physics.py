# -*- coding: utf-8 -*-
"""M31 刚体动力学 + 碰撞事件回调: 受重力下落/落地面停/不受重力/运动学/碰撞事件/
sceneio 序列化/undo 撤销."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import scripts
import undo as U
import sceneio as S
from mesh import create_cube, create_sphere, create_plane

eng = E.GLEngine.__new__(E.GLEngine)   # 不开窗口桩 (碰撞纯数学)
eng.models = []; eng.materials = []; eng.lights = []
eng.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

def add(mesh, pos, **kw):
    return eng.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), **kw)

# ---- 1) 刚体受重力下落 + 落地面停住 + 速度清零 ----
ball = add(create_sphere(0.5), (0, 2, 0), name="球")
ground = add(create_plane(10, 10), (0, -1, 0), name="地面")   # 地面 y=-1, 球半径0.5 -> 停 y≈-0.5
check("加刚体后 object.rigidbody 存在", ball.add_rigidbody() is not None)
for _ in range(150):
    eng.update_physics(0.1)                 # 15 秒步进
check("刚体受重力下落停地面 (y≈-0.5)", abs(ball.position.y - (-0.5)) < 0.1,
      "y=%.3f" % ball.position.y)
check("落地后速度清零", abs(ball.rigidbody.velocity.y) < 0.01,
      "vy=%.4f" % ball.rigidbody.velocity.y)

# ---- 2) use_gravity=False: 不受重力 ----
box = add(create_cube(1.0), (0, 3, 0), name="盒")
box.add_rigidbody(use_gravity=False)
eng.update_physics(0.5)
check("use_gravity=False 不受重力 (y 不变)", abs(box.position.y - 3.0) < 1e-6,
      "y=%.4f" % box.position.y)

# ---- 3) is_kinematic=True: 不被物理移动 ----
kin = add(create_cube(1.0), (5, 2, 0), name="运动学")
kin.add_rigidbody(is_kinematic=True)
eng.update_physics(0.5)
check("is_kinematic 不被物理移动", abs(kin.position.y - 2.0) < 1e-6)

# ---- 4) 碰撞事件回调 (on_collision_start / end) ----
class CollideProbe(scripts.Script):
    script_id = '_probe'
    name = 'probe'
    def __init__(self):
        super().__init__()
        self.starts = []
        self.ends = []
    def on_collision_start(self, other):
        self.starts.append(other.name if other else None)
    def on_collision_end(self, other):
        self.ends.append(other.name if other else None)
scripts.SCRIPTS['_probe'] = CollideProbe
A = add(create_cube(1.0), (0, 0, 0), name="A")
B = add(create_cube(1.0), (0, 0, 3), name="B")   # 初始不重叠
sc = A.add_script('_probe')
sc._script = CollideProbe()                      # 手动实例 (绕过 update_scripts)
B.position = E.Point3D(0, 0, 0.5)                # 移动撞上 A
eng.update_physics(0.1)
check("碰撞事件: on_collision_start 触发", sc._script.starts == ['B'],
      str(sc._script.starts))
B.position = E.Point3D(0, 0, 3)                  # 分离
eng.update_physics(0.1)
check("碰撞事件: on_collision_end 触发", sc._script.ends == ['B'],
      str(sc._script.ends))

# ---- 5) sceneio rigidbody 序列化 round-trip ----
d = S._emit_object(ball)
check("sceneio 序列化 rigidbody 字段", d.get('rigidbody') is not None, str(d.get('rigidbody')))
eng2 = E.GLEngine.__new__(E.GLEngine); eng2.models = []; eng2.materials = []
m2, _ = S._apply_object(eng2, d)
check("sceneio 加载 rigidbody (含 use_gravity)",
      m2.rigidbody is not None and m2.rigidbody.use_gravity,
      str(m2.rigidbody))
d3 = S._emit_object(box)                          # use_gravity=False 的刚体
eng3 = E.GLEngine.__new__(E.GLEngine); eng3.models = []; eng3.materials = []
m3, _ = S._apply_object(eng3, d3)
check("sceneio 加载 use_gravity=False", m3.rigidbody is not None
      and not m3.rigidbody.use_gravity)

# ---- 6) undo: 加刚体/移除刚体可撤销 ----
c = add(create_cube(1.0), (0, 0, 0), name="undo盒")
before = U.snapshot(c)
c.add_rigidbody(mass=2.0, use_gravity=False)
after = U.snapshot(c)
check("快照含刚体字段 (B1: 含摩擦/弹性/滚动摩擦)",
      after['rigidbody'] == (2.0, False, False, 0.5, 0.0, 0.1))
U.apply_snapshot(c, before)
check("undo 移除刚体", c.rigidbody is None)
U.apply_snapshot(c, after)
check("redo 恢复刚体", c.rigidbody is not None and c.rigidbody.mass == 2.0)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
