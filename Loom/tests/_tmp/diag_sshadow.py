# -*- coding: utf-8 -*-
"""隔离测试: 实测本驱动 sampler2DShadow 的比较行为 (存值 vs ref).
深度纹理填已知常数, 用不同 ref 采样, 输出 sh 颜色. 搞清比较方向.
运行: py -3.12 "Loom\tests\_tmp\diag_sshadow.py" (子进程+超时)"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import pygame, moderngl, numpy as np

pygame.init()
win = pygame.display.set_mode((64, 64), pygame.OPENGL | pygame.DOUBLEBUF)
ctx = moderngl.create_context()
ctx.enable(moderngl.DEPTH_TEST)

SIZE = 4
tex = ctx.depth_texture((SIZE, SIZE))
print("depth_texture 默认 filter =", tex.filter)
print("depth_texture 默认 compare_func =", tex.compare_func)
fbo = ctx.framebuffer(depth_attachment=tex)
fbo.clear(depth=0.10)                 # 贴图全部存 0.10
fbo.use()

prog = ctx.program(
    vertex_shader="""#version 330
    in vec2 in_pos;
    out vec2 v_uv;
    void main(){ v_uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }""",
    fragment_shader="""#version 330
    uniform sampler2DShadow u_sm;
    uniform float u_ref;
    in vec2 v_uv;
    out vec4 frag;
    void main(){
        float sh = texture(u_sm, vec3(v_uv, u_ref));
        frag = vec4(vec3(sh), 1.0);
    }""")
vbo = ctx.buffer(np.array([-1,-1, 1,-1, 1,1,  -1,-1, 1,1, -1,1], dtype='f4').tobytes())
vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_pos')])

rb = ctx.renderbuffer((64, 64), components=4)
cfbo = ctx.framebuffer(color_attachments=[rb])

def sample(ref, filt=None):
    if filt:
        tex.filter = filt
    tex.use(0)
    prog['u_sm'].value = 0
    prog['u_ref'].value = ref
    cfbo.use()
    ctx.clear()
    ctx.viewport = (0, 0, 64, 64)
    vao.render(moderngl.TRIANGLES)
    data = cfbo.read(components=4)
    a = np.frombuffer(data, dtype='u1').reshape(64, 64, 4)[:, :, 0].astype(float) / 255.0
    return float(a.mean())

print("\n存值=0.10, 用不同 ref 采样 (sh=1 照亮 / sh=0 阴影):")
print("%-8s %-10s %-10s" % ("ref", "NEAREST", "LINEAR"))
for ref in [0.05, 0.099, 0.10, 0.101, 0.15, 0.20, 0.50, 0.90]:
    n = sample(ref, (moderngl.NEAREST, moderngl.NEAREST))
    l = sample(ref, (moderngl.LINEAR, moderngl.LINEAR))
    print("%-8.3f %-10.3f %-10.3f" % (ref, n, l))
    # 判定比较方向
    if abs(n - 0.0) < 0.01 and abs(l - 0.0) < 0.01:
        verdict = "阴影 (sh=0)"
    elif abs(n - 1.0) < 0.01 and abs(l - 1.0) < 0.01:
        verdict = "照亮 (sh=1)"
    else:
        verdict = "部分 (插值/过滤)"
    print("          -> %s" % verdict)

pygame.quit()
print("\n完成")
