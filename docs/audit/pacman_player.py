# -*- coding: utf-8 -*-
"""pacman_player.py — 2D 吃豆人玩家（网格移动版）。

WASD 选择方向；角色在格心之间移动（与幽灵同一套格子规则），
目标格是墙就不走 —— 不会卡墙、不会穿墙。靠近豆子自动吃掉。
"""
import math

from engine import Point3D
from scripts import Script, register


@register
class PacmanPlayerScript(Script):
    script_id = "pacman_player"
    name = "吃豆人玩家"
    params = (("speed", "速度", 5.0, 0.5, 15.0, "%.1f"),
              ("eat_r", "吃豆半径", 0.55, 0.1, 2.0, "%.2f"))

    def on_start(self):
        self.score = 0
        self.total = sum(1 for m in self.engine.models
                         if (getattr(m, "name", "") or "").startswith("豆子"))
        self._walls = set()
        for m in self.engine.models:
            n = getattr(m, "name", "") or ""
            if n.startswith("墙_"):
                parts = n.split("_")
                if len(parts) >= 3:
                    try:
                        self._walls.add((int(parts[1]), int(parts[2])))
                    except ValueError:
                        pass
        p = self.engine.world_position(self.obj)
        self._cx, self._cz = int(round(p.x)), int(round(p.z))
        self._tx, self._tz = self._cx, self._cz
        self._y = p.y
        print("[吃豆人] 开始: 共 %d 颗豆子" % self.total)

    def _open(self, x, z):
        return (x, z) not in self._walls

    def update(self, dt):
        e = self.engine
        a = e.get_action
        dx = (1 if a("向右") else 0) - (1 if a("向左") else 0)
        dz = (1 if a("向前") else 0) - (1 if a("向后") else 0)
        p = e.world_position(self.obj)
        at_center = (abs(p.x - self._tx) < 1e-3 and abs(p.z - self._tz) < 1e-3)
        if at_center:
            self._cx, self._cz = self._tx, self._tz
            if dx or dz:
                if dx:
                    nx, nz = self._cx + dx, self._cz
                else:
                    nx, nz = self._cx, self._cz + dz
                if self._open(nx, nz):
                    self._tx, self._tz = nx, nz
            else:
                self.obj.position = Point3D(float(self._cx), self._y, float(self._cz))
        # 朝目标格心移动
        p = e.world_position(self.obj)
        tx, tz = float(self._tx), float(self._tz)
        ddx, ddz = tx - p.x, tz - p.z
        dist = math.hypot(ddx, ddz)
        if dist > 1e-6:
            step = float(self.vals["speed"]) * dt
            if step >= dist:
                self.obj.position = Point3D(tx, self._y, tz)
            else:
                self.obj.position = Point3D(p.x + ddx / dist * step, self._y,
                                            p.z + ddz / dist * step)
        # 吃豆
        p = e.world_position(self.obj)
        r2 = float(self.vals["eat_r"]) ** 2
        for m in list(e.models):
            if not (getattr(m, "name", "") or "").startswith("豆子"):
                continue
            if not getattr(m, "visible", True):
                continue
            q = e.world_position(m)
            if (p.x - q.x) ** 2 + (p.z - q.z) ** 2 <= r2:
                m.visible = False
                self.score += 1
                if self.score % 5 == 0 or self.score == self.total:
                    print("[吃豆人] 得分 %d / %d" % (self.score, self.total))
