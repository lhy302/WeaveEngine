# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import moderngl, numpy as np
from loom_shaders import _VERT_SRC, _FRAG_SRC

ctx = moderngl.create_standalone_context()
prog = ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)
prog['u_view_pos'].value=(0,0,5); prog['u_light_count'].value=0; prog['u_ambient_scale'].value=1.0
prog['u_albedo'].value=0; prog['u_normal_map'].value=1
try: prog['u_shadow_slot'].write(np.array([-1]*8,dtype='i4').tobytes())
except Exception: pass
try: prog['u_has_normal_map'].value=0.0
except Exception: pass

V = np.array([
    [-1,-1,0, 0,0,1, 1,1,1,1, 0,0],[ 1,-1,0, 0,0,1, 1,1,1,1, 1,0],
    [ 1, 1,0, 0,0,1, 1,1,1,1, 1,1],[-1, 1,0, 0,0,1, 1,1,1,1, 0,1]], dtype='f4')
vbo=ctx.buffer(V.tobytes())
inst=np.concatenate([np.eye(4,dtype='f4').reshape(-1),np.array([1,0,0,0],dtype='f4'),np.array([1,1,1,0],dtype='f4')]).astype('f4')
ib=ctx.buffer(inst.tobytes())
vao=ctx.vertex_array(prog,[(vbo,'3f 3f 4f 2f','in_pos','in_normal','in_color','in_uv'),
                           (ib,'4f 4f 4f 4f 4f 4f/i','a_w0','a_w1','a_w2','a_w3','a_sat','a_col')])

def render_with(internal_format, components, rgba_bytes):
    tex = ctx.texture((4,4), components, dtype='f1', internal_format=internal_format)
    tex.write(rgba_bytes)
    prog['u_view_proj'].write(np.eye(4,dtype='f4').tobytes())
    tex.use(0)
    fbo=ctx.simple_framebuffer((32,32)); fbo.use(); fbo.clear(0,0,0,1)
    vao.render(moderngl.TRIANGLE_FAN); ctx.finish()
    data=fbo.read(components=3,alignment=1)
    img=np.frombuffer(data,dtype=np.uint8).reshape(32,32,3)
    c=img[16,16].astype(int).tolist()
    tex.release(); fbo.release()
    return c

# 测试色: 橙红 (200,100,50)
px_rgba = np.tile(np.array([200,100,50,255],dtype=np.uint8),16).tobytes()
px_rgb = np.tile(np.array([200,100,50],dtype=np.uint8),16).tobytes()
print("原始色 (200,100,50)")
print("  未压缩 RGBA8 (0x1908):", render_with(0x1908, 4, px_rgba))
print("  RGB565 (0x8D62):", render_with(0x8D62, 3, px_rgb))
print("  RGBA4 (0x8056):", render_with(0x8056, 4, px_rgba))
print("  RGB5_A1 (0x8057):", render_with(0x8057, 4, px_rgba))
print("  未压缩 RGB8 (0x1907):", render_with(0x1907, 3, px_rgb))
vbo.release(); ib.release(); vao.release(); ctx.release()
print("完成")
