# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_cubemap import Cubemap

# 1) Cubemap 资产
c = Cubemap.from_solid((200, 100, 50), size=8)
print("Cubemap solid:", c.size, "guid=", c.guid[:8], "faces=", len(c._faces))
ctx = moderngl.create_standalone_context()
g = c.ensure_gl(ctx)
print("GL cubemap:", g.size)
ctx.release()

# 2) shader 采样（用引擎真实 _FRAG_SRC）
from loom_shaders import _VERT_SRC, _FRAG_SRC
ctx = moderngl.create_standalone_context()
prog = ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)
prog['u_view_pos'].value=(0,0,5); prog['u_light_count'].value=0; prog['u_ambient_scale'].value=1.0
prog['u_albedo'].value=0; prog['u_normal_map'].value=1; prog['u_env'].value=2
try: prog['u_has_normal_map'].value=0.0
except Exception: pass
try: prog['u_shadow_slot'].write(np.array([-1]*8,dtype='i4').tobytes())
except Exception: pass
prog['u_pbr_mode'].value=1.0; prog['u_material_pbr'].value=1.0
prog['u_metallic'].value=1.0; prog['u_roughness'].value=0.2

V = np.array([
    [-1,-1,0, 0,0,1, 1,1,1,1, 0,0],[ 1,-1,0, 0,0,1, 1,1,1,1, 1,0],
    [ 1, 1,0, 0,0,1, 1,1,1,1, 1,1],[-1, 1,0, 0,0,1, 1,1,1,1, 0,1]], dtype='f4')
vbo=ctx.buffer(V.tobytes())
inst=np.concatenate([np.eye(4,dtype='f4').reshape(-1),np.array([1,0,0,0],dtype='f4'),np.array([1,1,1,0],dtype='f4')]).astype('f4')
ib=ctx.buffer(inst.tobytes())
vao=ctx.vertex_array(prog,[(vbo,'3f 3f 4f 2f','in_pos','in_normal','in_color','in_uv'),
                           (ib,'4f 4f 4f 4f 4f 4f/i','a_w0','a_w1','a_w2','a_w3','a_sat','a_col')])
white=ctx.texture((1,1),4,dtype='f1'); white.write(np.array([255,255,255,255],dtype=np.uint8).tobytes())
env = Cubemap.from_solid((255, 0, 0), size=8).ensure_gl(ctx)   # 红色环境

def render(has_env):
    prog['u_view_proj'].write(np.eye(4,dtype='f4').tobytes())
    white.use(0)
    prog['u_has_env'].value = 1.0 if has_env else 0.0
    if has_env:
        env.use(2)
        prog['u_env_max_lod'].value = 3.0
    fbo=ctx.simple_framebuffer((64,64)); fbo.use(); fbo.clear(0,0,0,1)
    vao.render(moderngl.TRIANGLE_FAN); ctx.finish()
    data=fbo.read(components=3,alignment=1)
    img=np.frombuffer(data,dtype=np.uint8).reshape(64,64,3)
    fbo.release()
    return img[32,32].astype(int)

no_env = render(False)
with_env = render(True)
print("无 env 中心:", no_env)
print("有 env 中心:", with_env, "(红色环境应偏红)")
print("判定: env 改变输出 =", not np.array_equal(no_env, with_env))
print("判定: 红色环境偏红(R最大) =", with_env[0] >= with_env[1] and with_env[0] >= with_env[2])
vbo.release(); ib.release(); vao.release(); white.release(); ctx.release()
print("完成")
