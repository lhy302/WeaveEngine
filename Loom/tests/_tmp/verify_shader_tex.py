# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_shaders import _VERT_SRC, _FRAG_SRC

ctx = moderngl.create_standalone_context()
prog = ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)

prog['u_view_proj'].write(np.eye(4, dtype='f4').tobytes())
prog['u_view_pos'].value = (0.0, 0.0, 5.0)
prog['u_light_count'].value = 0
prog['u_ambient_scale'].value = 1.0
prog['u_albedo'].value = 0
try: prog['u_shadow_slot'].write(np.array([-1]*8, dtype='i4').tobytes())
except Exception: pass

inst = np.concatenate([np.eye(4, dtype='f4').reshape(-1),
                       np.array([1.0, 0, 0, 0], dtype='f4'),
                       np.array([1.0, 1.0, 1.0, 0.0], dtype='f4')]).astype('f4')
V = np.array([
    [-1, -1, 0, 0, 0, 1, 1, 1, 1, 1, 0.0, 0.0],
    [ 1, -1, 0, 0, 0, 1, 1, 1, 1, 1, 1.0, 0.0],
    [ 1,  1, 0, 0, 0, 1, 1, 1, 1, 1, 1.0, 1.0],
    [-1,  1, 0, 0, 0, 1, 1, 1, 1, 1, 0.0, 1.0],
], dtype='f4')
vbo = ctx.buffer(V.tobytes())
ib = ctx.buffer(inst.tobytes())
vao = ctx.vertex_array(prog, [
    (vbo, '3f 3f 4f 2f', 'in_pos', 'in_normal', 'in_color', 'in_uv'),
    (ib, '4f 4f 4f 4f 4f 4f/i', 'a_w0', 'a_w1', 'a_w2', 'a_w3', 'a_sat', 'a_col')])

def render(rgb):
    tex = ctx.texture((4, 4), 4, dtype='f1')
    px = np.tile(np.array([rgb[0], rgb[1], rgb[2], 255], dtype=np.uint8), 16)
    tex.write(px.tobytes())
    tex.use(0)
    fbo = ctx.simple_framebuffer((64, 64))
    fbo.use(); fbo.clear(0, 0, 0, 1.0)
    vao.render(moderngl.TRIANGLE_FAN)
    ctx.finish()
    data = fbo.read(components=3, alignment=1)
    arr = np.frombuffer(data, dtype=np.uint8).reshape(64, 64, 3)
    c = arr[32, 32]
    tex.release(); fbo.release()
    return c

r = render((255, 0, 0))
b = render((0, 0, 255))
g = render((0, 255, 0))
print("红纹理 -> 中心像素:", r)
print("蓝纹理 -> 中心像素:", b)
print("绿纹理 -> 中心像素:", g)
print("判定: 红R>蓝R=%s  蓝B>红B=%s  绿G>红G=%s" % (
    r[0] > b[0], b[2] > r[2], g[1] > r[1]))
ctx.release()
print("完成")
