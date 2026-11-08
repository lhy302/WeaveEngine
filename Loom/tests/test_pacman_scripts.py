# -*- coding: utf-8 -*-

"""吃豆人脚本行为回归: invuln 参数生效 / 幽灵防重叠 / 重开只恢复本局豆 / 墙名解析告警.
覆盖 beta3_scan_06 P-06-14 / P-06-05 / P-06-06 / P-06-07(告警部分).

脚本式回归: python tests/test_pacman_scripts.py
"""

import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import sys, os, io, math, random, contextlib, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loom_types import Point3D

LOOM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(fname, modname):
    spec = importlib.util.spec_from_file_location(modname, os.path.join(LOOM, "scripts", fname))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pl_mod = load("pacman_player.py", "reg06_pl")
gh_mod = load("pacman_ghost.py", "reg06_gh")

MAZE = [
    "###########",
    "#.........#",
    "#.###.###.#",
    "#.........#",
    "#.##.#.##.#",
    "#....#....#",
    "#.##.#.##.#",
    "#.........#",
    "#.###.###.#",
    "#.........#",
    "###########",
]
WALLS = set()
for zi, row in enumerate(MAZE):
    for xi, ch in enumerate(row):
        if ch == "#":
            WALLS.add((xi - 5, zi - 5))
BEANS = [(x, z) for x in range(-5, 6) for z in range(-5, 6) if (x, z) not in WALLS]
C_NAMES = {"wall": u"\u5899", "bean": u"\u8c46\u5b50", "ghost": u"\u5e7d\u7075",
           "player": u"\u5403\u8c46\u4eba"}

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


class M:
    def __init__(self, name, pos, visible=True):
        self.name = name
        self.position = Point3D(float(pos[0]), float(pos[1]), float(pos[2]))
        self.visible = visible


class FakeElem:
    def __init__(self):
        self.visible = False


class FakeCanvas:
    def __init__(self):
        self.root = self
        self._e = {u"\u901a\u5173\u9762\u677f": FakeElem()}

    def find(self, name):
        return self._e.get(name)


class Stub:
    def __init__(self, walls=True, beans=None, ghosts=(), wall_names=None):
        self.models = []
        self.ui = type("U", (), {"canvases": [FakeCanvas()]})()
        self.actions = {}
        self.paused = None
        self.exit_requested = False
        if walls:
            for (x, z) in sorted(WALLS):
                spec = (wall_names or {}).get((x, z))
                self.models.append(M(spec or (C_NAMES["wall"] + "_%d_%d" % (x, z)),
                                     (x, 0.3, z)))
        for (x, z) in (BEANS if beans is None else beans):
            self.models.append(M(C_NAMES["bean"] + "_%d_%d" % (x, z), (x, 0.3, z)))
        self.player = M(C_NAMES["player"], (1.0, 0.3, 0.0))
        self.models.append(self.player)
        for i, pos in enumerate(ghosts):
            self.models.append(M(C_NAMES["ghost"] + "%d" % i, (pos[0], 0.3, pos[1])))

    def get_action(self, name):
        return bool(self.actions.get(name, False))

    def world_position(self, m):
        return m.position

    def set_logic_paused(self, p):
        self.paused = bool(p)

    def request_game_exit(self):
        self.exit_requested = True


def mk_player(stub, **vars_):
    inst = pl_mod.PacmanPlayerScript()
    inst.engine = stub
    inst.obj = stub.player
    inst.vals.update(vars_ or {})
    with contextlib.redirect_stdout(io.StringIO()):
        inst.on_start()
    return inst


def mk_ghost(stub, obj):
    inst = gh_mod.PacmanGhostScript()
    inst.engine = stub
    inst.obj = obj
    inst.vals.update({"speed": 4.0, "turn_bias": 0.25, "avoid_r": 0.8, "avoid_cd": 0.1})
    with contextlib.redirect_stdout(io.StringIO()):
        inst.on_start()
    return inst


# =====================================================================
# 一、invuln 参数必须真正生效 (P-06-14)
# =====================================================================
print("=== 一. invuln 参数生效性 ===")


def measure_invuln(want):
    """幽灵压在出生点, 返回(捕获后立即的 _invuln, 下一次被抓的时刻秒)."""
    stub = Stub(ghosts=[(1, 0)])
    inst = mk_player(stub, speed=4.0, eat_r=0.5, invuln=want)
    inst.update(1 / 60.0)                        # 首次被抓
    first = inst._invuln
    dt = 1 / 60.0
    t = 0.0
    prev = inst.caught
    nxt = None
    for _ in range(int(8 / dt)):
        stub.models[0].position = Point3D(stub.player.position.x, 0.3,
                                          stub.player.position.z)
        inst.update(dt)
        t += dt
        if inst.caught != prev:
            nxt = round(t, 4)
            break
    return first, nxt


f15, n15 = measure_invuln(1.5)
f02, n02 = measure_invuln(0.2)
f50, n50 = measure_invuln(5.0)
print("  invuln=1.5 -> _invuln=%.4f 再被抓于 %ss" % (f15, n15))
print("  invuln=0.2 -> _invuln=%.4f 再被抓于 %ss" % (f02, n02))
print("  invuln=5.0 -> _invuln=%.4f 再被抓于 %ss" % (f50, n50))
check("1-1 捕获后无敌时长 = vals['invuln'] (1.5)", abs(f15 - 1.5) < 1e-9, "%.4f" % f15)
check("1-2 invuln=0.2 时无敌更短 (参数真的生效)", f02 is not None and abs(f02 - 0.2) < 1e-9
      and n02 is not None and n02 < 0.5, "invuln=%.4f 再抓=%s" % (f02, n02))
check("1-3 invuln=5.0 时 5s 内不会被再抓 (参数真的生效)", abs(f50 - 5.0) < 1e-9
      and (n50 is None or n50 > 4.9), "invuln=%.4f 再抓=%s" % (f50, n50))

# =====================================================================
# 二、幽灵同格同向不得长期完全重合 (P-06-05)
# =====================================================================
print()
print("=== 二. 幽灵防重叠 (同格同向) ===")
stub2 = Stub(ghosts=[(0, 0), (0, 0)])
ga = mk_ghost(stub2, stub2.models[-2])
gb = mk_ghost(stub2, stub2.models[-1])
random.seed(1)
for g in (ga, gb):
    g._cx, g._cz = 0, 0
    g._dir = (1, 0)
    g._tx, g._tz = 1, 0
    g._avoid_cd = 0.0
    g.obj.position = Point3D(0.0, 0.3, 0.0)
dt = 1 / 60.0
dists = []
flips = 0
prev = (ga._dir, gb._dir)
for _ in range(int(3 / dt)):
    ga.update(dt)
    gb.update(dt)
    dists.append(math.hypot(ga.obj.position.x - gb.obj.position.x,
                            ga.obj.position.z - gb.obj.position.z))
    if (ga._dir, gb._dir) != prev:
        flips += 1
        prev = (ga._dir, gb._dir)
print("  3s: 两两距离 min=%.4f max=%.4f 方向改变次数=%d" % (min(dists), max(dists), flips))
check("2-1 同格同向后 3s 内必然分开 (不再长期完全重合)", max(dists) > 0.5,
      "max=%.4f" % max(dists))
check("2-2 3s 末仍不重合", dists[-1] > 0.5, "末帧距离=%.4f" % dists[-1])

# 2-3 回归护栏: 真实场景 200s 不得穿墙/不得停摆
stub3 = Stub(ghosts=[(-4, -4), (4, -4), (-4, 4)])
gs = [mk_ghost(stub3, stub3.models[-3 + i]) for i in range(3)]
random.seed(17)
inwall = 0
nan = 0
bad_target = 0
for _ in range(int(200 / dt)):
    for g in gs:
        g.update(dt)
    for g in gs:
        p = g.obj.position
        if not all(map(math.isfinite, (p.x, p.y, p.z))):
            nan += 1
        if (int(round(p.x)), int(round(p.z))) in WALLS:
            inwall += 1
        if (g._tx, g._tz) in WALLS:
            bad_target += 1
check("2-3 三只幽灵 200s: 0 帧在墙格", inwall == 0, str(inwall))
check("2-3 三只幽灵 200s: 0 个 NaN 帧", nan == 0, str(nan))
check("2-3 三只幽灵 200s: 目标格始终通路", bad_target == 0, str(bad_target))

# =====================================================================
# 三、on_restart 不得点亮设计时隐藏的豆 (P-06-06)
# =====================================================================
print()
print("=== 三. 重开一局只恢复本局目标豆 ===")
only_last = BEANS[-1]
stub4 = Stub(beans=[only_last])          # 场上只有 1 颗可见豆
for (x, z) in BEANS[:-1]:                # 其余 57 颗是"设计时隐藏"
    stub4.models.append(M(C_NAMES["bean"] + "_%d_%d" % (x, z), (x, 0.3, z), visible=False))
stub4.player.position = Point3D(float(only_last[0]), 0.3, float(only_last[1]))
inst4 = mk_player(stub4, speed=4.0, eat_r=0.5)
print("  on_start: total=%d" % inst4.total)
inst4.update(1 / 60.0)                   # 吃掉那 1 颗 -> 通关
for _ in range(2):
    inst4.update(1 / 60.0)
vis_before = sum(1 for m in stub4.models
                 if m.name.startswith(C_NAMES["bean"]) and m.visible)
inst4.on_restart()
vis_after = sum(1 for m in stub4.models
                if m.name.startswith(C_NAMES["bean"]) and m.visible)
print("  restart 前可见豆=%d, 后=%d (设计时隐藏 57 颗)" % (vis_before, vis_after))
check("3-1 重开后可见豆数量 = on_start 时的目标豆数 (不点亮隐藏豆)",
      vis_after == inst4.total, "vis=%d total=%d" % (vis_after, inst4.total))
check("3-2 重开后那 1 颗目标豆恢复可见", any(m.visible for m in stub4.models
      if m.name == C_NAMES["bean"] + "_%d_%d" % only_last))
check("3-3 57 颗设计时隐藏豆仍然隐藏",
      sum(1 for m in stub4.models if m.name.startswith(C_NAMES["bean"])
          and not m.visible) == len(BEANS) - 1,
      "hidden=%d" % sum(1 for m in stub4.models
                        if m.name.startswith(C_NAMES["bean"]) and not m.visible))

# =====================================================================
# 四、墙名解析失败不得静默 (P-06-07)
# =====================================================================
print()
print("=== 四. 墙名不合规必须告警 (不静默) ===")
# 名字以 墙_ 开头但解析不出 (x,z) 的两种真实崩法: 段数不足 / 坐标不是整数
bad = {(-5, -5): C_NAMES["wall"] + "_1", (-4, -5): C_NAMES["wall"] + "_a_b"}
stub5 = Stub(wall_names=bad)
buf = io.StringIO()
inst5 = pl_mod.PacmanPlayerScript()
inst5.engine = stub5
inst5.obj = stub5.player
inst5.vals.update({"speed": 4.0, "eat_r": 0.5})
with contextlib.redirect_stdout(buf):
    inst5.on_start()
out = buf.getvalue()
print("  on_start 输出片段: %r" % (out.strip().splitlines()[-1] if out.strip() else "<空>"))
check("4-1 玩家脚本: 墙名解析失败会打印告警", ("墙名" in out) or ("ignored" in out.lower())
      or ("忽略" in out), repr(out[-120:]))

stub6 = Stub(wall_names=bad)
buf2 = io.StringIO()
gh = gh_mod.PacmanGhostScript()
gh.engine = stub6
gh.obj = stub6.models[-1] if stub6.models else None
gh.vals.update({"speed": 4.0, "turn_bias": 0.25})
with contextlib.redirect_stdout(buf2):
    gh.on_start()
out2 = buf2.getvalue()
print("  幽灵 on_start 输出片段: %r" % (out2.strip().splitlines()[-1] if out2.strip() else "<空>"))
check("4-2 幽灵脚本: 墙名解析失败会打印告警", ("墙名" in out2) or ("忽略" in out2),
      repr(out2[-120:]))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
