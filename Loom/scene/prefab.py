# -*- coding: utf-8 -*-
"""scene/prefab.py — **Prefab** 序列化/实例化（M16；B2 自 sceneio.py 拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  PREFAB_VERSION / prefab_to_dict / save_prefab / load_prefab / instantiate_prefab
"""
import json

from core.primitives import Point3D

from scene.asset import generate_guid
from scene.contract import ENGINE_VERSION, gate
from scene.io import save_json_atomic
from scene.object import (_apply_object, _emit_subtree, _link_by_map,
                          _validate_object_graph)




PREFAB_VERSION = 1



# ---------------- Prefab ----------------

def prefab_to_dict(root, ctx=None):
    """子树根 -> prefab 资产 dict (局部对象 id, 根 id = prefab guid)"""
    pguid = root.guid or generate_guid()
    objs = []
    _emit_subtree(root, objs, ctx=ctx)
    return {"version": PREFAB_VERSION,
            # R5-02 P-04: prefab 物体同样带 animator.speed / clip_meta,
            # 旧引擎读新 prefab 会静默丢 (once 变永远循环) —— 与场景同一道闸。
            "min_engine_version": ENGINE_VERSION,
            "prefab": {"guid": pguid, "name": root.name},
            "objects": objs}



def save_prefab(path, root, ctx=None):
    save_json_atomic(path, prefab_to_dict(root, ctx))



def load_prefab(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get('version', 1) < 1:
        data['version'] = 1
    # R5-02 P-04: prefab 与场景共用版本闸门 (旧 prefab 无该字段 -> 不拦)。
    # B7-16: 走契约模块的 gate（唯一实现；prefab 数据不迁移，故不用 prepare）。
    gate(data)
    return data



def instantiate_prefab(engine, data, offset=(0, 0, 0), ctx=None):
    """场景中实例化 prefab: 全部对象重新生成 GUID, 挂 prefab_ref, 根整体平移.
    返回创建的模型列表 (空 prefab 返回 []). ctx: 资产上下文（贴图/材质按 guid 解析）。

    R5-02 P-04: 入口再校验一次版本 —— undo 的 PrefabPlaceCommand 持有已读出的
    data 并在 redo 时重放, 不能只靠 load_prefab 那一处。
    B7-16: 同上，走契约模块的 gate。"""
    gate(data)
    objects = data.get('objects', [])
    if not isinstance(objects, list):
        objects = []
    _validate_object_graph(objects)     # 2026-11-07: Prefab 父链成环拒绝实例化
    pguid = data.get('prefab', {}).get('guid')
    models = []
    old_id_map = {}                       # 模板旧 id -> 新模型
    for obj in objects:
        m, oid = _apply_object(engine, obj, ctx)   # 此刻 m.guid = 模板 id
        old_id_map[oid] = m
        m.guid = generate_guid()          # 实例与模板解耦
        m.prefab_ref = pguid
        models.append(m)
    _link_by_map(objects, models, old_id_map)   # 用模板 id 键建父链
    if models:
        r = models[0]                     # DFS 前序根
        r.position = Point3D(r.position.x + offset[0],
                             r.position.y + offset[1],
                             r.position.z + offset[2])
    return models
