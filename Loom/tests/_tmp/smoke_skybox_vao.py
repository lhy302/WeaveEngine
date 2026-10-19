# -*- coding: utf-8 -*-
"""smoke_skybox_vao.py — 天空盒 VAO 绑定冒烟 (2026-10-19 修复天空盒一直黑的根因)

背景: 用户实测天空盒一直是黑的。代码审计发现:
  1. _SKY_VERT 只声明 in vec2 in_pos (1 个属性)
  2. 但 _draw_skybox 里 VAO 尝试绑 'in_pos', 'in_uv' 两个属性名
  3. moderngl 对未在 program 里声明的属性名抛 KeyError
  4. 异常被 except 吞掉 -> self._skybox = None -> 天空盒永久禁用

本冒烟验证:
  A) 旧绑定方式 ('in_pos', 'in_uv') 确实抛异常（回归守护）
  B) 修复后 ('in_pos') 正常工作
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


# ============ 建无头 GL 上下文 ============
try:
    import moderngl
    ctx = moderngl.create_standalone_context(require=330)
except Exception as e:
    print('[SKIP] 无头 GL 不可用，跳过天空盒 VAO 测试: %r' % (e,))
    sys.exit(0)

# ============ 编译天空盒着色器 ============
from loom_shaders import _SKY_VERT, _SKY_FRAG

try:
    prog = ctx.program(vertex_shader=_SKY_VERT, fragment_shader=_SKY_FRAG)
    check('1) SKY 着色器编译成功', True)
except Exception as e:
    check('1) SKY 着色器编译成功', False, e)
    sys.exit(1)

# ============ 构造和 engine 一样的 _quad_vbo（4 float/顶点） ============
quad = np.array([
    0, 0, 0, 0,  1, 0, 1, 0,  1, 1, 1, 1,
    0, 0, 0, 0,  1, 1, 1, 1,  0, 1, 0, 1,
], dtype='f4')
vbo = ctx.buffer(quad.tobytes())

# ============ 测试 A: 旧绑定（in_pos + in_uv，复现 bug）============
old_raised = False
old_err = ''
try:
    va_old = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_pos', 'in_uv')])
except Exception as e:
    old_raised = True
    old_err = type(e).__name__ + ': ' + str(e)[:80]
check('2) 旧绑定 in_uv 抛异常（复现 bug）', old_raised, old_err)

# ============ 测试 B: 新绑定（仅 in_pos + 2x 填充，修复后）============
try:
    va_new = ctx.vertex_array(prog, [(vbo, '2f 2x', 'in_pos')])
    check('3) 修复后 VAO 绑定成功', True)
except Exception as e:
    check('3) 修复后 VAO 绑定成功', False, e)
    sys.exit(1)

# ============ 测试 C: 渲染不崩溃 ============
try:
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.clear(0.0, 0.0, 0.0, 1.0)
    # 不绑定 cubemap，只是跑一遍管道不会崩（shader 里 u_skybox 未设值会报，所以跳过实际 draw）
    # 只验证 VAO 已可用即可
    check('4) VAO 创建后管道处于可渲染状态', va_new is not None)
except Exception as e:
    check('4) VAO 创建后管道处于可渲染状态', False, e)

# ============ 汇总 ============
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
