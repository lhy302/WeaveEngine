# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_texture import Texture

ctx = moderngl.create_standalone_context()
arr = np.zeros((32,32,4), dtype=np.uint8)
arr[:,:,0]=200; arr[:,:,1]=100; arr[:,:,2]=50; arr[:,:,3]=255

print("=== 各压缩格式 GL 纹理 ===")
for fmt in ('none','rgb24','rgb565','rgba4444','rgb5a1'):
    t = Texture.from_rgba(32,32,arr, compression=fmt)
    g = t.ensure_gl(ctx)
    print("  %-10s -> components=%d  size=%s" % (fmt, g.components, g.size))

print("=== 显存位深 (由 internal_format 决定) ===")
for fmt, (ifmt, ncomp, bpp) in Texture.COMPRESSION_FORMATS.items():
    print("  %-10s: %d bpp (相对 RGBA8 32bpp 省 %.0f%%)" % (fmt, bpp, 100*(1-bpp/32)))

print("=== 序列化含 compression ===")
import sceneio
from loom_material import Material
mat = Material(color='#FF0000')
mat.albedo = Texture.from_rgba(16,16,np.zeros((16,16,4),dtype=np.uint8), compression='rgb565')
d = sceneio._emit_material(mat)
print("  compression:", d['albedo'].get('compression'))

print("=== 无效压缩格式回退 none ===")
t = Texture.from_rgba(8,8,np.zeros((8,8,4),dtype=np.uint8), compression='bogus')
print("  bogus ->", t.compression, "(应 none)")
ctx.release()
print("完成")
