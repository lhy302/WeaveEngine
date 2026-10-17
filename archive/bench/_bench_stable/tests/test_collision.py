# -*- coding: utf-8 -*-
"""M28 简单物理碰撞: 碰撞体形状/相交判定/查询/带碰撞移动/重力落地/弹跳."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from mesh import create_cube, create_sphere, create_plane
import scripts

# 不开窗口的引擎桩 (碰撞系统是纯数学, 不碰 GPU)
eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []
eng.lights = []
eng.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

def add(mesh, pos, scale=(1, 1, 1), **kw):
    return eng.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), scale=scale, **kw)

# ---- 1) 形状自动派生 + 默认启用 ----
c = add(create_cube(1.0), (0, 0, 0))            # 立方体 -> box
sp = add(create_sphere(1.0), (5, 0, 0))         # 球体 -> sphere
pl = add(create_plane(3, 3), (0, -3, 0))        # 平面 -> box
check("形状自动派生 (盒/球/盒)", c.collider.shape == 'box'
      and sp.collider.shape == 'sphere' and pl.collider.shape == 'box')
check("碰撞体默认启用", c.collider.enabled and sp.collider.enabled)

# ---- 2) 盒-盒 ----
b = add(create_cube(1.0), (0.4, 0, 0))          # 与 c 重叠
far = add(create_cube(1.0), (8, 0, 0))          # 分离
check("盒-盒相交", eng.collider_hit(c, b))
check("盒-盒分离", not eng.collider_hit(c, far))
check("自己不算碰撞", not eng.collider_hit(c, c))

# ---- 3) 球-球 / 盒-球 ----
sp2 = add(create_sphere(1.0), (6.5, 0, 0))      # 球心距 sp=1.5 < 2 -> 相交
check("球-球相交", eng.collider_hit(sp, sp2))
sph_in = add(create_sphere(0.5), (0.2, 0, 0))   # 半径0.5 球心在盒 c 内
check("盒-球: 球在盒内相交", eng.collider_hit(c, sph_in))
check("盒-球: 远处分离", not eng.collider_hit(c, sp))

# ---- 4) shape=none / enabled=False 不参与 ----
sp.collider.shape = 'none'
check("shape=none 不参与", not eng.collider_hit(sp, sp2))
sp.collider.shape = 'sphere'
sp2.collider.enabled = False
check("enabled=False 不参与", not eng.collider_hit(sp, sp2))
sp2.collider.enabled = True

# ---- 5) 同树物体不互相碰撞 ----
parent = add(create_cube(1.0), (20, 0, 0))
child = add(create_cube(1.0), (20.4, 0, 0))     # 与 parent 重叠
eng.set_parent(child, parent)
check("父子重叠不互相碰撞", not eng.collider_hit(parent, child)
      and child not in eng.get_collisions(parent)
      and parent not in eng.get_collisions(child))
eng.set_parent(child, None)

# ---- 6) get_collisions 查询 ----
hits = eng.get_collisions(c)
check("get_collisions 返回重叠物体", b in hits and far not in hits
      and c not in hits, str([h.name for h in hits]))

# ---- 7) move_with_collision: 大位移也能被薄地面挡住 (子步防穿透) ----
ground = add(create_plane(8, 8), (0, -4, 0))    # 平面 y=0 厚 -> 顶面 y=-4
ball = add(create_cube(1.0), (3, 0, 0))         # x=3 避开上面 pl(0,-3) 的水平范围
eng.move_with_collision(ball, 0, -10, 0)
# 落到底: 立方体底贴平面顶 (-4) -> 中心 y ≈ -3.5
check("落到平面顶被挡住 (不穿透)", abs(ball.position.y - (-3.5)) < 0.05,
      str(ball.position))
y1 = ball.position.y
eng.move_with_collision(ball, 0, -1, 0)
check("静止后不再被推 (贴边=不碰撞)", abs(ball.position.y - y1) < 1e-6,
      str(ball.position))

# ---- 8) 内置脚本: 重力落地 (fall) ----
eng_fall = E.GLEngine.__new__(E.GLEngine)
eng_fall.models = []; eng_fall.materials = []; eng_fall.lights = []
eng_fall.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None
g2 = eng_fall.add_model(create_plane(8, 8), E.Point3D(0, -4, 0),
                        E.Point3D(0, 0, 0))
drop = eng_fall.add_model(create_cube(1.0), E.Point3D(0, 2, 0),
                          E.Point3D(0, 0, 0), name="落体")
drop.add_script('fall')
for _ in range(120):                            # 120 * 0.05s = 6s
    eng_fall.update_scripts(0.05)
check("重力落地: 落下并停在地面 (中心≈-3.5)", abs(drop.position.y - (-3.5)) < 0.1,
      str(drop.position))

# ---- 9) 内置脚本: 弹跳 (bounce) ----
eng_b = E.GLEngine.__new__(E.GLEngine)
eng_b.models = []; eng_b.materials = []; eng_b.lights = []
eng_b.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None
g3 = eng_b.add_model(create_plane(8, 8), E.Point3D(0, -4, 0),
                     E.Point3D(0, 0, 0))
ball2 = eng_b.add_model(create_cube(1.0), E.Point3D(0, 2, 0),
                        E.Point3D(0, 0, 0), name="球")
ball2.add_script('bounce', {'rest': 0.8})
hit_ground = False
peak_after = None
for _ in range(120):
    eng_b.update_scripts(0.05)
    if ball2.position.y <= -3.49:
        hit_ground = True
    if hit_ground:
        peak_after = ball2.position.y if peak_after is None \
            else max(peak_after, ball2.position.y)
check("弹跳: 第一次碰地后反弹 (峰值明显高于地面)", hit_ground
      and peak_after is not None and peak_after > -3.2,
      str((hit_ground, peak_after)))

# ---- 10) 脚本注册表含物理脚本 ----
all_ids = [sid for sid, _ in scripts.script_options()]
check("脚本表含 重力落地/弹跳", 'fall' in all_ids and 'bounce' in all_ids)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
