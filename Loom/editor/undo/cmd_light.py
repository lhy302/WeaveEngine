# -*- coding: utf-8 -*-
"""
灯光域撤销命令（原 Loom/undo.py 光源快照 (M21) 段 + 光源命令类；
目录重构 B4 批按域拆分，逐行未动）。

成员: light_snapshot / apply_light_snapshot / LightStateCommand /
AddLightCommand / DeleteLightCommand。
"""
from engine import Point3D

from editor.undo.registry import Command


# ---------------- 光源快照 (M21) ----------------

def light_snapshot(l):
    """光源可撤销字段 -> dict (与 apply_light_snapshot 成对; M29 加 mode/shape/size/shadow;
    M30 加平行光方向 3 角度 azimuth/elevation/roll)"""
    return {
        'kind': l.kind,
        'position': (l.position.x, l.position.y, l.position.z),
        'direction': (l.direction.x, l.direction.y, l.direction.z),
        'color': tuple(l.color),
        'intensity': l.intensity,
        'name': l.name,
        'mode': l.mode,
        'shape': l.shape,
        'size': l.size,
        'shadow': l.shadow,
        'range': getattr(l, 'range', 10.0),   # 2026-11-07 Q5=A: 点光范围也须可撤销
        'azimuth': l.azimuth,
        'elevation': l.elevation,
        'roll': l.roll,
        # 2026-10-19 第1档序9 聚光灯: 内外锥角（旧快照无此键 -> apply 用默认值）
        'spot_inner_angle': getattr(l, 'spot_inner_angle', 30.0),
        'spot_outer_angle': getattr(l, 'spot_outer_angle', 60.0),
    }

def apply_light_snapshot(l, snap):
    """把快照写回光源 (undo/redo 共用)"""
    l.kind = snap['kind']
    l.position = Point3D(*snap['position'])
    l.color = tuple(snap['color'])
    l.intensity = snap['intensity']
    l.name = snap['name']
    l.mode = snap.get('mode', 'full')
    l.shape = snap.get('shape', 'circle')
    l.size = snap.get('size', 5.0)
    l.shadow = snap.get('shadow', True)
    if 'range' in snap:                    # 2026-11-07: 点光范围 (旧快照跳过)
        l.range = snap['range']
    # 2026-10-19 第1档序9 聚光灯: 内外锥角（旧快照无此键 -> 保留原值 / 默认 30/60）
    if 'spot_inner_angle' in snap:
        l.spot_inner_angle = snap['spot_inner_angle']
    if 'spot_outer_angle' in snap:
        l.spot_outer_angle = snap['spot_outer_angle']
    if 'azimuth' in snap:
        # M30: 平行光方向 3 角度 (直接写角度, 保留 roll)
        l.azimuth = snap['azimuth']
        l.elevation = snap['elevation']
        l.roll = snap.get('roll', 0.0)
    else:
        l.direction = Point3D(*snap['direction'])   # 旧快照回退: 向量反算角度

class LightStateCommand(Command):
    """光源属性改值: before/after 是 light_snapshot (检查器/gizmo 拖光源)."""

    def __init__(self, label, engine, light, before, after):
        self.label = label
        self.engine = engine
        self.light = light
        self.before = before
        self.after = after

    def do(self):
        apply_light_snapshot(self.light, self.after)

    def undo(self):
        apply_light_snapshot(self.light, self.before)

class AddLightCommand(Command):
    """添加光源. do() 首次创建, 撤销移除, 重做重新入列表 (光源无 GPU 资源)."""

    def __init__(self, label, engine, kind, position=None, direction=None,
                 color=(1.0, 1.0, 1.0), intensity=1.0, name=None):
        self.label = label
        self.engine = engine
        self.kind = kind
        self.args = (kind, position, direction, color, intensity, name)
        self.light = None

    def do(self):
        if self.light is None:
            self.light = self.engine.add_light(*self.args)
        else:
            self.engine.lights.append(self.light)
        return self.light

    def undo(self):
        self.engine.remove_light(self.light)

class DeleteLightCommand(Command):
    """删除光源. 光源无 GPU 资源, 撤销直接把对象引用插回原位 (与 DeleteObjectCommand 同风格)."""

    def __init__(self, label, engine, light):
        self.label = label
        self.engine = engine
        self.light = light
        self.index = engine.lights.index(light)

    def do(self):
        self.engine.remove_light(self.light)

    def undo(self):
        if self.light not in self.engine.lights:
            self.engine.lights.insert(min(self.index, len(self.engine.lights)), self.light)
