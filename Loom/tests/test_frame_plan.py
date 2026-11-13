# -*- coding: utf-8 -*-
# test_frame_plan.py — FramePlan/PassSpec 骨架与 GL 执行器（2026-11-10 批次 A / 阶段 2A）
#
# 覆盖:
#   A. 描述层: 默认帧 = [main, sky]; 可选 world_ui; 冻结; 清屏色唯一来源; validate 抓错;
#   B. 编辑器与播放器 import 的是**同一个** frame_plan（共享描述的唯一证据）;
#   C. GL 执行器: 目标解析 -> 清屏 -> prepare -> 绘制源顺序; 状态应用/恢复（含无查询 API 的降级）;
#   D. 真实 GL 4.3 上下文里跑一帧 PlayerApp（证明播放器路径确实走 FramePlan）。
#
# 像素等价的最终证据不在本文件，而是 tests/test_ab_gl_vk.py（22 场景三向闸门，GL/参考恒为 0）。
import os
import sys

import moderngl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

from loom_pass import (SCREEN_TARGET, DrawCmd, DepthState, FramePlan, PassSpec,
                       RasterState, TargetDecl, frame_plan)
from loom_shaders import CLEAR_COLOR_RGBA
import loom_pass_gl as LPGL

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


# ---------------- A. 描述层 ----------------
def t_spec():
    print('=== A. FramePlan 描述层 ===')
    p = frame_plan()
    check('A1 默认帧 = main + sky', [x.id for x in p.passes] == ['main', 'sky'],
          [x.id for x in p.passes])
    check('A2 validate 通过', p.validate() == [], p.validate())
    check('A3 主 pass 目标 = 语义名 color.ldr',
          p.passes[0].target == SCREEN_TARGET == 'color.ldr',
          p.passes[0].target)
    check('A4 清屏色唯一来源 CLEAR_COLOR_RGBA',
          tuple(p.passes[0].clear) == tuple(CLEAR_COLOR_RGBA), p.passes[0].clear)
    sky = p.pass_by_id('sky')
    check('A5 天空 = 几何后（load=load）且 LEQUAL/不剔除',
          sky is not None and sky.load == 'load'
          and sky.depth.func == 'lequal' and sky.raster.cull == 'none',
          (sky.load, sky.depth.func, sky.raster.cull))
    check('A6 天空声明 depth.write=False（GL advisory，见模块头）',
          sky.depth.write is False, sky.depth.write)
    check('A7 无天空时只留 main',
          [x.id for x in frame_plan(include_sky=False).passes] == ['main'], '')
    check('A8 可选 world_ui 追加在末尾',
          [x.id for x in frame_plan(include_world_canvas=True).passes]
          == ['main', 'sky', 'world_ui'], '')
    try:
        p.passes[0].id = 'x'
        frozen = False
    except Exception:
        frozen = True
    check('A9 PassSpec 冻结（描述不可变）', frozen, '')

    bad = FramePlan(targets=(TargetDecl('a'),),
                    passes=(PassSpec('p', shader='s', target='missing',
                                    load='clear', draws=(DrawCmd('buckets'),)),))
    errs = bad.validate()
    check('A10 validate 抓未声明目标 + 缺 clear 颜色', len(errs) >= 2, errs)


# ---------------- B. 共享描述 ----------------
def t_shared():
    print('=== B. 编辑器/播放器共享同一份描述 ===')
    import editor
    import loom_render
    check('B1 编辑器用 loom_pass.frame_plan',
          editor.frame_plan is frame_plan, editor.frame_plan)
    check('B2 播放器用 loom_pass.frame_plan',
          loom_render.frame_plan is frame_plan, loom_render.frame_plan)
    src_e = open(os.path.join(ROOT, 'editor.py'), encoding='utf-8').read()
    src_p = open(os.path.join(ROOT, 'loom_render.py'), encoding='utf-8').read()
    check('B3 编辑器调用 frame_plan(include_shadow=..., ...)',
          'frame_plan(include_shadow=' in src_e, '')
    check('B4 播放器调用 frame_plan(include_shadow=..., ...)',
          'frame_plan(include_shadow=' in src_p, '')
    check('B5 编辑器不再手写清屏字面量 0.10, 0.12, 0.16',
          '0.10, 0.12, 0.16' not in src_e, '')


# ---------------- C. GL 执行器（假 ctx，可断言状态）----------------
class _FakeCtx:
    def __init__(self, fail_query=False):
        self.calls = []
        self._func = '<'
        self.fail_query = fail_query
        self.blend = None

    def enable(self, f):
        self.calls.append(('enable', f))

    def disable(self, f):
        self.calls.append(('disable', f))

    @property
    def depth_func(self):
        if self.fail_query:
            raise NotImplementedError('standalone')
        return self._func

    @depth_func.setter
    def depth_func(self, v):
        self.calls.append(('depth_func', v))
        self._func = v

    @property
    def front_face(self):
        return 'cw'

    @front_face.setter
    def front_face(self, v):
        self.calls.append(('front_face', v))

    @property
    def blend_func(self):
        return None

    @blend_func.setter
    def blend_func(self, v):
        self.blend = v


class _FakeFB:
    def __init__(self, log):
        self.log = log

    def use(self):
        self.log.append('fb.use')


class _FakeEngine:
    def __init__(self, log, fail_query=False):
        self.log = log
        self.ctx = _FakeCtx(fail_query=fail_query)
        self.fb = _FakeFB(log)

    def _screen_fb(self):
        return self.fb

    def _clear_main_fbo(self, *c):
        self.log.append(('clear', tuple(c)))

    def _draw_main_buckets(self):
        self.log.append('draw.main')

    def _draw_skybox_guarded(self):
        self.log.append('draw.sky')

    def _draw_world_canvases(self):
        self.log.append('draw.world')

    def _render_shadow_maps(self):
        self.log.append('draw.shadow')
        self.shadow_bound_own_target = True

    def _draw_hud(self):
        self.log.append('draw.hud')

    ui = None


def t_executor():
    print('=== C. GLFrameExecutor ===')
    log = []
    eng = _FakeEngine(log)
    ex = LPGL.GLFrameExecutor(eng)
    plan = frame_plan()
    ex.execute(plan, prepare=lambda: log.append('prepare'))
    check('C1 目标绑定 -> 清屏 -> prepare -> 主 pass 绘制',
          log[:4] == ['fb.use', ('clear', tuple(CLEAR_COLOR_RGBA)),
                      'prepare', 'draw.main'], log[:4])
    check('C2 天空 pass 重新绑定同一目标后绘制',
          log[4:] == ['fb.use', 'draw.sky'], log[4:])
    funcs = [c for c in eng.ctx.calls if c[0] == 'depth_func']
    check('C3 主 pass 声明 less、天空声明 lequal',
          ('depth_func', '<') in funcs and ('depth_func', '<=') in funcs, funcs)
    check('C4 帧末 depth_func 复位为迁移前的值', eng.ctx._func == '<', eng.ctx._func)
    check('C5 帧末深度测试/剔除开启（与旧代码稳态一致）',
          (moderngl.DEPTH_TEST in [c[1] for c in eng.ctx.calls if c[0] == 'enable'])
          and (moderngl.CULL_FACE in [c[1] for c in eng.ctx.calls if c[0] == 'enable']),
          eng.ctx.calls[-4:])
    check('C6 前脸设为 cw（引擎约定）',
          ('front_face', 'cw') in eng.ctx.calls, '')

    # 上下文不支持查询 depth_func（standalone 实测如此）时不得崩
    log2 = []
    eng2 = _FakeEngine(log2, fail_query=True)
    ex2 = LPGL.GLFrameExecutor(eng2)
    err = None
    try:
        ex2.execute(frame_plan())
    except BaseException as e:
        err = e
    check('C7 无状态查询 API 时执行器降级而不崩', err is None and 'draw.sky' in log2,
          repr(err))

    # 未注册绘制源 -> 明确报错（不静默跳过）
    log3 = []
    ex3 = LPGL.GLFrameExecutor(_FakeEngine(log3), draws={})
    err3 = None
    try:
        ex3.execute(frame_plan(include_sky=False))
    except BaseException as e:
        err3 = e
    check('C8 未注册绘制源 -> KeyError（不静默）', isinstance(err3, KeyError), err3)

    # 非法 plan -> ValueError（结构问题不吞）
    err4 = None
    try:
        ex.execute(FramePlan(targets=(), passes=(
            PassSpec('x', shader='s', target='nope',
                     draws=(DrawCmd('buckets'),)),)))
    except BaseException as e:
        err4 = e
    check('C9 非法 FramePlan -> ValueError', isinstance(err4, ValueError), err4)


# ---------------- S3/S4: 阴影与 HUD/UI 进描述 ----------------
class _FakeUI:
    def __init__(self, log):
        self.log = log

    def draw_all(self, engine):
        self.log.append('draw.ui')


def t_s3s4():
    print('=== E. S3 阴影 / S4 HUD+UI ===')
    p = frame_plan(include_shadow=True, include_world_canvas=True,
                   include_hud=True, include_ui=True)
    check('E1 全量顺序 = 阴影->主->天空->WorldUI->HUD->UI',
          [x.id for x in p.passes] == ['shadow_maps', 'main', 'sky',
                                       'world_ui', 'hud', 'ui'],
          [x.id for x in p.passes])
    check('E2 全量 plan 通过结构校验', p.validate() == [], p.validate())
    sh = p.pass_by_id('shadow_maps')
    tsh = p.target_by_name('shadow.depth')
    check('E3 阴影 = 真深度目标 + 深度写 + 不剔除',
          sh.target == 'shadow.depth' and sh.depth.func == 'less'
          and sh.depth.write is True and sh.raster.cull == 'none',
          (sh.target, sh.depth.func, sh.depth.write, sh.raster.cull))
    check('E4 阴影目标标记 owned_by_provider（逐面 FBO 归 loom_shadow）',
          tsh is not None and tsh.owned_by_provider is True
          and tsh.format == 'depth32float', None if tsh is None else tsh.owned_by_provider)
    hud = p.pass_by_id('hud')
    ui = p.pass_by_id('ui')
    check('E5 HUD/UI 都是 LDR 目标叠加层且不插手深度',
          hud.load == 'load' and ui.load == 'load'
          and hud.depth is None and ui.depth is None,
          (hud.load, ui.load, hud.depth, ui.depth))
    check('E6 HUD/UI 声明 alpha 混合、不剔除',
          hud.raster.blend == 'alpha' and ui.raster.blend == 'alpha'
          and hud.raster.cull == 'none' and ui.raster.cull == 'none', '')

    log = []
    eng = _FakeEngine(log)
    eng.ui = _FakeUI(log)
    ex = LPGL.GLFrameExecutor(eng)
    ex.execute(p)
    check('E7 执行顺序与描述一致（含阴影/HUD/UI）',
          [x for x in log if x != 'fb.use']
          == ['draw.shadow', ('clear', tuple(CLEAR_COLOR_RGBA)), 'draw.main',
              'draw.sky', 'draw.world', 'draw.hud', 'draw.ui'], log)
    check('E8 provider 自有目标不触发执行器绑定/清屏（阴影自己清）',
          log.index('draw.shadow') < log.index(('clear', tuple(CLEAR_COLOR_RGBA))), log)
    check('E9 阴影 pass 的深度状态被应用（深度写/比较不抛）',
          ('depth_func', '<') in eng.ctx.calls, eng.ctx.calls[:6])

    # 只挂 HUD 不挂 UI 也合法（ui 为 None 时）
    p2 = frame_plan(include_hud=True, include_ui=False)
    check('E10 仅 HUD 时 plan 合法',
          [x.id for x in p2.passes] == ['main', 'sky', 'hud'] and p2.validate() == [],
          [x.id for x in p2.passes])


# ---------------- 2B2: 后处理链结构 ----------------
def t_post():
    print('=== F. 2B2 后处理链（tonemap + bloom）===')
    from loom_post import HDR_TARGET, HALF_TARGET, QUARTER_TARGET, post_enabled
    p = frame_plan(include_shadow=False, include_world_canvas=True,
                   include_hud=True, include_ui=True, include_post=True)
    ids = [x.id for x in p.passes]
    check('F1 顺序 = 主->天空->WorldUI->bloom(bright/down)->tonemap->HUD->UI',
          ids == ['main', 'sky', 'world_ui', 'bloom.bright', 'bloom.down',
                  'tonemap', 'hud', 'ui'], ids)
    check('F2 结构校验通过', p.validate() == [], p.validate())
    check('F3 主链目标改为 HDR（color.hdr）',
          p.pass_by_id('main').target == HDR_TARGET
          and p.pass_by_id('sky').target == HDR_TARGET, p.pass_by_id('main').target)
    check('F4 HUD/UI 仍在 LDR 目标（tonemap 之后）',
          p.pass_by_id('hud').target == 'color.ldr'
          and p.pass_by_id('ui').target == 'color.ldr',
          (p.pass_by_id('hud').target, p.pass_by_id('ui').target))
    check('F5 bloom 目标是 0.5 / 0.25 尺寸声明',
          p.target_by_name(HALF_TARGET).scale == 0.5
          and p.target_by_name(QUARTER_TARGET).scale == 0.25, '')
    check('F6 HDR 目标为 rgba16float',
          p.target_by_name(HDR_TARGET).format == 'rgba16float', '')
    check('F7 后处理 pass 显式关深度（防污染 LDR 深度）',
          all(p.pass_by_id(k).depth is not None
              and p.pass_by_id(k).depth.test is False
              for k in ('bloom.bright', 'bloom.down', 'tonemap')), '')
    # 2026-11-10 发布阻塞项回归：moderngl 的 depth_func setter 只认符号（'<' '<=' '>' '>='）。
    # 传 'less'/'always' 会在 C++ 层「返回错误但没设异常」-> 源码版 SystemError、
    # 编译版(Nuitka) access violation。这里锁住：① 映射表只含符号；② 关深度时不设 depth_func。
    check('F7a depth_func 映射只含 moderngl 认的符号',
          set(LPGL._DEPTH_FUNC.values()) <= {'<', '<=', '>', '>='},
          LPGL._DEPTH_FUNC)
    log_f = []
    eng_f = _FakeEngine(log_f)
    ex_f = LPGL.GLFrameExecutor(eng_f)
    ex_f._apply(frame_plan(include_post=True).pass_by_id('tonemap'))
    check('F7b 后处理 pass（depth.test=False）不设置 depth_func',
          not [c for c in eng_f.ctx.calls if c[0] == 'depth_func'],
          eng_f.ctx.calls)
    check('F7c 关深度时确实禁用了 DEPTH_TEST',
          ('disable', moderngl.DEPTH_TEST) in eng_f.ctx.calls, eng_f.ctx.calls)

    p0 = frame_plan(include_post=False)
    check('F8 LOOM_POST 关闭时回到旧路径（主链直写 LDR）',
          p0.pass_by_id('main').target == 'color.ldr'
          and 'tonemap' not in [x.id for x in p0.passes], '')
    check('F9 开关默认开启（未设 LOOM_POST）', post_enabled() is True, '')


# ---------------- T3c-1: 场景参数 UBO 单一来源 ----------------
def t_scene_ubo():
    print('=== H. T3c-1 场景 UBO 单点表 ===')
    import loom_scene_ubo as SU
    import vk_renderer as VR
    check('H1 字段表：头 36 + 8*40 = 356 f32', SU.assert_layout() == 356, SU.FLOATS)
    check('H2 字节数 = 1424', SU.BYTES == 1424, SU.BYTES)
    check('H3 VK 旧常量与表一致',
          VR._SCENE_FLOATS == SU.FLOATS and VR._R_L0 == SU.HEAD
          and VR._LIGHT_F32 == SU.LIGHT_F32,
          (VR._SCENE_FLOATS, VR._R_L0, VR._LIGHT_F32))
    check('H4 每灯基址：0 -> 36，7 -> 316',
          SU.light_base(0) == 36 and SU.light_base(7) == 316,
          (SU.light_base(0), SU.light_base(7)))
    import numpy as np
    class _L:
        kind = 'directional'
        mode = 'full'
        shape = 'circle'
        shadow = True
        color = (1.0, 1.0, 1.0)
        intensity = 1.0
        direction = type('V', (), {'x': 0.0, 'y': -1.0, 'z': 0.0})()
        position = type('V', (), {'x': 0.0, 'y': 0.0, 'z': 0.0})()
        guid = 'g1'
        range = 10.0
        spot_inner_angle = 30.0
        spot_outer_angle = 60.0
    buf = SU.pack(np.eye(4), [_L()], (1.0, 2.0, 3.0), True, dir_slots={'g1': 0})
    check('H5 pack 输出长度 = 356 f32', len(buf) == 356, len(buf))
    check('H6 pack 输出字节 = 1424', buf.tobytes().__len__() == 1424,
          len(buf.tobytes()))
    import loom_shaders as SH
    from loom_shader_bindings import expand as _exp
    _blk = _exp(SU.glsl_block())
    check('H8 GL 主片段结构体 == 生成器输出（不手写第二份）',
          _blk in SH._FRAG_SRC and _blk in SH._VERT_SRC, '')
    _code = '\n'.join(ln.split('//')[0] for ln in SH._FRAG_SRC.splitlines())
    check('H9 GL shader 残留具名 uniform = 0（注释不算）',
          not any(k in _code for k in ('u_light_dir', 'u_light_kind',
                                       'u_shadow_slot', 'u_view_pos',
                                       'u_pbr_mode', 'u_ambient_scale')),
          '')
    import loom_shader_bindings as SB
    import vk_renderer as VR2
    check('H11 实例布局表 stride = 96', SB.INSTANCE_STRIDE == 96, SB.INSTANCE_STRIDE)
    check('H12 VK _INST_BYTES == 表 stride', VR2._INST_BYTES == SB.INSTANCE_STRIDE,
          (VR2._INST_BYTES, SB.INSTANCE_STRIDE))
    check('H13 表末字段偏移+16 == stride',
          SB.INSTANCE_LAYOUT[-1][2] + 16 == SB.INSTANCE_STRIDE,
          (SB.INSTANCE_LAYOUT[-1], SB.INSTANCE_STRIDE))
    _locs = [x[0] for x in SB.INSTANCE_LAYOUT]
    check('H14 实例 location 表 == 3..8 连续',
          _locs == list(range(3, 9)), _locs)
    check('H15 GL shader 的实例 location 与表一致',
          all('layout(location = %d) in vec4 %s' % (loc, name) in SH._VERT_SRC
              for loc, name, _off in SB.INSTANCE_LAYOUT),
          '')
    check('H17 桶级 UBO 表：8 字段 / 32B',
          SB.assert_bucket_layout() == 32 and SB.BUCKET_FLOATS == 8,
          (SB.BUCKET_BYTES, len(SB.BUCKET_FIELDS)))
    check('H18 GL 桶级 block == 生成器输出',
          _exp(SB.bucket_block_glsl()) in SH._FRAG_SRC, '')
    # T3a-3 (2026-11-13): VK 主片段改喂 main.frag 的 SPIR-V，没有 WGSL 结构体可查；
    # 改为把**生成器文本**与字段表绑死（比原来的 in-字符串更强）：字段序 + float 数。
    import re as _re
    _bblk = _exp(SB.bucket_block_glsl())
    _bnames = _re.findall(r'^\s*float\s+(\w+);', _bblk, _re.M)
    check('H19 桶级 block 字段序 == 表 且 float 数 == 32B/4',
          _bnames == [n for n, _o in SB.BUCKET_FIELDS]
          and len(_bnames) == SB.BUCKET_BYTES // 4, _bnames)
    import inspect as _insp
    check('H20 VK 桶级 buffer 32B == 表',
          'size=32' in _insp.getsource(VR2.VkRenderer._tex_group), '')
    check('H16 顶点布局表 0/1/2/13 与 VK 一致',
          [x[0] for x in SB.VERTEX_LAYOUT] == [0, 1, 2, 13], SB.VERTEX_LAYOUT)
    check('H10 GL shader 结构体字段顺序 == 表',
          SH._FRAG_SRC.index('mat4 mvp;') < SH._FRAG_SRC.index('vec4 cam;')
          < SH._FRAG_SRC.index('vec4 cnt;') < SH._FRAG_SRC.index('Light lights[8];'),
          '')
    check('H7 头字段：pbr=1 / count=1 / 灯槽位=0',
          buf[28] == 1.0 and buf[29] == 1.0 and buf[32 + 35] == 0.0,
          (buf[28], buf[29], buf[32 + 35]))


# ---------------- Q-D1-3=A: profiler 默认空实现 ----------------
def t_profiler_defaults():
    print('=== G. Q-D1-3=A: RenderMixin 的 profiler 默认空实现 ===')
    from loom_render import RenderMixin
    from loom_profiler import ProfilerMixin

    class OnlyRender(RenderMixin):
        pass

    h = OnlyRender()
    check('G1 只混 RenderMixin: _prof_t0() 返回 0.0（不抛 AttributeError）',
          h._prof_t0() == 0.0, h._prof_t0())
    check('G2 只混 RenderMixin: _prof_add 不抛且返回 None',
          h._prof_add('x', 0.0) is None)
    check('G3 只混 RenderMixin: _profile 直接执行原函数',
          h._profile('x', lambda: 7) == 7)

    class Spy:
        def _prof_t0(self):
            return 42.0

        def _prof_add(self, name, t0):
            return ('added', name, t0)

    class RenderFirst(RenderMixin, Spy):        # 与 GLEngine 相同的基类次序
        pass

    r = RenderFirst()
    check('G4 RenderMixin 在前时委托给真实 profiler（不被空实现遮蔽）',
          r._prof_t0() == 42.0, r._prof_t0())
    check('G5 _prof_add 同样委托', r._prof_add('a', 1.0) == ('added', 'a', 1.0),
          r._prof_add('a', 1.0))

    class ProfFirst(ProfilerMixin, RenderMixin):
        def __init__(self):
            self._stage_times = {}
            self._stage_calls = {}

    check('G6 ProfilerMixin 在前时真实现优先（MRO 不受影响）',
          ProfFirst._prof_t0 is ProfilerMixin._prof_t0)


# ---------------- D. 真实 GL ----------------
def t_real_gl():
    print('=== D. 真实 GL 4.3 跑一帧 PlayerApp ===')
    import runtime
    try:
        ctx = moderngl.create_standalone_context(require=430)
    except Exception as e:
        print('SKIP 无 GL 4.3 上下文: %r' % (e,))
        return
    fbo = ctx.framebuffer(color_attachments=[ctx.renderbuffer((64, 64), components=4)],
                          depth_attachment=ctx.depth_renderbuffer((64, 64)))
    app = runtime.PlayerApp(width=64, height=64, ctx=ctx, scene_data={
        'version': 10, 'objects': [], 'lights': [], 'materials': [],
        'cameras': [], 'active_camera': None})
    app._external_fb = fbo
    err = None
    try:
        app.render(1 / 60.0)
    except BaseException as e:
        err = e
    check('D1 播放器一帧走 FramePlan 不崩', err is None, repr(err))
    check('D2 帧内算出 VP', getattr(app, '_vp', None) is not None, '')
    check('D3 执行器已挂在引擎上', getattr(app, '_frame_executor', None) is not None, '')
    try:
        ctx.release()
    except Exception:
        pass


def main():
    t_spec()
    t_shared()
    t_executor()
    t_s3s4()
    t_post()
    t_scene_ubo()
    t_profiler_defaults()
    t_real_gl()
    print('')
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
