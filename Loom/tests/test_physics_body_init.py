# -*- coding: utf-8 -*-

"""物理建体初始化 + 桥生命周期回归 (scan_08_physics P1/P2 修复锁定).

覆盖:
  1. 建体即用世界位姿: 动态体初始旋转不被首帧 identity 回写清零
  2. 旋转父下子体局部旋转不被改成 inv(R_parent)
  3. 偏心网格 (AABB 中心 != 模型原点) 建体后不瞬移到 AABB 中心
  4. 父无碰撞体时父移动 -> 子体跟随 (局部位置不被写成 -4.0)
  5. is_trigger 进形态签名: 播放中切换 Trigger 会重建体
  6. 树位回收: 树内最后一个体移除后释放 category 位 (新树复用不撞位)
  7. 重建体继承角速度与睡眠态 (不被重置为清醒/零角速)
  8. physics_glue 前置校验: dtype/形状/长度/连续性不符抛 ValueError
     (含 n==0 也不再静默 rc=0)

culverin 缺失 -> SKIP exit 0 (与 test_physics_bridge 同策略).
用法: py -3.12 tests\test_physics_body_init.py
"""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 中文/符号 print 会抛
# UnicodeEncodeError 造成假失败; 统一 UTF-8(replace), 失败信号只由断言决定.
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门: 出现以 FAIL 开头的行 -> 退出码改 1 (run_all 不假绿).
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


import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import culverin  # noqa: F401
    HAS_CV = True
except Exception:
    HAS_CV = False

if not HAS_CV:
    print("SKIP: culverin 未安装, 建体初始化用例跳过")
    sys.exit(0)

import numpy as np                 # noqa: E402
import physics_bridge as B          # noqa: E402
import physics_glue as pg           # noqa: E402
import engine as E                  # noqa: E402
from mesh import create_cube, create_sphere, create_plane   # noqa: E402

DT = 1.0 / 60.0
ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def make_obj(mesh, pos, rot=(0.0, 0.0, 0.0), primitive='cube', shape=None,
             mass=None, use_gravity=True, is_kinematic=False, parent=None,
             name='obj'):
    """真 GameObject (真网格) — 桥按引擎模型语义建体."""
    m = E.GameObject(mesh, E.Point3D(*pos), E.Point3D(*rot), name=name,
                     primitive=primitive)
    if shape is not None:
        m.collider.shape = shape
    if mass is not None:
        m.add_rigidbody(mass=mass, use_gravity=use_gravity,
                        is_kinematic=is_kinematic)
    if parent is not None:
        m.parent = parent
    return m


def near(a, b, tol=1e-4):
    return all(abs(float(x) - float(y)) < tol for x, y in zip(a, b))


def vec(m):
    p = m.position
    return (p.x, p.y, p.z)


def rot(m):
    r = m.rotation
    return (r.x, r.y, r.z)


# ============================================================
# 1. 动态体初始旋转不被首帧 identity 回写清零
# ============================================================
b = B.PhysicsWorldBridge()
m = make_obj(create_cube(1.0), (0, 3, 0), rot=(0.4, 0.2, 0.1),
             shape='box', mass=1.0, use_gravity=False, name='旋转体')
b.build([m])
for _ in range(5):
    b.frame(DT)
check("1a.动态体初始旋转不被清零", near(rot(m), (0.4, 0.2, 0.1), 1e-4),
      "rotation=%s" % (rot(m),))
check("1b.动态体初始位置不被写回", near(vec(m), (0, 3, 0), 1e-5),
      "position=%s" % (vec(m),))
b.destroy()

# ============================================================
# 2. 旋转父下子体局部旋转不被改成 inv(R_parent)
# ============================================================
b = B.PhysicsWorldBridge()
parent = make_obj(create_cube(1.0), (2, 0, 0), rot=(0.2, 0.3, 0.1),
                  shape='box', name='旋转父')
child = make_obj(create_sphere(0.5), (0, 0, 0), rot=(0.4, 0.2, 0.1),
                 primitive='sphere', shape='sphere', mass=1.0,
                 use_gravity=False, parent=parent, name='子球')
b.build([parent, child])
for _ in range(5):
    b.frame(DT)
check("2.旋转父下子体局部旋转保持 (未被改成 inv(R_parent))",
      near(rot(child), (0.4, 0.2, 0.1), 1e-3), "rotation=%s" % (rot(child),))
check("2b.旋转父下子体局部位置保持", near(vec(child), (0, 0, 0), 1e-3),
      "position=%s" % (vec(child),))
b.destroy()

# ============================================================
# 3. 偏心网格不瞬移 (AABB 中心 != 模型原点)
# ============================================================
mesh = create_cube(1.0)
mesh.vertices = [(x + 3.0, y, z) for (x, y, z) in mesh.vertices]   # 网格偏 +3x
off = make_obj(mesh, (0, 3, 0), shape='box', mass=1.0,
               use_gravity=False, name='偏心体')
b = B.PhysicsWorldBridge()
b.build([off])
b.frame(DT)
check("3.偏心网格建体后不瞬移到 AABB 中心", near(vec(off), (0, 3, 0), 1e-5),
      "position=%s (AABB 中心应为 (3,3,0))" % (vec(off),))
b.destroy()

# ============================================================
# 4. 父无碰撞体时父移动 -> 子体跟随
# ============================================================
b = B.PhysicsWorldBridge()
parent = make_obj(create_cube(1.0), (0, 0, 0), shape='box', name='无碰撞父')
parent.collider.enabled = False                       # 父不建体 (无碰撞体)
child = make_obj(create_cube(0.5), (0, 0, 0), shape='box', mass=1.0,
                 use_gravity=False, parent=parent, name='子体')
b.build([parent, child])
parent.position = E.Point3D(4.0, 0.0, 0.0)            # 父移动 +4x
b.frame(DT)
b.frame(DT)
check("4a.父无碰撞体时子体世界位置跟随", near(tuple(B.world_position_vec(child)),
                                               (4.0, 0.0, 0.0), 1e-4),
      "world=%s" % (tuple(B.world_position_vec(child)),))
check("4b.子体局部位置不被写成 -4.0", near(vec(child), (0.0, 0.0, 0.0), 1e-4),
      "local=%s" % (vec(child),))
b.destroy()

# ============================================================
# 5. is_trigger 进形态签名: 切换 Trigger 重建体
# ============================================================
a = make_obj(create_cube(1.0), (0, 5, 0), shape='box', mass=1.0,
             use_gravity=False, name='a')
c = make_obj(create_cube(1.0), (5, 5, 0), shape='box', mass=1.0,
             use_gravity=False, name='c')
b = B.PhysicsWorldBridge()
b.build([a, c])
c0 = b.body_count
a.collider.is_trigger = True                          # 播放中勾 Trigger
created, destroyed, rebuilt = b.ensure_models([a, c])
check("5.is_trigger 进签名 -> 播放中切换重建体",
      rebuilt == 1 and created == 0 and destroyed == 0 and b.body_count == c0,
      "created/destroyed/rebuilt=%d/%d/%d count=%d"
      % (created, destroyed, rebuilt, b.body_count))

# ============================================================
# 6. 树位回收 (移除树内最后一个体)
# ============================================================
bits0 = dict(b._tree_bit)
key_c = id(b._root_of(c))
check("6a.两棵树各占一位", len(bits0) == 2 and len(set(bits0.values())) == 2,
      "bits=%s" % ({k: bin(v) for k, v in bits0.items()},))
b.ensure_models([a])                                  # 移除 c 所在树
check("6b.移除体回收树位", len(b._tree_bit) == 1 and key_c not in b._tree_bit
      and key_c not in b._tree_ref,
      "bits=%d refs=%d" % (len(b._tree_bit), len(b._tree_ref)))
b.ensure_models([a, c])                               # 重新加回
bits1 = set(b._tree_bit.values())
check("6c.重新建树位不撞位", len(bits1) == 2, "bits=%s" % ([bin(v) for v in bits1],))

# ============================================================
# 7. 重建体继承角速度与睡眠态
# ============================================================
h_old = [e for e in b._entries if e['model'] is a][0]['handle']
b._w.set_angular_velocity(h_old, 0.0, 5.0, 0.0)
b._w.deactivate(h_old)
b._w.step(0.0)
ang0 = b._w.get_angular_velocity(h_old)
a.collider.friction = 0.73                            # 触发签名变化 -> 重建
created, destroyed, rebuilt = b.ensure_models([a, c])
h_new = [e for e in b._entries if e['model'] is a][0]['handle']
ang1 = b._w.get_angular_velocity(h_new)
check("7a.重建体继承角速度",
      rebuilt == 1 and abs(float(ang1[1]) - 5.0) < 1e-3,
      "rebuilt=%d ang=%s" % (rebuilt, tuple(float(x) for x in ang1)))
check("7b.重建体继承睡眠态", b._w.is_active(h_new) is False,
      "active=%s" % (b._w.is_active(h_new),))
b.destroy()

# ============================================================
# 8. physics_glue 前置校验 (失败抛 ValueError, 不静默 rc=0)
# ============================================================
n = 3
lv = np.zeros((n, 3), dtype=np.float64)
av = np.zeros((n, 3), dtype=np.float64)
dyn = np.ones(n, dtype=np.uint8)
grav = np.ones(n, dtype=np.uint8)
act = np.ones(n, dtype=np.uint8)
fric = np.full(n, 0.5, dtype=np.float64)
roll = np.full(n, 0.1, dtype=np.float64)


def raises_value(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


check("8a.float32 速度数组 -> ValueError", raises_value(
    lambda: pg.pre_step(lv.astype(np.float32), av, dyn, grav, act, fric, roll, -9.8, DT)))
check("8b.速度数组形状非 (n,3) -> ValueError", raises_value(
    lambda: pg.pre_step(lv, av[:, :2].copy(), dyn, grav, act, fric, roll, -9.8, DT)))
check("8c.非 C 连续切片 -> ValueError", raises_value(
    lambda: pg.pre_step(np.zeros((n, 6), np.float64)[:, ::2], av, dyn, grav,
                        act, fric, roll, -9.8, DT)))
check("8d.标志数组长度不一致 -> ValueError", raises_value(
    lambda: pg.pre_step(lv, av, dyn[:2], grav, act, fric, roll, -9.8, DT)))
check("8e.n=0 错误 dtype 不再静默 rc=0 -> ValueError", raises_value(
    lambda: pg.pre_step(np.empty((0, 3), np.float32), np.empty((0, 3)),
                        np.empty(0, np.uint8), np.empty(0, np.uint8),
                        np.empty(0, np.uint8), np.empty(0), np.empty(0),
                        -9.8, DT)))
check("8f.post_step is_active dtype 错 -> ValueError", raises_value(
    lambda: pg.post_step(lv, av, act.astype(np.int32))))
check("8g.合法输入仍 rc=0", pg.pre_step(lv, av, dyn, grav, act, fric, roll,
                                        -9.8, DT) == 0)

# ============================================================
# 9. 万向锁 (beta=±90°): quat -> euler -> 矩阵 往返误差 < 1e-6
#    (与 matlib.decompose_euler 的 P-13/P-14 同款符号修正; |cos beta|<1e-9)
# ============================================================
def euler_roundtrip(euler_in):
    """euler -> quat -> euler -> 矩阵, 返回 (矩阵最大误差, 回读欧拉, 原矩阵)."""
    M0 = B.engine_mat3_from_euler(np.array([euler_in], dtype=np.float64))[0]
    q = B.quat_from_mat3(M0[np.newaxis, :, :])[0]
    e = B.quat_to_euler_batch(q[np.newaxis, :])[0]
    M1 = B.engine_mat3_from_euler(e[np.newaxis, :])[0]
    return float(np.abs(M1 - M0).max()), e, M0


for _beta in (math.pi / 2.0, -math.pi / 2.0):
    err, e, M0 = euler_roundtrip((0.3, _beta, 0.7))
    check("9.万向锁 beta=%+.0f° 往返矩阵误差<1e-6" % math.degrees(_beta),
          err < 1e-6,
          "err=%.3e euler=(%.6f, %.6f, %.6f)"
          % (err, float(e[0]), float(e[1]), float(e[2])))

# beta=+90° 既有结果不变: alpha 仍取 atan2(R[1,0], R[1,1]) (s=+1)
err_p, e_p, M_p = euler_roundtrip((0.3, math.pi / 2.0, 0.7))
exp_alpha = math.atan2(float(M_p[1, 0]), float(M_p[1, 1]))
check("9b.beta=+90° alpha 取法不变 (既有结果)",
      abs(float(e_p[0]) - exp_alpha) < 1e-12,
      "alpha=%.9f expect=%.9f" % (float(e_p[0]), exp_alpha))

# beta=-90° 且 gamma=0 (asin 参数精确饱和): 旧取法 (不翻符号) 得到 -alpha,
# 新取法 atan2(-R[1,0], R[1,1]) 恢复 +alpha; 矩阵往返一致.
err_n, e_n, M_n = euler_roundtrip((0.3, -math.pi / 2.0, 0.0))
old_alpha = math.atan2(float(M_n[1, 0]), float(M_n[1, 1]))
check("9c.beta=-90° 符号修正生效 (旧取法符号相反且矩阵不一致)",
      abs(float(e_n[0]) - 0.3) < 1e-9 and abs(old_alpha + 0.3) < 1e-9
      and err_n < 1e-6,
      "new_alpha=%.6f old_alpha=%.6f err=%.3e"
      % (float(e_n[0]), old_alpha, err_n))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
