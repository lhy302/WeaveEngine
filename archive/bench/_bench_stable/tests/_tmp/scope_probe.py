# -*- coding: utf-8 -*-
"""临时探针: 验证 moderngl scope enable_only 的位或/元组写法 (用完即删)."""
import moderngl

print("DEPTH_TEST=", moderngl.DEPTH_TEST, "BLEND=", moderngl.BLEND)
combined = moderngl.DEPTH_TEST | moderngl.BLEND
print("combined=", combined)
try:
    ctx = moderngl.create_standalone_context()
    print("standalone ctx OK")
    tex = ctx.texture((16, 16), 4)
    fbo = ctx.framebuffer(color_attachments=[tex])
    for label, arg in [("single", moderngl.DEPTH_TEST),
                       ("combined", combined),
                       ("tuple", (moderngl.DEPTH_TEST, moderngl.BLEND))]:
        try:
            with ctx.scope(framebuffer=fbo, enable_only=arg):
                pass
            print(label, "OK")
        except Exception as e:
            print(label, "ERR", type(e).__name__, e)
except Exception as e:
    print("standalone failed:", type(e).__name__, e)
