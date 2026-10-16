# -*- coding: utf-8 -*-
"""《未测试功能测试方向指南》A5(材质池孤儿回收/共享引用边界) + A6(Prefab 材质与碰撞体继承)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import sceneio
from mesh import create_cube

E.GLEngine._build_gpu = lambda self, m: None

def new_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []; e.materials = []; e.lights = []
    e.current_model_index = 0
    return e

def add(e, mesh, pos, **kw):
    return e.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), **kw)

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# ============ A5 材质池: 孤儿回收 与 共享引用边界 ============
e = new_eng()
a = add(e, create_cube(1.0), (0, 0, 0))
matA = a.renderer.material
check("A5 初始材质在库", matA in e.materials)
e.remove_model(a)
check("A5 删唯一引用物体 -> 材质移出库(无孤儿)",
      matA not in e.materials and a not in e.models)

e2 = new_eng()
x = add(e2, create_cube(1.0), (0, 0, 0))
y = add(e2, create_cube(1.0), (3, 0, 0))
shared = e2.add_material(color=(1.0, 0.0, 0.0))
x.renderer.material = shared
y.renderer.material = shared
e2.remove_model(x)
check("A5 共享材质删一个仍在库(还有引用)", shared in e2.materials
      and y.renderer.material is shared)
e2.remove_model(y)
check("A5 删最后一个引用 -> 共享材质移出库", shared not in e2.materials)

e3 = new_eng()
p = add(e3, create_cube(1.0), (0, 0, 0))
q = add(e3, create_cube(1.0), (3, 0, 0))
check("A5 两物体各自新建材质是独立对象",
      p.renderer.material is not q.renderer.material
      and p.renderer.material in e3.materials and q.renderer.material in e3.materials)
p.renderer.material.color = (0.0, 0.0, 1.0)
check("A5 改一个材质另一个不受影响", q.renderer.material.color != p.renderer.material.color)

# ============ A6 Prefab 材质 / 碰撞体继承 ============
e4 = new_eng()
root = add(e4, create_cube(1.0), (0, 0, 0))
shared4 = e4.add_material(color=(1.0, 0.5, 0.0))
root.renderer.material = shared4
root.collider.shape = 'sphere'
root.collider.enabled = False
data = sceneio.prefab_to_dict(root)
inst = sceneio.instantiate_prefab(e4, data, offset=(5, 0, 0))
i0 = inst[0]
check("A6 Prefab 实例引用同一共享材质(资产共享)", i0.renderer.material is shared4)
check("A6 Prefab 实例碰撞体继承模板 (shape/enabled)",
      i0.collider.shape == 'sphere' and not i0.collider.enabled)
e4.remove_model(i0)
check("A6 删实例不影响模板与其他实例",
      root in e4.models and shared4 in e4.materials)

e5 = new_eng()
root5 = add(e5, create_cube(1.0), (0, 0, 0))
child5 = add(e5, create_cube(1.0), (0, 1, 0))
e5.set_parent(child5, root5)
e5.add_light(kind='point', position=(0, 4, 0))
data5 = sceneio.prefab_to_dict(root5)
check("A6 Prefab 含子树, 不含光源",
      len(data5.get('objects', [])) == 2 and 'lights' not in data5
      and len(e5.lights) == 1)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
