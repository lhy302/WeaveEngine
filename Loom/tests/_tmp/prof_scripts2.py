# -*- coding: utf-8 -*-
"""prof_scripts2.py — update_scripts 内部逐段计时 (2026-10-14)"""
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0] = os.path.join(BASE, 'Loom.py')
os.environ['LOOM_PROFILE'] = '1'
import numpy as np
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
    models = ed.models
    from scripts import get_script
    import script_glue as _sg
    from loom_types import Point3D
    dt = clk.fixed_dt
    N = 300
    # A: 纯遍历 501 物体
    t0=time.perf_counter()
    for _ in range(N):
        for m in models:
            _ = m.scripts
    print("A 遍历501物体=%.3f ms" % ((time.perf_counter()-t0)/N*1000))
    # B: 收集 rotate 项
    rot_items=[]
    for m in models:
        for sc in m.scripts:
            rot_items.append((m,sc,sc._script))
    print("rotate项数:", len(rot_items))
    # C: 装箱(填numpy)
    t0=time.perf_counter()
    for _ in range(N):
        for i,(m,sc,s) in enumerate(rot_items):
            r=m.rotation; v=s.vals
            _=(float(r.x),float(r.y),float(r.z),float(v.get('sx',0)),float(v.get('sy',90)),float(v.get('sz',0)))
    print("C 装箱(读属性)100项=%.3f ms" % ((time.perf_counter()-t0)/N*1000))
    # D: 调 C batch_rotate
    n=len(rot_items)
    rb=np.empty((n,3)); sb=np.empty((n,3)); ob=np.empty((n,3))
    for i,(m,sc,s) in enumerate(rot_items):
        r=m.rotation; v=s.vals
        rb[i]=(r.x,r.y,r.z); sb[i]=(v.get('sx',0),v.get('sy',90),v.get('sz',0))
    t0=time.perf_counter()
    for _ in range(N):
        _sg.batch_rotate(rb, sb, dt, out_rot=ob)
    print("D C_batch_rotate=%0.3f ms" % ((time.perf_counter()-t0)/N*1000))
    # E: 拆箱(写回Point3D)
    t0=time.perf_counter()
    for _ in range(N):
        for i,(m,sc,s) in enumerate(rot_items):
            m.rotation=Point3D(float(ob[i,0]),float(ob[i,1]),float(ob[i,2]))
    print("E 拆箱(写Point3D)100项=%.3f ms" % ((time.perf_counter()-t0)/N*1000))
    # F: 直接调 update_scripts 分解
    t0=time.perf_counter()
    for _ in range(N):
        ed.update_scripts(dt)
    print("F update_scripts整体=%.3f ms" % ((time.perf_counter()-t0)/N*1000))
    ed._stop_parallel()
    import pygame; pygame.quit()

if __name__ == '__main__':
    main()
