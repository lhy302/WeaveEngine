# -*- coding: utf-8 -*-
"""loom_post_gl.py — GL 侧后处理链（HDR 目标 + bloom + tonemap，2026-11-10 阶段 2B2）。

链路（与 VK 侧逐公式一致，见 loom_post.py 模块头为什么 main/sky 不用改）：
  color.hdr(rgba16f, 含深度) -> bloom.half(0.5) [bright]
                             -> bloom.quarter(0.25) [down 4-tap]
                             -> color.ldr [tonemap: pow2.2 -> Reinhard -> pow(1/2.2)]
  注：**没有独立 up pass** —— 上采样合成在 tonemap 里做（双线性读 0.25 目标）。
  早先写的「up 加法混合」已删（GL blend_func 在该场景读不到也还原不了，会污染后续 UI）。

所有目标都是全屏 quad 全覆盖写；size 变化时自动重建（ensure）。
"""
import moderngl

from loom_post import HDR_TARGET, HALF_TARGET, QUARTER_TARGET, params




def shared_src(name):
    """T3：读取 `Loom/shaders/<name>` 单源，展开兼容层 + 绑定号单点表（GL 用 #version 430）。"""
    import os
    import loom_shader_bindings
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders')
    with open(os.path.join(base, name), encoding='utf-8') as fh:
        src = fh.read()
    with open(os.path.join(base, 'loom_shader_compat.glsl'), encoding='utf-8') as fh:
        compat = fh.read()
    src = src.replace('//@@COMPAT@@', compat)
    src = loom_shader_bindings.expand(src)
    return src.replace('#version 450', '#version 430')


def shared_frag(name):
    return shared_src(name)


def shared_vert():
    return shared_src('post_fullscreen.vert')

_TARGETS = (HDR_TARGET, HALF_TARGET, QUARTER_TARGET)






def chain(engine):
    """按引擎缓存一条后处理链（懒建；尺寸变化由 ensure 处理）。"""
    c = getattr(engine, '_post_gl', None)
    if c is None:
        c = GLPostChain(engine)
        engine._post_gl = c
    return c


def fbo_for(engine, name):
    return chain(engine).fbo(name)


def draw(engine, source):
    chain(engine).draw(source)


class GLPostChain:
    """HDR 目标 + bloom 链的执行体（懒建；尺寸变化重建）。"""

    def __init__(self, engine):
        self.engine = engine
        self.ctx = engine.ctx
        self.size = (0, 0)
        self._fbo = {}
        self._tex = {}
        self._prog = {}
        self._vao = None
        self._vbo = None

    # ---------- 资源 ----------
    def ensure(self, w, h):
        w, h = max(1, int(w)), max(1, int(h))
        # 缓存键必须含「每个目标的尺寸 + 格式」：只比屏幕尺寸会让同一引擎内动态改
        # TargetDecl.scale/format 时 GL 不重建（VK 会重建）—— 两端行为不一致（goal_01 反例）。
        _sz = getattr(self.engine, '_post_sizes', None) or {}
        _fm = getattr(self.engine, '_post_formats', None) or {}
        _key = (w, h,
                tuple(sorted((k, tuple(v)) for k, v in _sz.items())),
                tuple(sorted(_fm.items())))
        if getattr(self, '_key', None) == _key and self._fbo:
            return
        self._key = _key
        self.release()
        self.size = (w, h)
        ctx = self.ctx

        _fmts = getattr(self.engine, '_post_formats', None) or {}

        def _mk_fbo(name, tw, th, with_depth):
            # 2026-11-11: 纹理格式来自 TargetDecl.format（rgba16float -> f2；8 位 -> u1）
            _fmt = str(_fmts.get(name, 'rgba16float'))
            if _fmt.endswith('16float'):
                tex = ctx.texture((tw, th), 4, dtype='f2')
            else:
                tex = ctx.texture((tw, th), 4)      # 8 位（u1）
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = False
            tex.repeat_y = False
            kw = {}
            if with_depth:
                kw['depth_attachment'] = ctx.depth_renderbuffer((tw, th))
            self._fbo[name] = ctx.framebuffer(color_attachments=[tex], **kw)
            self._tex[name] = tex

        # 2026-11-11 goal_01: 尺寸来自**共享描述**的 TargetDecl.scale（执行器写入
        # engine._post_sizes）；没有声明时才退回 1/0.5/0.25 默认。
        _sizes = getattr(self.engine, '_post_sizes', None) or {}

        def _sz(name, dflt):
            v = _sizes.get(name)
            return (max(1, int(v[0])), max(1, int(v[1]))) if v else dflt

        _mk_fbo(HDR_TARGET, *_sz(HDR_TARGET, (w, h)), True)
        _mk_fbo(HALF_TARGET, *_sz(HALF_TARGET, (max(1, w // 2), max(1, h // 2))), False)
        _mk_fbo(QUARTER_TARGET, *_sz(QUARTER_TARGET, (max(1, w // 4), max(1, h // 4))), False)
        if self._vao is None:
            import numpy as np
            quad = np.array([
                -1.0, -1.0, 0.0, 0.0,   1.0, -1.0, 1.0, 0.0,   1.0, 1.0, 1.0, 1.0,
                -1.0, -1.0, 0.0, 0.0,   1.0, 1.0, 1.0, 1.0,   -1.0, 1.0, 0.0, 1.0,
            ], dtype='f4')
            self._vbo = self.ctx.buffer(quad.tobytes())
            self._vao = {}

    def _program(self, key, frag):
        """T3 Phase 1：GL 也用单源（顶点=全屏三角，无顶点属性）。"""
        p = self._prog.get(key)
        if p is not None:
            return p
        prog = self.ctx.program(vertex_shader=shared_vert(), fragment_shader=frag)
        self._prog[key] = prog
        # 无顶点属性：gl_VertexID 生成全屏三角（3 顶点）
        self._vao[key] = self.ctx.vertex_array(prog, [])
        if getattr(self, '_ubo', None) is None:
            self._ubo = self.ctx.buffer(reserve=32)
        try:
            prog['Params'].binding = 3
        except Exception:
            pass
        return prog

    def fbo(self, name):
        self.ensure(self.engine.width, self.engine.height)
        return self._fbo.get(name)

    def tex(self, name):
        self.ensure(self.engine.width, self.engine.height)
        return self._tex.get(name)

    def release(self):
        for f in list(self._fbo.values()):
            try:
                f.release()
            except Exception:
                pass
        self._fbo.clear()
        self._tex.clear()
        self.size = (0, 0)

    # ---------- 绘制（目标由 FramePlan 执行器绑定）----------
    def draw(self, source):
        """T3 Phase 1：bright/down/tonemap 全部走单源 GLSL（参数一律 std140 UBO）。"""
        import struct
        p = params()
        _key = {'post.bright': 'bright', 'post.down': 'down',
                'post.tonemap': 'tonemap'}.get(source)
        if _key is None:
            raise KeyError('未知后处理绘制源: %s' % (source,))
        prog = self._program(_key, shared_frag({'bright': 'post_bright.frag',
                                                'down': 'post_down.frag',
                                                'tonemap': 'post_tonemap.frag'}[_key]))
        _sizes = getattr(self.engine, '_post_sizes', None) or {}
        hw, hh = _sizes.get(HALF_TARGET, (max(1, self.engine.width // 2),
                                          max(1, self.engine.height // 2)))
        qw, qh = _sizes.get(QUARTER_TARGET, (max(1, self.engine.width // 4),
                                             max(1, self.engine.height // 4)))
        if _key == 'bright':
            self.tex(HDR_TARGET).use(0)
            try:
                prog['u_hdr'].value = 0
            except Exception:
                pass
            p0 = (p['threshold'], p['knee'], p['exposure'], 0.0)
            p1 = (float(hw), float(hh), 0.0, 0.0)
        elif _key == 'down':
            self.tex(HALF_TARGET).use(0)
            try:
                prog['u_tex'].value = 0
            except Exception:
                pass
            p0 = (0.0, 0.0, 0.0, 0.0)
            p1 = (float(qw), float(qh), 1.0 / max(1, hw), 1.0 / max(1, hh))
        else:
            self.tex(HDR_TARGET).use(0)
            _src = getattr(self.engine, '_post_bloom_src', QUARTER_TARGET)
            self.tex(_src).use(1)
            try:
                prog['u_hdr'].value = 0
                prog['u_bloom'].value = 1
            except Exception:
                pass
            p0 = (0.0, 0.0, p['strength'], p['exposure'])
            p1 = (float(self.engine.width), float(self.engine.height), 0.0, 0.0)
        self._ubo.write(struct.pack('8f', *(list(p0) + list(p1))))
        self._ubo.bind_to_uniform_block(3)
        self._vao[_key].render(moderngl.TRIANGLES, vertices=3)
