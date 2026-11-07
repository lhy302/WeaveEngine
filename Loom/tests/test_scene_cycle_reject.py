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

"""sceneio 父链成环: 加载拒绝 + 保存前拒绝 (不静默丢对象)."""
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

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

# 1) 加载: A<->B 成环 -> 拒绝, 且引擎旧状态不被破坏
cyc = {"version": 10, "objects": [
    {"id": "a", "parent_id": "b", "type": "cube", "position": [0, 0, 0]},
    {"id": "b", "parent_id": "a", "type": "cube", "position": [0, 0, 0]},
]}
e = new_engine()
raised = False
try:
    S.scene_from_dict(e, cyc)
except S.SceneCycleError:
    raised = True
check("加载父链成环 -> SceneCycleError", raised)
check("拒绝加载时引擎旧场景未被破坏", e.models == [] and e.materials == [])

# 2) 自环也算成环
selfcyc = {"version": 10, "objects": [
    {"id": "x", "parent_id": "x", "type": "cube", "position": [0, 0, 0]},
]}
e = new_engine()
raised = False
try:
    S.scene_from_dict(e, selfcyc)
except S.SceneCycleError:
    raised = True
check("自环 parent_id=x -> 拒绝", raised)

# 3) 保存: 运行时父链成环 -> 拒绝序列化 (否则 DFS 静默丢整棵)
e = new_engine()
a = e.add_model(create_cube(1.0), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name="A")
b = e.add_model(create_cube(1.0), E.Point3D(1, 0, 0), E.Point3D(0, 0, 0), name="B")
# 2026-11-07: GameObject.parent 已加直写成环保护 (拒绝并抛 ValueError), 故这里
# 用 TransformComponent 层直写构造"已损坏的父链"(模拟旧存档/旁路写入),
# 继续验证 sceneio 保存前防御仍能拒绝。
a.transform.parent = b
b.transform.parent = a
a.children.append(b)
b.children.append(a)
raised = False
try:
    S.scene_to_dict(e)
except S.SceneCycleError:
    raised = True
check("保存父链成环 -> SceneCycleError", raised)

# 4) 正常父链仍可加载/保存 (不误伤)
good = {"version": 10, "objects": [
    {"id": "root", "parent_id": None, "type": "cube", "position": [0, 0, 0]},
    {"id": "child", "parent_id": "root", "type": "cube", "position": [1, 0, 0]},
]}
e = new_engine()
S.scene_from_dict(e, good)
check("正常父链可加载", len(e.models) == 2
      and e.models[1].parent is e.models[0])
d = S.scene_to_dict(e)
check("正常父链可保存", len(d["objects"]) == 2)

# 5) Prefab 实例化也拒绝成环模板
pdata = {"prefab": {"guid": "p"}, "objects": [
    {"id": "a", "parent_id": "b", "type": "cube", "position": [0, 0, 0]},
    {"id": "b", "parent_id": "a", "type": "cube", "position": [0, 0, 0]},
]}
e = new_engine()
raised = False
try:
    S.instantiate_prefab(e, pdata)
except S.SceneCycleError:
    raised = True
check("Prefab 父链成环 -> 拒绝实例化", raised and e.models == [])

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
