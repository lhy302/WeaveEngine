# -*- coding: utf-8 -*-
"""pacman_ghost.py — 2D 吃豆人幽灵：沿走廊网格移动（不再绕圈）。

约定: 墙名 墙_<x>_<z>，x/z 为整数世界格坐标；幽灵在格心之间直线移动，
到格心后从"可通行且非反向"的邻居里随机选方向。
"""
import math
import random

from engine import Point3D
from scripts import Script, register


@register
class PacmanGhostScript(Script):
    script_id = "pacman_ghost"
    name = "吃豆人幽灵"
    params = (("speed", "速度", 4.0, 0.5, 8.0, "%.1f"),
              ("turn_bias", "转向概率", 0.25, 0.0, 1.0, "%.2f"))

    def on_start(self):
        self._walls = set()
        for m in self.engine.models:
            n = getattr(m, "name", "") or ""
            if not n.startswith("墙_"):
                continue
            parts = n.split("_")
            if len(parts) >= 3:
                try:
                    self._walls.add((int(parts[1]), int(parts[2])))
                except ValueError:
                    pass
        p = self.engine.world_position(self.obj)
        self._cx, self._cz = int(round(p.x)), int(round(p.z))
        self._tx, self._tz = self._cx, self._cz
        self._dir = None
        self._choose_dir()

    def _open(self, x, z):
        return (x, z) not in self._walls

    def _choose_dir(self):
        cands = []
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, nz = self._cx + dx, self._cz + dz
            if not self._open(nx, nz):
                continue
            if self._dir is not None and (dx, dz) == (-self._dir[0], -self._dir[1]):
                continue
            cands.append((dx, dz))
        if not cands:
            if self._dir is not None:
                cands = [(-self._dir[0], -self._dir[1])]
            else:
                cands = [(1, 0)]
        if self._dir is not None and len(cands) > 1 and random.random() > self.vals["turn_bias"]:
            keep = [d for d in cands if d == self._dir]
            if keep:
                cands = keep
        self._dir = random.choice(cands)
        self._tx = self._cx + self._dir[0]
        self._tz = self._cz + self._dir[1]

    def update(self, dt):
        e = self.engine
        p = e.world_position(self.obj)
        tx, tz = float(self._tx), float(self._tz)
        dx, dz = tx - p.x, tz - p.z
        dist = math.hypot(dx, dz)
        step = float(self.vals["speed"]) * dt
        if dist <= step or dist < 1e-6:
            self.obj.position = Point3D(tx, p.y, tz)
            self._cx, self._cz = self._tx, self._tz
            self._choose_dir()
        else:
            k = step / dist
            self.obj.position = Point3D(p.x + dx * k, p.y, p.z + dz * k)
