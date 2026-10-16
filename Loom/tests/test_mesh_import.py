# -*- coding: utf-8 -*-
"""M36 模型导入: obj 解析 (顶点/面/vn/vt/MTL/四边三角化/坏文件) + sceneio obj 重读 round-trip."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
import sceneio as S
from mesh import load_obj

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

def _write(text, suffix='.obj'):
    p = tempfile.mktemp(suffix=suffix)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)
    return p

# ---- obj 解析 (基础) ----
p = _write("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
mesh = load_obj(p)
check("load_obj 解析顶点", len(mesh.vertices) == 3, str(len(mesh.vertices)))
check("load_obj 解析面", len(mesh.faces) == 1, str(len(mesh.faces)))
check("load_obj primitive=obj + 路径", mesh.primitive == 'obj' and 'obj' in mesh.params,
      str(mesh.primitive))

# 无 vn 自动平滑法线 (Unity 默认): 数量对齐顶点, 面在 xy 平面 -> 法线 +z 单位向量
check("无 vn 自动计算平滑法线 (数量对齐)",
      mesh.normals is not None and len(mesh.normals) == 3,
      str(None if mesh.normals is None else len(mesh.normals)))
n = mesh.normals[0] if mesh.normals else (0, 0, 0)
check("无 vn 平滑法线为 +z 单位向量",
      abs(n[0]) < 1e-6 and abs(n[1]) < 1e-6 and abs(n[2] - 1.0) < 1e-6, str(n))
check("无 vt 时 uvs 为 None", mesh.uvs is None, str(mesh.uvs))

# 四边面自动三角化
p2 = _write("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n")
mesh2 = load_obj(p2)
check("load_obj 四边面三角化为 2 面", len(mesh2.faces) == 2, str(len(mesh2.faces)))

# vn/vt 解析 (有 vn 用 obj 法线; vt 存进 uvs)
p3 = _write("# 注释\nvn 0 0 1\nvt 0 0\nvt 1 0\nvt 0 1\n"
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1/1 2/2/1 3/3/1\n")
mesh3 = load_obj(p3)
check("load_obj 解析 vn/vt/注释 (3 顶点 1 面)",
      len(mesh3.vertices) == 3 and len(mesh3.faces) == 1,
      "%d/%d" % (len(mesh3.vertices), len(mesh3.faces)))
check("有 vn 用 obj 法线",
      mesh3.normals is not None and len(mesh3.normals) == 3
      and all(abs(mesh3.normals[i][0]) < 1e-6 and abs(mesh3.normals[i][1]) < 1e-6
              and abs(mesh3.normals[i][2] - 1.0) < 1e-6 for i in range(3)),
      str(mesh3.normals))
check("vt 存进 mesh.uvs",
      mesh3.uvs is not None and len(mesh3.uvs) == 3
      and mesh3.uvs[0] == (0.0, 0.0) and mesh3.uvs[1] == (1.0, 0.0)
      and mesh3.uvs[2] == (0.0, 1.0), str(mesh3.uvs))

# MTL 颜色应用 (Kd 漫反射色, 0..1 与 0..255 两种写法)
mtl = _write("newmtl red\nKd 1.0 0.0 0.0\nnewmtl blue\nKd 0 0 255\n", suffix='.mtl')
p4 = _write("mtllib %s\n"
            "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl red\nf 1 2 3\n"
            "usemtl blue\nv 1 1 0\nf 1 3 4\n" % os.path.basename(mtl))
mesh4 = load_obj(p4)
check("MTL 颜色应用 (Kd 漫反射)",
      len(mesh4.face_colors) == 2
      and mesh4.face_colors[0] == "#ff0000" and mesh4.face_colors[1] == "#0000ff",
      str(mesh4.face_colors))

# 坏 MTL 容错 (mtllib 缺失 / 材质无 Kd)
p5 = _write("mtllib _no_such_material.mtl\n"
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl x\nf 1 2 3\n")
mesh5 = load_obj(p5)
check("坏 MTL 容错 -> 默认面色",
      len(mesh5.face_colors) == 1 and mesh5.face_colors[0] == "#AAAAAA",
      str(mesh5.face_colors))

# 坏文件
try:
    load_obj(os.path.join(tempfile.gettempdir(), '_no_such_model_xyz.obj'))
    check("load_obj 缺失文件抛 ValueError", False)
except ValueError:
    check("load_obj 缺失文件抛 ValueError", True)

# ---- sceneio obj round-trip (存路径, 加载重读) ----
eng = E.GLEngine.__new__(E.GLEngine); eng.models = []; eng.materials = []
eng.lights = []
E.GLEngine._build_gpu = lambda self, m: None
m = eng.add_model(mesh, E.Point3D(0, 0, 0), E.Point3D(0, 0, 0))
d = S._emit_object(m)
check("sceneio obj 序列化 type=obj+路径", d.get('type') == 'obj'
      and isinstance(d.get('params', {}).get('obj'), str), str(d.get('type')))
m2, _ = S._apply_object(eng, d)
check("sceneio obj 加载重读 (面数一致)", m2.mesh is not None and len(m2.mesh.faces) == 1,
      str(len(m2.mesh.faces) if m2.mesh else None))
check("sceneio obj 重读保留法线 (vn/平滑法线兼容序列化)",
      m2.mesh is not None and m2.mesh.normals is not None and len(m2.mesh.normals) == 3,
      str(None if (m2.mesh is None or m2.mesh.normals is None) else len(m2.mesh.normals)))

# 文件失效 -> 立方体兜底
d['params'] = {'obj': os.path.join(tempfile.gettempdir(), '_gone.obj')}
m3, _ = S._apply_object(eng, d)
check("sceneio obj 文件失效兜底立方体", m3.mesh is not None
      and len(m3.mesh.faces) == 12, str(len(m3.mesh.faces) if m3.mesh else None))

# 2026-08-20 安全加固 (Qoder 报告低危5): OBJ 资源上限 (内存 DoS 防护)
import mesh as _mesh_mod
_old_v = _mesh_mod._OBJ_MAX_VERTS
_mesh_mod._OBJ_MAX_VERTS = 3
try:
    _lim = os.path.join(tempfile.gettempdir(), '_loom_limit.obj')
    with open(_lim, 'w', encoding='utf-8') as _f:
        _f.write("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nf 1 2 3\n")
    try:
        load_obj(_lim)
        check("OBJ 顶点超限抛 ValueError (资源上限)", False)
    except ValueError:
        check("OBJ 顶点超限抛 ValueError (资源上限)", True)
finally:
    _mesh_mod._OBJ_MAX_VERTS = _old_v

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
