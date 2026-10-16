# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl
print("moderngl 全部公开名:", [a for a in dir(moderngl) if not a.startswith('_')])
ctx = moderngl.create_standalone_context()
print("ctx 全部方法:", [m for m in dir(ctx) if not m.startswith('_')])
# 试 RGB (3 components) —— 无 alpha 纹理省 25% 显存
print("=== 试 RGB 3 分量纹理 ===")
try:
    import numpy as np
    t = ctx.texture((16,16), 3, dtype='f1')
    data = np.zeros((16,16,3), dtype=np.uint8)
    t.write(data.tobytes())
    print("  RGB 纹理 OK: components=", t.components, " size=", t.size)
except Exception as e:
    print("  RGB 失败:", e)
# 试 internal_format 指定压缩 (用真实 GL 常量)
print("=== 试 glCompressedTexImage2D 路径 (moderngl internal_format) ===")
import ctypes
try:
    # 用 moderngl 底层 gl 调用? 先看 ctx 有无 gl 访问
    print("  ctx.gl? ", hasattr(ctx, 'gl'))
    print("  ctx.mglo? ", hasattr(ctx, 'mglo'))
except Exception as e:
    print("  ", e)
ctx.release()
print("完成")
