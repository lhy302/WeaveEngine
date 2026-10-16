# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_shaders import _VERT_SRC, _FRAG_SRC

ctx = moderngl.create_standalone_context()
prog = ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)
prog['u_view_pos'].value = (0,0,5)
prog['u_light_count'].value = 1
ld = np.zeros(24, dtype='f4'); ld[2] = 1.0     # 光行进 +z
prog['u_light_dir'].write(ld.tobytes())
lc = np.zeros(24, dtype='f4'); lc[0]=lc[1]=lc[2]=1.0
prog['u_light_color'].write(lc.tobytes())
li = np.zeros(8, dtype='f4'); li[0]=1.0
prog['u_light_intensity'].write(li.tobytes())
prog['u_light_kind'].write(np.zeros(8, dtype='f4').tobytes())
prog['u_light_pos'].write(np.zeros(24, dtype='f4').tobytes())
prog['u_light_range'].write(np.ones(8, dtype='f4').tobytes())
try: prog['u_light_mode'].write(np.zeros(8,dtype='f4').tobytes())
except Exception: pass
prog['u_ambient_scale'].value = 1.0
prog['u_albedo'].value = 0
prog['u_normal_map'].value = 1
try: prog['u_shadow_slot'].write(np.array([-1]*8,dtype='i4').tobytes())
except Exception: pass

V = np.array([
    [-1,-1,0, 0,0,1, 1,1,1,1, 0,0],
    [ 1,-1,0, 0,0,1, 1,1,1,1, 1,0],
    [ 1, 1,0, 0,0,1, 1,1,1,1, 1,1],
    [-1, 1,0, 0,0,1, 1,1,1,1, 0,1],
], dtype='f4')
vbo = ctx.buffer(V.tobytes())
inst = np.concatenate([np.eye(4,dtype='f4').reshape(-1),
                       np.array([1,0,0,0],dtype='f4'),
                       np.array([1,1,1,0],dtype='f4')]).astype('f4')
ib = ctx.buffer(inst.tobytes())
vao = ctx.vertex_array(prog, [
    (vbo,'3f 3f 4f 2f','in_pos','in_normal','in_color','in_uv'),
    (ib,'4f 4f 4f 4f 4f 4f/i','a_w0','a_w1','a_w2','a_w3','a_sat','a_col')])

white = ctx.texture((1,1),4,dtype='f1'); white.write(np.array([255,255,255,255],dtype=np.uint8).tobytes())
flatn = ctx.texture((4,4),4,dtype='f1')
flatn.write(np.tile(np.array([128,128,0,255],dtype=np.uint8),16).tobytes())   # (0,0,-1)
siden = ctx.texture((4,4),4,dtype='f1')
siden.write(np.tile(np.array([255,128,128,255],dtype=np.uint8),16).tobytes()) # (1,0,0)

def render(norm_tex, has_nrm):
    prog['u_view_proj'].write(np.eye(4,dtype='f4').tobytes())
    white.use(0)
    if has_nrm: norm_tex.use(1)
    prog['u_has_normal_map'].value = 1.0 if has_nrm else 0.0
    fbo = ctx.simple_framebuffer((64,64)); fbo.use(); fbo.clear(0,0,0,1)
    vao.render(moderngl.TRIANGLE_FAN); ctx.finish()
    data = fbo.read(components=3, alignment=1)
    img = np.frombuffer(data,dtype=np.uint8).reshape(64,64,3)
    fbo.release()
    return img[32,32].astype(int)

base = render(flatn, False)
wf = render(flatn, True)
ws = render(siden, True)
print("无法线贴图:", base)
print("法线(0,0,-1):", wf)
print("法线(1,0,0): ", ws)
print("判定: 法线贴图改变光照 =", not np.array_equal(base, wf))
print("判定: 不同法线方向不同 =", not np.array_equal(wf, ws))
vbo.release(); ib.release(); vao.release(); white.release(); flatn.release(); siden.release(); ctx.release()
print("完成")
