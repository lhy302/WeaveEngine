# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl, numpy as np
ctx = moderngl.create_standalone_context()
print("moderngl 版本:", moderngl.__version__)
# 压缩相关常量
comp = [a for a in dir(moderngl) if 'COMPRESS' in a or 'DXT' in a or 'S3TC' in a or 'BC' in a.upper() or 'ASTC' in a or 'ETC' in a]
print("moderngl 压缩常量:", comp)
# ctx 的纹理方法
print("ctx 纹理相关方法:", [m for m in dir(ctx) if 'texture' in m.lower() or 'compress' in m.lower()])
# texture 方法签名
import inspect
try:
    print("ctx.texture 签名:", inspect.signature(ctx.texture))
except Exception as e:
    print("签名取不到:", e)
# 试创建压缩纹理
print("=== 试 ctx.texture(compressed) ===")
try:
    # moderngl 压缩纹理: ctx.texture(size, components, data, dtype) 不支持压缩;
    # 需用 ctx.texture(size, comp, data) 的其它路径
    t = ctx.texture((16,16), 4, dtype='f1')
    print("普通纹理 OK, 可写 compress?", hasattr(t, 'compress'))
    print("Texture 属性:", [a for a in dir(t) if 'compress' in a.lower() or 'mip' in a.lower()])
except Exception as e:
    print("异常:", e)
ctx.release()
print("完成")
