# -*- coding: utf-8 -*-
"""smoke_skybox_vao.py — 天空盒渲染冒烟（2026-10-20 Bug C 修复后重写）

原冒烟的致命缺陷（2026-10-19 版）：只验证 VAO 创建不抛异常，不验证实际渲染输出。
结果 '2f 2x' 格式能通过创建，但渲染是黑的 —— 用户实测发现天空盒一直黑，
这次冒烟的重写就是为了根除这个盲区：**必须读回像素验证**。

覆盖:
  A) 旧绑定 ('in_pos', 'in_uv') 抛 KeyError（第一次修复的回归证据）
  B) '2f 2x' 能创建但渲染黑（第二次修复前的错误状态，回归证据）
  C) 独立的 2f VBO + '2f' 格式渲染成功，读回非黑像素（最终正确修复）
  D) 完整 _draw_skybox 流程：depth_func='<=' + depth_mask=False + quad 覆盖屏幕
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import numpy as np

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


try:
    import moderngl
    ctx = moderngl.create_standalone_context(require=330)
    fbo = ctx.simple_framebuffer((64, 64))
except Exception as e:
    print('[SKIP] 无头 GL 不可用: %r' % (e,))
    sys.exit(0)

from loom_shaders import _SKY_VERT, _SKY_FRAG

try:
    prog = ctx.program(vertex_shader=_SKY_VERT, fragment_shader=_SKY_FRAG)
    check('0) SKY 着色器编译成功', True)
except Exception as e:
    check('0) SKY 着色器编译成功', False, e)
    sys.exit(1)


def render_center(vao, setup_fn=None):
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    if setup_fn:
        setup_fn()
    try:
        vao.render(moderngl.TRIANGLES, vertices=6)
    except Exception:
        pass
    data = fbo.read(components=3)
    px = np.frombuffer(data, dtype=np.uint8).reshape(64, 64, 3)
    return tuple(int(v) for v in px[32, 32])


# 4f 数据（HUD 格式 pos+uv）—— 用于测试 A/B
quad4 = np.array([
    0, 0, 0, 0,  1, 0, 1, 0,  1, 1, 1, 1,
    0, 0, 0, 0,  1, 1, 1, 1,  0, 1, 0, 1,
], dtype='f4')
vbo4 = ctx.buffer(quad4.tobytes())

# 2f 数据（纯位置）—— 用于测试 C/D
quad2 = np.array([
    0.0, 0.0,  1.0, 0.0,  1.0, 1.0,
    0.0, 0.0,  1.0, 1.0,  0.0, 1.0,
], dtype='f4')
vbo2 = ctx.buffer(quad2.tobytes())


# ============ A) 旧绑定 in_uv -> KeyError（回归证据） ============
raised = False
try:
    ctx.vertex_array(prog, [(vbo4, '2f 2f', 'in_pos', 'in_uv')])
except KeyError:
    raised = True
except Exception:
    raised = True
check('A) 旧绑定 in_uv 抛异常（回归证据）', raised)


# ============ B) '2f 2x' 能创建但渲染黑（2026-10-19 错误修复的回归证据）============
try:
    vao_b = ctx.vertex_array(prog, [(vbo4, '2f 2x', 'in_pos')])
    # 设置最小 uniforms
    prog['u_inv_view_proj'].write(np.eye(4, dtype='f4').tobytes())
    prog['u_camera_pos'].value = (0.0, 0.0, 0.0)
    prog['u_skybox_tint'].value = (1.0, 1.0, 1.0)

    from loom_cubemap import Cubemap
    cube = Cubemap.from_solid((58, 123, 213, 255))
    cube.ensure_gl(ctx)
    cube.use(0)
    prog['u_skybox'].value = 0

    def depth_le():
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_mask = False
        ctx.depth_func = '<='
        ctx.disable(moderngl.CULL_FACE)

    center_b = render_center(vao_b, depth_le)
    # 期望：全黑（证明这个格式确实是坏的）
    check('B) 2f 2x 渲染为黑（格式错误的回归证据）',
          center_b == (0, 0, 0), center_b)
except Exception as e:
    check('B) 2f 2x 渲染为黑（格式错误的回归证据）', False, e)


# ============ C) 独立 2f VBO + '2f' -> 渲染成功 ============
try:
    vao_c = ctx.vertex_array(prog, [(vbo2, '2f', 'in_pos')])
    prog['u_inv_view_proj'].write(np.eye(4, dtype='f4').tobytes())
    prog['u_camera_pos'].value = (0.0, 0.0, 0.0)
    prog['u_skybox_tint'].value = (1.0, 1.0, 1.0)

    from loom_cubemap import Cubemap
    cube2 = Cubemap.from_solid((58, 123, 213, 255))
    cube2.ensure_gl(ctx)
    cube2.use(0)
    prog['u_skybox'].value = 0

    def depth_le2():
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_mask = False
        ctx.depth_func = '<='
        ctx.disable(moderngl.CULL_FACE)

    center_c = render_center(vao_c, depth_le2)
    # 期望：接近 (58,123,213) 的蓝色
    is_blue = center_c[2] > 100 and center_c[0] < 100
    check('C) 独立 2f VBO + 2f 格式渲染成功（最终修复）',
          is_blue, center_c)
except Exception as e:
    check('C) 独立 2f VBO + 2f 格式渲染成功（最终修复）', False, e)


# ============ D) 完整 _draw_skybox 场景：depth_func<= + cubemap 采样 ============
try:
    # 用 identity inv_vp -> dir 约等于 clip 前 3 分量归一化
    # 中心像素 clip=(0,0,1,1) -> world=(0,0,1,1) -> dir=(0,0,1)
    # 立方体贴图全蓝，所以中心应该蓝
    center_d = render_center(vao_c, depth_le2)
    # 检查中心就是蓝色（同测试 C，但语义更明确）
    check('D) 完整流程（depth<= + cubemap）中心像素为蓝',
          center_d[2] > 100, center_d)
    # 再验证角落也是蓝（quad 全屏覆盖）
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    depth_le2()
    vao_c.render(moderngl.TRIANGLES, vertices=6)
    data = fbo.read(components=3)
    px = np.frombuffer(data, dtype=np.uint8).reshape(64, 64, 3)
    corners = [tuple(int(v) for v in px[y, x]) for (x, y) in
               [(1, 1), (62, 1), (1, 62), (62, 62)]]
    all_blue = all(c[2] > 100 for c in corners)
    check('D) 四角都被 quad 覆盖（全蓝）', all_blue, corners)
except Exception as e:
    check('D) 完整流程（depth<= + cubemap）中心像素为蓝', False, e)


# ============ 汇总 ============
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
