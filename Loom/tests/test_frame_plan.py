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
    t_real_gl()
    print('')
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
