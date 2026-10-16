# -*- coding: utf-8 -*-
"""reset_fall.py — 游戏脚本 (2026-08-22 教学演示: "游戏脚本目录"机制)

放在引擎/玩家运行时 旁 的 scripts/ 目录里, 引擎启动自动加载注册 (@register),
检查器可挂、运行时实例化; 构建器 (build_game.py) 发布时把本目录所有 .py
收集进"游戏包.lsc"混淆打包 —— 玩家文件夹无明文脚本 (Unity 脚本编译进 Build 对齐).

功能: 挂到玩家角色, 跌出世界 (y < resume_y) 自动重置回起点
(确保撞飞/跌落不会卡死丢玩家).
"""
from engine import Point3D
from scripts import Script, register


@register
class ResetFallScript(Script):
    """跌出世界重置: 检测 y 低于阈值 -> 瞬移回出生点 + 速度清零."""
    script_id = 'reset_fall'
    name = '跌出重置'
    params = (('min_y', '阈值Y', -50.0, -500.0, 0.0, '%.0f'),)

    def on_start(self):
        self.spawn = (self.obj.position.x, self.obj.position.y,
                      self.obj.position.z)

    def update(self, dt):
        if self.obj.position.y < self.vals['min_y']:
            self.obj.position = Point3D(*self.spawn)
            rb = getattr(self.obj, 'rigidbody', None)
            if rb is not None:
                rb.velocity = Point3D(0.0, 0.0, 0.0)
