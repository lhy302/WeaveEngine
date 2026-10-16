# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl

print("=== 3. VAO 顶点格式扩展 (加 UV 2f) ===")
ctx = moderngl.create_standalone_context()
prog = ctx.program(
    vertex_shader="""#version 330
in vec3 in_pos; in vec3 in_normal; in vec4 in_color; in vec2 in_uv;
out vec2 v_uv; out vec4 v_color; out vec3 v_n;
void main(){ v_uv=in_uv; v_color=in_color; v_n=in_normal; gl_Position=vec4(in_pos,1.0); }""",
    fragment_shader="""#version 330
in vec2 v_uv; in vec4 v_color; in vec3 v_n; out vec4 frag;
uniform sampler2D u_albedo;
void main(){ frag = v_color * texture(u_albedo, v_uv) * vec4(v_n*0.5+0.5,1.0); }""")
verts = np.array([
    [-1,-1,0, 0,0,1, 1,1,1,1, 0,0],
    [ 1,-1,0, 0,0,1, 1,1,1,1, 1,0],
    [ 1, 1,0, 0,0,1, 1,1,1,1, 1,1],
    [-1, 1,0, 0,0,1, 1,1,1,1, 0,1],
], dtype='f4')
vbo = ctx.buffer(verts.tobytes())
vao = ctx.vertex_array(prog, [(vbo, '3f 3f 4f 2f', 'in_pos','in_normal','in_color','in_uv')])
print("  VAO '3f 3f 4f 2f' 创建 OK (12 floats/顶点)")
tex = ctx.texture((2,2), 4, dtype='f1')
tex.write(np.array([255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,0,255],dtype=np.uint8).tobytes())
tex.use(0); prog['u_albedo'].value = 0
fbo = ctx.simple_framebuffer((4,4)); fbo.use(); fbo.clear()
vao.render(moderngl.TRIANGLE_FAN)
print("  带贴图+法线的渲染 OK")
vao.release(); vbo.release(); tex.release(); fbo.release(); ctx.release()
print("完成")
