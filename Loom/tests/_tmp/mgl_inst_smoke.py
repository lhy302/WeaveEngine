# -*- coding: utf-8 -*-
"""多属性 /i 格式串验证: 单缓冲多个实例属性 offset 是否依次排布 (stride=格式总长)."""
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
# 实例缓冲: 每实例 32B = a_w(16B) + a_h(16B); a_w.xy 是位置, a_h.xy 是尺寸 (0.2, 0.5)
inst = ctx.buffer(np.array([
    [-0.8, 0.0, 0, 0, 0.2, 0.5, 0, 0],
    [0.8, 0.0, 0, 0, 0.2, 0.5, 0, 0]], 'f4').tobytes())
vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_pos')],
                       ) if False else ctx.vertex_array(
    prog, [], )
vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_pos'),
                              (inst, '4f/i 4f/i', 'a_w', 'a_h')])
tex = ctx.texture((64, 16), 4)
fbo = ctx.framebuffer(color_attachments=[tex])
fbo.use()
fbo.clear(0, 0, 1, 1)
vao.render(moderngl.TRIANGLES, instances=2)
data = np.frombuffer(fbo.read(components=4), np.uint8).reshape(16, 64, 4)
left = data[8, 10, :3]
mid = data[8, 32, :3]
right = data[8, 60, :3]
ok = (left[0] > 200 and mid[0] < 50 and right[0] > 200)
print("left=%s mid=%s right=%s -> %s" % (left, mid, right, "PASS" if ok else "??"))
