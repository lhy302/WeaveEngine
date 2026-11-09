# -*- coding: utf-8 -*-
"""loom_pass_gl.py — FramePlan 的 moderngl 执行器（2026-11-10 批次 A / 阶段 2A）。

只承担 S0-S2 需要的事，且**行为零变化**（A/B 三向闸门数值必须与迁移前逐值相同）：
  · 目标解析：color.ldr -> engine._screen_fb()（窗口 / Qt 宿主 FBO / 离屏探针同一条路）
  · 清屏：沿用 engine._clear_main_fbo（外部 / 默认 FBO 两种分支都在它里面）
  · 状态：pass 开始按声明应用（depth/raster），结束恢复；帧末恢复迁移前稳态
  · 绘制源：buckets / skybox / world_canvas 仍调用引擎现有实现（迁移期语义不变）

GL 的能力边界（别假装做到了）：
  · moderngl 5.12 **没有** depth_mask / is_enabled —— DepthState.write 只是 advisory，
    深度写掩码仍无法表达（天空靠「几何后画 + LEQUAL 等值通过」才正确）；
  · 因此 cull 的「记录值」按迁移前稳态假设为 True（GL 无查询 API）；
  · 不做 pass 排序/裁剪/别名（一期只有顺序列表）。
"""
import moderngl

from loom_pass import SCREEN_TARGET

_DEPTH_FUNC = {'less': '<', 'lequal': '<=', 'always': '*'}
# moderngl 只有 CULL_FACE 开关 + front_face(绕序), **没有**「剔除前面」的独立开关
# （无 moderngl.BACK/FRONT 常量）。S0-S2 只用到 none/back；front 明确拒绝而不是假装支持。
_CULL_SUPPORTED = ('none', 'back')
_BLEND = {'alpha': (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA),
          'additive': (moderngl.SRC_ALPHA, moderngl.ONE)}


def _safe_get(obj, name, default):
    """读 GL 状态属性；驱动 / 上下文不支持时用迁移前稳态默认值（不抛）。"""
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _safe_set(obj, name, value):
    try:
        setattr(obj, name, value)
        return True
    except Exception:
        return False


class GLTargetPool:
    """语义目标 -> 原生 FBO。S0-S2 只解析窗口/宿主目标（离屏目标等 S5 再用）。"""

    def __init__(self, engine):
        self.engine = engine

    def resolve(self, decl):
        if decl is None:
            raise KeyError('目标声明缺失')
        if decl.name == SCREEN_TARGET:
            return self.engine._screen_fb()
        raise KeyError('GL 后端暂不支持的目标: %s（S0-S2 只做 %s）'
                       % (decl.name, SCREEN_TARGET))


class GLFrameExecutor:
    """按 FramePlan 顺序执行 pass。同一份 plan 编辑器与播放器共用。"""

    def __init__(self, engine, draws=None):
        self.engine = engine
        self.ctx = engine.ctx
        self.pool = GLTargetPool(engine)
        self.draws = dict(_DEFAULT_DRAWS) if draws is None else dict(draws)

    # ---------- 对外 ----------
    def execute(self, plan, prepare=None):
        """执行一帧。prepare 只在第一个 pass 清屏后调用一次（相机/VP/uniform 上传）。"""
        errs = plan.validate()
        if errs:
            raise ValueError('FramePlan 非法: %s' % '; '.join(errs))
        ctx = self.ctx
        func_before = _safe_get(ctx, 'depth_func', '<')   # 迁移前稳态默认 '<'
        first = True
        for spec in plan.passes:
            fb = self.pool.resolve(plan.target_by_name(spec.target))
            fb.use()
            if spec.load == 'clear':
                self.engine._clear_main_fbo(*spec.clear)
            if first and prepare is not None:
                prepare()
            first = False
            self._apply(spec)
            for cmd in spec.draws:
                fn = self.draws.get(cmd.source)
                if fn is None:
                    raise KeyError('未注册的绘制源: %s' % (cmd.source,))
                fn(self.engine, cmd)
            self._restore(spec)
        # 帧末恢复迁移前稳态: 深度测试/剔除开启, depth_func 复位, 前脸 cw。
        # （旧代码在 main 里 enable 两者, 天空 finally 里 enable 剔除并复位 depth_func）
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.CULL_FACE)
        if _safe_set(ctx, 'depth_func', func_before) is False:
            pass
        _safe_set(ctx, 'front_face', 'cw')
        return plan

    # ---------- 状态 ----------
    def _apply(self, spec):
        ctx = self.ctx
        if spec.depth is not None:
            if spec.depth.test:
                ctx.enable(moderngl.DEPTH_TEST)
            else:
                ctx.disable(moderngl.DEPTH_TEST)
            _safe_set(ctx, 'depth_func', _DEPTH_FUNC.get(spec.depth.func, '<'))
            # depth.write 是 advisory: moderngl 无 depth_mask，故意不处理（见模块头）
        cull = spec.raster.cull
        if cull == 'none':
            ctx.disable(moderngl.CULL_FACE)
        else:
            if cull not in _CULL_SUPPORTED:
                raise NotImplementedError(
                    'GL 后端不支持 cull=%r（moderngl 无「剔除前面」开关）' % (cull,))
            ctx.enable(moderngl.CULL_FACE)
            _safe_set(ctx, 'front_face', spec.raster.front_face)
        if spec.raster.blend != 'none':
            bl = _BLEND.get(spec.raster.blend)
            if bl is not None:
                ctx.enable(moderngl.BLEND)
                ctx.blend_func = bl

    def _restore(self, spec):
        """pass 结束恢复「旧代码退出时」的状态：深度测试/剔除开, 混合关, 前脸 cw。

        旧代码：main 之后 depth+cull 都开；天空 finally 里 enable 剔除 + 复位 depth_func；
        world quad 之后 disable 混合。这里按 spec 的退出语义还原（GL 无状态查询可用）。
        """
        ctx = self.ctx
        if spec.depth is not None:
            ctx.enable(moderngl.DEPTH_TEST)
        if spec.raster.blend != 'none':
            ctx.disable(moderngl.BLEND)
        # 天空是唯一会关剔除的 3D pass；其余 pass 退出时剔除保持开启（旧代码如此）
        if spec.id == 'sky' or spec.raster.cull != 'none':
            ctx.enable(moderngl.CULL_FACE)
            _safe_set(ctx, 'front_face', 'cw')


def _draw_buckets(engine, cmd):
    engine._draw_main_buckets()


def _draw_skybox(engine, cmd):
    engine._draw_skybox_guarded()


def _draw_world_canvas(engine, cmd):
    engine._draw_world_canvases()


_DEFAULT_DRAWS = {
    'buckets': _draw_buckets,
    'skybox': _draw_skybox,
    'world_canvas': _draw_world_canvas,
}
