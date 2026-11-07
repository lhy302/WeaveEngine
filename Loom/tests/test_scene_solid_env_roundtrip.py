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

"""sceneio 纯色 env / 天空盒往返: solid_color 不丢."""
import engine as E
from mesh import create_cube
import sceneio as S
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
                name="反射块")
mat = m.renderer.material
mat.env_map = Cubemap.from_solid("#336699", size=4)
mat.pbr = True
e._skybox = Cubemap.from_solid("#112233", size=2)
d = S.scene_to_dict(e)

md = [x for x in d["materials"] if x["id"] == mat.guid][0]
check("材质纯色 env 写入 solid_color",
      md.get("env_map", {}).get("solid_color") == [51, 102, 153, 255],
      str(md.get("env_map")))
check("场景天空盒写入 solid_color",
      (d.get("skybox") or {}).get("solid_color") == [17, 34, 51, 255],
      str(d.get("skybox")))

e2 = new_engine()
S.scene_from_dict(e2, d)
env = e2.models[0].renderer.material.env_map
check("材质纯色 env 加载还原", env is not None and env.paths is None
      and env._solid_color == (51, 102, 153, 255),
      str(getattr(env, "_solid_color", None)))
check("场景天空盒加载还原", e2._skybox is not None
      and e2._skybox._solid_color == (17, 34, 51, 255))

d2 = S.scene_to_dict(e2)
md2 = [x for x in d2["materials"] if x["id"] == mat.guid][0]
check("再次保存仍保留纯色 env",
      md2.get("env_map", {}).get("solid_color") == [51, 102, 153, 255])
check("再次保存仍保留纯色天空盒",
      (d2.get("skybox") or {}).get("solid_color") == [17, 34, 51, 255])

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
