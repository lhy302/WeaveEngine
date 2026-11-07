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

"""undo 全覆盖: normal_mode/prefab_ref/材质 albedo+PBR+env/LOD/光源 range/Shape."""
from types import SimpleNamespace
import numpy as np

import engine as E
from mesh import create_cube
import undo as U
from loom_texture import Texture
from loom_cubemap import Cubemap

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

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

e = new_engine()
m = e.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0),
                name="obj")
r = m.renderer
mat = r.material
tex = Texture.from_rgba(1, 1, np.full((1, 1, 4), 123, dtype=np.uint8),
                        name="albedo")
cube = Cubemap.from_solid("#336699", size=2)
mesh_hi = create_cube(2.0)
mesh_lo = create_cube(3.0)

before = U.snapshot(m)
m.normal_mode = "vertex"
m.prefab_ref = "pf-x"
mat.pbr = True
mat.metallic = 0.8
mat.roughness = 0.2
mat.albedo = tex
mat.env_map = cube
r.lod_levels = [(10.0, mesh_hi)]
r.lod_screen_levels = [(0.5, mesh_lo)]
r.lod_bias = 2.5
after = U.snapshot(m)

um = U.UndoManager()
um.push(U.StateCommand("全字段", e, m, before, after))
check("改后 normal_mode", m.normal_mode == "vertex")
check("改后 prefab_ref", m.prefab_ref == "pf-x")
check("改后材质 PBR/albedo/env", mat.pbr is True
      and abs(mat.metallic - 0.8) < 1e-9 and mat.albedo is tex
      and mat.env_map is cube)
check("改后 LOD", r.lod_levels == [(10.0, mesh_hi)]
      and r.lod_screen_levels == [(0.5, mesh_lo)]
      and abs(r.lod_bias - 2.5) < 1e-9)

um.undo()
check("undo normal_mode", m.normal_mode == "flat")
check("undo prefab_ref", m.prefab_ref is None)
check("undo 材质 PBR/albedo/env", mat.pbr is False
      and abs(mat.metallic - 0.0) < 1e-9
      and abs(mat.roughness - 0.5) < 1e-9
      and mat.albedo is None and mat.env_map is None)
check("undo LOD", r.lod_levels is None and r.lod_screen_levels is None
      and abs(r.lod_bias - 1.0) < 1e-9)

um.redo()
check("redo 全字段", m.normal_mode == "vertex" and m.prefab_ref == "pf-x"
      and mat.pbr is True and mat.albedo is tex and mat.env_map is cube
      and r.lod_levels == [(10.0, mesh_hi)])

# 光源 range 进快照
l = E.LightState(kind="point", position=(1, 2, 3), range=10.0)
lb = U.light_snapshot(l)
l.range = 99.0
la = U.light_snapshot(l)
check("光源 range 快照捕获", lb["range"] == 10.0 and la["range"] == 99.0)
U.apply_light_snapshot(l, lb)
check("光源 range undo 还原", abs(l.range - 10.0) < 1e-9)

# Shape UI 撤销分支 (EAI ui_set 可达)
elem = SimpleNamespace(
    ctype="shape", name="s", rect=(0, 0, 10, 10), anchor=(0, 0), pivot=(0, 0),
    visible=True, enabled=True, z_order=1, shape_type="line",
    points=[(0, 0), (1, 1)], radius=0.0, stroke_color=(1, 2, 3, 255),
    stroke_width=2, fill_color=None, segments=32, close=False)
sb = U.ui_elem_snapshot(elem)
elem.shape_type = "circle"
elem.points = []
elem.radius = 5.0
elem.stroke_color = None
elem.stroke_width = 9
elem.fill_color = (9, 9, 9, 255)
elem.segments = 8
elem.close = True
sa = U.ui_elem_snapshot(elem)
check("Shape 快照含 shape_type/points", sb.get("shape_type") == "line"
      and sb.get("points") == [(0, 0), (1, 1)])
U.ui_apply_snapshot(elem, sb)
check("Shape undo 还原", elem.shape_type == "line"
      and elem.points == [(0, 0), (1, 1)] and elem.radius == 0.0
      and elem.stroke_color == (1, 2, 3, 255) and elem.stroke_width == 2
      and elem.fill_color is None and elem.segments == 32
      and elem.close is False)
U.ui_apply_snapshot(elem, sa)
check("Shape redo 生效", elem.shape_type == "circle" and elem.points == []
      and elem.fill_color == (9, 9, 9, 255) and elem.close is True)

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
