# -*- coding: utf-8 -*-
r"""gpu_probe.py — GPU 利用率采样播放态 (诊断批): bench 路径 vs Qt 播放态.

nvidia-smi 0.15s 轮询; PlayerApp (bench 等价) 分离模式 unlimited 跑 8s,
记录 GPU% 与 FPS. 回答"GPU 只在 50 帧上下徘徊没有吃满"的 GPU 侧证据.
"""
import os
import sys
import time
import threading
import queue
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'

import pygame                                   # noqa: E402
pygame.init()
pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)


def gpu_sampler(stop_ev, q):
    while not stop_ev.is_set():
        try:
            out = subprocess.run(
                ['nvidia-smi', '--query-gpu=utilization.gpu',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            q.put(float(out.stdout.strip().splitlines()[0]))
        except Exception:
            pass
        stop_ev.wait(0.15)


def main():
    scene = os.path.join(BASE, 'tests', '_tmp', 'stress_500spheres.json')
    import runtime
    eng = runtime.PlayerApp(scene, 1024, 768)
    eng.set_mouse_locked(False)
    from engine import gc_play_enter
    for _ in range(40):
        eng.render(1.0 / 120.0)
    gc_play_enter()

    stop_ev = threading.Event()
    gq = queue.Queue()
    gth = threading.Thread(target=gpu_sampler, args=(stop_ev, gq), daemon=True)
    gth.start()

    eng._stage_times.clear()
    N = 400
    t0 = time.perf_counter()
    steps = psteps = 0
    for _ in range(N):
        eng.render(1.0 / 120.0)
        clk = getattr(eng, '_clock', None)
        if clk is not None:
            steps += clk.steps
            psteps += clk.phys_steps
    wall = time.perf_counter() - t0
    stop_ev.set()
    gth.join(timeout=2)
    gpus = []
    try:
        while True:
            gpus.append(gq.get_nowait())
    except queue.Empty:
        pass
    fps = N / wall
    print("\n[PlayerApp 分离] %d 帧 FPS=%.1f (帧 %.2f ms) 逻辑步/帧=%.2f 物理步/帧=%.2f" % (
        N, fps, wall / N * 1000, steps / N, psteps / N))
    if gpus:
        print("GPU 利用率: 平均 %.1f%% 峰值 %.1f%% 最低 %.1f%% (%d 样本)" % (
            sum(gpus) / len(gpus), max(gpus), min(gpus), len(gpus)))
    st = eng._stage_times
    tot = 0.0
    for k in ('logic_step', 'interp', 'physics', 'pipe_wait', 'world_matrices',
              'aabbs', 'shadow_prep', 'collide_pairs', 'buckets', 'dispatch'):
        v = st.get(k, 0.0) / N
        tot += v
        print("  %-18s %7.2f ms/帧" % (k, v))
    print("  已插桩合计         %7.2f ms/帧 (帧 %.2f) 未插桩=%.2f" % (
        tot, wall / N * 1000, max(0, wall / N * 1000 - tot)))
    eng._stop_parallel()
    pygame.quit()
    print("完成。")


if __name__ == '__main__':
    main()
