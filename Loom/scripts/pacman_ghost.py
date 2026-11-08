# -*- coding: utf-8 -*-
"""pacman_ghost.py — 2D 吃豆人幽灵：走廊网格移动 + 同伴防重叠。

约定: 墙名 墙_<x>_<z>；幽灵在格心间直线移动，到格心后从可通行且非反向的
邻居里选方向。发现与同伴距离过近时立刻掉头，并有 0.1s 冷却防抖动。
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
              ("turn_bias", "转向概率", 0.25, 0.0, 1.0, "%.2f"),
              ("avoid_r", "同伴间距", 0.8, 0.2, 3.0, "%.2f"),
              ("avoid_cd", "掉头冷却", 0.1, 0.0, 2.0, "%.2f"))

    def on_start(self):
        self._walls = set()
        _bad_wall_names = 0
        for m in self.engine.models:
            n = getattr(m, "name", "") or ""
            if not n.startswith("墙_"):
                continue
            parts = n.split("_")
            _ok_name = False
            if len(parts) >= 3:
                try:
                    self._walls.add((int(parts[1]), int(parts[2])))
                    _ok_name = True
                except ValueError:
                    _ok_name = False
            if not _ok_name:
                _bad_wall_names += 1
        # 2026-11-08 beta3 scan_06 P-06-07: 墙名解析失败过去是静默 pass
        # (该墙不生效 -> 幽灵可走进去). 改为一次性告警.
        if _bad_wall_names:
            print("[幽灵] 墙名不合规, 已忽略 %d 个 (需要 墙_<整数x>_<整数z>)" % _bad_wall_names)
        p = self.engine.world_position(self.obj)
        self._cx, self._cz = int(round(p.x)), int(round(p.z))
        self._tx, self._tz = self._cx, self._cz
        self._dir = None
        self._avoid_cd = 0.0
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

    # 2026-11-08 beta3 scan_06 P-06-05: 距离平方 <= 该值 (距离 <= 0.01) 视为"完全同格".
    # 这种位形下两只幽灵若同向, 双方一起掉头 = 共同位移 -> 相对位形不变,
    # 会永远重合且每个 avoid_cd 抖一次 (实测 3 秒 26 次同步翻转, 距离恒 0).
    _STACK_EPS2 = 1e-4

    def _model_index(self, obj):
        """物体在 engine.models 里的下标 (只用于"同格时谁让位"的稳定仲裁)."""
        try:
            for i, m in enumerate(self.engine.models):
                if m is obj:
                    return i
        except Exception:
            pass
        return None

    def _avoid(self, dt):
        """同伴防重叠: 同伴挡在**前方**且靠太近时掉头 (带冷却, 防抖)。

        2026-11-08 beta3 scan_06 P-06-05 修复"长期完全重合 + 同步抖动":
          · 旧规则只看距离, 谁靠得近谁就掉头 —— 两只同向贴在一起时**双方一起
            掉头**, 相对位形不变 => 永远重合、每 avoid_cd 同步抖一次
            (实测 3 秒 26 次翻转、距离恒 0); 掉头后互相靠近再一起掉头的 ping-pong
            也来自这里.
          · 新规则加"方向判据": 只有当同伴落在我**前方** (与我当前方向的点积 > 0)
            时才由我让位; 同伴在我身后时由它让位, 我不掉头 => 追尾/擦身不再双掉头.
          · 距离≈0 (完全同格) 时"前后"无定义, 改用**序号仲裁**: 只有 models 下标
            大的那只掉头, 小的保持原方向. 小序号那只本帧完全不改状态, 所以结果与
            update 调用顺序无关 (确定性)."""
        self._avoid_cd = max(0.0, self._avoid_cd - dt)
        if self._avoid_cd > 0.0 or not self._dir:
            return
        p = self.engine.world_position(self.obj)
        lim = float(self.vals["avoid_r"]) ** 2
        ddx, ddz = self._dir
        for g in self.engine.models:
            if g is self.obj:
                continue
            if not (getattr(g, "name", "") or "").startswith("幽灵"):
                continue
            gp = self.engine.world_position(g)
            ex, ez = gp.x - p.x, gp.z - p.z
            d2 = ex * ex + ez * ez
            if d2 >= lim:
                continue
            if d2 <= self._STACK_EPS2:
                _mi = self._model_index(self.obj)
                _gi = self._model_index(g)
                if _mi is not None and _gi is not None and _mi < _gi:
                    continue          # 同格: 序号小者不让位
            elif (ex * ddx + ez * ddz) <= 0.0:
                continue              # 同伴在我身后: 该由它让位, 我不掉头
            back = (self._cx - self._dir[0], self._cz - self._dir[1])
            self._dir = (-self._dir[0], -self._dir[1])
            if self._open(*back):
                self._tx, self._tz = back
            else:
                self._tx, self._tz = self._cx, self._cz
            self._avoid_cd = float(self.vals["avoid_cd"])
            return

    def update(self, dt):
        e = self.engine
        self._avoid(dt)
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
