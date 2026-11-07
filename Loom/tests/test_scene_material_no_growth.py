# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""sceneio 材质孤儿: 连续 load->save 材质数不增长 (D2=A)."""
import engine as E
from mesh import create_cube
import sceneio as S

E.GLEngine._build_gpu = lambda self, m: None

def new_engine():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []
    e.materials = []
    e.lights = []
    e.cameras = []
    e.active_camera = None
    e.current_model_index = 0
    return e

def is_default(mat):
    return (getattr(mat, "color", None) is None
            and not getattr(mat, "pbr", False)
            and getattr(mat, "albedo", None) is None
            and getattr(mat, "normal_map", None) is None
            and getattr(mat, "env_map", None) is None
            and getattr(mat, "name", None) in (None, "材质"))

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

# ---- 稳定场景: 3 物体各引用自己的材质 -> 连续 5 次 load->save 不增长 ----
e = new_engine()
for i in range(3):
    e.add_model(create_cube(1.0), E.Point3D(i, 0, 0), E.Point3D(0, 0, 0),
                name="m%d" % i, color=["#FF0000", "#00FF00", "#0000FF"][i])
d = S.scene_to_dict(e)
base = len(d["materials"])
check("初始材质数=3", base == 3, "got %d" % base)
counts = []
for i in range(5):
    e2 = new_engine()
    S.scene_from_dict(e2, d)
    d = S.scene_to_dict(e2)
    counts.append(len(d["materials"]))
check("连续 5 次 load->save 材质数不变", all(c == base for c in counts),
      str(counts))
refs = {o.get("material_id") for o in d["objects"]}
check("每个保存材质都被物体引用",
      all(m["id"] in refs for m in d["materials"]),
      str([m["id"] for m in d["materials"]]))

# ---- 孤儿默认材质: 加载时丢弃; 用户显式彩色材质即使未引用也保留 ----
e = new_engine()
for i in range(2):
    e.add_model(create_cube(1.0), E.Point3D(i, 0, 0), E.Point3D(0, 0, 0),
                name="o%d" % i)
orphan = e.add_material()                       # 无引用默认材质 (应丢弃)
kept = e.add_material(color="#ABCDEF", name="库材质")   # 显式材质 (应保留)
d2 = S.scene_to_dict(e)
check("保存端不动: 孤儿默认材质仍写入", len(d2["materials"]) == 4,
      "got %d" % len(d2["materials"]))
e2 = new_engine()
S.scene_from_dict(e2, d2)
check("加载丢弃无引用默认材质",
      all(m.guid != orphan.guid for m in e2.materials),
      str([(m.name, m.color) for m in e2.materials]))
check("显式彩色材质即使未引用也保留",
      any(m.guid == kept.guid for m in e2.materials))
d3 = S.scene_to_dict(e2)
check("清理后再次 load->save 稳定", len(d3["materials"]) == 3,
      "got %d" % len(d3["materials"]))

# ---- material_id 指向库外材质 -> 加载补建且只补一次 (不膨胀) ----
ghost = {"version": 10, "materials": [], "objects": [
    {"id": "g", "parent_id": None, "type": "cube", "position": [0, 0, 0],
     "material_id": "ghost-guid"},
]}
e3 = new_engine()
S.scene_from_dict(e3, ghost)
check("库外 material_id 加载补建", len(e3.materials) == 1
      and e3.materials[0].guid == "ghost-guid")
g2 = S.scene_to_dict(e3)
e4 = new_engine()
S.scene_from_dict(e4, g2)
check("库外材质二次加载不膨胀", len(e4.materials) == 1)

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
