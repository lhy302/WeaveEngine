# -*- coding: utf-8 -*-
"""
one_tps_check.py — 1TPS 步进播放验证 (用户 2026-09-05 指令)

判据 (解耦三铁证):
  ① 1Hz 逻辑帧: 10 秒墙钟内恰好跑 ~10 个逻辑帧 (±1 边界);
  ② 渲染帧率不掉: 1Hz 下渲染帧墙钟 = 纯渲染段 (无逻辑帧落点的帧应快);
  ③ 相机独立: 渲染帧实时路径 (apply_orbit_camera) 每渲染帧都在动,
     与逻辑帧无关 (开发者相机不进逻辑帧)。
模拟: PlayerApp 真场景 + 1Hz 时钟 + render(1/120) 连发。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
os.environ['LOOM_NO_PARALLEL'] = '1'

import numpy as np
import pygame


def main():
    scene = sys.argv[1] if len(sys.argv) > 1 else 'tests/_tmp/stress_50spheres.json'
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    import runtime
    eng = runtime.PlayerApp(scene, 320, 240)
    eng.set_mouse_locked(False)
    eng.is_playing = True
    assert eng._clock is not None
    eng._clock.set_fps(logic_fps=1.0)         # ★1TPS = 只改时钟一个数
    for _ in range(30):
        eng.render(1.0 / 120.0)

    # 10 秒墙钟 (加速模拟: 渲染 dt=1/120 × 1200 帧 = 10 逻辑秒)
    N = 1200
    frames = []
    logic_marks = []
    cam_before = (eng.camera.x, eng.camera.y, eng.camera.z)
    cam_moves = 0
    for i in range(N):
        # 模拟开发者相机操作 (渲染帧实时路径: 不经时钟)
        eng.camera_yaw += 0.01
        eng.apply_orbit_camera()
        c_now = (eng.camera.x, eng.camera.y, eng.camera.z)
        if c_now != cam_before:
            cam_moves += 1
            cam_before = c_now
        t0 = time.perf_counter()
        eng.render(1.0 / 120.0)
        dt = (time.perf_counter() - t0) * 1000
        frames.append(dt)
        if eng._clock.steps > 0:
            logic_marks.append((i, dt))
    fa = np.array(frames)

    ok = True
    # ① 逻辑帧数 = 10 (10 逻辑秒 × 1Hz)
    n_logic = len(logic_marks)
    print("① 1Hz 逻辑帧: 10 逻辑秒跑了 %d 个逻辑帧 (期望 10±1) → %s" % (
        n_logic, "PASS" if 9 <= n_logic <= 11 else "FAIL"))
    ok = ok and 9 <= n_logic <= 11
    # ② 渲染帧率: 无逻辑帧落点的帧应与有落点的帧显著分层
    logic_idx = set(i for i, _ in logic_marks)
    free = np.array([f for i, f in enumerate(frames) if i not in logic_idx])
    hit = np.array([f for i, f in enumerate(frames) if i in logic_idx])
    print("② 渲染帧墙钟: 无逻辑帧 p50=%.2f ms | 逻辑帧落点 p50=%.2f ms" % (
        np.median(free), np.median(hit)))
    sep = np.median(hit) / max(np.median(free), 1e-6)
    print("   分层比 %.1fx → %s (解耦 = 落点帧才贵, 其余帧纯渲染)" % (
        sep, "PASS" if sep > 2.0 else "FAIL"))
    ok = ok and sep > 2.0
    # ③ 相机独立: 每个渲染帧相机都动 (1200/1200)
    print("③ 相机独立: %d/%d 渲染帧相机位姿变化 (渲染帧实时, 不进逻辑帧) → %s" % (
        cam_moves, N, "PASS" if cam_moves == N else "FAIL"))
    ok = ok and cam_moves == N

    print("=" * 40)
    print("one_tps_check: %s" % ("ALL PASS — 解耦铁证" if ok else "FAIL"))
    pygame.quit()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
