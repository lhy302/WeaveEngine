# -*- coding: utf-8 -*-
import os, sys, time, statistics
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_物理_动态1200刚体.json'))
ed.toggle_play(); clk=ed._ensure_split()
for _ in range(40): ed._logic_frame(clk.fixed_dt)
br=ed._phys_bridge

def med(env, N=80, R=7):
    for k in ('LOOM_PHYS_NO_FRICT','LOOM_PHYS_NO_WRITE'): os.environ.pop(k,None)
    for k,v in env.items(): os.environ[k]=v
    runs=[]
    for _ in range(R):
        br.post_step()
        t0=time.perf_counter()
        for _ in range(N): br.post_step()
        runs.append((time.perf_counter()-t0)/N*1000)
    return statistics.median(runs)

base=med({}); no_f=med({'LOOM_PHYS_NO_FRICT':'1'})
no_w=med({'LOOM_PHYS_NO_WRITE':'1'}); no_b=med({'LOOM_PHYS_NO_FRICT':'1','LOOM_PHYS_NO_WRITE':'1'})
print("post_step 完整:   %.3f ms" % base)
print("  跳过摩擦段:     %.3f ms  (省 %.3f)" % (no_f, base-no_f))
print("  跳过写回段:     %.3f ms  (省 %.3f)" % (no_w, base-no_w))
print("  两者都跳:       %.3f ms  (省 %.3f)" % (no_b, base-no_b))
ed._stop_parallel()
import pygame; pygame.quit()
print("完成")
