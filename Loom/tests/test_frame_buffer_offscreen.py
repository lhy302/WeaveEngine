# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""FPS 缓冲预画: 真正写入离屏 FBO + 深度附件 + 引擎渲染目标恢复 (Q8=A)."""
import weakref
import engine as E
from frame_buffer import RenderFrameBuffer

ok = True
def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False

class FakeTex:
    def __init__(self):
        self.filter = None
        self.released = False
    def release(self):
        self.released = True

class FakeDepth:
    def __init__(self):
        self.released = False
    def release(self):
        self.released = True

class FakeFB:
    def __init__(self, color, depth):
        self.color = color
        self.depth = depth
        self.used = False
        self.released = False
    def use(self):
        self.used = True
    def release(self):
        self.released = True

class FakeCtx:
    def __init__(self):
        self.last_fb = None
        self.cleared = None
        self.copied = None
        self.viewport = None
        self.scissor = object()
    def texture(self, size, components, dtype=None, internal_format=None):
        return FakeTex()
    def depth_renderbuffer(self, size):
        return FakeDepth()
    def framebuffer(self, color_attachments=None, depth_attachment=None):
        self.last_fb = FakeFB(color_attachments[0], depth_attachment)
        return self.last_fb
    def clear(self, *a, **k):
        self.cleared = (a, k)
    def copy_framebuffer(self, target, src):
        self.copied = (target, src)

class FakeEngine:
    pass

rb = RenderFrameBuffer()
check("闸门开启", rb.configure({"frame_buffer_fps": True}, 60))
ctx = FakeCtx()
fe = FakeEngine()
fe._render_buf = rb
fe.ctx = ctx
fe._external_ctx = False
fe._external_fb = "widget-fbo"
E.GLEngine._LIVE_INSTANCES.append(weakref.ref(fe))
try:
    check("begin 成功", rb.begin(ctx, 32, 24))
    check("离屏 FBO 有深度附件", rb._fbo is not None
          and rb._fbo.depth is not None)
    check("预画期间引擎目标=离屏 FBO",
          fe._external_fb is rb._fbo and fe._external_ctx is True)
    check("视口/清屏按离屏尺寸", ctx.viewport == (0, 0, 32, 24)
          and ctx.cleared is not None and ctx.cleared[1].get("depth") == 1.0)
    rb.commit()
    check("commit 后恢复 widget 目标",
          fe._external_fb == "widget-fbo" and fe._external_ctx is False)
    check("commit 后 ready", rb.has_ready())
    target = object()
    check("blit 拷贝离屏帧", rb.blit(ctx, target) and ctx.copied == (target, rb._fbo))

    # abort 路径同样恢复目标
    check("再次 begin", rb.begin(ctx, 32, 24))
    rb.abort()
    check("abort 后恢复 widget 目标",
          fe._external_fb == "widget-fbo" and fe._external_ctx is False)
    check("abort 后 idle", rb.state == "idle")

    fb = rb._fbo
    depth = rb._depth
    rb._release()
    check("release 释放颜色/深度附件",
          fb.released and depth.released
          and rb._fbo is None and rb._depth is None)
finally:
    try:
        E.GLEngine._LIVE_INSTANCES.remove(weakref.ref(fe))
    except ValueError:
        pass

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
