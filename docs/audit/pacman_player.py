# -*- coding: utf-8 -*-
"""pacman_player.py — 3D 吃豆人玩家（MCP 实机演示脚本）

WASD 移动（世界轴）+ 靠近豆子自动吃掉并计分。
豆子 = 名字以「豆子」开头的物体；吃掉后隐藏。
"""
import math

from engine import Point3D
from scripts import Script, register


@register
class PacmanPlayerScript(Script):
    script_id = "pacman_player"
    name = "吃豆人玩家"
    params = (("speed", "速度", 4.0, 0.0, 20.0, "%.1f"),
              ("eat_r", "吃豆半径", 0.5, 0.1, 2.0, "%.2f"))

    def on_start(self):
        self.score = 0
        self.total = 0
        try:
            self.total = sum(1 for m in self.engine.models
                            if (getattr(m, "name", "") or "").startswith("豆子"))
        except Exception:
            self.total = 0
        print("[吃豆人] 开始: 共 %d 颗豆子" % self.total)

    def update(self, dt):
        e = self.engine
        a = e.get_action
        dx = (1 if a("向右") else 0) - (1 if a("向左") else 0)
        dz = (1 if a("向前") else 0) - (1 if a("向后") else 0)
        if dx or dz:
            s = self.vals["speed"] * dt
            e.move_with_collision(self.obj, dx * s, 0.0, dz * s)
        p = e.world_position(self.obj)
        r2 = float(self.vals["eat_r"]) ** 2
        for m in list(e.models):
            if not (getattr(m, "name", "") or "").startswith("豆子"):
                continue
            if not getattr(m, "visible", True):
                continue
            q = e.world_position(m)
            if (p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2 <= r2:
                m.visible = False
                self.score += 1
                if self.score % 5 == 0 or self.score == self.total:
                    print("[吃豆人] 得分 %d / %d" % (self.score, self.total))
