# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE); os.chdir(BASE)
import numpy as np, moderngl
from loom_shaders import _VERT_SRC, _FRAG_SRC

ctx = moderngl.create_standalone_context()
prog = ctx.program(vertex_shader=_VERT_SRC, fragment_shader=_FRAG_SRC)
prog['u_view_pos'].value = (0,0,5)
prog['u_light_count'].value = 0
prog['u_ambient_scale'].value = 1.0
prog['u_albedo'].value = 0
try: prog['u_shadow_slot'].write(np.array([-1]*8,dtype='i4').tobytes())
except Exception: pass

# 64x64 棋盘 (8x8 格, 每格 8 像素)
arr = np.zeros((64,64,4), dtype=np.uint8)
for y in range(64):
    for x in range(64):
        c = ((x//8)+(y//8)) % 2
        arr[y,x] = [255,0,0,255] if c==0 else [0,0,255,255]
tex = ctx.texture((64,64), 4, dtype='f1'); tex.write(arr.tobytes())
tex.build_mipmaps()   # -> filter 自动 LINEAR_MIPMAP_LINEAR

def render_quad(scale):
    # quad 顶点范围 -scale..scale (scale小=屏幕占比小=高频=高mip)
    V = np.array([
        [-scale,-scale,0, 0,0,1, 1,1,1,1, 0,0],
        [ scale,-scale,0, 0,0,1, 1,1,1,1, 1,0],
        [ scale, scale,0, 0,0,1, 1,1,1,1, 1,1],
        [-scale, scale,0, 0,0,1, 1,1,1,1, 0,1],
    ], dtype='f4')
    vbo = ctx.buffer(V.tobytes())
    inst = np.concatenate([np.eye(4,dtype='f4').reshape(-1),
                           np.array([1,0,0,0],dtype='f4'),
                           np.array([1,1,1,0],dtype='f4')]).astype('f4')
    ib = ctx.buffer(inst.tobytes())
    vao = ctx.vertex_array(prog, [
        (vbo,'3f 3f 4f 2f','in_pos','in_normal','in_color','in_uv'),
        (ib,'4f 4f 4f 4f 4f 4f/i','a_w0','a_w1','a_w2','a_w3','a_sat','a_col')])
    vp = np.eye(4, dtype='f4')   # 单位矩阵: 正交投影, 顶点直出
    prog['u_view_proj'].write(vp.tobytes())
    tex.use(0)
    fbo = ctx.simple_framebuffer((64,64)); fbo.use(); fbo.clear(0,0,0,1)
    vao.render(moderngl.TRIANGLE_FAN); ctx.finish()
    data = fbo.read(components=3, alignment=1)
    img = np.frombuffer(data, dtype=np.uint8).reshape(64,64,3)
    vbo.release(); ib.release(); vao.release(); fbo.release()
    return img

big = render_quad(0.95)   # 占屏幕大部分 -> mip0 -> 清晰棋盘
small = render_quad(0.12) # 占屏幕很小 -> 高 mip -> 模糊

def stats(img):
    region = img[24:40, 24:40].astype(int)   # 中心 16x16
    return region.std(), region.mean(axis=(0,1))

sb, mb = stats(big)
ss, ms = stats(small)
print("大 quad (mip0, 应清晰): 方差=%.1f 均值=%s" % (sb, mb.round(0)))
print("小 quad (高mip, 应模糊): 方差=%.1f 均值=%s" % (ss, ms.round(0)))
print("判定: 小quad方差 < 大quad方差 = %s (模糊=方差小)" % (ss < sb))
print("判定: 小quad均值接近混合(紫,红蓝平均) = %s" % (ms[0]>50 and ms[2]>50))
tex.release(); ctx.release()
print("完成")
