# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)

def run(no_skip):
    if no_skip: os.environ.pop('LOOM_PHYS_SKIP_SLEEP', None)
    else: os.environ['LOOM_PHYS_SKIP_SLEEP']='1'
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
    N=40
    t0=time.perf_counter()
    for _ in range(N): br.post_step()
    per=(time.perf_counter()-t0)/N*1000
    fp=[(round(m.position.x,9),round(m.position.y,9),round(m.position.z,9)) for m in ed.models[:1200]]
    ed._stop_parallel()
    import pygame; pygame.quit()
    return per, fp

p1,fp1=run(True)   # 不跳过
p2,fp2=run(False)  # 跳过睡眠
print("不跳过: %.3f ms" % p1)
print("跳过睡眠: %.3f ms" % p2)
diff=sum(1 for a,b in zip(fp1,fp2) if a!=b)
print("位姿差异行数: %d / %d" % (diff, len(fp1)))
print("完成")
