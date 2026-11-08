# -*- coding: utf-8 -*-
"""pacman_player.py — 2D 吃豆人玩家（网格移动 + 吃豆 + 通关规则）。

WASD 选方向，角色在格心之间移动（目标格是墙就不走）。
吃到豆子计分；撞到幽灵回出生点；吃完所有豆子 => 通关：暂停逻辑 + 弹出 UI，
UI 按钮回调 on_restart / on_quit。
"""
import math

from engine import Point3D
from scripts import Script, register


@register
class PacmanPlayerScript(Script):
    script_id = "pacman_player"
    name = "吃豆人玩家"
    params = (("speed", "速度", 4.0, 0.5, 15.0, "%.1f"),
              ("eat_r", "吃豆半径", 0.55, 0.1, 2.0, "%.2f"),
              ("invuln", "复活无敌秒", 1.5, 0.0, 5.0, "%.2f"))

    def on_start(self):
        self.score = 0
        self.caught = 0
        self.won = False
        self._invuln = 0.0        # 复活无敌剩余秒数 (经典吃豆人: 复活不被秒)
        # 只统计"可见"的豆子 (隐藏的不算目标, 便于分关卡/调试)
        # 2026-11-08 beta3 scan_06 P-06-06: 把"本局目标豆"记成列表 —— on_restart
        # 只能恢复这些, 不能把设计上隐藏的豆点亮 (否则 score 上限与 total 脱节).
        self._beans = [m for m in self.engine.models
                       if (getattr(m, "name", "") or "").startswith("豆子")
                       and getattr(m, "visible", True)]
        self.total = len(self._beans)
        self._walls = set()
        _bad_wall_names = 0
        for m in self.engine.models:
            n = getattr(m, "name", "") or ""
            if n.startswith("墙_"):
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
        # 2026-11-08 beta3 scan_06 P-06-07: 关卡几何靠"墙_<整数x>_<整数z>"命名约定,
        # 解析失败过去是静默 pass (该墙不生效 -> 玩家能走进墙里). 改为一次性告警.
        if _bad_wall_names:
            print("[吃豆人] 墙名不合规, 已忽略 %d 个 (需要 墙_<整数x>_<整数z>)" % _bad_wall_names)
        p = self.engine.world_position(self.obj)
        self._cx, self._cz = int(round(p.x)), int(round(p.z))
        self._tx, self._tz = self._cx, self._cz
        self._y = p.y
        self._spawn = (float(self._cx), float(self._cz))
        self._panel = self._find_ui("通关面板")
        self._set_panel(False)
        print("[吃豆人] 开始: 共 %d 颗豆子" % self.total)

    # ---------- UI ----------
    def _find_ui(self, name):
        try:
            canvases = getattr(self.engine.ui, "canvases", []) or []
        except Exception:
            return None
        for c in canvases:
            try:
                e = c.root.find(name)
            except Exception:
                e = None
            if e is not None:
                return e
        return None

    def _set_panel(self, visible):
        if self._panel is not None:
            self._panel.visible = bool(visible)

    # ---------- 规则 ----------
    def _open(self, x, z):
        return (x, z) not in self._walls

    def _win(self):
        self.won = True
        self._set_panel(True)
        try:
            if hasattr(self.engine, "set_logic_paused"):
                self.engine.set_logic_paused(True)
            else:
                self.engine._logic_paused = True
        except Exception:
            pass
        print("[吃豆人] 通关! 得分 %d" % self.score)

    def on_restart(self, *a):
        """UI 按钮: 新开一局"""
        # 2026-11-08 beta3 scan_06 P-06-06: 只恢复 on_start 时统计到的目标豆,
        # 设计上隐藏的豆保持隐藏 (与 total 的口径一致).
        for m in getattr(self, "_beans", ()):
            m.visible = True
        self.score = 0
        self.caught = 0
        self.won = False
        self.obj.position = Point3D(self._spawn[0], self._y, self._spawn[1])
        self._cx, self._cz = int(self._spawn[0]), int(self._spawn[1])
        self._tx, self._tz = self._cx, self._cz
        self._set_panel(False)
        try:
            if hasattr(self.engine, "set_logic_paused"):
                self.engine.set_logic_paused(False)
            else:
                self.engine._logic_paused = False
        except Exception:
            pass
        print("[吃豆人] 新开一局")

    def on_quit(self, *a):
        """UI 按钮: 退出游戏 (退出播放, 回到编辑态)"""
        self._set_panel(False)
        try:
            if hasattr(self.engine, "set_logic_paused"):
                self.engine.set_logic_paused(False)
            if hasattr(self.engine, "request_game_exit"):
                self.engine.request_game_exit()
            else:
                self.engine._request_exit_play = True
        except Exception:
            pass
        print("[吃豆人] 退出游戏")

    def update(self, dt):
        if self.won:
            return
        if self._invuln > 0.0:
            self._invuln = max(0.0, self._invuln - float(dt))
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
        # 被幽灵抓住 (无敌期内跳过)
        p = e.world_position(self.obj)
        for g in ([] if self._invuln > 0.0 else list(e.models)):
            if not (getattr(g, "name", "") or "").startswith("幽灵"):
                continue
            gp = e.world_position(g)
            if (p.x - gp.x) ** 2 + (p.z - gp.z) ** 2 <= 0.55 ** 2:
                self.caught += 1
                # 2026-11-08 beta3 scan_06 P-06-14: 读参数 invuln (默认 1.5s).
                # 之前硬编码 1.5, 导致场景 vars / 编辑器面板调这个参数完全无效.
                self._invuln = max(0.0, float(self.vals.get("invuln", 1.5)))
                self.obj.position = Point3D(self._spawn[0], self._y, self._spawn[1])
                self._cx, self._cz = int(self._spawn[0]), int(self._spawn[1])
                self._tx, self._tz = self._cx, self._cz
                print("[吃豆人] 被幽灵抓住! 回到出生点 (第 %d 次)" % self.caught)
                break
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
        if self.total and self.score >= self.total:
            self._win()
