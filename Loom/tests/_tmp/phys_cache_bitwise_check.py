# -*- coding: utf-8 -*-
"""phys_cache_bitwise_check.py — dmb 跨子步缓存位形逐位对拍 (2026-09-07)

修复版 (缓存路径) vs 强制 miss (每子步清缓存 = 旧路径) — 同输入 100 逻辑帧,
对比全部模型 pos/rot 逐位一致。缓存语义等价性的端到端闸门。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'

import numpy as np
import moderngl
from editor import EditorApp


def run(force_miss, frames=100):
    ctx = moderngl.create_standalone_context()
    e = EditorApp(320, 240, ctx=ctx)
    e._external_fb = ctx.detect_framebuffer()
    _og = e.view.gui.render
    e.view.gui.render = (lambda *a, **kw: _og(target=e._external_fb))
    e.load_scene(os.path.join('保存', '压测500混合.json'))
    e.toggle_play()
    for _ in range(10):
        e.advance_logic(0.05)
        e.render(0.05)
    br = e._phys_bridge
    if force_miss:
        orig = br._dirty_mask_batch

        def w(entries):
            br._dmb_cache = None          # 强制 miss = 旧路径
            return orig(entries)
        br._dirty_mask_batch = w
    for _ in range(frames):
        e.advance_logic(0.05)
    snap = [(m.position.x, m.position.y, m.position.z,
             m.rotation.x, m.rotation.y, m.rotation.z) for m in e.models]
    e.toggle_play()
    e._stop_parallel()
    return snap


s_cached = run(False)
s_forced = run(True)
a = np.array(s_cached)
b = np.array(s_forced)
same = bool((a == b).all())
maxdiff = float(np.abs(a - b).max())
print("100 逻辑帧后位形: 逐位一致 = %s | maxdiff = %.3e" % (same, maxdiff))
print("总结果:", "ALL PASS ✅" if same else "有 FAIL ❌")
sys.exit(0 if same else 1)
