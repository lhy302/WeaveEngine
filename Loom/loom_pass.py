# -*- coding: utf-8 -*-
"""loom_pass.py — 渲染 Pass 描述层（FramePlan / PassSpec），**纯数据，无后端依赖**。

2026-11-10 批次 A 阶段 2A（S0）：按 docs/design/research_beta6_01_render_pass.md §2.3
把「一次 pass 的跨后端语义」收敛成 6 项：目标 + 状态(depth/raster) + 着色器 +
语义槽绑定 + 参数块 + 绘制源。本阶段只接 GL 后端（VK 仍走 vk_renderer 现有实现），
**要求行为零变化**（A/B 三向闸门数值不变）。

设计边界（别假装统一了）：
  · 这里只描述「语义」，不描述指令序 —— GL 的「几何后画天空 + LEQUAL 等值通过」与
    VK 的「几何前画天空 + depth_compare=always」是同一语义的两种实现；
  · DepthState.write 在 GL 侧是 **advisory**：moderngl 5.12 没有 depth_mask API，
    GL 后端不会（也无法）真的关深度写；
  · 着色器仍是 GLSL/WGSL 两份镜像，本模块不负责统一；
  · 阴影目标编码（GL 真深度 / VK r32float）差异留到 S3。
"""
from dataclasses import dataclass, field
from typing import Literal, Sequence

from loom_shaders import CLEAR_COLOR_RGBA

# 语义目标名（后端各自解析；GL = engine._screen_fb()）
SCREEN_TARGET = 'color.ldr'


@dataclass(frozen=True)
class TargetDecl:
    """一张帧内目标的声明（不含任何原生句柄）。"""
    name: str
    format: str = "rgba8unorm"
    size: Literal['screen', 'shadow', 'fixed'] = 'screen'
    scale: float = 1.0
    fixed: tuple[int, int] | None = None
    depth: Literal['none', 'own', 'shared'] = 'own'
    depth_format: str = "depth32float"


@dataclass(frozen=True)
class DepthState:
    test: bool = True
    write: bool = True          # GL advisory（moderngl 无 depth_mask，见模块头）
    func: Literal['less', 'lequal', 'always'] = 'less'
    clear: float | None = 1.0


@dataclass(frozen=True)
class RasterState:
    cull: Literal['none', 'back', 'front'] = 'back'
    front_face: Literal['cw', 'ccw'] = 'cw'
    topology: Literal['triangle-list', 'triangle-strip'] = 'triangle-list'
    blend: Literal['none', 'alpha', 'additive'] = 'none'


@dataclass(frozen=True)
class BindingSpec:
    """语义槽绑定（不写 unit / @binding 号，由后端分配）。"""
    slot: str
    stage: Literal['vertex', 'fragment', 'both'] = 'fragment'
    kind: Literal['uniform', 'texture2d', 'texturecube', 'sampler'] = 'texture2d'
    sample_type: Literal['float', 'unfilterable-float', 'depth'] = 'float'


@dataclass(frozen=True)
class ParamField:
    """参数块字段（GL 具名 uniform / VK std140 偏移，偏移由顺序推导）。"""
    name: str
    dtype: Literal['f32', 'i32'] = 'f32'
    count: int = 1
    stage: Literal['vertex', 'fragment', 'both'] = 'fragment'


@dataclass(frozen=True)
class DrawCmd:
    """绘制源。S0-S2 只登记语义名，实际绘制仍由引擎现有实现提供（见 loom_pass_gl）。"""
    source: Literal['buckets', 'skybox', 'world_canvas', 'fullscreen']
    key: str | None = None
    count: int | None = None
    instances: int | None = None


@dataclass(frozen=True)
class PassSpec:
    """一次 pass 的全部跨后端语义。"""
    id: str
    shader: str
    target: str = SCREEN_TARGET
    load: Literal['clear', 'load', 'dontcare'] = 'clear'
    clear: tuple[float, float, float, float] | None = None
    depth: DepthState | None = None
    raster: RasterState = field(default_factory=RasterState)
    bindings: tuple[BindingSpec, ...] = ()
    params: tuple[ParamField, ...] = ()
    draws: tuple[DrawCmd, ...] = ()
    submit: Literal['frame', 'own'] = 'frame'


@dataclass(frozen=True)
class FramePlan:
    """有序 Pass 列表 + 显式目标声明。顺序即执行序（一期不做拓扑排序）。"""
    targets: tuple[TargetDecl, ...]
    passes: tuple[PassSpec, ...]
    revision: int = 1

    def pass_by_id(self, pid: str) -> PassSpec | None:
        for p in self.passes:
            if p.id == pid:
                return p
        return None

    def target_by_name(self, name: str) -> TargetDecl | None:
        for t in self.targets:
            if t.name == name:
                return t
        return None

    def validate(self) -> list[str]:
        """结构校验（返回问题列表；空 = 通过）。给测试与构建期用。"""
        errs: list[str] = []
        names = {t.name for t in self.targets}
        ids = set()
        for p in self.passes:
            if p.id in ids:
                errs.append('重复 pass id: %s' % p.id)
            ids.add(p.id)
            if p.target not in names:
                errs.append('pass %s 引用了未声明目标 %s' % (p.id, p.target))
            if p.load == 'clear' and p.clear is None:
                errs.append('pass %s load=clear 但没给 clear 颜色' % p.id)
            if not p.draws:
                errs.append('pass %s 没有绘制源' % p.id)
        return errs


# ---- 共享的帧描述构造（编辑器与播放器**同一份**）----
_MAIN_BINDINGS = (
    BindingSpec('scene', stage='both', kind='uniform'),
    BindingSpec('inst', stage='vertex', kind='uniform'),
    BindingSpec('shadow.dir0', kind='texture2d', sample_type='depth'),
    BindingSpec('shadow.dir1', kind='texture2d', sample_type='depth'),
    BindingSpec('shadow.point', kind='texturecube', sample_type='depth'),
    BindingSpec('albedo', kind='texture2d'),
    BindingSpec('normal_map', kind='texture2d'),
    BindingSpec('env', kind='texturecube'),
)

_SKY_BINDINGS = (
    BindingSpec('sky.uniforms', stage='both', kind='uniform'),
    BindingSpec('sky.cube', kind='texturecube'),
    BindingSpec('sky.sampler', kind='sampler'),
)


# 每帧都会调用 frame_plan() —— 实测裸构造 22.4 us/次（1ms 帧 = 2.2%），
# 而描述只由 (清屏色, 是否天空, 是否 world UI) 决定，故按这三元组缓存。
_PLAN_CACHE: dict[tuple, FramePlan] = {}


def frame_plan(clear_color: Sequence[float] = CLEAR_COLOR_RGBA,
               include_sky: bool = True,
               include_world_canvas: bool = False) -> FramePlan:
    """构造一帧的 Pass 列表（编辑器 / 播放器共用）——**按参数缓存**，返回同一 frozen 对象。"""
    if clear_color is CLEAR_COLOR_RGBA:      # 两条渲染路径都用默认常量 -> 走极速键
        key = (True, bool(include_sky), bool(include_world_canvas))
    else:
        key = (tuple(round(float(c), 6) for c in clear_color),
               bool(include_sky), bool(include_world_canvas))
    plan = _PLAN_CACHE.get(key)
    if plan is None:
        plan = _build_plan(clear_color, include_sky, include_world_canvas)
        _PLAN_CACHE[key] = plan
    return plan


def _build_plan(clear_color: Sequence[float],
                include_sky: bool,
                include_world_canvas: bool) -> FramePlan:
    """构造一帧的 Pass 列表（编辑器 / 播放器共用）。

    顺序与迁移前逐位同序：主 pass（清屏 + 几何） -> 天空 -> World Canvas。
    天空的深度/剔除语义 = 「几何后画 + LEQUAL 等值通过 + 不剔除」（GL 现状）。
    """
    targets = (TargetDecl(SCREEN_TARGET, format='rgba8unorm', size='screen', depth='own'),)
    passes = [
        PassSpec('main', shader='main', target=SCREEN_TARGET, load='clear',
                 clear=tuple(clear_color),
                 depth=DepthState(test=True, write=True, func='less', clear=1.0),
                 raster=RasterState(cull='back', front_face='cw'),
                 bindings=_MAIN_BINDINGS,
                 params=(ParamField('u_view_proj', count=16),
                         ParamField('u_view_pos', count=3),
                         ParamField('u_light_count', dtype='i32')),
                 draws=(DrawCmd('buckets'),)),
    ]
    if include_sky:
        passes.append(
            PassSpec('sky', shader='sky', target=SCREEN_TARGET, load='load',
                     depth=DepthState(test=True, write=False, func='lequal'),
                     raster=RasterState(cull='none'),
                     bindings=_SKY_BINDINGS,
                     params=(ParamField('u_inv_view_proj', count=16),
                             ParamField('u_camera_pos', count=3),
                             ParamField('u_skybox_tint', count=3)),
                     draws=(DrawCmd('skybox'),))
        )
    if include_world_canvas:
        passes.append(
            PassSpec('world_ui', shader='world_ui', target=SCREEN_TARGET, load='load',
                     depth=DepthState(test=True, write=False, func='less'),
                     raster=RasterState(cull='none', blend='alpha'),
                     draws=(DrawCmd('world_canvas'),))
        )
    return FramePlan(targets=targets, passes=tuple(passes))
