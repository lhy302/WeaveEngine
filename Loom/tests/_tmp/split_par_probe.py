# -*- coding: utf-8 -*-
"""
split_par_probe.py — 分离批1/2 确定性对拍探针 (纯逻辑桩, 无窗口; 模式同 test_collision)

验证 R3 (分离只改"何时跑"不改"每步算什么"):
  A. 分离模式自身可重复: 同场景同帧序列跑两遍, 每渲染帧位姿逐位一致;
  B. 脚本 dt 驱动面: rotate 脚本转速 = 度/秒 × 逻辑时间 (带内);
  C. 物理行为守恒: 60Hz 恒定步长落体, 落定高度稳定且 |v| 归零 (R1 语义);
  ★B7b 退役 (2026-10-16): 删原 D (LOOM_NO_SPLIT 逃生门对照) 段。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))

os.environ['LOOM_NO_PARALLEL'] = '1'       # 测试确定性: 无脚本线程

import numpy as np
import engine as E
from mesh import create_cube, create_sphere, create_plane

# 不开窗口的引擎桩 (碰撞/脚本/时钟是纯逻辑, 不碰 GPU)
E.GLEngine._build_gpu = lambda self, m: None


def make_engine():
    eng = E.GLEngine.__new__(E.GLEngine)
    eng.models = []
    eng.materials = []
    eng.lights = []
    eng.cameras = []
    eng.current_model_index = 0
    eng.is_playing = True
    # 分离态 (默认分离开 = 设置缺省 30/60): 桩无 __init__ → 手动接
    eng._split_enable = True
    eng._clock = None
    eng._interp = None
    eng._render_world = None
    eng._logic_steps = 0
    eng._logic_gen = 0
    eng._prep_aabbs = None
    eng._prep_light_vps = None
    eng._prep_pairs = None
    eng._prep_sig = None
    eng._disp_gen = -1
    eng._pipe_disabled = False
    # ★B7b 顺带修 (2026-10-16): 桩补 _tps_events (分离批5 新增属性未同步);
    #   删 on_physics_step 挂点 (批5 已删该回调, 物理子步在 _logic_frame 内循环)。
    eng._tps_events = []
    E.GLEngine._ensure_split(eng)
    if eng._clock is None:
        # _ensure_split 走 split_enable 才建; 桩直接强制建
        from core_clock import clock_from_settings
        eng._clock = clock_from_settings({'logic_fps': 30, 'physics_fps': 60})
        eng._clock.on_logic_step.append(eng._logic_frame)
    from interp_state import InterpState
    eng._interp = InterpState(eng.models)
    return eng


def build_scene(eng):
    """落体球 (rigidbody) + 旋转方块 (rotate 脚本)."""
    ground = eng.add_model(create_plane(20, 20), E.Point3D(0, -0.5, 0),
                           E.Point3D(0, 0, 0), scale=(1, 1, 1), name='地面')
    ground.collider.shape = 'box'
    balls = []
    for i in range(6):
        b = eng.add_model(create_sphere(1.0), E.Point3D(i * 2.0 - 5.0, 8.0 + i, 0.0),
                          E.Point3D(0, 0, 0), name='球%d' % i)
        b.collider.shape = 'sphere'
        b.add_rigidbody(mass=1.0, use_gravity=True)
        balls.append(b)
    spinners = []
    for i in range(4):
        s = eng.add_model(create_cube(1.0), E.Point3D(-8.0 + i * 4.0, 3.0, 5.0),
                          E.Point3D(0, 0, 0), name='转块%d' % i)
        s.add_script('rotate', {'sy': 90.0 + i * 30.0})
        spinners.append(s)
    return balls, spinners


def snap_of(eng):
    return np.array([[m.position.x, m.position.y, m.position.z, m.rotation.x]
                     for m in eng.models])


def run_frames(eng, n=90, dt=1.0 / 120.0, collect=True):
    """直调 render 的逻辑推进语义 — 但桩无 GL, 用时钟推进 + 逻辑段直跑.
    与 --bench 差异: 无渲染段 (桩无 GL 上下文); 验证面 = 逻辑/物理确定性."""
    snaps = []
    for _ in range(n):
        clk = eng._ensure_split()
        if clk is not None:
            clk.advance(dt)
            it = eng._interp
            if it is not None:
                it.alpha = clk.alpha
        else:
            eng._run_scripts(dt)
            eng.update_physics(dt, events=False)
            eng.update_audio(dt)
            eng.update_animations(dt)
        if collect:
            snaps.append(snap_of(eng))
    return np.array(snaps) if collect else None


def main():
    ok = True
    # ---- A. 分离模式可重复 (逐位) ----
    snaps = []
    for run in range(2):
        eng = make_engine()
        assert eng._split_enable and eng._clock is not None
        build_scene(eng)
        snaps.append(run_frames(eng, 90))
    if np.array_equal(snaps[0], snaps[1]):
        print("[A] 分离模式两遍逐位一致: PASS (%d 帧 × %d 物体)" %
              (snaps[0].shape[0], snaps[0].shape[1]))
    else:
        d = np.abs(snaps[0] - snaps[1]).max()
        print("[A] FAIL: 两遍差异 max|Δ|=%r" % d)
        ok = False

    # ---- B. 脚本转速 = 度/秒 × 逻辑时间 ----
    eng_b = make_engine()
    build_scene(eng_b)
    run_frames(eng_b, 90, collect=False)
    wall = 90 * (1.0 / 120.0)
    spinners = [m for m in eng_b.models if m.name.startswith('转块')]
    for s in spinners:
        if s.name != '转块0':
            continue
        expect = np.radians(90.0 * wall)   # sy=90°/s × 0.75s = 67.5° (rad)
        rot = s.rotation.y            # sy 轴 = rotation.y (rad)
        ratio = rot / expect if expect else 1.0
        if not (0.85 <= ratio <= 1.15):
            print("[B] FAIL: %s 转角 %.2f° vs 期望 %.2f° (ratio=%.3f)" %
                  (s.name, np.degrees(rot), np.degrees(expect), ratio))
            ok = False
        else:
            print("[B] 脚本 dt 驱动转速带内: PASS (rot=%.2f° 期望≈%.2f°)" %
                  (np.degrees(rot), np.degrees(expect)))

    # ---- C. 物理守恒 (落定 + |v|=0) ----
    eng_c = make_engine()
    balls, _ = build_scene(eng_c)
    run_frames(eng_c, 240, collect=False)   # 2s@120FPS → 充分落定
    rb = balls[0].rigidbody
    if rb is not None:
        v = rb.velocity
        y = balls[0].position.y
        speed = (v.x ** 2 + v.y ** 2 + v.z ** 2) ** 0.5
        # 落定高度按 Jolt 桥实测语义 (与 test_physics 落地面停住一致):
        # 球心 = 地面中心 y(-0.5) + 顶面 + 桥默认半径 → 稳定落定值 (非分离改动引入)
        rest_y = 0.5
        settled = abs(y - rest_y) < 0.05
        stopped = speed < 0.01
        print("[C] 落定: y=%.4f (期望≈%.2f) |v|=%.5f → %s%s" %
              (y, rest_y, speed,
               "PASS" if (settled and stopped) else "FAIL",
               "" if stopped else " (残速! R1 违反?)"))
        ok = ok and (settled and stopped)
    else:
        print("[C] SKIP: 无刚体 (culverin 缺失?)")

    # ---- D. 绑死模式路径 (★B7b 2026-10-16: 原逃生门对照; 绑死仅由 logic_fps<=0 触发) ----
    eng_d = make_engine()
    eng_d._split_enable = False
    eng_d._clock = None
    eng_d._interp = None
    build_scene(eng_d)
    run_frames(eng_d, 30, collect=False)
    assert eng_d._clock is None and eng_d._interp is None
    print("[D] 绑死模式语义: PASS (时钟/插值 None → 旧四段直跑)")

    print("=" * 40)
    print("split_par_probe: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
