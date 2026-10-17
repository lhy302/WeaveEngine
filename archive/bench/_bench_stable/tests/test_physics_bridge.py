# -*- coding: utf-8 -*-
"""B1 物理换库 — Culverin (Jolt) 桥数值用例 (需 culverin, 系统 py3.12 已装).

设计 §5 自动行 (桥路径) + P1 必修项锁定:
  1. 球落地面停点 (|Δ|<0.03)            2. 速度落定 |v|<0.01
  3. gravity=-20 时落点变快            4. kinematic 不被推 (动态挡停不穿模)
  5. 同树不互撞 (父-子穿父落地面)+异树被挡
  6. use_gravity=False 零漂移 (<1e-6)
  7. 快照建销 (build→destroy 再建 count 一致)
  8. R4 欧拉转换器单测 (点旋转/往返 <1e-9)
  9. 动量对比报告 (legacy 撞停 vs Jolt 冲量传递, 数值输出供人工对照)
  10. P1 滚动摩擦衰减 (10a 停时 2-4.5s / 10b 停后入眠 / 10c 关闭不生效)
  11. P2 建体激活保底 (落定后入眠, 保底不防眠)
  11b/11c. 修复_b② 残速死带 (残速 1s 内清零; 正常被推箱体滑距不受影响)
  12. 修复_b① 无碰撞体动态体自由积分 (重力与碰撞体解耦, legacy/Unity 契约)

culverin 缺失 -> 本文件 print SKIP 并 exit 0 (套件继续).
用法: py -3.12 tests\\test_physics_bridge.py
"""
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
    print("SKIP: culverin 未安装, physics_bridge 用例跳过 (legacy 路径不受影响)")
    sys.exit(0)

import physics_bridge as B          # noqa: E402
import engine as E                 # noqa: E402
import numpy as np                 # noqa: E402
from mesh import create_cube, create_sphere, create_plane   # noqa: E402

DT = 1.0 / 60.0
ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def make_obj(mesh, pos, primitive='cube', shape=None, mass=None, use_gravity=True,
             is_kinematic=False, parent=None, **kw):
    """真 GameObject (真网格) — 桥按引擎模型语义建体."""
    m = E.GameObject(mesh, E.Point3D(*pos), E.Point3D(0, 0, 0), name=kw.get('name', 'obj'),
                     primitive=primitive)
    if shape is not None:
        m.collider.shape = shape
    if mass is not None:
        m.add_rigidbody(mass=mass, use_gravity=use_gravity,
                        is_kinematic=is_kinematic,
                        friction=kw.get('friction', 0.5),
                        restitution=kw.get('restitution', 0.0),
                        rolling_friction=kw.get('rolling_friction', 0.1))
    if parent is not None:
        m.parent = parent
    return m


# ---------------- 1/2. 球落地停点 + 速度归零 ----------------
def case_land():
    b = B.PhysicsWorldBridge()
    ground = make_obj(create_plane(20, 20), (0, -0.5, 0), primitive='cube',
                      shape='box', name='地面')          # 顶面 y=-0.5 (零厚盒)
    ball = make_obj(create_sphere(0.5), (0, 10, 0), primitive='sphere',
                    shape='sphere', mass=1.0, name='球')  # r=0.5 -> 期望停 y=0.0
    b.build([ground, ball])
    v_series = []
    for i in range(600):
        b.frame(DT)
        if i >= 560:
            v_series.append((ball.position.y, ball.rigidbody.velocity))
    y_final = ball.position.y
    speed = math.sqrt(sum(c * c for c in ball.rigidbody.velocity))
    y_var = max(y for y, _ in v_series) - min(y for y, _ in v_series)
    check("1.球落地停点 |Δ|<0.03", abs(y_final - 0.0) < 0.03,
          "y=%.5f (期望 0.0; 末40帧抖动=%.6f)" % (y_final, y_var))
    check("2.落地速度落定 |v|<0.01", speed < 0.01, "|v|=%.6f" % speed)
    return y_final, speed


# ---------------- 3. gravity=-20 落点变快 ----------------
def case_gravity():
    ys = {}
    for g in (-9.8, -20.0):
        b = B.PhysicsWorldBridge()
        ground = make_obj(create_plane(20, 20), (0, -0.5, 0), primitive='cube',
                          shape='box', name='地面')
        ball = make_obj(create_sphere(0.5), (0, 10, 0), primitive='sphere',
                        shape='sphere', mass=1.0)
        b.build([ground, ball])
        for _ in range(30):                    # 0.5s: g20 下落 ~2.5m, g9.8 ~1.22m
            b.frame(DT, gravity=g)
        ys[g] = ball.position.y
    check("3.gravity=-20 落点变快 (0.5s 后更低)",
          ys[-20.0] < ys[-9.8] - 0.5,
          "g9.8: y=%.3f  g20: y=%.3f" % (ys[-9.8], ys[-20.0]))
    return ys


# ---------------- 4. kinematic 不被推 ----------------
def case_kinematic():
    b = B.PhysicsWorldBridge()
    ground = make_obj(create_plane(20, 20), (0, -0.5, 0), primitive='cube',
                      shape='box', name='地面')
    kin = make_obj(create_sphere(0.5), (5, 0.5, 0), primitive='sphere',
                   shape='sphere', mass=1.0, is_kinematic=True, name='kin')
    dyn = make_obj(create_sphere(0.5), (0, 0.5, 0), primitive='sphere',
                   shape='sphere', mass=1.0, use_gravity=False, name='dyn')
    b.build([ground, kin, dyn])
    kx0 = kin.position.x
    for _ in range(240):
        dyn.rigidbody.velocity = E.Point3D(3.0, 0.0, 0.0)   # 数据驱动每帧压速
        b.frame(DT)
    dx_kin = kin.position.x - kx0
    check("4.kinematic 不被推走 (Δx<0.001; 动态被挡停不穿模)",
          abs(dx_kin) < 0.001 and dyn.position.x < 4.5,
          "kin Δx=%.5f; dyn x=%.3f (r=0.5: 前端 ~4.0)" % (dx_kin, dyn.position.x))
    return dx_kin


# ---------------- 5. 同树不互撞 (父-子穿父) + 异树被挡 ----------------
def case_same_tree():
    b = B.PhysicsWorldBridge()
    parent = make_obj(create_cube(1.0), (0, 0, 0), primitive='cube',
                      shape='box', name='父盒')
    parent.scale = (4.0, 1.0, 4.0)           # cube 半长 0.5 -> 世界半长 (2.0, 0.5, 2.0), 顶 y=0.5
    child = make_obj(create_sphere(0.5), (-0.3, 1.5, 0), primitive='sphere',
                     shape='sphere', mass=1.0, parent=parent, name='子球')
    child.scale = (0.25, 1.0, 0.25)          # 补偿父缩放: 子世界半长 = 0.5; 世界位置 (-1.2, 1.5, 0)
    ground = make_obj(create_plane(20, 20), (0, -1.5, 0), primitive='cube',
                      shape='box', name='地面')            # 顶面 y=-1.5
    other = make_obj(create_sphere(0.5), (1.2, 1.5, 0), primitive='sphere',
                     shape='sphere', mass=1.0, name='别树球')
    b.build([parent, child, ground, other])
    for _ in range(360):
        b.frame(DT)
    cy, oy = child.position.y, other.position.y
    check("5a.同树父子 (同树位) 子球穿父盒落地面 y≈-1.0",
          abs(cy - (-1.0)) < 0.05, "child y=%.4f (被父挡应停 1.0)" % cy)
    check("5b.异树球被父盒挡停 y≈1.0",
          abs(oy - 1.0) < 0.05, "other y=%.4f (盒顶 0.5 + r 0.5)" % oy)
    return cy, oy


# ---------------- 6. use_gravity=False 零漂移 ----------------
def case_no_gravity():
    b = B.PhysicsWorldBridge()
    ball = make_obj(create_sphere(0.5), (0, 5, 0), primitive='sphere',
                    shape='sphere', mass=1.0, use_gravity=False)
    b.build([ball])
    ys = []
    for _ in range(240):
        b.frame(DT)
        ys.append(ball.position.y)
    d = max(ys[-60:]) - min(ys[-60:])
    check("6.use_gravity=False 零漂移 (<1e-6)", d < 1e-6,
          "末60帧 Δy=%.2e (活跃=%d)" % (d, b.active_count))
    return d


# ---------------- 7. 快照建销 (build→destroy 再建 count 一致) ----------------
def case_build_destroy():
    def scene(tag):
        b = B.PhysicsWorldBridge()
        objs = [make_obj(create_cube(0.8), (i * 2.0, 5.0, 0), primitive='cube',
                         name='c%d' % i) for i in range(4)]
        objs.insert(0, make_obj(create_plane(20, 20), (0, -0.5, 0),
                                primitive='cube', shape='box', name='地面'))
        return b, objs
    b, objs = scene('a')
    b.build(objs)
    c0 = b.body_count
    b.destroy()
    c1 = b.body_count
    b2, objs2 = scene('b')
    b2.build(objs2)
    c2 = b2.body_count
    # 差量: 移除 1 个 + 恢复
    b2.ensure_models(objs2[:-1])
    c3 = b2.body_count
    b2.ensure_models(objs2)
    c4 = b2.body_count
    check("7.快照建销: 建%d→销%d→再建%d 一致; 差量移除%d→恢复%d"
          % (c0, c1, c2, c3, c4),
          c0 > 0 and c1 == 0 and c2 == c0 and c3 == c0 - 1 and c4 == c0,
          "counts=%d/%d/%d/%d/%d" % (c0, c1, c2, c3, c4))
    return c0, c1, c2, c3, c4


# ---------------- 8. R4 欧拉转换器单测 ----------------
def case_r4():
    deg = (30.0, 45.0, 60.0)
    rad = tuple(math.radians(d) for d in deg)
    p = np.array([1.0, 2.0, 3.0])
    cx, sx = math.cos(rad[0]), math.sin(rad[0])
    cy, sy = math.cos(rad[1]), math.sin(rad[1])
    cz, sz = math.cos(rad[2]), math.sin(rad[2])
    Rx = np.array([[1, 0, 0], [0, cx, sx], [0, -sx, cx]])
    Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    Rz = np.array([[cz, sz, 0], [-sz, cz, 0], [0, 0, 1]])
    M_engine = Rx @ Ry @ Rz
    r1 = p @ M_engine
    q = B.euler_to_quat_batch(np.array([rad]))[0]
    C = B.engine_mat3_from_quat(q[np.newaxis, :])[0]
    r2 = p @ C
    d1 = float(np.abs(r1 - r2).max())
    e2 = B.quat_to_euler_batch(q[np.newaxis, :])[0]
    d2 = float(np.abs(e2 - np.array(rad)).max())
    check("8.R4 转换器: 点旋转/往返 max|Δ|<1e-9",
          d1 < 1e-9 and d2 < 1e-9, "点旋转 Δ=%.2e 往返 Δ=%.2e" % (d1, d2))
    return d1, d2


# ---------------- 9. 动量对比报告 (legacy 撞停 vs Jolt 冲量) ----------------
def case_momentum():
    # legacy: GLEngine.__new__ 桩 (无 __init__ -> 无 _phys_bridge_auto -> 永久 legacy)
    e = E.GLEngine.__new__(E.GLEngine)
    e.models = []; e.materials = []; e.lights = []; e.current_model_index = 0
    E.GLEngine._build_gpu = lambda self, m: None
    g = e.add_model(create_plane(20, 20), E.Point3D(0, -0.5, 0), E.Point3D(0, 0, 0))
    g.collider.shape = 'box'
    m1 = e.add_model(create_sphere(0.5), E.Point3D(0, 0.5, 0), E.Point3D(0, 0, 0))
    m1.collider.shape = 'sphere'
    m1.add_rigidbody(use_gravity=False)
    m1.rigidbody.velocity = E.Point3D(3.0, 0, 0)
    m2 = e.add_model(create_sphere(0.5), E.Point3D(2.0, 0.5, 0), E.Point3D(0, 0, 0))
    m2.collider.shape = 'sphere'
    m2.add_rigidbody(use_gravity=False)
    for _ in range(300):
        e.update_physics(DT)
    leg_v1 = m1.rigidbody.velocity.x
    leg_dx2 = m2.position.x - 2.0

    # 桥路径 (同场景, Jolt 冲量)
    b = B.PhysicsWorldBridge()
    bg = make_obj(create_plane(20, 20), (0, -0.5, 0), primitive='cube',
                  shape='box', name='地面')
    b1 = make_obj(create_sphere(0.5), (0, 0.5, 0), primitive='sphere',
                  shape='sphere', mass=1.0, use_gravity=False, name='撞球')
    b2 = make_obj(create_sphere(0.5), (2.0, 0.5, 0), primitive='sphere',
                  shape='sphere', mass=1.0, use_gravity=False, name='被撞球')
    b.build([bg, b1, b2])
    b1.rigidbody.velocity = E.Point3D(3.0, 0, 0)
    for _ in range(300):
        b.frame(DT)
    bw_v1 = b1.rigidbody.velocity.x
    bw_dx2 = b2.position.x - 2.0
    check("9.动量对比 (报告数值, 不判定)",
          True,
          "legacy: 撞球 v1=%.4f (撞停), 被撞球 Δx=%.4f | Jolt: 撞球 v1=%.4f, "
          "被撞球 Δx=%.4f (冲量传递)" % (leg_v1, leg_dx2, bw_v1, bw_dx2))
    print("  [动量对比输出] legacy v1=%.4f dx2=%.4f | jolt v1=%.4f dx2=%.4f" %
          (leg_v1, leg_dx2, bw_v1, bw_dx2))
    return leg_v1, leg_dx2, bw_v1, bw_dx2


# ---------------- 10. 滚动摩擦衰减 (B1-P1 用户实测: 球滚起来停不下来) ----------------
def case_rolling():
    """P1: culverin 0.14.0 无原生滚动摩擦 -> 桥内 ω/水平线速度按
    f = max(0, 1-μ·rolling·K·dt) 衰减 (K=23 标定: r=0.5 球 μ=0.5 rolling=0.1
    从 3m/s 起滚应在 2-4s 停; 实测见下). 停后须自然入眠 (active=0)."""
    b = B.PhysicsWorldBridge()
    ground = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                      shape='box', name='大地面')            # 顶 y=-0.5, 大平面防滚出界
    ball = make_obj(create_sphere(0.5), (0, 0, 0), primitive='sphere',
                    shape='sphere', mass=1.0, friction=0.5, name='滚球')
    b.build([ground, ball])
    ball.rigidbody.velocity = E.Point3D(3.0, 0.0, 0.0)       # 3m/s 起滚
    t_stop = None
    for i in range(600):                                    # 10s 上限
        b.frame(DT)
        sp = math.sqrt(sum(c * c for c in ball.rigidbody.velocity))
        if sp < 0.01:
            t_stop = i * DT
            break
    check("10a.滚动摩擦停止时间在 2-4.5s (K=23 标定值)",
          t_stop is not None and 2.0 <= t_stop <= 4.5,
          "停止=%.3fs" % (t_stop if t_stop is not None else -1.0))
    # 修复_b②: 死带把尾部 (|v_h|<0.03 且 |ω|<0.3) 当帧清 0 —— 比旧"指数尾巴
    # 磨到 0.01"更早到达全停; Jolt 入睡有其内部计时 (实测 ~0.5s 后), 故
    # "active=0" 断言放开到"停后 3s 窗内入眠" (睡眠红利不变, 只错开判定时刻).
    sleep_at = None
    for j in range(180):
        b.frame(DT)
        if b.active_count == 0:
            sleep_at = j * DT
            break
    check("10b.全停后 3s 内自然入眠 active=0 (睡眠红利保留)",
          sleep_at is not None, "停后 %.3fs 入眠" % (sleep_at if sleep_at is not None else -1.0))
    b2 = B.PhysicsWorldBridge()
    g2 = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                  shape='box', name='地面2')
    ball2 = make_obj(create_sphere(0.5), (0, 0, 0), primitive='sphere',
                     shape='sphere', mass=1.0, friction=0.5,
                     rolling_friction=0.0, name='滚球2')     # rolling=0 = 关闭
    b2.build([g2, ball2])
    ball2.rigidbody.velocity = E.Point3D(3.0, 0.0, 0.0)
    for _ in range(45):
        b2.frame(DT)
    sp2 = math.sqrt(sum(c * c for c in ball2.rigidbody.velocity))
    check("10c.rolling=0 关闭 -> 0.75s 后仍 >2.0 m/s (衰减不生效)",
          sp2 > 2.0, "v=%.3f" % sp2)
    return t_stop


# ---------------- 11. 建体即激活保底 (B1-P2 用户实测: 加碰撞器+刚体后浮空) ----------------
def case_p2_guard():
    """P2: 新体 activate (@build) + pre_step 保底 (首 90 帧内睡眠体再次唤醒+当帧重力)
    不改变"落定后可入眠"语义: 球落地 6s 后 active 计数须回 0 且位形稳定
    (保底不防眠 —— 目标 2.4µs/步 睡眠红利保住)."""
    b = B.PhysicsWorldBridge()
    ground = make_obj(create_plane(20, 20), (0, -0.5, 0), primitive='cube',
                      shape='box', name='地面')
    ball = make_obj(create_sphere(0.5), (0, 5, 0), primitive='sphere',
                    shape='sphere', mass=1.0, name='球')
    b.build([ground, ball])
    for _ in range(360):                       # 6s: 落定 + 保底窗(90帧)结束 + 0.5s 入眠
        b.frame(DT)
    y0 = ball.position.y
    for _ in range(60):                        # 再 1s 稳度验证
        b.frame(DT)
    dy = max(ball.position.y, y0) - min(ball.position.y, y0)
    check("11.落定入眠保底不防眠: active=0 且末帧位形稳定",
          b.active_count == 0 and abs(ball.position.y - y0) < 1e-4
          and abs(dy) < 1e-4,
          "active=%d y=%.4f dy=%.4f" % (b.active_count, ball.position.y, dy))
    return b.active_count


# ---------------- 11b/11c. 残速死带 (B1-修复_b ②: 滑动残速尾巴彻底清除) ----------------
def case_stall():
    """用户二轮实测: "有减速但仍有极轻微缓慢移动" = Jolt 库仑摩擦亚阈值尾巴。
    死带: 清醒 DYNAMIC 体同时 |v_h|<V_STALL_EPS 且 |ω|<W_STALL_EPS 且 |vy|<1 ->
    水平/角速度当帧清 0。断言: 残留滑动体 1s 内全停+停后入眠; 0.5m/s 被推箱体
    自然滑距不受死带影响 (带开/关距离差 < 2cm —— "推得动"语义保留)."""
    box0 = B.V_STALL_EPS

    def slider(v0):
        b = B.PhysicsWorldBridge()
        ground = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                          shape='box', name='大地面')
        ground.collider.friction = 0.5
        box = make_obj(create_cube(1.0), (0, 0.0, 0), primitive='cube',
                       shape='box', mass=1.0, friction=0.5, name='滑盒')
        box.collider.friction = 0.5
        b.build([ground, box])
        box.rigidbody.velocity = E.Point3D(v0, 0.0, 0.0)
        x0 = box.position.x
        t_zero = None
        for i in range(600):
            b.frame(DT)
            sp = math.sqrt(sum(c * c for c in box.rigidbody.velocity))
            if sp < 1e-4:
                t_zero = i * DT
                break
        return b, box, t_zero, box.position.x - x0
    B.V_STALL_EPS = 0.0
    b_off, box_off, tz_off, dx_off = slider(0.5)          # 死带关: 自然滑距
    B.V_STALL_EPS = 0.03
    b_on, box_on, tz_on, dx_on = slider(0.3)              # 死带开: 残留滑动体
    sleep_at = None
    for j in range(180):
        b_on.frame(DT)
        if b_on.active_count == 0:
            sleep_at = j * DT
            break
    b_on2, box_on2, tz_on2, dx_on2 = slider(0.5)          # 死带开: 正常推箱
    B.V_STALL_EPS = box0
    check("11b.残留滑动体 (μ=0.5, v0=0.3m/s) 1s 内速度归 0 且停后入眠",
          tz_on is not None and tz_on < 1.0 and sleep_at is not None,
          "全停=%.3fs 停后%.3fs 入眠" % (tz_on if tz_on is not None else -1.0,
                                        sleep_at if sleep_at is not None else -1.0))
    check("11c.被推箱体 (v0=0.5m/s) 死带不影响自然滑距 (带开/关 |Δ|<2cm)",
          dx_on2 is not None and dx_off is not None and abs(dx_on2 - dx_off) < 0.02,
          "带关滑距=%.4fm 带开滑距=%.4fm" % (dx_off, dx_on2))
    return (tz_on, dx_on2, dx_off)


# ---------------- 12. 无碰撞体动态体自由积分 (B1-修复_b ①: 碰撞器/重力解耦) ----------
def case_free_fall():
    """用户二轮实测"碰撞器+重力=浮空"根因: 桥对 collider 禁用/none 的动态体不建体
    (P2 §4.7'已知差异') -> 世界重力=0 -> 永悬空。修复 = Python 侧积分 (legacy 契约:
    重力与碰撞体无关; legacy 对无碰撞体同样自由移动). 断言联动:
      12a 禁用碰撞器 + 重力: 1s 跌落 ~4.98m (Euler 精确值 -g·dt²·n(n+1)/2)
      12b shape=none 同 12a; Jolt 侧不建体 (仅地面 1 体)
      12c use_gravity=False + 脚本速度 3m/s: 自由滑移 ~3.0m 且 y 不漂 (无摩擦路径)
      12d 播放中恢复碰撞器 -> 转 Jolt 路径仍下落 (ensure_models 差量切换)"""
    # 12a
    b = B.PhysicsWorldBridge()
    ground = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                      shape='box', name='地面')
    box = make_obj(create_cube(1.0), (0, 5.0, 0), primitive='cube',
                   shape='box', mass=1.0, name='无碰盒')
    box.collider.enabled = False                      # 用户"点一次碰撞器"后的真实状态
    b.build([ground, box])
    for _ in range(60):                               # 1s
        b.frame(DT)
    dy_a = 5.0 - box.position.y
    check("12a.碰撞器禁用+重力: 1s 自由跌落 ≈4.98m (legacy/Unity 语义对齐)",
          abs(dy_a - 4.98) < 0.35, "dy=%.3fm" % dy_a)
    # 12b
    b2 = B.PhysicsWorldBridge()
    g2 = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                  shape='box', name='地面2')
    ball = make_obj(create_sphere(0.5), (0, 5, 0), primitive='sphere',
                    shape='none', mass=1.0, name='无碰球')
    b2.build([g2, ball])
    for _ in range(60):
        b2.frame(DT)
    check("12b.shape=none+重力: 同自由下落; Jolt 不建体 (仅地面 1 体)",
          abs(-(ball.position.y - 5.0) - 4.98) < 0.35 and b2.body_count == 1,
          "dy=%.3fm 体数=%d" % (-(ball.position.y - 5.0), b2.body_count))
    # 12c
    b3 = B.PhysicsWorldBridge()
    g3 = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                  shape='box', name='地面3')
    glider = make_obj(create_cube(1.0), (0, 3.0, 0), primitive='cube',
                      shape='box', mass=1.0, use_gravity=False, name='滑体')
    glider.collider.enabled = False
    b3.build([g3, glider])
    glider.rigidbody.velocity = E.Point3D(3.0, 0.0, 0.0)
    for _ in range(60):
        b3.frame(DT)
    check("12c.use_gravity=False+速度3m/s: 自由滑移 ≈3.0m 且竖直零漂",
          abs(glider.position.x - 3.0) < 0.05 and abs(glider.position.y - 3.0) < 1e-6,
          "x=%.3f y=%.4f" % (glider.position.x, glider.position.y))
    # 12d
    b4 = B.PhysicsWorldBridge()
    g4 = make_obj(create_plane(200, 200), (0, -0.5, 0), primitive='cube',
                  shape='box', name='地面4')
    box4 = make_obj(create_cube(1.0), (0, 5.0, 0), primitive='cube',
                    shape='box', mass=1.0, name='切换盒')
    box4.collider.enabled = False
    b4.build([g4, box4])
    for _ in range(30):
        b4.frame(DT)
    box4.collider.enabled = True                      # 播放中恢复碰撞器
    b4.ensure_models([g4, box4])
    for _ in range(60):
        b4.frame(DT)
    check("12d.播放中恢复碰撞器: 转 Jolt 体继续下落 (ensure 差量切换)",
          box4.position.y < 4.0, "y=%.3f (初 5.0)" % box4.position.y)
    return dy_a


# ---------------- main ----------------
if __name__ == '__main__':
    print("=== B1 物理桥用例 (test_physics_bridge.py) | culverin ok:", HAS_CV, "===")
    r = case_land()
    case_gravity()
    case_kinematic()
    case_same_tree()
    case_no_gravity()
    case_build_destroy()
    case_r4()
    case_momentum()
    case_rolling()
    case_p2_guard()
    case_stall()
    case_free_fall()
    print()
    print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
    sys.exit(0 if ok else 1)
