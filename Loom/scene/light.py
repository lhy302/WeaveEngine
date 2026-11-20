# -*- coding: utf-8 -*-
"""scene/light.py — 场景**光源**序列化（B2 自 sceneio.py 拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）: _emit_light / _apply_lights（M21/M29/M30，聚光灯第1档序9）。
"""
from scene.object import _f1, _f3




# ---------------- 光源 (M21) ----------------

def _emit_light(l):
    """LightState -> dict (M30: 平行光加 3 角度字段; direction 保留为派生兼容旧读者)"""
    return {
        "id": l.guid,
        "name": l.name,
        "kind": l.kind,
        "position": [l.position.x, l.position.y, l.position.z],
        "direction": [l.direction.x, l.direction.y, l.direction.z],
        "azimuth": l.azimuth,      # M30: 平行光 朝向 (度, 0..360)
        "elevation": l.elevation,  # M30: 平行光 俯仰 (度)
        "roll": l.roll,            # M30: 平行光 倾斜 (度, 绕方向线自旋)
        "color": [l.color[0], l.color[1], l.color[2]],
        "intensity": l.intensity,
        "mode": l.mode,          # M29: 'full' 全场景 | 'beam' 光束
        "shape": l.shape,        # M29: 'circle' | 'rect' (beam 截面)
        "size": l.size,          # M29: 光束截面尺寸 (圆=半径/矩形=半边长)
        "shadow": l.shadow,      # M29: 是否投射阴影 (物理遮挡)
        "range": l.range,        # 点光范围 (对齐 Unity Light.range)
        # 2026-10-19 第1档序9 聚光灯: 内外锥角（旧文件无此键 -> 缺省 30/60）
        "spot_inner_angle": getattr(l, 'spot_inner_angle', 30.0),
        "spot_outer_angle": getattr(l, 'spot_outer_angle', 60.0),
    }



def _apply_lights(engine, light_dicts):
    """光源 dict 列表 -> engine.lights (清空重建; 文件 id 覆盖 guid)"""
    engine.lights.clear()
    for d in light_dicts:
        kind = d.get('kind', 'directional')
        # 2026-10-19 第1档序9: 允许 'spot'（旧文件仅 dir/point，非法值降级为 dir）
        if kind not in ('directional', 'point', 'spot'):
            kind = 'directional'
        kwargs = dict(position=_f3(d.get('position'), (0, 5, 0)),
                      direction=_f3(d.get('direction'), (0, -1, 0)),
                      color=_f3(d.get('color'), (1.0, 1.0, 1.0)),
                      intensity=_f1(d.get('intensity'), 1.0),
                      name=d.get('name'),
                      mode=d.get('mode', 'full'),
                      shape=d.get('shape', 'circle'),
                      size=_f1(d.get('size'), 5.0),
                      shadow=d.get('shadow', True),
                      range=_f1(d.get('range'), 10.0),
                      spot_inner_angle=_f1(d.get('spot_inner_angle'), 30.0),
                      spot_outer_angle=_f1(d.get('spot_outer_angle'), 60.0))
        if d.get('azimuth') is not None:   # M30: 优先用 3 角度; 旧文件只有 direction 走反算
            kwargs['azimuth'] = d['azimuth']
            kwargs['elevation'] = d.get('elevation', 0.0)
            kwargs['roll'] = d.get('roll', 0.0)
        l = engine.add_light(kind, **kwargs)
        if d.get('id'):
            l.guid = d['id']
