# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl
ctx = moderngl.create_standalone_context()
info = ctx.info
print("GL 版本:", info.get('GL_VERSION'))
print("GL 厂商:", info.get('GL_VENDOR'), " 渲染器:", info.get('GL_RENDERER'))
print("=== 压缩相关扩展 ===")
for e in sorted(info.get('GL_EXTENSIONS', [])):
    el = e.lower()
    if any(k in el for k in ('compress', 's3tc', 'dxt', 'bptc', 'astc', 'etc', 'rgtc')):
        print("  ", e)
print("=== ctx.info 全部键 ===")
print(list(info.keys()))
# 试上传压缩纹理: moderngl 5.x 用 internal_format 指定压缩格式
print("=== 试上传 DXT1 (若支持) ===")
try:
    # GL_COMPRESSED_RGBA_S3TC_DXT1_EXT = 0x83F1
    # 16x16 的 DXT1 = 8 字节/4x4块 * 16 块 = 128 字节
    data = b'\x00' * 128
    t = ctx.texture((16,16), 4, data, internal_format=0x83F1)
    print("  DXT1 纹理创建 OK:", t.size, t.components)
    print("  可 build_mipmaps:", hasattr(t, 'build_mipmaps'))
except Exception as e:
    print("  DXT1 失败:", type(e).__name__, e)
ctx.release()
print("完成")
