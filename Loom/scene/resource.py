# -*- coding: utf-8 -*-
"""scene/resource.py — **独立资产文件**（材质/网格，M24 资源浏览器；B2 自 sceneio.py 拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  ASSET_VERSION / material_to_dict / save_material_asset / load_material_asset /
  save_mesh_asset / load_mesh_asset
"""
import json

from scene.asset import generate_guid
from scene.io import save_json_atomic
from scene.material import _emit_material




# ---------------- 资源资产 (M24 资源浏览器面板) ----------------
# 独立资产文件: 材质 -> assets/materials/*.json, 网格 -> assets/meshes/*.json,
# Prefab -> assets/*.prefab (M16). 材质资产文件内容与 _emit_material 同构 (含 guid),
# 供资源浏览器面板列出/点选预览/拖到场景; 跨文件引用统一走 guid.

ASSET_VERSION = 1



def material_to_dict(mat, ctx=None):
    """Material -> 材质资产 dict (与 _emit_material 同构 + version)"""
    return {** _emit_material(mat, ctx), "version": ASSET_VERSION}



def save_material_asset(path, mat):
    """材质落盘为独立资产文件 (assets/materials/*.json). 返回绝对路径."""
    return save_json_atomic(path, material_to_dict(mat))



def load_material_asset(path):
    """读取材质资产文件 -> dict (id/name/color/saturation). 损坏/缺 id 返回 None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get('id'):
        return None
    data.setdefault('name', '材质')
    data.setdefault('color', None)
    data.setdefault('saturation', 1.0)
    return data



def save_mesh_asset(path, primitive, params):
    """网格落盘为独立资产文件 (assets/meshes/*.json): 基元 spec + 资产 guid.
    返回绝对路径."""
    data = {"version": ASSET_VERSION, "id": generate_guid(),
            "type": primitive or 'cube',
            "params": dict(params) if params else {}}
    return save_json_atomic(path, data)



def load_mesh_asset(path):
    """读取网格资产文件 -> dict (type/params/id). 损坏/缺 type 返回 None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get('type'):
        return None
    data.setdefault('params', {})
    return data
