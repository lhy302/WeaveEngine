# -*- coding: utf-8 -*-
"""prof_scripts.py — 脚本段分解探针 (2026-10-14)
分解 update_scripts 的 11.65ms: 各 script_id 数量 + C分流 vs 通用Python 耗时。
"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import moderngl
import editor as editor_mod

def main():
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
    for _ in range(60):
        ed._logic_frame(clk.fixed_dt)
    # 统计脚本类型
    from collections import Counter
    c = Counter()
    n_with = 0
    for m in ed.models:
        if m.scripts:
            n_with += 1
            for sc in m.scripts:
                c[sc.script_id] += 1
    print("有脚本物体:", n_with, "/", len(ed.models))
    print("脚本类型分布:", dict(c))
    import script_glue as _sg
    print("script.dll handle:", _sg.handle() is not None)   # ★B3: disabled() 已删
    # 单独计时 update_scripts
    N = 200
    t0 = time.perf_counter()
    for _ in range(N):
        ed.update_scripts(clk.fixed_dt)
    print("update_scripts = %.3f ms/call" % ((time.perf_counter()-t0)/N*1000))
    ed._stop_parallel()
    import pygame; pygame.quit()

if __name__ == '__main__':
    main()
