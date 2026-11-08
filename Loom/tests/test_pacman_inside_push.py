# -*- coding: utf-8 -*-

"""盒-球推出 (loom_physics._push_out) 的"球心在盒内"分支: 同分破法与方向语义.
覆盖 beta3_scan_06 P-06-02 (同分不稳定) 与 P-06-03 (盒-球方向未取反 + 位移放大).

判定基准 (白盒契约):
  B1  Loom/loom_physics.py:291-294  "把 a 推出 b 的碰撞体 ... 只改 a.position"
  B2  Loom/loom_physics.py:356-359  "改为沿最近面推出 (与盒-盒最小穿透轴一致): 永远走最短路径出去"
      盒-盒同分时的既有规则: loom_physics.py:320-322 "相等: 朝远离对方中心方向"

本文件是脚本式回归 (与 test_collision*.py 同风格): python tests/test_pacman_inside_push.py
"""

import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门 (与 test_collision.py 同款): 出现 "FAIL" 开头行 -> exit 1
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


import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E
from mesh import create_cube, create_sphere, create_plane

E.GLEngine._build_gpu = lambda self, m: None

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def new_eng():
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []
    e.materials = []
    e.lights = []
    e.current_model_index = 0
    return e


def add(e, mesh, pos, scale=(1, 1, 1), name=""):
    return e.add_model(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), scale=scale,
                       name=name)


def push(a_sphere, b_sphere):
    """a 是球 / b 是盒 时为 True (与 _push_out(a,b) 的实参顺序一致)."""
    return a_sphere and not b_sphere


# =====================================================================
# 一、同分破法 (P-06-02)
# =====================================================================
print("=== 一. 球心在盒内且各面等距: 方向必须是确定性固定规则 ===")

# 1-1 墙 0.92 x 0.5 x 0.92, 球 r=0.25 球心正在墙体正中 (y 轴 lo==hi 精确同分)
e = new_eng()
wall = add(e, create_cube(1.0), (0, 0.25, 0), scale=(0.92, 0.5, 0.92), name="墙")
sph = add(e, create_sphere(0.5), (0, 0.25, 0), scale=(0.5, 0.5, 0.5), name="球")
bmn, bmx = e.collider_bounds(wall)[1]
sc, r = e.collider_bounds(sph)[1]
lo_y = (sc.y - bmn.y) + r
hi_y = (bmx.y - sc.y) + r
print("  墙 AABB y=[%.6f, %.6f] 球心 y=%.6f r=%.6f  lo_y=%.6f hi_y=%.6f (同分=%.1e)"
      % (bmn.y, bmx.y, sc.y, r, lo_y, hi_y, abs(lo_y - hi_y)))
e._push_out(sph, wall)
dy = sph.position.y - 0.25
check("1-1 精确同分 (球心在墙体中分面): 推出方向为 +y (向上), 不是向下穿地板",
      dy > 0.0, "dy=%+.6f pos_y=%.6f" % (dy, sph.position.y))
check("1-1 推出后与墙分离", not e.collider_hit(wall, sph), str(e.collider_bounds(sph)[1]))

# 1-2 立方体中心: 三轴全同分 -> 固定符号优先级 (+ 侧)
e2 = new_eng()
box = add(e2, create_cube(2.0), (0, 0, 0), name="盒")
sph2 = add(e2, create_sphere(0.2), (0, 0, 0), name="球")
e2._push_out(sph2, box)
p = sph2.position
moved = [p.x, p.y, p.z]
nz = [i for i, v in enumerate(moved) if abs(v) > 1e-9]
check("1-2 球心在盒心 (三轴同分): 只沿一轴推出, 且为 +侧 (固定符号优先)",
      len(nz) == 1 and moved[nz[0]] > 0,
      "pos=%s" % (tuple(moved),))
check("1-2 推出量 = 半边长 + r + 1e-4 (= 1.2001)", len(nz) == 1
      and abs(moved[nz[0]] - 1.2001) < 1e-6, "quant=%.6f" % (moved[nz[0]] if nz else -1))
check("1-2 推出后分离", not e2.collider_hit(box, sph2))

# 1-3 零厚度地面平面 + 球心正落在平面上: 必须向上抬出, 而不是穿到地板下方
e3 = new_eng()
ground = add(e3, create_plane(8, 8), (0, 0, 0), name="地面")
sph3 = add(e3, create_sphere(0.2), (0, 0, 0), name="球")
e3._push_out(sph3, ground)
check("1-3 零厚度平面 (球心在平面上): 推出方向 +y (抬出地板), 不是 -y",
      sph3.position.y > 0.0, "pos_y=%+.6f" % sph3.position.y)
check("1-3 推出后分离", not e3.collider_hit(ground, sph3))

# 1-4 确定性: 同一输入重复 50 次完全一致
seen = set()
for _ in range(50):
    e4 = new_eng()
    w4 = add(e4, create_cube(1.0), (0, 0.25, 0), scale=(0.92, 0.5, 0.92))
    s4 = add(e4, create_sphere(0.5), (0, 0.25, 0), scale=(0.5, 0.5, 0.5))
    e4._push_out(s4, w4)
    seen.add((round(s4.position.x, 9), round(s4.position.y, 9), round(s4.position.z, 9)))
check("1-4 同分推出方向确定 (50 次结果唯一)", len(seen) == 1, str(seen))

# =====================================================================
# 二、盒-球方向语义 (P-06-03): a 是盒时必须把盒推离球, 且一次调用即分离
# =====================================================================
print()
print("=== 二. a=盒 / b=球 且球心在盒内: 方向必须与'球心在盒外'分支一致 (推离) ===")

for label, cx in (("球心浅入盒内 (0.9,0,0)", 0.9), ("球心深入盒内 (0.02,0,0)", 0.02)):
    e5 = new_eng()
    bx = add(e5, create_cube(2.0), (0, 0, 0), name="盒")
    sp = add(e5, create_sphere(0.2), (cx, 0, 0), name="球")
    # 几何最小分离量 (推出前量): 盒须沿 -x 走到 box.max <= 球.minx(=cx-r), 或沿 +x 走到 box.min >= 球.maxx(=cx+r)
    bmn5, bmx5 = e5.collider_bounds(bx)[1]
    need_minus = bmx5.x - (cx - 0.2)    # 沿 -x 的最小位移
    need_plus = (cx + 0.2) - bmn5.x     # 沿 +x 的最小位移
    exp_dx = min(need_minus, need_plus)
    e5._push_out(bx, sp)
    sep = not e5.collider_hit(bx, sp)
    dx = bx.position.x
    print("  [%s] 盒位移 dx=%+.6f 分离=%s | 几何最小分离量: -x %.4f / +x %.4f"
          % (label, dx, sep, need_minus, need_plus))
    check("2-1 一次 _push_out 后不重叠: " + label, sep)
    check("2-1 盒被推离球 (方向 = -x, 与球心在盒外时的取反语义一致): " + label,
          dx < 0, "dx=%+.6f" % dx)
    check("2-1 位移量 = 几何最小分离量 (不再是指向球的那侧的空转): " + label,
          abs(abs(dx) - (exp_dx + 1e-4)) < 1e-6,
          "|dx|=%.6f 期望=%.6f" % (abs(dx), exp_dx + 1e-4))

# 2-2 回归护栏: a 是球时行为不能被改坏 (仍是一次分离 + 正向推出)
e6 = new_eng()
bx6 = add(e6, create_cube(2.0), (0, 0, 0))
sp6 = add(e6, create_sphere(0.2), (0.9, 0, 0))
e6._push_out(sp6, bx6)
check("2-2 a=球 时仍一次分离且沿 +x 推出 (原行为不变)",
      not e6.collider_hit(bx6, sp6) and abs(sp6.position.x - 1.2001) < 1e-6,
      "pos=%s" % (sp6.position,))

# 2-3 回归护栏: "球心在盒外"分支逐位不变
e7 = new_eng()
bx7 = add(e7, create_cube(2.0), (0, 0, 0))
sp7 = add(e7, create_sphere(0.2), (1.05, 0, 0))
e7._push_out(sp7, bx7)
expect7 = 1.0 + 0.2 + 1e-4      # 推出后球心 = 盒面 + r + 1e-4
check("2-3 球心在盒外 (距面 0.05 < r): 推出到 r+1e-4 贴边之外 (行为不变)",
      abs(sp7.position.x - expect7) < 1e-6,
      "x=%.6f 期望=%.6f" % (sp7.position.x, expect7))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
