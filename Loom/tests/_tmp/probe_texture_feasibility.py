# -*- coding: utf-8 -*-
"""probe_texture_feasibility.py — 贴图系统技术可行性验证"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np

# 1) pygame.image 能否解码图片 (pygame 已是主依赖)
print("=== 1. pygame 图片解码能力 ===")
try:
    import pygame
    pygame.init()
    print("  pygame", pygame.version.ver, "OK")
    # 生成一张测试图并保存
    surf = pygame.Surface((64, 64))
    surf.fill((255, 0, 0))
    pygame.draw.rect(surf, (0, 255, 0), (16, 16, 32, 32))
    tmp = os.path.join(BASE, 'tests', '_tmp', '_tex_probe.png')
    pygame.image.save(surf, tmp)
    # 再加载回来
    img = pygame.image.load(tmp)
    print("  加载:", img.get_size(), img.get_flags())
    raw = pygame.image.tostring(img, 'RGBA')
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(img.get_height(), img.get_width(), 4)
    print("  RGBA 字节:", len(raw), "shape:", arr.shape, " 像素[0,0]:", arr[0,0])
    print("  像素[32,32] (应为绿):", arr[32,32])
    os.remove(tmp)
except Exception as e:
    import traceback; traceback.print_exc()

# 2) moderngl texture mipmap 支持
print("=== 2. moderngl mipmap 支持 ===")
try:
    import moderngl
    ctx = moderngl.create_standalone_context()
    tex = ctx.texture((64, 64), 4, dtype='f1')
    print("  创建纹理 OK, mipmaps 初始:", getattr(tex, 'mipmaps', '?'))
    data = np.zeros((64,64,4), dtype=np.uint8)
    tex.write(data.tobytes())
    tex.build_mipmaps()
    print("  build_mipmaps OK, 现在 mipmaps:", getattr(tex, 'mipmaps', '?'))
    print("  filter:", tex.filter)
    tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
    print("  设 mipmap 过滤 OK:", tex.filter)
    tex.release()
    ctx.release()
except Exception as e:
    import traceback; traceback.print_exc()

# 3) 顶点格式扩展验证: '3f 3f 4f' -> 加 2f UV
print("=== 3. VAO 顶点格式扩展 (加 UV 2f) ===")
try:
    import moderngl
    ctx = moderngl.create_standalone_context()
    prog = ctx.program(
        vertex_shader="""#version 330
in vec3 in_pos; in vec3 in_normal; in vec4 in_color; in vec2 in_uv;
out vec2 v_uv; out vec4 v_color;
void main(){ v_uv=in_uv; v_color=in_color; gl_Position=vec4(in_pos,1.0); }""",
        fragment_shader="""#version 330
in vec2 v_uv; in vec4 v_color; out vec4 frag;
uniform sampler2D u_albedo;
void main(){ frag = v_color * texture(u_albedo, v_uv); }""")
    # 4 顶点，格式 3f 3f 4f 2f = 12 f
    verts = np.array([
        [-1,-1,0, 0,0,1, 1,1,1,1, 0,0],
        [ 1,-1,0, 0,0,1, 1,1,1,1, 1,0],
        [ 1, 1,0, 0,0,1, 1,1,1,1, 1,1],
        [-1, 1,0, 0,0,1, 1,1,1,1, 0,1],
    ], dtype='f4')
    vbo = ctx.buffer(verts.tobytes())
    vao = ctx.vertex_array(prog, [(vbo, '3f 3f 4f 2f', 'in_pos','in_normal','in_color','in_uv')])
    print("  VAO '3f 3f 4f 2f' 创建 OK (12 floats/顶点)")
    # 纹理
    tex = ctx.texture((2,2), 4, dtype='f1')
    tex.write(np.array([255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255],dtype=np.uint8).tobytes())
    tex.use(0); prog['u_albedo'].value = 0
    fbo = ctx.simple_framebuffer((4,4)); fbo.use(); fbo.clear()
    vao.render(moderngl.TRIANGLE_FAN)
    print("  带贴图渲染 OK")
    vao.release(); vbo.release(); tex.release(); fbo.release(); ctx.release()
except Exception as e:
    import traceback; traceback.print_exc()
print("完成")
