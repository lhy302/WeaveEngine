# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_texture import Texture

ctx = moderngl.create_standalone_context()
arr = np.zeros((32,32,4), dtype=np.uint8)

print("=== wrap=repeat (默认) ===")
t = Texture.from_rgba(32,32,arr, wrap='repeat')
g = t.ensure_gl(ctx); print("  repeat_x=", g.repeat_x, " filter=", g.filter)
print("=== wrap=clamp ===")
t = Texture.from_rgba(32,32,arr, wrap='clamp')
g = t.ensure_gl(ctx); print("  repeat_x=", g.repeat_x, " filter=", g.filter)
print("=== filter=point ===")
t = Texture.from_rgba(32,32,arr, filter_mode='point')
g = t.ensure_gl(ctx); print("  filter=", g.filter, " (应含 NEAREST)")
print("=== filter=bilinear ===")
t = Texture.from_rgba(32,32,arr, filter_mode='bilinear')
g = t.ensure_gl(ctx); print("  filter=", g.filter)
print("=== aniso=8 ===")
t = Texture.from_rgba(32,32,arr, aniso=8.0)
g = t.ensure_gl(ctx); print("  anisotropy=", g.anisotropy)

print("=== max_size 缩放 ===")
import pygame
pygame.init()
surf = pygame.Surface((256, 128)); surf.fill((10,20,30))
p = os.path.join(BASE,'tests','_tmp','_tex_maxsize.png')
pygame.image.save(surf, p)
t = Texture.from_file(p, max_size=64)
print("  原始 256x128, max_size=64 ->", t.width, "x", t.height, " (应 64x32)")
t2 = Texture.from_file(p, max_size=0)
print("  max_size=0 ->", t2.width, "x", t2.height, " (不缩放)")
os.remove(p)
ctx.release()
print("完成")
