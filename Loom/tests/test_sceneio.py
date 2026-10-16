# -*- coding: utf-8 -*-
"""sceneio.py 无头测试: round-trip/迁移/原子写/Prefab 实例化."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from mesh import create_cube, create_plane, create_sphere
import sceneio as S

eng = E.GLEngine.__new__(E.GLEngine)
eng.models = []
eng.materials = []
eng.lights = []
eng.cameras = []
eng.active_camera = None
eng.current_model_index = 0
E.GLEngine._build_gpu = lambda self, m: None

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond: ok = False

# 搭建树: 根A(球) -> 子B(立方体) -> 孙C(平面); 旁挂 根D
A = eng.add_model(create_sphere(1.0), E.Point3D(0,0,0), E.Point3D(0,0,0), normal_mode='vertex', name="球A", color="#00FF00",
                  saturation=1.5)
B = eng.add_model(create_cube(1.5), E.Point3D(2,0,0), E.Point3D(0,0,0), normal_mode='flat', name="方B")
C = eng.add_model(create_plane(3,3), E.Point3D(1,0,0), E.Point3D(0,0,0), normal_mode='flat', name="平C")
D = eng.add_model(create_cube(2.0), E.Point3D(9,9,9), E.Point3D(0,0,0), name="独立D")
eng.set_parent(B, A)
eng.set_parent(C, B)
A.script_id = 'rotate'                       # M27: 给 A 挂脚本 (随场景/Prefab 序列化)
A.script_vars = {'sx': 10.0, 'sy': 20.0}
A.add_script('bob', {'amp': 2.0, 'freq': 1.5})   # M25: 再挂一个脚本组件 (多脚本)

cam = {"target": [1,2,3], "distance": 20.0, "yaw": 0.5, "pitch": -0.2}
data = S.scene_to_dict(eng, camera=cam)
check("v6 输出 version", data["version"] == S.SCENE_VERSION)
check("v6 输出 materials 有 4 个 (每物体自建)", len(data["materials"]) == 4)
check("v6 输出 lights 空数组", data["lights"] == [])
check("objects 共 4 个", len(data["objects"]) == 4)
ids = [o["id"] for o in data["objects"]]
check("DFS 前序 [A,B,C,D]", ids == [A.guid, B.guid, C.guid, D.guid])
check("B 的 parent_id = A", data["objects"][1]["parent_id"] == A.guid)
check("C 的 parent_id = B", data["objects"][2]["parent_id"] == B.guid)
check("D 的 parent_id = None", data["objects"][3]["parent_id"] is None)
check("normal_mode/color 保留", data["objects"][0]["normal_mode"] == "vertex"
      and data["objects"][0]["color"] == "#00FF00")
check("saturation 序列化", data["objects"][0]["saturation"] == 1.5)
check("scripts 序列化 (M25 多脚本)", data["objects"][0]["scripts"] ==
      [{"id": "rotate", "vars": {'sx': 10.0, 'sy': 20.0}},
       {"id": "bob", "vars": {'amp': 2.0, 'freq': 1.5}}])
check("无脚本对象 scripts=[]", data["objects"][1]["scripts"] == [])

# --- 原子写 + 回读 ---
tmp = os.path.join(r"C:\Users\<USER>\.claude\jobs\6fa5b18c\tmp", "scene_test.json")
S.save_json_atomic(tmp, data)
check("原子写生成文件", os.path.exists(tmp) and not os.path.exists(tmp + ".tmp"))
with open(tmp, encoding="utf-8") as f:
    loaded = json.load(f)
check("回读 == 原数据", loaded == data)

# --- 空引擎加载 (含相机) ---
eng2 = E.GLEngine.__new__(E.GLEngine)
eng2.models = []
eng2.materials = []
eng2.lights = []
eng2.cameras = []
eng2.active_camera = None
eng2.current_model_index = 0
cam_out = {}
ms = S.scene_from_dict(eng2, loaded, camera_out=cam_out)
check("加载 4 个对象", len(eng2.models) == 4)
gmap = {m.guid: m for m in eng2.models}
check("父链 A<-B<-C 恢复", gmap[B.guid].parent is gmap[A.guid]
      and gmap[C.guid].parent is gmap[B.guid]
      and gmap[A.guid].parent is None and gmap[D.guid].parent is None)
check("children 表恢复", gmap[A.guid].children == [gmap[B.guid]]
      and gmap[B.guid].children == [gmap[C.guid]])
check("名字/类型/颜色保留", gmap[A.guid].name == "球A"
      and gmap[A.guid].primitive == "sphere"
      and gmap[A.guid].color == "#00FF00")
check("saturation 回读", abs(gmap[A.guid].saturation - 1.5) < 1e-9)
check("脚本回读 (id+vars)", gmap[A.guid].script_id == "rotate"
      and gmap[A.guid].script_vars == {'sx': 10.0, 'sy': 20.0})
check("多脚本回读 (M25)", len(gmap[A.guid].scripts) == 2
      and gmap[A.guid].scripts[1].script_id == "bob"
      and gmap[A.guid].scripts[1].script_vars == {'amp': 2.0, 'freq': 1.5})
# 2026-08-16: set_parent 保世界 -> C 局部被换算到 B 空间 (-1), 世界仍 1.0
check("世界位置合成后正确 (挂父保世界)", abs(gmap[C.guid].position.x + 1.0) < 1e-9
      and abs(eng2.world_position(gmap[C.guid]).x - 1.0) < 1e-9)
check("相机恢复", cam_out["target"] == (1,2,3) and cam_out["distance"] == 20.0)

# --- 光源 round-trip (M21) ---
eng.lights.append(E.LightState(kind='directional', direction=(1, -1, 0.5),
                               color=(1.0, 0.9, 0.8), intensity=0.8, name="太阳"))
eng.lights.append(E.LightState(kind='point', position=(3, 4, 5),
                               color=(0.2, 0.4, 1.0), intensity=2.0, name="灯"))
d2 = S.scene_to_dict(eng)
check("场景 dict 含 2 光源", len(d2["lights"]) == 2)
check("光源字段完整", d2["lights"][0]["kind"] == "directional"
      # M30: direction 归一化 (由 朝向/俯仰 派生), (1,-1,0.5) 归一 = (0.667,-0.667,0.333)
      and abs(d2["lights"][0]["direction"][0] - 2 / 3) < 1e-3
      and abs(d2["lights"][0]["direction"][1] + 2 / 3) < 1e-3
      and abs(d2["lights"][0]["direction"][2] - 1 / 3) < 1e-3
      and abs(d2["lights"][0]["azimuth"] - 63.435) < 0.1
      and abs(d2["lights"][0]["elevation"] + 41.810) < 0.1
      and d2["lights"][0]["color"] == [1.0, 0.9, 0.8]
      and d2["lights"][0]["intensity"] == 0.8
      and d2["lights"][1]["position"] == [3, 4, 5])
eng4 = E.GLEngine.__new__(E.GLEngine); eng4.models = []; eng4.materials = []
eng4.lights = []; eng4.cameras = []; eng4.active_camera = None
eng4.current_model_index = 0
S.scene_from_dict(eng4, d2)
check("加载恢复光源", len(eng4.lights) == 2
      and eng4.lights[1].kind == "point"
      and tuple(eng4.lights[1].position) == (3, 4, 5)
      and eng4.lights[0].intensity == 0.8
      and eng4.lights[0].name == "太阳")
eng.lights.clear()                            # 清理, 不影响后续 Prefab 测试

# --- v1 迁移 ---
v1 = {"version": 1, "camera": cam,
      "objects": [{"id": "obj_0001", "name": "旧物", "type": "cube",
                   "params": {"size": 1.0}, "position": [1,1,1],
                   "rotation": [0,0,0], "scale": [1,1,1], "color": None,
                   "normal_mode": "flat", "visible": True}]}
m2 = S.migrate(v1)
check("v1 迁移到 v6", m2["version"] == S.SCENE_VERSION)
check("v1 补 lights 空数组", m2["lights"] == [])
check("v1 补 materials 空数组", m2["materials"] == [])
check("v1 补 parent_id/prefab_ref", m2["objects"][0]["parent_id"] is None
      and m2["objects"][0]["prefab_ref"] is None)
check("v1 id 保留", m2["objects"][0]["id"] == "obj_0001")
# 缺 id 的 v1 也能迁
v1b = {"version": 1, "objects": [{"name": "无id"}]}
m2b = S.migrate(v1b)
check("v1 缺 id -> 生成", bool(m2b["objects"][0].get("id")))

# --- v3 -> v4 迁移: 单 "script" 字段 -> "scripts" 数组 (M25) ---
v3 = {"version": 3, "lights": [], "objects": [
    {"id": "o1", "name": "旧", "type": "cube", "params": {"size": 1.0},
     "position": [0,0,0], "rotation": [0,0,0], "scale": [1,1,1],
     "color": None, "normal_mode": "flat", "visible": True,
     "script": {"id": "rotate", "vars": {"sx": 30.0}}}]}
m3 = S.migrate(v3)
check("v3 迁移到 v6", m3["version"] == S.SCENE_VERSION)
check("v3 script -> scripts 数组", m3["objects"][0]["scripts"] ==
      [{"id": "rotate", "vars": {"sx": 30.0}}])
check("v3 迁移后 script 键移除", "script" not in m3["objects"][0])

# --- v4 -> v5 迁移 (M23): 无 material_id 的对象加载时自建材质 ---
v4 = {"version": 4, "materials": [], "lights": [], "objects": [
    {"id": "o1", "name": "旧", "type": "cube", "params": {"size": 1.0},
     "position": [0,0,0], "rotation": [0,0,0], "scale": [1,1,1],
     "color": "#112233", "normal_mode": "flat", "saturation": 1.2,
     "visible": True, "scripts": []}]}
m4 = S.migrate(v4)
check("v4 迁移到 v6", m4["version"] == S.SCENE_VERSION)
check("v4 迁移补 materials 数组", m4["materials"] == [])
eng5 = E.GLEngine.__new__(E.GLEngine); eng5.models = []; eng5.materials = []
eng5.lights = []; eng5.cameras = []; eng5.active_camera = None; eng5.current_model_index = 0
S.scene_from_dict(eng5, m4)
check("v4 旧对象加载 -> 自建材质进库", len(eng5.materials) == 1
      and eng5.models[0].renderer.material is eng5.materials[0]
      and eng5.models[0].color == "#112233"
      and abs(eng5.models[0].saturation - 1.2) < 1e-9)

# --- M23 共享材质 round-trip: 两物体引用同一材质, 改一个全变 ---
shared = eng.add_material(color="#FF8800", saturation=1.3, name="共享橙")
B.renderer.material = shared
C.renderer.material = shared
d3 = S.scene_to_dict(eng)
ids = {m.guid: m for m in [A, B, C, D]}
check("材质库含 5 个材质 (A/B/C/D 自建 + 共享橙; 换材质不清库)", len(d3["materials"]) == 5)
check("B/C 的 material_id 指向共享橙", d3["objects"][1]["material_id"] == shared.guid
      and d3["objects"][2]["material_id"] == shared.guid)
check("A 用独立材质", d3["objects"][0]["material_id"] != shared.guid
      and d3["objects"][0]["material_id"] == A.renderer.material.guid)
eng6 = E.GLEngine.__new__(E.GLEngine); eng6.models = []; eng6.materials = []
eng6.lights = []; eng6.cameras = []; eng6.active_camera = None; eng6.current_model_index = 0
S.scene_from_dict(eng6, d3)
g6 = {m.guid: m for m in eng6.models}
check("加载后 B/C 共享同一材质对象", g6[B.guid].renderer.material is g6[C.guid].renderer.material)
# 改共享材质 -> 两个物体都变 (资产语义)
g6[B.guid].renderer.material.color = "#0000FF"
check("改共享材质 -> B/C 一起变", g6[B.guid].color == "#0000FF"
      and g6[C.guid].color == "#0000FF")
check("加载后 A 用独立材质", g6[A.guid].renderer.material is not g6[B.guid].renderer.material)

# --- M28 碰撞体 round-trip: shape/enabled 序列化 + 回读 ---
B.collider.shape = 'sphere'      # 立方体B 改球体碰撞体 (演示覆盖)
C.collider.enabled = False       # 平C 关碰撞 (纯装饰)
d4 = S.scene_to_dict(eng)
def col_of(guid_):
    for o in d4["objects"]:
        if o["id"] == guid_:
            return o.get("collider")
# B1 (2026-08-30): _emit collider 另有 friction/restitution/rolling_friction
# 键 (材质三件套), 断言改为字段级 (旧"整 dict 相等"契约不再适用)
cB, cC = col_of(B.guid), col_of(C.guid)
check("collider 序列化 (shape/enabled + B1 材质三键默认)",
      cB['shape'] == 'sphere' and cB['enabled'] is True
      and cC['shape'] == 'box' and cC['enabled'] is False
      and cB.get('friction') == 0.5 and cB.get('restitution') == 0.0
      and cB.get('rolling_friction') == 0.1, str((cB, cC)))
eng7 = E.GLEngine.__new__(E.GLEngine); eng7.models = []; eng7.materials = []
eng7.lights = []; eng7.cameras = []; eng7.active_camera = None; eng7.current_model_index = 0
S.scene_from_dict(eng7, d4)
g7 = {m.guid: m for m in eng7.models}
check("collider 回读 (覆盖/禁用)", g7[B.guid].collider.shape == 'sphere'
      and g7[C.guid].collider.shape == 'box' and not g7[C.guid].collider.enabled)
check("默认碰撞体按类型派生", g7[A.guid].collider.shape == 'sphere'   # A=球
      and g7[A.guid].collider.enabled and g7[D.guid].collider.shape == 'box')

# --- 容错加载: 未知类型 -> 立方体 ---
bad = {"version": 2, "objects": [{"id": "x1", "type": "ufo", "params": {},
                                  "name": "外星", "position": [0,0,0],
                                  "rotation": [0,0,0], "scale": [1,1,1],
                                  "color": None, "normal_mode": "flat",
                                  "visible": True}]}
eng3 = E.GLEngine.__new__(E.GLEngine); eng3.models = []; eng3.materials = []
eng3.lights = []; eng3.cameras = []; eng3.active_camera = None
eng3.current_model_index = 0
S.scene_from_dict(eng3, bad)
check("未知类型兜底立方体", len(eng3.models) == 1
      and eng3.models[0].mesh is not None)

# --- Prefab: 保存子树 -> 实例化两次 (独立 GUID + offset) ---
pf = S.prefab_to_dict(A)                      # A 及其子树 B,C
check("prefab 含 3 对象", len(pf["objects"]) == 3)
check("prefab 根 id = A.guid", pf["objects"][0]["id"] == A.guid)
pfile = os.path.join(r"C:\Users\<USER>\.claude\jobs\6fa5b18c\tmp", "test.prefab")
S.save_prefab(pfile, A)
pdata = S.load_prefab(pfile)
inst1 = S.instantiate_prefab(eng, pdata, offset=(0, 3, 0))
inst2 = S.instantiate_prefab(eng, pdata, offset=(0, 6, 0))
check("实例化 3+3 = 6 新对象", len(inst1) == 3 and len(inst2) == 3)
check("根加 offset", abs(inst1[0].position.y - 3.0) < 1e-9
      and abs(inst2[0].position.y - 6.0) < 1e-9)
# 2026-08-16: 模板 C 局部已按保世界换算为 -1 -> 实例也 -1 (相对位置/世界位置保留)
check("子树相对位置不变 (挂父保世界)", abs(inst1[2].position.x + 1.0) < 1e-9
      and abs(inst2[1].position.x - 2.0) < 1e-9)
g1 = {m.guid for m in inst1}; g2 = {m.guid for m in inst2}
check("实例 GUID 不与模板冲突", not ({A.guid, B.guid, C.guid} & (g1 | g2)))
check("实例间 GUID 互不冲突", not (g1 & g2))
check("实例挂 prefab_ref", inst1[0].prefab_ref == pf["prefab"]["guid"]
      and inst2[1].prefab_ref == pf["prefab"]["guid"])
check("Prefab 实例继承脚本 (M27)", inst1[0].script_id == "rotate"
      and inst1[0].script_vars == {'sx': 10.0, 'sy': 20.0})
check("实例父链完整", inst1[1].parent is inst1[0] and inst1[2].parent is inst1[1]
      and inst1[0].parent is None)
check("原场景未被动", eng.models[0] is A and len(eng.models) == 10)

# ===== 坏场景文件容错 (安全加固 2026-08-20: sceneio._f3/_f1) =====
print()
bad_obj = {"version": 10, "objects": [
    {"id": "x1", "name": "坏pos", "type": "cube", "position": "oops",
     "rotation": [1, 2], "scale": None},
    {"id": "x2", "name": "正常", "type": "cube", "position": [0, 0, 0]},
]}
try:
    ms = S.scene_from_dict(eng, bad_obj)
    check("坏 position/rotation/scale 字段不崩且用默认值",
          len(ms) == 2 and ms[0].position == E.Point3D(0, 0, 0)
          and tuple(ms[0].scale) == (1.0, 1.0, 1.0))
except Exception as e:
    check("坏 position/rotation/scale 字段不崩", False, repr(e))

bad_light = {"version": 10, "objects": [], "lights": [
    {"kind": "point", "position": "bad", "intensity": "abc", "color": [1, 2]},
]}
try:
    S.scene_from_dict(eng, bad_light)
    check("坏光源字段不崩 (默认位置/强度/颜色)", True)
except Exception as e:
    check("坏光源字段不崩", False, repr(e))

bad_cam = {"version": 10, "objects": [], "cameras": [
    {"position": {"x": 1}, "yaw": "bad", "fov": None},
]}
try:
    S.scene_from_dict(eng, bad_cam)
    check("坏摄像机字段不崩 (默认位置/朝向/FOV)", True)
except Exception as e:
    check("坏摄像机字段不崩", False, repr(e))

co = {}
S.scene_from_dict(eng, {"version": 10, "camera": {"target": "bad", "distance": "x"}},
                  camera_out=co)
check("坏轨道相机字段容错", co['target'] == (0, 0, 0) and co['distance'] == 10.0)

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
