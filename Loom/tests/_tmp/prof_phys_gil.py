# -*- coding: utf-8 -*-
"""prof_phys_gil.py — 物理线程GIL争抢验证 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import moderngl
import editor as editor_mod

ctx = moderngl.create_standalone_context()
ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
ed._external_fb = ctx.detect_framebuffer()
try:
    _g = ed.view.gui.render
    ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE, '保存', '压力测试', '压力_综合_小镇.json'))
ed.toggle_play()
clk = ed._ensure_split()
for _ in range(20):
    ed._logic_frame(clk.fixed_dt)

br = ed._phys_bridge
print("physics bridge:", br, " sub_steps:", clk.sub_steps, " sub_dt:", clk.sub_dt, flush=True)
dt = clk.sub_dt; g = getattr(ed, 'gravity', -9.8)

# ---- 单独计时 pre_step / step / post_step ----
N = 30
for label, fn in (('pre_step', lambda: br.pre_step(dt, g)),
                  ('step', lambda: br.step(dt)),
                  ('post_step', lambda: br.post_step())):
    fn()  # warm
    t0 = time.perf_counter()
    for _ in range(N):
        fn()
    print("  %-12s %.3f ms/次" % (label, (time.perf_counter()-t0)/N*1000), flush=True)

# ---- 物理线程运行中，主线程 render 的耗时（含GIL争抢） ----
print("\n=== 有物理线程: 主线程逐渲染帧耗时 ===", flush=True)
ed._stage_times.clear(); ed._stage_calls.clear()
NF = 60
t0 = time.perf_counter()
for _ in range(NF):
    now = time.perf_counter(); d = min(now - ed.last_frame_time, 0.1)
    ed.last_frame_time = now
    ed.advance_logic(d)
    ed.render(d)
wall_pipe = (time.perf_counter()-t0)/NF*1000
print("  有物理线程 render: %.2f ms/frame" % wall_pipe, flush=True)

# ---- 关物理线程（走 _pipe_disabled 降级标志；★B4c 后 LOOM_NO_PIPE 已删）----
ed._pipe_disabled = True
for _ in range(10):
    now = time.perf_counter(); d = min(now - ed.last_frame_time, 0.1)
    ed.last_frame_time = now; ed.advance_logic(d); ed.render(d)
t0 = time.perf_counter()
for _ in range(NF):
    now = time.perf_counter(); d = min(now - ed.last_frame_time, 0.1)
    ed.last_frame_time = now
    ed.advance_logic(d)
    ed.render(d)
wall_nopipe = (time.perf_counter()-t0)/NF*1000
print("  无物理线程 render: %.2f ms/frame" % wall_nopipe, flush=True)

ed._stop_parallel()
import pygame; pygame.quit()
print("\n完成", flush=True)
