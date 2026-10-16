# -*- coding: utf-8 -*-
"""prof_scripts4.py — batch_rotate 三环境对比 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
import numpy as np
import ctypes
import script_glue as _sg

def bench(label, fn, N=300):
    fn()  # warm
    t0 = time.perf_counter()
    for _ in range(N): fn()
    per = (time.perf_counter()-t0)/N*1000
    print("  %-40s %.4f ms" % (label, per))
    return per

def main():
    n = 100
    rb = np.zeros((n,3)); sb = np.zeros((n,3)); ob = np.zeros((n,3)); sb[:,1]=90.0
    h = _sg.handle()
    pd = ctypes.POINTER(ctypes.c_double)
    fn = h.get_fn('loom_script_batch_rotate', ctypes.c_int32, [pd,pd,ctypes.c_double,ctypes.c_int64,pd])
    print("=== 纯环境(无引擎) ===")
    bench("raw fn", lambda: fn(rb.ctypes.data_as(pd), sb.ctypes.data_as(pd), ctypes.c_double(1/30), ctypes.c_int64(n), ob.ctypes.data_as(pd)))
    bench("_sg.batch_rotate", lambda: _sg.batch_rotate(rb, sb, 1/30, out_rot=ob))
    bench("get_fn only", lambda: h.get_fn('loom_script_batch_rotate', ctypes.c_int32, [pd,pd,ctypes.c_double,ctypes.c_int64,pd]))

    print("\n=== 引擎上下文 ===")
    import moderngl
    import editor as editor_mod
    ctx = moderngl.create_standalone_context()
    ed = editor_mod.EditorApp(1280, 800, ctx=ctx)
    ed._external_fb = ctx.detect_framebuffer()
    try:
        _g = ed.view.gui.render
        ed.view.gui.render = lambda *a, **k: _g(target=ed._external_fb)
    except Exception: pass
    ed.load_scene(os.path.join(BASE, '保存', '压测500混合.json'))
    ed.toggle_play()
    clk = ed._ensure_split()
    for _ in range(30): ed._logic_frame(clk.fixed_dt)
    bench("raw fn (engine ctx)", lambda: fn(rb.ctypes.data_as(pd), sb.ctypes.data_as(pd), ctypes.c_double(1/30), ctypes.c_int64(n), ob.ctypes.data_as(pd)))
    bench("_sg.batch_rotate (engine ctx)", lambda: _sg.batch_rotate(rb, sb, 1/30, out_rot=ob))
    bench("update_scripts (engine ctx)", lambda: ed.update_scripts(clk.fixed_dt), N=100)
    ed._stop_parallel()
    import pygame; pygame.quit()

if __name__ == '__main__':
    main()
