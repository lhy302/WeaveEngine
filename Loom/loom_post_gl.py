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

_TARGETS = (HDR_TARGET, HALF_TARGET, QUARTER_TARGET)

_VS = """#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}"""

_BRIGHT = """#version 330
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_tex;
uniform float u_threshold;
uniform float u_knee;
uniform float u_exposure;
void main() {
    // HDR 存 gamma 编码值 -> 反线性；再乘曝光（与 tonemap 同一曝光），阈值按曝光后线性亮度
    vec3 c = pow(max(texture(u_tex, v_uv).rgb, vec3(0.0)), vec3(2.2)) * u_exposure;
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float w = smoothstep(u_threshold, u_threshold + max(u_knee, 1e-4), l);
    frag_color = vec4(c * w, 1.0);
}"""

_DOWN = """#version 330
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_tex;
uniform vec2 u_texel;
void main() {
    vec2 o = u_texel;
    vec3 c = texture(u_tex, v_uv + vec2(-o.x, -o.y)).rgb
           + texture(u_tex, v_uv + vec2( o.x, -o.y)).rgb
           + texture(u_tex, v_uv + vec2(-o.x,  o.y)).rgb
           + texture(u_tex, v_uv + vec2( o.x,  o.y)).rgb;
    frag_color = vec4(c * 0.25, 1.0);
}"""

_TONEMAP = """#version 330
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform sampler2D u_bloom;
uniform float u_strength;
uniform float u_exposure;
void main() {
    vec3 c = pow(max(texture(u_hdr, v_uv).rgb, vec3(0.0)), vec3(2.2));
    c += texture(u_bloom, v_uv).rgb * u_strength;
    c *= u_exposure;
    c = c / (1.0 + c);                       // Reinhard（线性空间）
    frag_color = vec4(pow(c, vec3(1.0 / 2.2)), 1.0);
}"""


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
        if self.size == (w, h):
            return
        self.release()
        self.size = (w, h)
        ctx = self.ctx

        def _mk_fbo(name, tw, th, with_depth):
            tex = ctx.texture((tw, th), 4, dtype='f2')
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
        p = self._prog.get(key)
        if p is not None:
            return p
        prog = self.ctx.program(vertex_shader=_VS, fragment_shader=frag)
        self._prog[key] = prog
        self._vao[key] = self.ctx.vertex_array(
            prog, [(self._vbo, '2f 2f', 'in_pos', 'in_uv')])
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
        p = params()
        if source == 'post.bright':
            prog = self._program('bright', _BRIGHT)
            self.tex(HDR_TARGET).use(0)
            prog['u_tex'].value = 0
            prog['u_threshold'].value = p['threshold']
            prog['u_knee'].value = p['knee']
            prog['u_exposure'].value = p['exposure']
        elif source == 'post.down':
            prog = self._program('down', _DOWN)
            half = self._tex[HALF_TARGET]
            half.use(0)
            prog['u_tex'].value = 0
            # 4-tap 偏移按**源**（half）一个像素
            prog['u_texel'].value = (1.0 / max(1, half.width),
                                     1.0 / max(1, half.height))
        elif source == 'post.tonemap':
            prog = self._program('tonemap', _TONEMAP)
            self.tex(HDR_TARGET).use(0)
            # 2a 补：无 down pass 时（LOOM_POST_STAGE=2）直接读 0.5 目标 —— 否则 bright 的
            # 输出没有消费者，档 2 会与档 1 逐位相同（死档）。
            _src = getattr(self.engine, '_post_bloom_src', QUARTER_TARGET)
            self.tex(_src).use(1)
            prog['u_hdr'].value = 0
            prog['u_bloom'].value = 1
            prog['u_strength'].value = p['strength']
            prog['u_exposure'].value = p['exposure']
        else:
            raise KeyError('未知后处理绘制源: %s' % (source,))
        self._vao[{'post.bright': 'bright', 'post.down': 'down',
                   'post.tonemap': 'tonemap'}[source]].render(
            moderngl.TRIANGLES, vertices=6)
