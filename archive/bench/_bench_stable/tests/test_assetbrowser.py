# -*- coding: utf-8 -*-
"""M24 资源浏览器面板: 资产扫描 / 落盘 / 按 guid 应用 / 拖放落点 无头测试.
资产读写全部走临时目录, 不碰真实 assets/."""
import sys, os, json, math, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import engine as E
import sceneio
from mesh import create_cube
from matlib import mat4_perspective, mat4_view_yaw_pitch
from undo import UndoManager
from editor import EditorApp

E.GLEngine._build_gpu = lambda self, m: None


def new_app():
    """无头 EditorApp 桩: 引擎数据 + 撤销 + 播放关 (M24 相关方法只依赖这些)."""
    app = EditorApp.__new__(EditorApp)
    app.models = []; app.materials = []; app.lights = []
    app.current_model_index = 0
    app.script_keys = {}
    app.undo = UndoManager()
    app.is_playing = False
    app.selected_index = -1
    app.selected_light_index = -1
    app.prefab_count = 0
    app._hier_row_targets = []
    app._res_selected = None
    app._res_drag = None
    return app


def new_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []; e.materials = []; e.lights = []
    e.current_model_index = 0
    e.script_keys = {}
    return e


def add(e, mesh, pos, **kw):
    return e.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), **kw)


ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False


# ============ T1 _scan_assets: 内置恒在 + 文件资产分组列出 ============
tmp = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(tmp, 'materials'))
    os.makedirs(os.path.join(tmp, 'meshes'))
    with open(os.path.join(tmp, 'materials', '红.json'), 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'id': 'm1', 'name': '红', 'color': '#FF0000',
                   'saturation': 1.0}, f)
    with open(os.path.join(tmp, 'meshes', 'cube1.json'), 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'id': 'g1', 'type': 'cube',
                   'params': {'size': 1.5}}, f)
    with open(os.path.join(tmp, 'my.prefab'), 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'prefab': {'guid': 'p1'}, 'objects': []}, f)
    app = new_app()
    items = app._scan_assets(tmp)
    meshes = [it for it in items if it['type'] == 'mesh']
    mats = [it for it in items if it['type'] == 'material']
    pf = [it for it in items if it['type'] == 'prefab']
    check("T1 内置网格恒在 (3)", len([it for it in meshes if it.get('builtin')]) == 3)
    check("T1 网格资产列出", any(it['name'] == 'cube1' for it in meshes))
    check("T1 材质资产列出", any(it['name'] == '红' for it in mats))
    check("T1 Prefab 资产列出", any(it['name'] == 'my' for it in pf))
    check("T1 资产项 key 唯一", len({it['key'] for it in items}) == len(items))
    check("T1 内置网格带 spec", next(it for it in meshes if it.get('builtin')).get('spec'))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ============ T2 材质资产 save/load round-trip + 同 guid 覆盖更新 ============
tmp = tempfile.mkdtemp()
try:
    e = new_eng()
    a = add(e, create_cube(1.0), (0, 0, 0))
    mat = a.renderer.material
    mat.color = '#FF5500'; mat.name = '测试红'
    p = os.path.join(tmp, 'test.json')
    sceneio.save_material_asset(p, mat)
    data = sceneio.load_material_asset(p)
    check("T2 材质资产 round-trip (guid/color/sat/name)",
          data['id'] == mat.guid and data['color'] == '#FF5500'
          and abs(data['saturation'] - 1.0) < 1e-9 and data['name'] == '测试红')
    app = new_app()
    found = app._asset_file_by_guid(tmp, mat.guid, '.json')
    check("T2 _asset_file_by_guid 命中同 guid 文件", found == p)
    mat.color = '#00FF00'
    sceneio.save_material_asset(found, mat)               # 再存=覆盖更新
    files = [f for f in os.listdir(tmp) if f.endswith('.json')]
    check("T2 同 guid 再存覆盖不新建 (1 个文件)", len(files) == 1)
    data2 = sceneio.load_material_asset(found)
    check("T2 覆盖后颜色更新", data2['color'] == '#00FF00')
    check("T2 load_material_asset 缺 id 返回 None",
          sceneio.load_material_asset(os.path.join(tmp, '坏.json')) is None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ============ T3 网格资产 save/load ============
tmp = tempfile.mkdtemp()
try:
    p = os.path.join(tmp, 'cube.json')
    sceneio.save_mesh_asset(p, 'cube', {'size': 1.5})
    data = sceneio.load_mesh_asset(p)
    check("T3 网格资产 round-trip (type/params/guid)",
          data['type'] == 'cube' and data['params'] == {'size': 1.5}
          and bool(data.get('id')))
    check("T3 load_mesh_asset 缺 type 返回 None",
          sceneio.load_mesh_asset(os.path.join(tmp, '坏.json')) is None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ============ T4 _apply_material_asset: 按 guid 应用/复用/撤销 ============
tmp = tempfile.mkdtemp()
try:
    app = new_app()
    src = add(app, create_cube(1.0), (0, 0, 0))
    dst = add(app, create_cube(1.0), (2, 0, 0))
    mat = src.renderer.material
    mat.color = '#336699'; mat.name = '蓝灰'
    p = os.path.join(tmp, 'm.json')
    sceneio.save_material_asset(p, mat)
    it = {'type': 'material', 'path': p, 'name': 'm'}
    n = len(app.materials)
    app._apply_material_asset(it, dst)
    check("T4 材质资产应用到物体 (共享同一材质对象)", dst.renderer.material is mat)
    check("T4 应用不新增库中材质 (按 guid 复用)", len(app.materials) == n)
    app.undo.undo()
    check("T4 应用材质可撤销", dst.renderer.material is not mat)
    app.undo.redo()
    check("T4 应用材质可重做", dst.renderer.material is mat)
    # 空库: guid 不在库 -> 按 guid 自建
    app2 = new_app()
    d2 = add(app2, create_cube(1.0), (0, 0, 0))
    app2._apply_material_asset(it, d2)
    check("T4 空库按 guid 自建材质", d2.renderer.material.guid == mat.guid
          and d2.renderer.material is not mat)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ============ T5 _asset_drop_to_scene: 网格/Prefab 落点 + 材质应用到选中 ============
tmp = tempfile.mkdtemp()
try:
    # 网格拖入视口
    app = new_app()
    app._mouse_to_ground = lambda px, py: (2.0, 0.0, 3.0)
    it = {'type': 'mesh', 'key': 'builtin.cube', 'name': '立方体', 'builtin': True,
          'spec': {'type': 'cube', 'params': {}}, 'path': None}
    n0 = len(app.models)
    app._asset_drop_to_scene(it, (0, 0))
    m = app.models[-1]
    check("T5 拖内置网格 -> 落点加物体 (primitive/位置)",
          len(app.models) == n0 + 1 and m.primitive == 'cube'
          and abs(m.position.x - 2.0) < 1e-9 and abs(m.position.y) < 1e-9
          and abs(m.position.z - 3.0) < 1e-9, str(m.position))
    app.undo.undo()
    check("T5 网格拖入可撤销", len(app.models) == n0)

    # Prefab 拖入视口 (根贴地)
    e = new_eng()
    root = add(e, create_cube(1.0), (0, 1.5, 0))
    child = add(e, create_cube(1.0), (0, 2.5, 0))
    e.set_parent(child, root)
    pp = os.path.join(tmp, 'tower.prefab')
    sceneio.save_prefab(pp, root)
    app2 = new_app()
    app2._mouse_to_ground = lambda px, py: (5.0, 0.0, 6.0)
    itp = {'type': 'prefab', 'key': 'prefab.tower.prefab', 'name': 'tower', 'path': pp}
    app2._asset_drop_to_scene(itp, (0, 0))
    r0 = app2.models[0]
    check("T5 拖 Prefab -> 根贴地实例化 (2 物体, 根在落点)",
          len(app2.models) == 2 and abs(r0.position.x - 5.0) < 1e-9
          and abs(r0.position.y) < 1e-9 and abs(r0.position.z - 6.0) < 1e-9,
          str(r0.position))
    check("T5 Prefab 实例带 prefab_ref", bool(r0.prefab_ref))
    app2.undo.undo()
    check("T5 Prefab 拖入可撤销", len(app2.models) == 0)

    # 材质拖入视口 -> 应用到选中物体
    app3 = new_app()
    a = add(app3, create_cube(1.0), (0, 0, 0))
    mat = a.renderer.material; mat.color = '#AABBCC'; mat.name = '资产'
    mp = os.path.join(tmp, 'm.json')
    sceneio.save_material_asset(mp, mat)
    sel = add(app3, create_cube(1.0), (4, 0, 0))
    app3.selected_index = len(app3.models) - 1
    app3._asset_drop_to_scene({'type': 'material', 'path': mp, 'name': 'm'}, (0, 0))
    check("T5 拖材质 -> 应用到选中物体", sel.renderer.material is mat)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ============ T6 _mouse_to_ground: 屏幕中心射线落地面 = 相机目标 ============
app = new_app()
app.width, app.height = 1280, 800
app._fov = math.radians(60); app.near = 0.1; app.far = 100.0
app.camera_target = (0.0, 0.0, 0.0)
app.camera_yaw = 0.6; app.camera_pitch = -0.35; app.camera_distance = 10.0
app.apply_orbit_camera()
V = mat4_view_yaw_pitch(np, (app.camera.x, app.camera.y, app.camera.z),
                        app.camera_yaw, app.camera_pitch)
P = mat4_perspective(np, app._fov, app.width / app.height, app.near, app.far)
app._vp = V @ P
pt = app._mouse_to_ground(app.width / 2.0, app.height / 2.0)
check("T6 屏幕中心射线落地面 = 相机目标 (0,0,0)",
      abs(pt[0]) < 1e-6 and abs(pt[1]) < 1e-9 and abs(pt[2]) < 1e-6, str(pt))
pt2 = app._mouse_to_ground(app.width * 0.3, app.height * 0.7)
check("T6 任意像素射线交点在地面上 y=0", abs(pt2[1]) < 1e-9, str(pt2))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
