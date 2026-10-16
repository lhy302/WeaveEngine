# -*- coding: utf-8 -*-
"""试探多属性实例格式串: '4f 4f/i' / '4f 4f /i' 等; 像素验证 a_w.xy(位置) a_h.xy(尺寸)."""
import numpy as np
import moderngl

ctx = moderngl.create_standalone_context()
VS = """#version 330
in vec2 in_pos; in vec4 a_w; in vec4 a_h;
void main(){ gl_Position = vec4(in_pos * a_h.xy + a_w.xy, 0.0, 1.0); }"""
FS = """#version 330
out vec4 f; void main(){ f = vec4(1.0, 0.0, 0.0, 1.0); }"""
prog = ctx.program(vertex_shader=VS, fragment_shader=FS)
vbo = ctx.buffer(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], 'f4').tobytes())
inst = ctx.buffer(np.array([
    [-0.8, 0.0, 0, 0, 0.2, 0.5, 0, 0],
    [0.8, 0.0, 0, 0, 0.2, 0.5, 0, 0]], 'f4').tobytes())
tex = ctx.texture((64, 16), 4)
fbo = ctx.framebuffer(color_attachments=[tex])


def try_fmt(label, fmt):
    try:
        vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_pos'),
                                      (inst, fmt, 'a_w', 'a_h')])
    except Exception as e:
        print("%-24s 构造失败: %r" % (label, e))
        return
    fbo.use()
    fbo.clear(0, 0, 1, 1)
    try:
        vao.render(moderngl.TRIANGLES, instances=2)
    except Exception as e:
        print("%-24s render 失败: %r" % (label, e))
        return
    data = np.frombuffer(fbo.read(components=4), np.uint8).reshape(16, 64, 4)
    left = data[8, 10, :3]
    mid = data[8, 32, :3]
    right = data[8, 60, :3]
    ok = (left[0] > 200 and mid[0] < 50 and right[0] > 200)
    print("%-24s left=%s mid=%s right=%s -> %s" % (label, left, mid, right, "PASS" if ok else "??"))


try_fmt("'4f 4f/i'", '4f 4f/i')
try_fmt("'4f 4f 4f 4f 4f 4f/i'", '4f 4f 4f 4f 4f 4f/i')
