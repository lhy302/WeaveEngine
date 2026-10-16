# -*- coding: utf-8 -*-
import moderngl, numpy as np
ctx = moderngl.create_standalone_context()
t = ctx.texture((16,16), 4, dtype='f1')
print("wrap 相关属性:", [a for a in dir(t) if 'repeat' in a.lower() or 'wrap' in a.lower() or 'aniso' in a.lower() or 'mirror' in a.lower()])
print("repeat_x 默认:", getattr(t, 'repeat_x', 'N/A'))
print("repeat_y 默认:", getattr(t, 'repeat_y', 'N/A'))
print("anisotropy 默认:", getattr(t, 'anisotropy', 'N/A'))
import moderngl as m
print("m.REPEAT=", getattr(m,'REPEAT','N/A'), " m.CLAMP_TO_EDGE=", getattr(m,'CLAMP_TO_EDGE','N/A'), " m.MIRRORED_REPEAT=", getattr(m,'MIRRORED_REPEAT','N/A'))
print("m.LINEAR_MIPMAP_LINEAR=", getattr(m,'LINEAR_MIPMAP_LINEAR','N/A'))
# 试设
t.repeat_x = False
print("设 repeat_x=False 后:", t.repeat_x)
try:
    t.anisotropy = 4.0
    print("设 aniso=4 OK:", t.anisotropy)
except Exception as e:
    print("aniso 设置异常:", e)
ctx.release()
print("完成")
