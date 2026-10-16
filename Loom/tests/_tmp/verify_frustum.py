# -*- coding: utf-8 -*-
import os, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import ast
ast.parse(open(os.path.join(BASE,'loom_render.py'),encoding='utf-8').read()); print("parse ok")
sys.argv[0]=os.path.join(BASE,'Loom.py')
import moderngl, editor as editor_mod
ctx=moderngl.create_standalone_context()
ed=editor_mod.EditorApp(1280,800,ctx=ctx); ed._external_fb=ctx.detect_framebuffer()
try:
    _g=ed.view.gui.render; ed.view.gui.render=lambda* a,**k:_g(target=ed._external_fb)
except Exception: pass
ed.load_scene(os.path.join(BASE,'保存','压力测试','压力_综合_小镇.json'))
# 多渲染几帧让 VP 就位
for _ in range(30):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
mbn = getattr(ed, '_main_bucket_n', {})
total_all = sum(len(idxs) for _,idxs in ed._render_buckets)
total_main = sum(mbn.values())
print("桶数=%d  全量实例=%d  主pass可见=%d  (剔%.0f%%)" % (
    len(ed._render_buckets), total_all, total_main, 100*(1-total_main/max(total_all,1))))
# 对比: 无剔除时主pass=全量 (★B7b 2026-10-16: 改设置项 _frustum_cull=False;
#   原 LOOM_NO_FRUSTUM env 已退役)
ed._frustum_cull = False
for _ in range(5):
    now=time.perf_counter(); d=min(now-ed.last_frame_time,0.1); ed.last_frame_time=now; ed.render(d)
mbn2 = getattr(ed, '_main_bucket_n', {})
print("排错后门(无剔除) 主pass=%d" % sum(mbn2.values()))
ed._stop_parallel(); import pygame; pygame.quit()
print("完成")
