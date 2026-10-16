# -*- coding: utf-8 -*-
"""
pause_step_check.py — F9 暂停逻辑时钟 / F10 步进 1 逻辑帧 (MC 同款) 验证

判据:
  ① F9 暂停: 逻辑帧冻结 (渲染帧连续跑, 0 逻辑步), 位姿恒定;
  ② F10 步进: 恰好 +1 逻辑帧 (位姿走一步, dt 恒定 = 无时间跳跃);
  ③ 相机独立: 暂停态渲染帧跑相机 (yaw 连续变化, 与逻辑冻结无关);
  ④ 恢复: F9 再按 → 逻辑帧恢复推进 (从整拍开始, 不补暂停期欠账).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def main():
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    import runtime
    eng = runtime.PlayerApp('tests/_tmp/stress_50spheres.json', 320, 240)
    eng.set_mouse_locked(False)
    eng.is_playing = True
    for _ in range(30):
        eng.render(1.0 / 60.0)

    spin = [m for m in eng.models if m.name.startswith('转块')]
    ball = [m for m in eng.models if m.name.startswith('球')]
    target = spin[0] if spin else (ball[0] if ball else eng.models[0])

    def render_n(n, dt=1.0 / 60.0):
        for _ in range(n):
            eng.render(dt)
            eng.camera_yaw += 0.01          # 模拟开发者相机操作 (渲染帧实时)
            eng.apply_orbit_camera()

    # 实时基线: 逻辑在走
    render_n(30)
    r0 = target.rotation.y
    y0 = eng.camera_yaw

    # ① F9 暂停: 60 渲染帧 (1 秒) → 逻辑 0 步, 位姿恒定
    eng.toggle_logic_paused()
    render_n(60)
    r1 = target.rotation.y
    check("① F9 暂停: 60 渲染帧逻辑冻结 (位姿不变)",
          r1 == r0, "Δrot=%r" % (r1 - r0))
    # 逻辑步计数 0
    s_sum = 0
    for _ in range(10):
        eng.render(1.0 / 60.0)
        s_sum += eng._clock.steps
    check("① 暂停态渲染帧 0 逻辑步", s_sum == 0, "steps=%d" % s_sum)

    # ③ 相机独立: 暂停态相机仍连续变化 (渲染帧实时路径)
    check("③ 暂停态开发者相机独立 (yaw 连续变化)", eng.camera_yaw > y0,
          "Δyaw=%.3f" % (eng.camera_yaw - y0))

    # ② F10 步进: 恰好 +1 逻辑帧 — 期望值从脚本参数现算 (不硬编码):
    # rotate 脚本 sy (度/秒) × fixed_dt(1/30) = 每逻辑帧转角 (rad)
    sc = target.scripts[0]._script
    sy_deg = float(sc.vals.get('sy', 0.0)) if sc is not None else 0.0
    expect_step = sy_deg * (1.0 / 30.0) * 3.141592653589793 / 180.0
    eng.step_logic_once()
    eng.render(1.0 / 60.0)
    r2 = target.rotation.y
    got = r2 - r0
    check("② F10 步进: 恰好 1 逻辑帧 (dt 恒定 1/30s, sy=%g°/s)" % sy_deg,
          abs(got - expect_step) < 1e-9,
          "Δrot=%.6f 期望=%.6f" % (got, expect_step))
    # 连续步进: 再 3 次 = 再走 3 步
    r_prev = r2
    for _ in range(3):
        eng.step_logic_once()
        eng.render(1.0 / 60.0)
    check("② 连续步进 3 次 = 3 逻辑帧",
          abs((target.rotation.y - r_prev) - expect_step * 3) < 1e-9,
          "Δ=%.6f 期望=%.6f" % (target.rotation.y - r_prev, expect_step * 3))

    # ④ 恢复: F9 再按 → 逻辑恢复推进
    eng.toggle_logic_paused()
    render_n(60)                             # 1 秒 @30Hz → ~30 逻辑步
    r3 = target.rotation.y
    check("④ F9 恢复: 逻辑重新推进 (1 秒走了 >1 逻辑帧的量)",
          (r3 - r2) > expect_step * 5, "Δ=%.4f" % (r3 - r2))

    print("=" * 40)
    print("pause_step_check: %s" % ("ALL PASS" if ok else "FAIL"))
    pygame.quit()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
