# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""纹理/cubemap 换 GL ctx: 释放旧资源 + 弱引用归属 (不误用失效纹理)."""
import gc
import numpy as np

from loom_texture import Texture
from loom_cubemap import Cubemap

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

class FakeTex:
    def __init__(self, kind):
        self.kind = kind
        self.released = False
        self.writes = []
    def write(self, *a):
        self.writes.append(a)
    def build_mipmaps(self):
        pass
    def release(self):
        self.released = True
    def use(self, unit=0):
        pass

class FakeCtx:
    def __init__(self):
        self.textures = []
    def texture(self, size, components, dtype=None, internal_format=None):
        t = FakeTex("2d")
        self.textures.append(t)
        return t
    def texture_cube(self, size, components, dtype=None):
        t = FakeTex("cube")
        self.textures.append(t)
        return t

# ---- Texture ----
tex = Texture.from_rgba(2, 2, np.full((2, 2, 4), 255, dtype=np.uint8),
                        mipmaps=False)
c1 = FakeCtx()
t1 = tex.ensure_gl(c1)
check("ctx1 创建 GPU 纹理", tex.gl_tex is t1 and not t1.released)
c2 = FakeCtx()
t2 = tex.ensure_gl(c2)
check("换 ctx 释放旧纹理", t1.released and tex.gl_tex is t2)
check("同 ctx 复用纹理", tex.ensure_gl(c2) is t2)
c3 = FakeCtx()
t3 = tex.ensure_gl(c3)
check("第二次换 ctx 释放 t2", t2.released and tex.gl_tex is t3)
ref = tex._gl_ctx_ref
check("ctx 归属用弱引用", ref is not None and ref() is c3)
del c3
gc.collect()
check("ctx 回收后弱引用失效", ref() is None)
c4 = FakeCtx()
t4 = tex.ensure_gl(c4)
check("旧 ctx 失效后重建纹理", t4 is not t3 and t3.released)
tex.release()
check("release 清空纹理与 ctx 引用", tex.gl_tex is None and tex._gl_ctx_ref is None)

# ---- Cubemap ----
cube = Cubemap.from_solid("#FF0000", size=2)
c5 = FakeCtx()
k1 = cube.ensure_gl(c5)
c6 = FakeCtx()
k2 = cube.ensure_gl(c6)
check("cubemap 换 ctx 释放旧纹理", k1.released and cube.gl_tex is k2)
check("cubemap 同 ctx 复用", cube.ensure_gl(c6) is k2)
cube.release()
check("cubemap release 清空", cube.gl_tex is None and cube._gl_ctx_ref is None)

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
