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

# moderngl 5.13 的 depth_func setter 只认符号（'<' '<= ' '>' '>='）；传 'less'/'always' 这类
# 名字会在 C++ 层「返回错误但没设 Python 异常」-> SystemError；**编译版（Nuitka）下这一步
# 直接 access violation（beta6 发布阻塞项根因，2026-11-10 实测栈：_safe_set -> depth_func）。
# 因此只允许符号，且「深度测试关闭」时根本不设 depth_func（此时该值无意义）。
_DEPTH_FUNC = {'less': '<', 'lequal': '<=', 'greater': '>', 'gequal': '>='}
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
        # owned_by_provider: 该 pass 自己分配/绑定目标（阴影逐光源逐面），返回 None 表示
        # 执行器不要 use/clear —— 迁移期用它保住「阴影循环一行不改」（S3b 再显式化）。
        if getattr(decl, 'owned_by_provider', False):
            return None
        if decl.name == SCREEN_TARGET:
            return self.engine._screen_fb()
        from loom_post import HDR_TARGET, HALF_TARGET, QUARTER_TARGET
        if decl.name in (HDR_TARGET, HALF_TARGET, QUARTER_TARGET):
            import loom_post_gl
            return loom_post_gl.fbo_for(self.engine, decl.name)
        raise KeyError('GL 后端暂不支持的目标: %s（S0-S3 只做 %s、HDR/bloom 与 provider 自有目标）'
                       % (decl.name, SCREEN_TARGET))


class GLFrameExecutor:
    """按 FramePlan 顺序执行 pass。同一份 plan 编辑器与播放器共用。"""

    def __init__(self, engine, draws=None):
        self.engine = engine
        self.ctx = engine.ctx
        self.pool = GLTargetPool(engine)
        self.draws = dict(_DEFAULT_DRAWS) if draws is None else dict(draws)
        # 每个 plan 的 (pass, 目标声明, 绘制源名) 只解析一次：帧缓存之外的第二层热路径优化。
        self._row_cache: dict[int, tuple] = {}

    # ---------- 对外 ----------
    def execute(self, plan, prepare=None, before_pass=None, after_pass=None):
        """执行一帧。

        prepare    : 只在第一个绑定屏幕目标的 pass 清屏后调用一次（相机/VP/uniform）。
        before_pass: 每个 pass **执行前**（用于剖面分段，如 HUD 起点）。
        after_pass : 每个 pass **执行后**（用于剖面收口，如阴影段）。
        """
        errs = plan.validate()
        if errs:
            raise ValueError('FramePlan 非法: %s' % '; '.join(errs))
        ctx = self.ctx
        func_before = _safe_get(ctx, 'depth_func', '<')   # 迁移前稳态默认 '<'
        first = True
        for spec, decl, srcs in self._rows(plan):
            if before_pass is not None:
                before_pass(spec)
            fb = self.pool.resolve(decl)
            if fb is not None:               # provider 自有目标的 pass 自己绑定（阴影）
                fb.use()
                if spec.load == 'clear':
                    if decl.name == SCREEN_TARGET:
                        self.engine._clear_main_fbo(*spec.clear)   # 旧路径逐位不变
                    else:
                        d = spec.depth.clear if spec.depth is not None else None
                        fb.clear(*tuple(spec.clear),
                                 depth=(1.0 if d is None else float(d)))
            if first and prepare is not None:
                prepare()
            first = False
            self._apply(spec)
            for src in srcs:
                fn = self.draws.get(src)
                if fn is None:
                    raise KeyError('未注册的绘制源: %s' % (src,))
                fn(self.engine, src)
            self._restore(spec)
            if after_pass is not None:
                after_pass(spec)
        # 帧末恢复迁移前稳态: 深度测试/剔除开启, depth_func 复位, 前脸 cw。
        # （旧代码在 main 里 enable 两者, 天空 finally 里 enable 剔除并复位 depth_func）
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.CULL_FACE)
        if _safe_set(ctx, 'depth_func', func_before) is False:
            pass
        _safe_set(ctx, 'front_face', 'cw')
        return plan

    def _rows(self, plan):
        """解析并缓存 (pass, 目标声明, 绘制源名) —— 目标解析与绘制源名每帧都要用。"""
        ent = self._row_cache.get(id(plan))
        if ent is not None and ent[0] is plan:
            return ent[1]
        rows = tuple((spec, plan.target_by_name(spec.target),
                      tuple(c.source for c in spec.draws)) for spec in plan.passes)
        self._row_cache[id(plan)] = (plan, rows)
        return rows

    # ---------- 状态 ----------
    def _apply(self, spec):
        ctx = self.ctx
        if spec.depth is not None:
            if spec.depth.test:
                ctx.enable(moderngl.DEPTH_TEST)
                # 只转发 moderngl 认的符号；声明里的 'always' 等语义在「关深度」时不需要落地。
                _safe_set(ctx, 'depth_func', _DEPTH_FUNC.get(spec.depth.func, '<'))
            else:
                ctx.disable(moderngl.DEPTH_TEST)
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
                # 保存旧 blend_func：UI 层只在建 program 时设过 blend_func，
                # 若我们留下「加法」blend_func 不还原，后续 UI 会按加法混合画（实测变亮）。
                self._blend_saved = _safe_get(ctx, 'blend_func', None)
                ctx.enable(moderngl.BLEND)
                ctx.blend_func = bl

    def _restore(self, spec):
        """pass 结束恢复「旧代码退出时」的状态（**只补真正改过的项**，省 GL 调用）。

        旧代码的退出状态：main 之后 depth+cull 都开（apply 已开，无需重复）；
        天空 finally 里 enable 剔除 + 复位 depth_func；world/HUD/UI 之后混合关。
        阴影段旧代码就是「深度开 + 剔除关」并且**不恢复剔除** —— 这里保持一致。
        """
        ctx = self.ctx
        if spec.depth is not None and not spec.depth.test:
            ctx.enable(moderngl.DEPTH_TEST)      # 只有 apply 关过才需要恢复
        if spec.raster.blend != 'none':
            ctx.disable(moderngl.BLEND)
            saved = getattr(self, '_blend_saved', None)
            if saved is not None:
                _safe_set(ctx, 'blend_func', saved)   # 还原给 UI/HUD 用
        if spec.id == 'sky':                     # apply 关过剔除 -> 恢复开启（旧 finally 同款）
            ctx.enable(moderngl.CULL_FACE)
            _safe_set(ctx, 'front_face', 'cw')


def _draw_buckets(engine, cmd):
    engine._draw_main_buckets()


def _draw_skybox(engine, cmd):
    engine._draw_skybox_guarded()


def _draw_world_canvas(engine, cmd):
    engine._draw_world_canvases()


def _draw_shadow_maps(engine, cmd):
    # S3: 阴影的逐光源/逐面 FBO 与绘制循环仍在 loom_shadow（行为零变化）
    engine._render_shadow_maps()


def _draw_hud(engine, cmd):
    engine._draw_hud()


def _draw_post(engine, src):
    # 2B2: 后处理链的四个全屏 pass（目标已由执行器绑定）
    import loom_post_gl
    loom_post_gl.draw(engine, src)


def _draw_screen_ui(engine, cmd):
    # 与迁移前 `if self.ui is not None: self.ui.draw_all(self)` 同语义
    ui = getattr(engine, 'ui', None)
    if ui is not None:
        ui.draw_all(engine)


_DEFAULT_DRAWS = {
    'buckets': _draw_buckets,
    'skybox': _draw_skybox,
    'world_canvas': _draw_world_canvas,
    'shadow_maps': _draw_shadow_maps,
    'hud': _draw_hud,
    'screen_ui': _draw_screen_ui,
    'post.bright': _draw_post,
    'post.down': _draw_post,
    'post.up': _draw_post,
    'post.tonemap': _draw_post,
}
