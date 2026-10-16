# -*- coding: utf-8 -*-
"""《未测试功能测试方向指南》A1-A3: 碰撞体系薄弱分支回归.
A1 旋转/缩放物体的碰撞体; A2 盒-球/球-球边界几何; A3 多物体/斜向/堆叠."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from mesh import create_cube, create_sphere, create_plane

# 不开窗口的引擎桩 (碰撞系统纯数学, 不碰 GPU)
E.GLEngine._build_gpu = lambda self, m: None

def new_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []; e.materials = []; e.lights = []
    e.current_model_index = 0
    return e

def add(e, mesh, pos, scale=(1, 1, 1), **kw):
    return e.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), scale=scale, **kw)

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ============ A1 旋转 / 缩放物体的碰撞体 ============
e = new_eng()
cube = add(e, create_cube(2.0), (0, 0, 0))              # 边长2, 半边长1
shp, (mn, mx) = e.collider_bounds(cube)
check("A1 未旋转立方体 AABB 半宽=1", abs(mx.x - mn.x - 2.0) < 1e-6)
cube.rotation = E.Point3D(0, math.radians(45), 0)        # 绕 Y 转 45°
_, (mn2, mx2) = e.collider_bounds(cube)
half45 = (mx2.x - mn2.x) * 0.5
check("A1 旋转45° AABB 半宽 ≈ √2 (AABB 是已知近似)", abs(half45 - math.sqrt(2)) < 0.01,
      f"half={half45:.4f}")
check("A1 旋转后 AABB 明显大于未旋转", half45 > 1.05)

e2 = new_eng()
s = add(e2, create_cube(1.0), (0, 0, 0), scale=(2, 0.5, 2))   # 半边长 (1, 0.25, 1)
_, (smn, smx) = e2.collider_bounds(s)
hx, hy, hz = (smx.x - smn.x) * 0.5, (smx.y - smn.y) * 0.5, (smx.z - smn.z) * 0.5
check("A1 非等比缩放碰撞体跟随 AABB",
      abs(hx - 1.0) < 1e-6 and abs(hy - 0.25) < 1e-6 and abs(hz - 1.0) < 1e-6,
      f"半宽=({hx:.3f},{hy:.3f},{hz:.3f})")

# ============ A2 盒-球 / 球-球 边界几何 ============
e3 = new_eng()
box = add(e3, create_cube(2.0), (0, 0, 0))               # AABB [-1,1]^3
sph_corner = add(e3, create_sphere(0.2), (1, 1, 1))      # 球心=盒角点, 最近点=角点 距0
check("A2 球在盒角上: 相交", e3.collider_hit(box, sph_corner))
sph_face = add(e3, create_sphere(0.2), (1.3, 0, 0))      # 距面 0.3 > r
check("A2 球紧贴盒面外侧: 分离", not e3.collider_hit(box, sph_face))
# 严格< 边界: 略内(0.1999<r)相交 / 略外(0.2001>r)分离. 恰好=0.2000 是 float 舍入敏感点, 不测.
sph_in = add(e3, create_sphere(0.2), (1.1999, 0, 0))     # 距面 0.1999 < r -> 相交
sph_out = add(e3, create_sphere(0.2), (1.2001, 0, 0))    # 距面 0.2001 > r -> 分离
check("A2 球略入盒面(距 0.1999<r): 相交", e3.collider_hit(box, sph_in))
check("A2 球略出盒面(距 0.2001>r): 分离", not e3.collider_hit(box, sph_out))

e4 = new_eng()
sA = add(e4, create_sphere(1.0), (0, 0, 0))
sB = add(e4, create_sphere(1.0), (0, 0, 0))              # 同圆心
check("A2 球-球同圆心: 相交", e4.collider_hit(sA, sB))
sC = add(e4, create_sphere(100.0), (50, 0, 0))           # 半径悬殊: 大球包小球
check("A2 球-球半径悬殊(100 vs 1): 相交", e4.collider_hit(sA, sC))

e5 = new_eng()
h1 = add(e5, create_cube(2.0), (0, 0, 0))
h2 = add(e5, create_cube(2.0), (0, 0, 0))                # 完全重合
check("A2 盒盒完全重合: 相交", e5.collider_hit(h1, h2))
e5._push_out(h1, h2)                                     # 无运动信息 -> 原最小穿透逻辑
check("A2 推挤后两盒分离", not e5.collider_hit(h1, h2),
      f"h1={h1.position}")

# ============ A3 多物体 / 斜向 / 堆叠 ============
# A3-1 一摞盒子 + 落体: 应停在最上层, 不挤穿下面
e6 = new_eng()
g6 = add(e6, create_plane(8, 8), (0, -4, 0))             # 地面(零厚度, 顶 y=-4)
b1 = add(e6, create_cube(1.0), (0, -3, 0))               # AABB y [-3.5,-2.5]
b2 = add(e6, create_cube(1.0), (0, -2, 0))               # AABB y [-2.5,-1.5]
drop = add(e6, create_cube(1.0), (0, 2, 0))              # 从上方落下
e6.move_with_collision(drop, 0, -10, 0)
check("A3 堆叠: 落体停最上层 (中心≈-1.0)", abs(drop.position.y - (-1.0)) < 0.05,
      f"drop y={drop.position.y:.4f}")
check("A3 堆叠: 全部两两不重叠",
      all(not e6.collider_hit(x, y) for x, y in
          [(drop, b2), (drop, b1), (drop, g6), (b2, b1), (b1, g6)]))

# A3-2 左右墙夹住: 能推出不卡死
e7 = new_eng()
lw = add(e7, create_cube(1.0), (-4, 0, 0))               # x [-4.5,-3.5]
rw = add(e7, create_cube(1.0), (4, 0, 0))                # x [3.5,4.5]
mid = add(e7, create_cube(1.0), (0, 0, 0))
mid.position = E.Point3D(3.6, 0, 0)                      # 压入右墙重叠区
check("A3 夹住: 先确认与右墙重叠", e7.collider_hit(mid, rw))
hit7 = e7.resolve_collisions(mid, max_iter=4)
check("A3 夹住: resolve 推出右墙不卡死", hit7 and not e7.collider_hit(mid, rw)
      and mid.position.x < 3.5, str(mid.position))

# A3-3 极大位移: 子步 5000 截断后不崩、无 NaN
e8 = new_eng()
g8 = add(e8, create_plane(8, 8), (0, -4, 0))
faller = add(e8, create_cube(1.0), (0, 100, 0))
e8.move_with_collision(faller, 0, -10000, 0)
p8 = faller.position
check("A3 极大位移: 无 NaN 且返回不崩",
      all(math.isfinite(v) for v in (p8.x, p8.y, p8.z)),
      str(p8))

# A3-4 斜向撞墙 (同时 dx/dy/dz): 不穿模 + 撞到 + y 到位
e9 = new_eng()
wall = add(e9, create_cube(6.0), (8, 3, 0))              # AABB x[5,11] y[0,6] z[-3,3]
role = add(e9, create_cube(0.6), (0, 0, 0))              # 半边长0.3
hit9 = e9.move_with_collision(role, 5.2, 3.0, 0)
p9 = role.position
check("A3 斜向撞墙: 不穿模 (右缘贴墙面 5.0)", hit9
      and p9.x + 0.3 <= 5.0 + 0.05, str(p9))
check("A3 斜向撞墙: y 推进到位且无 NaN",
      abs(p9.y - 3.0) < 0.1
      and all(math.isfinite(v) for v in (p9.x, p9.y, p9.z)), str(p9))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
