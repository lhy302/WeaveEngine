# -*- coding: utf-8 -*-
"""prof_logicframe.py — 逻辑帧各段耗时 + prep 复用验证探针 (2026-10-14)

目标: 回答"逻辑帧里哪些重活每帧都在重算、即使物体没动"。
方法: 无头建 EditorApp + 加载 压测500混合 场景 + toggle_play,
      连续跑 _logic_frame, 读 LOOM_PROFILE 插桩的 stage_times;
      再冻结 _logic_gen 连续调 _logic_prep, 验证复用机制是否被 gen bump 挡住。
不修改引擎: 只读插桩 + 直接调用。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'

import moderngl
import editor as editor_mod


def main():
    scene = os.path.join(BASE, '保存', '压测500混合.json')
    print("scene:", scene, flush=True)
    ctx = moderngl.create_standalone_context()
    ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
    ed._external_fb = ctx.detect_framebuffer()
    try:
        _g = ed.view.gui.render
        ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
    except Exception as e:
        print("view.gui.render patch skipped:", repr(e), flush=True)
    ed.load_scene(scene)
    print("models:", len(ed.models), "lights:", len(ed.lights), flush=True)

    for _ in range(20):
        now = time.perf_counter()
        dt = min(now - ed.last_frame_time, 0.1)
        ed.last_frame_time = now
        ed.render(dt)
    ed.toggle_play()
    clk = ed._ensure_split()
    print("split clock:", clk is not None, "is_playing:", ed.is_playing,
          "phys_pipe:", getattr(ed, '_phys_pipe', None), flush=True)
    if clk is None:
        from core_clock import clock_from_settings
        clk = ed._clock = clock_from_settings({'logic_fps': 30})
        clk.on_logic_step.append(ed._logic_frame)

    for _ in range(60):
        ed._logic_frame(clk.fixed_dt)

    # ---- 测1: 连续逻辑帧各段耗时 ----
    ed._stage_times.clear()
    ed._stage_calls.clear()
    N = 300
    t0 = time.perf_counter()
    for _ in range(N):
        ed._logic_frame(clk.fixed_dt)
    wall = time.perf_counter() - t0
    snap = ed.profile_snapshot()
    print("\n=== 逻辑帧各段 (per-frame) N=%d  wall=%.3f ms/frame ===" % (N, wall / N * 1000), flush=True)
    for k in sorted(snap['times']):
        per = snap['times'][k] / N
        print("  %-22s %8.4f ms   calls/frame=%.2f" % (k, per, snap['calls'].get(k, 0) / N), flush=True)

    # ---- 测2: prep 复用验证 ----
    print("\n=== prep 复用验证 ===", flush=True)
    ed._logic_gen = getattr(ed, '_logic_gen', 0)
    ed._prep_sig = None
    t0 = time.perf_counter()
    ed._logic_prep(clk.fixed_dt)
    t1 = time.perf_counter() - t0
    t0 = time.perf_counter()
    ed._logic_prep(clk.fixed_dt)   # gen 未变 -> 应命中跳过
    t2 = time.perf_counter() - t0
    ed._logic_gen += 1
    t0 = time.perf_counter()
    ed._logic_prep(clk.fixed_dt)   # gen 变 -> 重算
    t3 = time.perf_counter() - t0
    print("  prep 首次(算)=%.3f ms  二次(同gen,应命中)=%.3f ms  bumpgen后(重算)=%.3f ms"
          % (t1 * 1000, t2 * 1000, t3 * 1000), flush=True)

    # ---- 测3: prep 子段单独计时 ----
    print("\n=== prep 子段单独计时 ===", flush=True)
    models = ed.models
    fw = getattr(ed, '_frame_world', None)
    if fw is None:
        fw = ed.compute_world_matrices(models)
        ed._frame_world = fw
    t0 = time.perf_counter()
    for _ in range(20):
        a = ed._model_aabbs_par(models, fw, visible_only=False)
    print("  aabbs(full)    = %.3f ms" % ((time.perf_counter() - t0) / 20 * 1000), flush=True)
    t0 = time.perf_counter()
    for _ in range(20):
        v = ed._compute_light_vps(a)
    print("  light_vps      = %.3f ms" % ((time.perf_counter() - t0) / 20 * 1000), flush=True)
    t0 = time.perf_counter()
    for _ in range(20):
        w = ed.compute_world_matrices(models)
    print("  world_matrices = %.3f ms" % ((time.perf_counter() - t0) / 20 * 1000), flush=True)

    ed._stop_parallel()
    import pygame
    pygame.quit()
    print("\n完成 (进程即将退出)", flush=True)


if __name__ == '__main__':
    main()
