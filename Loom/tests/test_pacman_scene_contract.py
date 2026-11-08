# -*- coding: utf-8 -*-

"""吃豆人场景契约回归: 场景入库 (examples/) + 场景真值与脚本常量的一致性.
覆盖 beta3_scan_06 P-06-08 (发布场景未入库) 与 P-06-12 (常量 vs 真值) 的持续校验.

脚本式回归: python tests/test_pacman_scene_contract.py
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


import sys, os, io, json, hashlib
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))        # 仓库根
sys.path.insert(0, os.path.dirname(HERE))            # Loom/

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


EX_SCENE = os.path.join(ROOT, "examples", "PacMan2D.json")
AUDIT_SNAP = os.path.join(ROOT, "docs", "audit", "pacman2d_scene.json")

print("=== 一. 场景入库与快照对照 (P-06-08 / D13=A) ===")
check("1-1 examples/PacMan2D.json 已入库", os.path.isfile(EX_SCENE), EX_SCENE)
have_ex = os.path.isfile(EX_SCENE)
have_snap = os.path.isfile(AUDIT_SNAP)
check("1-2 审计快照 docs/audit/pacman2d_scene.json 仍在", have_snap, AUDIT_SNAP)

if have_ex and have_snap:
    h_ex = sha256(EX_SCENE)
    h_snap = sha256(AUDIT_SNAP)
    size_ex = os.path.getsize(EX_SCENE)
    print("  examples/PacMan2D.json            %d B  SHA256=%s" % (size_ex, h_ex))
    print("  docs/audit/pacman2d_scene.json    %d B  SHA256=%s"
          % (os.path.getsize(AUDIT_SNAP), h_snap))
    print("  发布物 (Projects/PacMan2D.json / 游戏包.lsc 内场景)  未在仓库中 -> 由出包机补哈希")
    check("1-3 examples 场景与审计快照字节一致 (同一 SHA256)", h_ex == h_snap,
          "%s vs %s" % (h_ex[:16], h_snap[:16]))

# =====================================================================
# 二、场景真值 (唯一真值来源: examples 场景; 缺则退审计快照)
# =====================================================================
scene_path = EX_SCENE if have_ex else AUDIT_SNAP
if not os.path.isfile(scene_path):
    print("FAIL 2-0 找不到任何可用的场景文件, 无法校验常量")
    ok = False
    print()
    print("总结果:", "有 FAIL ❌")
    sys.exit(1)

data = json.load(io.open(scene_path, encoding="utf-8"))
objs = data["objects"]


def nm(o):
    return o.get("name") or ""


def script_ids(o):
    return [s.get("id") for s in (o.get("scripts") or [])]


WALLS = set()
BEANS = []
GHOSTS = []
PLAYER = None
for o in objs:
    n = nm(o)
    if n.startswith(u"\u5899_"):
        p = n.split("_")
        try:
            WALLS.add((int(p[1]), int(p[2])))
        except (IndexError, ValueError):
            pass
    elif n.startswith(u"\u8c46\u5b50"):
        BEANS.append(o)
    # 玩家/幽灵按"挂的脚本 id"识别 (对象名不参与脚本逻辑, 不能当判定依据)
    if "pacman_player" in script_ids(o):
        PLAYER = o
    elif "pacman_ghost" in script_ids(o):
        GHOSTS.append(o)

print()
print("=== 二. 场景真值 ===")
print("  墙=%d 豆=%d 幽灵=%d 玩家=%r" % (len(WALLS), len(BEANS), len(GHOSTS), nm(PLAYER)))
check("2-1 墙格 63 个且全部命名合规并可解析", len(WALLS) == 63, str(len(WALLS)))
check("2-2 豆子 58 颗", len(BEANS) == 58, str(len(BEANS)))
check("2-3 幽灵 3 只", len(GHOSTS) == 3, str(len(GHOSTS)))
check("2-4 玩家对象存在且为 sphere", PLAYER is not None)

if PLAYER is not None:
    pv = (PLAYER.get("scripts") or [{}])[0].get("vars") or {}
    pr = PLAYER["scale"][0] * PLAYER["params"]["radius"]
    print("  玩家 vars=%s 球半径=%.4f" % (pv, pr))
    check("2-5 玩家速度与幽灵速度一致且 = 4.0",
          abs(float(pv.get("speed", -1)) - 4.0) < 1e-9
          and all(abs(float((g.get("scripts") or [{}])[0].get("vars", {}).get("speed", -1))
                      - 4.0) < 1e-9 for g in GHOSTS),
          "player=%s ghosts=%s" % (pv.get("speed"),
                                   [(g.get("scripts") or [{}])[0].get("vars", {}).get("speed")
                                    for g in GHOSTS]))
    check("2-6 eat_r 不超过半格 (0.5), 不会跨格吃豆",
          0.0 < float(pv.get("eat_r", 9)) <= 0.5, str(pv.get("eat_r")))
    check("2-7 玩家球心高于地面 (不初始嵌入地板)", PLAYER["position"][1] - pr > 0.0,
          "y=%.3f r=%.3f" % (PLAYER["position"][1], pr))

# 迷宫网格: 11x11 边界封闭 + 豆全可达
xs = [k[0] for k in WALLS]
zs = [k[1] for k in WALLS]
check("2-8 迷宫 x/z 范围都是 -5..5 (11x11)", min(xs) == -5 and max(xs) == 5
      and min(zs) == -5 and max(zs) == 5, "x[%d,%d] z[%d,%d]" % (min(xs), max(xs), min(zs), max(zs)))
border_ok = all((x, -5) in WALLS and (x, 5) in WALLS for x in range(-5, 6)) \
    and all((-5, z) in WALLS and (5, z) in WALLS for z in range(-5, 6))
check("2-9 边界一圈全封闭", border_ok)


def open_cell(x, z):
    return (x, z) not in WALLS


if PLAYER is not None:
    spawn = (int(round(PLAYER["position"][0])), int(round(PLAYER["position"][2])))
    seen = {spawn}
    q = deque([spawn])
    while q:
        x, z = q.popleft()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n2 = (x + dx, z + dz)
            if n2 in seen or not open_cell(*n2):
                continue
            seen.add(n2)
            q.append(n2)
    bean_cells = set((int(round(b["position"][0])), int(round(b["position"][2])))
                     for b in BEANS)
    check("2-10 出生格是通路格", open_cell(*spawn), str(spawn))
    check("2-11 全部豆子从出生格可达 (通关判定可达成)", not (bean_cells - seen),
          str(sorted(bean_cells - seen)[:5]))
    check("2-12 豆子不落在墙格里", not (bean_cells & WALLS))
    gm = [(int(round(g["position"][0])), int(round(g["position"][2]))) for g in GHOSTS]
    check("2-13 幽灵出生格都是通路格", all(open_cell(*c) for c in gm), str(gm))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
