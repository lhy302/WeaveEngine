# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_texture import Texture

print("=== moderngl 纹理 mip 相关属性 ===")
ctx = moderngl.create_standalone_context()
t = ctx.texture((64, 64), 4, dtype='f1')
t.write(np.zeros((64,64,4), dtype=np.uint8).tobytes())
print("  dir(tex) mip/level/filter 相关:", [a for a in dir(t) if 'mip' in a.lower() or 'level' in a.lower() or 'filter' in a.lower()])
print("  filter 默认:", t.filter)
t.build_mipmaps()
print("  build_mipmaps 后 filter:", t.filter)
import moderngl as m
t.filter = (m.LINEAR_MIPMAP_LINEAR, m.LINEAR)
print("  设 LINEAR_MIPMAP_LINEAR 后:", t.filter)
try:
    print("  tex.mipmaps =", t.mipmaps)
except Exception as e:
    print("  tex.mipmaps 不可读:", e)
print("  tex.levels? ", getattr(t, 'levels', 'N/A'))
t.release()

print("=== Texture.ensure_gl 的 mipmap 行为 ===")
arr = np.random.default_rng(0).integers(0, 255, (128, 128, 4), dtype=np.uint8)
tex = Texture.from_rgba(128, 128, arr, name='测试')
gt = tex.ensure_gl(ctx)
print("  ensure_gl 返回:", gt is not None)
print("  filter:", gt.filter, " (应含 MIPMAP)")
try:
    print("  mipmaps:", gt.mipmaps)
except Exception as e:
    print("  mipmaps 不可读:", e)
gt.release(); ctx.release()
print("完成")
