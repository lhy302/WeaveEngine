# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl, numpy as np
ctx = moderngl.create_standalone_context()
print("=== ctx.extensions ===")
ext = ctx.extensions
print("类型:", type(ext), " 条数:", len(ext))
comp = [e for e in ext if any(k in e.lower() for k in ('compress','s3tc','dxt','bptc','astc','etc','rgtc'))]
print("压缩相关扩展:", comp if comp else "(无)")

print("=== internal_format 降位深测试 ===")
# GL 常量: GL_RGB=0x1907, GL_RGBA=0x1908, GL_RGB5_A1=0x8057, GL_RGB565=0x8D62, GL_RGBA4=0x8056
for name, fmt, comp_n, bpp in [
    ('RGB5_A1', 0x8057, 4, 2), ('RGB565', 0x8D62, 3, 2), ('RGBA4', 0x8056, 4, 2),
    ('R8', 0x8229, 1, 1), ('RG8', 0x822B, 2, 2),
]:
    try:
        t = ctx.texture((16,16), comp_n, dtype='f1', internal_format=fmt)
        print("  %s internal_format OK: components=%d" % (name, t.components))
    except Exception as e:
        print("  %s 失败: %s" % (name, e))

print("=== mglo 底层对象 ===")
print("  mglo 类型:", type(ctx.mglo))
print("  mglo 属性:", [a for a in dir(ctx.mglo) if not a.startswith('_')][:20])
ctx.release()
print("完成")
