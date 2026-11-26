# -*- coding: utf-8 -*-
"""eai.target — 命令目标寻址（共享前置）

我负责：按 name/guid 找物体·光源·相机 (_find_all / _find / _find_model_by_name)。
我不负责：歧义裁决与提交（见 commit.py）；也不负责具体命令。
"""

def _find_all(ed, name_or_id):
    """按 name 或 guid 找出目标 [(kind, obj, index)...].

    2026-10-19 P0-3: 支持 GUID 精确寻址（Agent 用稳定 ID 定位，重名也不误中）。
    匹配优先级：
      1) guid 精确匹配（若 name_or_id 看起来像 guid 且命中）
      2) name 匹配（可能有多个同名，返回全部供 _resolve 判断歧义）
    场景里重名是允许的 (复制/Prefab 实例常见)，命令层必须知道有没有歧义。
    """
    if not name_or_id:
        return []
    # 第一优先级：guid 精确匹配
    guid_hits = []
    for kind, seq in (('model', ed.models), ('light', ed.lights),
                      ('camera', ed.cameras)):
        for i, o in enumerate(seq):
            g = getattr(o, 'guid', None)
            if g and g == name_or_id:
                guid_hits.append((kind, o, i))
    if guid_hits:
        return guid_hits
    # 回退：name 匹配
    hits = []
    for kind, seq in (('model', ed.models), ('light', ed.lights),
                      ('camera', ed.cameras)):
        for i, o in enumerate(seq):
            if o.name == name_or_id:
                hits.append((kind, o, i))
    return hits


def _find(ed, name):
    """按名字找单个目标, 返回 (kind, obj, index); 找不到 (None, None, -1).
    重名时返回第一个 —— 需要区分歧义的调用点用 _find_all/_resolve."""
    hits = _find_all(ed, name)
    return hits[0] if hits else (None, None, -1)


def _find_model_by_name(ed, name):
    for m in getattr(ed, 'models', []) or []:
        if m.name == name:
            return m
    return None
