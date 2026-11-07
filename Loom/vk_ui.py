# -*- coding: utf-8 -*-
"""vk_ui.py — Vulkan 后端 Canvas UI / HUD 绘制子系统 (2026-11-06)

目标: 让 Vulkan 后端能画 loom_ui.UIManager 的 screen Canvas 元素树与 HUD 文本,
视觉与 GL 路径 (loom_hud.draw_text_quad / draw_screen_rect + loom_shaders._HUD_*) 一致.

设计 (与 GL 一一对应的"最小面"):
  GL 侧 UI 最终只落到两个原语上 ——
    * draw_screen_rect(rect, color)        1x1 白纹理 + u_color 乘法
    * draw_text_quad(text, x, y, color, s) pygame 渲染成纹理 -> 画 quad
  (Image 走 draw_texture_quad, Shape 走 draw_screen_polygon/lines)
  因此本模块实现**同一套原语门面** VkUIEngine, 直接喂给 UIManager.draw_all(),
  所有上层元素 (Panel/Text/Button/Slider/Toggle/ProgressBar/ScrollView/InputField/
  Dropdown/GridLayout) 无需改动即可复用 —— 元素绘制逻辑只有一份 (loom_ui.py).

  ★ 驱动约束 (本项目 GPU 有 bind group 组合 / 动态 sampler 索引死锁史):
    只用**一条独立 UI 管线 + 单 bind group (uniform + 1 texture + 1 sampler)**,
    同一时刻只绑一组, 不与其他管线 (主 pass / 天空盒 / 阴影) 混用, 也无数组索引.

  ★ 坐标/UV 约定 (与 GL 单位 quad 逐顶点对齐):
    GL: in_pos(0,0)(1,0)(1,1)(0,0)(1,1)(0,1), in_uv 同值; NDC y 向上 =>
      in_pos.y=0 是 quad **底边**; 纹理上传时行序已翻转 (loom_hud._surf_to_tex
      的 [::-1]), 故 GL 的 v=0 = 图像底行。
    wgpu/Vulkan 纹理 v=0 = 上传数据第 0 行 => 上传前同样翻转行序, 保持 v=0=底行。
    顶点位置用屏幕像素坐标 (y 向下), 着色器内换算 NDC (y 翻转)。

  ★ 混合: 与 GL ctx.enable(BLEND) 默认同式 (SRC_ALPHA / ONE_MINUS_SRC_ALPHA)。

用法 (渲染层):
    ui = VkUIEngine(device, format)          # 懒建, 随 VkRenderer 存活
    ui.begin_frame(w, h)                     # 清空本帧 op 列表
    ui.draw_hud_lines(lines)                 # 可选: HUD 文本行
    ui.draw_all(ui_manager)                  # 可选: Canvas 元素树
    ui.submit(rp)                            # 在 load_op='load' 的 pass 里提交
"""
from collections import OrderedDict

import numpy as np
import wgpu

# 每顶点 32B: 位置 xy(像素) + uv + 颜色 rgba (与 GL 的 "quad 属性 + u_color" 等价)
_VERT_BYTES = 32
_TEXT_CACHE_MAX = 400          # 与 engine._text_cache_max 一致

# ---- R2 契约 (2026-11-06, 2026-11-07 修订) ---------------------------------
# GL 的 Shape 描边走 engine.draw_screen_lines -> GL_LINES + line_width (光栅化
# 规则由 GL 驱动决定); VK 没有 line 图元, 用三角带逐段展开近似. 两者在
# **线段边缘/端点/连接处的像素覆盖**上不同 -> 不是逐像素等价.
# A/B 实测 (480x320, tests/_tmp/ui_lines_scene.json / ui_lines_alpha_scene.json):
#   不透明场景 MAE=0.00357361 (858/153600 像素不同; 唯一 width=1 的 line1
#   实测 0 像素差, 残差全部来自 width>=2 描边的三角带 vs GL 2/4px 线)
#   alpha 场景  MAE=0.00680006 (10044/153600; 其中 9500 像素是 poly3 填充的
#   alpha 语义差 —— GL draw_screen_polygon 走 draw_lines 不切混合、忽略 alpha,
#   VK 恒 SRC_ALPHA; 描边部分约 544 像素)
# 2026-11-07 line-list 实验 (已回退): 曾给 width<=1 描边单开一条 line-list
#   管线 (wgpu 拓扑 line-list, 恒 1px). 实测本驱动 (NVIDIA Vulkan) 的 1px 线
#   光栅化与三角带 hw=0.5 **逐像素相同**: 多角度探针 (0/18/22/45/60/90°) 与
#   5 角度 GPU 直测均 0 像素差, 两个验收场景 MAE 与改前逐值相同 -> 无改善,
#   按"不保留看起来修了"回退.
#   残差根因: (a) 858px 全在 width>=2, WebGPU 线宽恒为 1px, line-list 覆盖
#   不到; (b) 1px 水平线存在 GL/VK tie-break 差 (GL 画 row20, VK 画 row19),
#   line-list 同样不修. 详见 docs/audit/fix_vk_render_batch.md 第 9 节.
# 结论: 走契约层声明 (非门禁项), 不宣称像素一致. 见残差报告 R2.
STROKE_PIXEL_EQUIVALENT = False
STROKE_METHOD = 'triangle-band'

_UI_WGSL = """
struct UIC {
    screen: vec4f,      // xy = 屏幕像素尺寸 (z/w 备用)
};
@group(0) @binding(0) var<uniform> uc: UIC;
@group(0) @binding(1) var t_ui: texture_2d<f32>;
@group(0) @binding(2) var s_ui: sampler;

struct VSOut {
    @builtin(position) pos: vec4f,
    @location(0) uv: vec2f,
    @location(1) color: vec4f,
};

// 像素坐标 (左上原点, y 向下) -> NDC (y 向上, 与 GL 同约定)
@vertex fn vs(@location(0) p: vec2f,
              @location(1) uv: vec2f,
              @location(2) c: vec4f) -> VSOut {
    var o: VSOut;
    let n = vec2f(p.x / uc.screen.x * 2.0 - 1.0,
                  1.0 - p.y / uc.screen.y * 2.0);
    o.pos = vec4f(n, 0.0, 1.0);
    o.uv = uv;
    o.color = c;
    return o;
}

@fragment fn fs(i: VSOut) -> @location(0) vec4f {
    // 与 GL _HUD_FRAG 同式: texture(u_tex, v_uv) * u_color
    return textureSample(t_ui, s_ui, i.uv) * i.color;
}
"""


def _c4(color):
    """(r,g,b) / (r,g,b,a) 0..255 -> 0..1 f32 四元组 (同 loom_hud 的 /255 语义)."""
    if color is None:
        return (1.0, 1.0, 1.0, 1.0)
    if len(color) >= 4:
        return (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0,
                color[3] / 255.0)
    return (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)


class UiTexture:
    """GPU 纹理句柄 (surface/图片上传产物). 仅记录 view 与像素尺寸."""

    __slots__ = ('tex', 'view', 'w', 'h', 'key')

    def __init__(self, tex, view, w, h, key=None):
        self.tex = tex
        self.view = view
        self.w = w
        self.h = h
        self.key = key


_FONT_CHAIN = None


def _font_chain():
    """进程级 FontChain 单例 (与 loom_hud 共用同一实现, 字形栅格化逐像素一致)."""
    global _FONT_CHAIN
    if _FONT_CHAIN is None:
        from loom_font import FontChain
        _FONT_CHAIN = FontChain()
    return _FONT_CHAIN


def surf_to_rgba(surf):
    """pygame Surface -> 连续 RGBA (h, w, 4) 且**行序翻转** (v=0 对齐图像底行).

    与 loom_hud._surf_to_tex 的 transpose + 行倒序结果同源:
    那里是 (w,h,4) 列优先塞给 GL (GL 行 0 = 底行); 这里给 wgpu 用行主序,
    所以把行序倒过来即可 (v=0 仍然采到图像底行).
    """
    import pygame
    w, h = surf.get_size()
    rgb = pygame.surfarray.array3d(surf)            # (w,h,3)
    alpha = pygame.surfarray.array_alpha(surf)      # (w,h)
    rgba = np.concatenate([rgb, alpha[:, :, None]], axis=2).astype('u1')
    rgba = np.transpose(rgba, (1, 0, 2))            # (h,w,4) 行主序 (y 向下)
    return np.ascontiguousarray(rgba[::-1])         # v=0 <-> 图像底行


class VkUIEngine:
    """GL 引擎 UI 原语门面: UIManager.draw_all(engine) / 各元素 draw() 直接复用.

    只记录绘制指令 (ops), 真正的 GPU 提交在 submit() 里做 —— 这样 UIManager 的
    绘制语义 (父子次序 / scissor / 文本纹理) 与 GL 完全一致.
    """

    def __init__(self, pipeline):
        self._r = pipeline
        self.width = 0
        self.height = 0
        # 每个 op: (texture_or_None, scissor_or_None, verts Nx8 float32)
        self._ops = []
        self._scissor = None
        self._scissor_stack = []
        self.draw_stats = {'rect': 0, 'text': 0, 'image': 0, 'polygon': 0,
                           'lines': 0, 'skipped': 0}

    # ---------------- 帧 ----------------
    def begin_frame(self, width, height):
        self.width = int(width)
        self.height = int(height)
        self._ops = []
        self._scissor = None
        self._scissor_stack = []
        for k in self.draw_stats:
            self.draw_stats[k] = 0

    def has_content(self):
        return bool(self._ops)

    # ---------------- 文本测量/渲染 (loom_ui / loom_hud 契约) ----------------
    def _measure_text(self, text, size=None):
        return _font_chain().measure(text, size or 16)

    def _render_text(self, text, color, size=None):
        return _font_chain().render(text, color, size or 16)

    def _surf_to_tex(self, surf):
        """pygame Surface -> UiTexture (Image 元素与 draw_text_quad 共用)."""
        return self._r.texture_from_surface(surf)

    # ---------------- 基础原语 (与 loom_hud 同名同签名) ----------------
    def draw_screen_rect(self, rect, color):
        """屏幕像素填充矩形 (左上原点), 语义同 loom_hud.draw_screen_rect."""
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        self._push_quad(None, x, y, w, h, _c4(color))
        self.draw_stats['rect'] += 1

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        """屏幕像素坐标画文字 (x,y 左上角), 语义同 loom_hud.draw_text_quad."""
        if not text:
            return
        tex = self._r.texture_for_text(text, color, size)
        if tex is None:
            self.draw_stats['skipped'] += 1
            return
        self._push_quad(tex, float(x), float(y), float(tex.w), float(tex.h),
                        (1.0, 1.0, 1.0, 1.0))
        self.draw_stats['text'] += 1

    def draw_texture_quad(self, tex, rect, tint=(255, 255, 255, 255)):
        """任意纹理 quad (Image 元素); tint 0..255 乘到纹理上."""
        if tex is None:
            return
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        if not isinstance(tex, UiTexture):
            self.draw_stats['skipped'] += 1     # GL 纹理对象无法在 Vk 侧采样
            return
        self._push_quad(tex, x, y, w, h, _c4(tint))
        self.draw_stats['image'] += 1

    def draw_screen_polygon(self, pts_2d, color):
        """三角形扇填充 (与 engine.draw_screen_polygon 同三角化: 从第 0 点扇出)."""
        if not pts_2d or len(pts_2d) < 3:
            return
        c = _c4(color)
        # 2026-11-07 对齐 GL 状态语义: engine.draw_screen_polygon 也走 draw_lines,
        # 而 GL 在 UI 绘制期间 BLEND 处于关闭 -> 多边形填充的 alpha **被忽略**
        # (画成不透明)。Vk 恒开混合, 若直接用 alpha, 半透明填充会比 GL 淡。
        # 实测: alpha 描边场景 10044 差异像素里 ~9500 来自本项 (非描边)。
        c = (c[0], c[1], c[2], 1.0)
        p0 = pts_2d[0]
        verts = []
        for i in range(1, len(pts_2d) - 1):
            for (px, py) in (p0, pts_2d[i], pts_2d[i + 1]):
                verts.append((float(px), float(py), 0.0, 0.0,
                              c[0], c[1], c[2], c[3]))
        self._emit(None, np.asarray(verts, dtype=np.float32))
        self.draw_stats['polygon'] += 1

    def draw_screen_lines(self, pts_2d, color, width=2.0, close=False):
        """折线描边 — 三角带近似 (每段展开成 width 像素宽的 quad).

        ★ 与 GL **非逐像素等价** (契约见模块级 STROKE_PIXEL_EQUIVALENT):
          GL   = GL_LINES + line_width, 覆盖规则是驱动的线段光栅化 (diamond
                 规则的像素交点判定);
          VK   = 每段一个 width 宽的矩形三角带, 覆盖规则是像素中心落在矩形内.
        两者在斜线/端点/拐角处会差 1px 的覆盖; 实测 480x320 场景仅 858 个
        像素不同 (0.56%), 但 MAX 可达 0.93 (整像素级), MAE=0.00357.
        该差异属"图元级近似", 不能靠三角带参数调优消除 (已实测 cap/miter
        变体, MAE 反而略升) —— 见 tests/_tmp/VK_UI残差收口_20261106.md R2.
        2026-11-07 line-list 实验已实测并回退: width<=1 的 1px line-list 与
        本三角带逐像素相同 (探针 0 像素差), 无改善 —— 见模块级契约注释.
        """
        if not pts_2d or len(pts_2d) < 2:
            return
        c = _c4(color)
        # 2026-11-07 对齐 GL 状态语义: engine.draw_screen_lines 走 draw_lines,
        # 而 GL 在 UI 绘制期间 BLEND 处于关闭 -> 描边的 alpha **被忽略**(画成
        # 不透明)。Vk 恒开混合, 若直接用 alpha, 半透明描边会比 GL 淡一大截
        # (实测 alpha 场景 MAE 0.0103 / 7.5% 像素)。这里把 alpha 钉成 1 复刻
        # 同一视觉效果 (alpha=1 混合 == 直接写色)。
        c = (c[0], c[1], c[2], 1.0)
        segs = [(pts_2d[i], pts_2d[i + 1]) for i in range(len(pts_2d) - 1)]
        if close:
            segs.append((pts_2d[-1], pts_2d[0]))
        hw = max(0.5, float(width) * 0.5)
        verts = []
        for (p0, p1) in segs:
            x0, y0 = float(p0[0]), float(p0[1])
            x1, y1 = float(p1[0]), float(p1[1])
            dx, dy = x1 - x0, y1 - y0
            ln = (dx * dx + dy * dy) ** 0.5
            if ln < 1e-6:
                continue
            nx, ny = -dy / ln * hw, dx / ln * hw
            a = (x0 + nx, y0 + ny)
            b = (x1 + nx, y1 + ny)
            d = (x1 - nx, y1 - ny)
            e = (x0 - nx, y0 - ny)
            for tri in ((a, b, d), (a, d, e)):
                for (px, py) in tri:
                    verts.append((px, py, 0.0, 0.0,
                                  c[0], c[1], c[2], c[3]))
        if verts:
            self._emit(None, np.asarray(verts, dtype=np.float32))
            self.draw_stats['lines'] += 1

    # ---------------- scissor (ScrollView 裁剪, 与 loom_hud 同语义) ----------------
    def push_scissor(self, rect):
        self._scissor_stack.append(self._scissor)
        x, y, w, h = rect
        cur = self._scissor
        if cur is not None:
            ox, oy, ow, oh = cur
            nx = max(x, ox)
            ny = max(y, oy)
            nw = max(0.0, min(x + w, ox + ow) - nx)
            nh = max(0.0, min(y + h, oy + oh) - ny)
            self._scissor = (nx, ny, nw, nh)
        else:
            self._scissor = (max(0.0, x), max(0.0, y), max(0.0, w), max(0.0, h))

    def pop_scissor(self):
        if self._scissor_stack:
            self._scissor = self._scissor_stack.pop()

    # ---------------- 高层入口 ----------------
    def draw_hud_lines(self, lines, x=10, y=10, line_h=24,
                       color=(255, 255, 255)):
        """HUD 文本行 (语义同 loom_hud._draw_hud: 左上加 10px 内边距, 行高 24)."""
        for i, text in enumerate(lines or ()):
            self.draw_text_quad(text, x, y + i * line_h, color)

    def draw_all(self, ui_manager):
        """渲染 UIManager 的所有 screen Canvas (直接复用保留模式绘制逻辑)."""
        if ui_manager is None:
            return
        try:
            ui_manager.draw_all(self)
        except Exception as e:      # UI 异常不得拖垮 3D 帧
            print('[vk] Canvas UI 绘制异常 (跳过):', repr(e))

    # ---------------- op 记录 ----------------
    def _push_quad(self, tex, x, y, w, h, c):
        """与 engine._build_hud_quad 的 6 顶点/UV 一一对应 (in_pos.y=0 是底边)."""
        x0, y0, x1, y1 = x, y, x + w, y + h
        r, g, b, a = c
        verts = np.asarray([
            (x0, y1, 0.0, 0.0, r, g, b, a),
            (x1, y1, 1.0, 0.0, r, g, b, a),
            (x1, y0, 1.0, 1.0, r, g, b, a),
            (x0, y1, 0.0, 0.0, r, g, b, a),
            (x1, y0, 1.0, 1.0, r, g, b, a),
            (x0, y0, 0.0, 1.0, r, g, b, a),
        ], dtype=np.float32)
        self._emit(tex, verts)

    def _emit(self, tex, verts):
        self._ops.append((tex, self._scissor, verts))

    # ---------------- 提交 ----------------
    def submit(self, render_pass):
        """在已开启 (load_op='load', 无深度附件) 的 render pass 内提交全部 op."""
        if not self._ops:
            return 0
        r = self._r
        groups = r.prepare(self._ops)          # [(tex, scissor, first, count)]
        rp = render_pass
        rp.set_pipeline(r.pipeline)
        r.bind_vertex_buffer(rp)
        rp.set_bind_group(0, r.uniform_group, [], 0, 1)
        draws = 0
        for tex, sc, first, count in groups:
            if count <= 0:
                continue
            if not self._apply_scissor(rp, sc):
                continue                    # 裁剪区完全在屏外: 整组跳过
            rp.set_bind_group(0, r.group_for(tex), [], 0, 1)
            rp.draw(count, 1, first, 0)
            draws += 1
        return draws

    def _apply_scissor(self, rp, sc):
        """设置 scissor; 返回 False 表示该组完全被裁掉 (wgpu 不接受 0 尺寸)."""
        w, h = self.width, self.height
        if sc is None:
            rp.set_scissor_rect(0, 0, max(1, w), max(1, h))
            return True
        x, y, sw, sh = sc
        x0 = max(0, int(round(x)))
        y0 = max(0, int(round(y)))
        x1 = min(w, int(round(x + sw)))
        y1 = min(h, int(round(y + sh)))
        if x1 <= x0 or y1 <= y0:
            return False
        rp.set_scissor_rect(x0, y0, x1 - x0, y1 - y0)
        return True


def hud_lines_from_driver(driver, backend='Vulkan (wgpu)', extra=()):
    """按 loom_hud._hud_lines 的**语义**生成 Vk 侧 HUD 文本行 (可用子集).

    GL 的 _hud_lines 依赖 GLEngine 内部状态 (fps / 帧长方差 / 逻辑时钟对象),
    scene_driver 上没有这些; 这里用 driver 能给出的等价事实 (相机位姿 / 模型数 /
    三角形数) 拼同一套格式, 其余行由调用方用 extra 追加 (例如 FPS)。
    行**绘制**语义与 GL 完全一致: (10,10) 起, 行高 24, 16 号白字, 见
    VkUIEngine.draw_hud_lines。
    """
    import math
    cam = getattr(driver, 'camera_pos', None)
    if callable(cam):
        cam = cam()
    cam = cam or (0.0, 0.0, 0.0)
    yaw = float(getattr(driver, 'yaw', 0.0))
    pitch = float(getattr(driver, 'pitch', 0.0))
    yaw_deg = 360 - math.degrees(yaw) % 360
    pitch_deg = math.degrees(pitch)
    models = list(getattr(driver, 'models', []) or [])
    faces = 0
    for m in models:
        mesh = getattr(m, 'mesh', None)
        try:
            faces += len(mesh.faces) if mesh is not None else 0
        except Exception:
            pass
    lines = [
        '相机位置: (%.2f, %.2f, %.2f) | 视角: 偏航角=%.1f°, 俯仰角=%.1f°'
        % (cam[0], cam[1], cam[2], yaw_deg, pitch_deg),
        '模型数: %d | 三角形: %d' % (len(models), faces),
        '渲染后端: %s | 硬件深度测试 + 背面剔除' % backend,
    ]
    lines.extend(extra)
    return lines


class VkUIPipeline:
    """UI 管线资源: 单 pipeline + 单 bind group 模板 (uniform/tex/sampler)."""

    def __init__(self, device, present_format):
        self.device = device
        self.format = present_format
        d = device
        shader = d.create_shader_module(code=_UI_WGSL)
        self.bgl = d.create_bind_group_layout(entries=[
            {'binding': 0,
             'visibility': wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
             'buffer': {'type': 'uniform'}},
            {'binding': 1, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 2, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'filtering'}}])
        self.pipeline = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[self.bgl]),
            vertex={'module': shader, 'entry_point': 'vs', 'buffers': [{
                'array_stride': _VERT_BYTES, 'step_mode': 'vertex',
                'attributes': [
                    {'shader_location': 0, 'offset': 0, 'format': 'float32x2'},
                    {'shader_location': 1, 'offset': 8, 'format': 'float32x2'},
                    {'shader_location': 2, 'offset': 16, 'format': 'float32x4'}]}]},
            primitive={'topology': 'triangle-list', 'cull_mode': 'none'},
            fragment={'module': shader, 'entry_point': 'fs', 'targets': [{
                'format': present_format,
                'blend': {
                    # ★ alpha 通道也必须 SRC_ALPHA/ONE_MINUS_SRC_ALPHA ——
                    # GL 的 ctx.blend_func=(SRC_ALPHA, ONE_MINUS_SRC_ALPHA) 对
                    # RGB 和 alpha 同时生效. 屏幕 pass 的 alpha 被忽略, 但 world
                    # Canvas 的离屏纹理 alpha 会参与世界 quad 混合: 若这里用
                    # (ONE, ONE_MINUS_SRC_ALPHA), 半透明文字边缘的 alpha 会从
                    # a² 变成 a, 世界 quad 合成结果与 GL 不一致 (实测 MAE 4e-4).
                    'color': {'operation': 'add',
                              'src_factor': 'src-alpha',
                              'dst_factor': 'one-minus-src-alpha'},
                    'alpha': {'operation': 'add',
                              'src_factor': 'src-alpha',
                              'dst_factor': 'one-minus-src-alpha'}}}]})
        self.uniform_buf = d.create_buffer(
            size=16, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.sampler = d.create_sampler(
            mag_filter='linear', min_filter='linear',
            address_mode_u='clamp-to-edge', address_mode_v='clamp-to-edge')
        # 1x1 白纹理 (纯色矩形用, 同 engine._hud_white_tex)
        self.white_tex = d.create_texture(
            size=(1, 1, 1), format='rgba8unorm',
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        d.queue.write_texture({'texture': self.white_tex},
                              bytes([255, 255, 255, 255]),
                              {'bytes_per_row': 4, 'rows_per_image': 1}, (1, 1, 1))
        self.white_view = self.white_tex.create_view()
        # 2026-11-07: bind group 池改成有界 LRU (原来是普通 dict, 每出现一个新
        # view 就多一条, 永不清 —— Image/文本纹理换一批就长一批)。
        self._groups = OrderedDict()
        self._vbuf = None
        self._vcap = 0
        self._text_cache = OrderedDict()
        self._last_size = None
        self._stats = {'textures': 0, 'groups': 0}

    # ---------------- bind group ----------------
    _GROUPS_MAX = 512          # bind group 池上限 (> _TEXT_CACHE_MAX, 留图片 headroom)

    def group_for(self, tex):
        view = self.white_view if tex is None else tex.view
        key = id(view)
        item = self._groups.get(key)
        if item is not None:
            self._groups.move_to_end(key)
        else:
            g = self.device.create_bind_group(layout=self.bgl, entries=[
                {'binding': 0, 'resource': {'buffer': self.uniform_buf,
                                            'offset': 0, 'size': 16}},
                {'binding': 1, 'resource': view},
                {'binding': 2, 'resource': self.sampler}])
            item = (g, view)
            self._groups[key] = item
            self._stats['groups'] += 1
            # 上限淘汰: 丢的只是 group 对象 (view 仍在调用方手里, 下次用到
            # 会按同一 view 重建) —— 不销毁纹理, 不属于纹理所有权。
            while len(self._groups) > self._GROUPS_MAX:
                self._groups.popitem(last=False)
        return item[0]

    @property
    def uniform_group(self):
        return self.group_for(None)

    # ---------------- 纹理 ----------------
    def _upload(self, rgba, w, h, key=None):
        d = self.device
        tex = d.create_texture(
            size=(max(1, w), max(1, h), 1), format='rgba8unorm',
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        arr = np.ascontiguousarray(rgba, dtype=np.uint8)
        d.queue.write_texture(
            {'texture': tex},
            arr.tobytes(),
            {'bytes_per_row': max(1, w) * 4, 'rows_per_image': max(1, h)},
            (max(1, w), max(1, h), 1))
        self._stats['textures'] += 1
        return UiTexture(tex, tex.create_view(), w, h, key)

    def texture_from_surface(self, surf):
        """pygame Surface -> UiTexture (Image 元素 / 文本共用同一上传路径)."""
        if surf is None:
            return None
        w, h = surf.get_size()
        return self._upload(surf_to_rgba(surf), w, h)

    def texture_for_text(self, text, color, size):
        """文本 -> 纹理 (LRU, 键与 GL 的 (text, color, size) 同构)."""
        key = (text, tuple(color) if color is not None else None, size)
        item = self._text_cache.get(key)
        if item is not None:
            self._text_cache.move_to_end(key)
            return item
        try:
            surf = _font_chain().render(text, color, size or 16)
        except Exception:
            return None
        tex = self.texture_from_surface(surf)
        if tex is None:
            return None
        tex.key = key
        self._text_cache[key] = tex
        # 2026-11-07 修复: 原来只 popitem 出 LRU 字典, 既不销毁 GPU 纹理, 也
        # 不清楚 _groups (以 id(view) 为键) —— 文本纹理与 bind group 双双无界
        # 增长 (每出现一条新文本就漏 1 张纹理 + 1 个 group)。
        self._evict_text_lru()
        return tex

    def _evict_text_lru(self):
        """文本纹理 LRU 淘汰: 销毁 GPU 纹理并摘掉它的 bind group."""
        while len(self._text_cache) > _TEXT_CACHE_MAX:
            _k, tex = self._text_cache.popitem(last=False)
            self._release_texture(tex)

    def _release_texture(self, tex):
        """释放一个 UiTexture 的 GPU 资源.

        顺序要紧: bind group 里钉着 view, 必须先摘 group 再 destroy 纹理;
        否则淘汰只是"字典里忘了", 显存与 group 都还在。
        """
        if tex is None:
            return
        try:
            self._groups.pop(id(getattr(tex, 'view', None)), None)
        except Exception:
            pass
        destroy = getattr(getattr(tex, 'tex', None), 'destroy', None)
        if destroy is not None:
            try:
                destroy()
            except Exception:
                pass

    def clear_cache(self):
        for tex in list(self._text_cache.values()):
            self._release_texture(tex)
        self._text_cache.clear()
        self._groups.clear()
        self._stats['groups'] = 0

    # ---------------- 顶点组装 ----------------
    def prepare(self, ops):
        """ops -> 顶点缓冲已写入, 返回 [(tex, scissor, first_vertex, count)]."""
        total = sum(int(v.shape[0]) for _, _, v in ops)
        if total <= 0:
            return []
        buf = np.empty((total, 8), dtype=np.float32)
        pos = 0
        groups = []
        cur = None
        for tex, sc, verts in ops:
            n = int(verts.shape[0])
            buf[pos:pos + n] = verts
            gkey = (id(tex) if tex is not None else 0,
                    None if sc is None else tuple(sc))
            if cur is not None and cur[0] == gkey:
                cur[3] += n
            else:
                cur = [gkey, tex, sc, n, pos]
                groups.append(cur)
            pos += n
        self._ensure_vbuf(total * _VERT_BYTES)
        self.device.queue.write_buffer(self._vbuf, 0, buf.tobytes())
        return [(g[1], g[2], g[4], g[3]) for g in groups]

    def _ensure_vbuf(self, nbytes):
        if self._vbuf is not None and self._vcap >= nbytes:
            return
        cap = max(4096, nbytes * 2)
        self._vbuf = self.device.create_buffer(
            size=cap, usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self._vcap = cap

    def bind_vertex_buffer(self, rp):
        if self._vbuf is not None:
            rp.set_vertex_buffer(0, self._vbuf)

    def set_screen(self, w, h):
        key = (int(w), int(h))
        if self._last_size == key:
            return
        self._last_size = key
        arr = np.zeros(4, dtype=np.float32)
        arr[0] = float(w)
        arr[1] = float(h)
        self.device.queue.write_buffer(self.uniform_buf, 0, arr.tobytes())

    def stats(self):
        return dict(self._stats, cached_text=len(self._text_cache))

# ==================== R1: World Space Canvas (2026-11-06) ====================
# 与 GL loom_render._draw_world_canvases 同语义:
#   1) world Canvas 的元素树先画进一张离屏 RGBA8 纹理 (透明底, 与 GL clear(0,0,0,0) 同);
#   2) 再以世界坐标 quad 贴回主 pass, 参与深度测试 (depth_write=False,
#      compare='less'), 因此可被 3D 物体遮挡 —— 与 GL 的 depth_mask=False 同。
# ★驱动约束沿用: 独立一条管线 + 单 bind group (VP uniform + 1 texture + 1
#   sampler), 不与主 pass/屏幕 UI 的 bind group 混用。
#
# ★UV 方向: 离屏纹理在 wgpu 里 v=0 = 第 0 行 = 画布顶端 (UI 管线把 y=0 映到
#   NDC +1). 与 GL 的 v=1=顶端相反, 所以世界 quad 的 uv 在 VK 侧上下翻转
#   (TL=(0,0), BL=(0,1)), 采样出的图像方向才与 GL 一致。
_WORLD_UI_WGSL = """
struct WorldC {
    vp: mat4x4<f32>,        // 与主 pass 同一行主序字节直传 (WGSL 列主序解释 = 数学行主序)
};
@group(0) @binding(0) var<uniform> wc: WorldC;
@group(0) @binding(1) var t_world: texture_2d<f32>;
@group(0) @binding(2) var s_world: sampler;

struct VSOut {
    @builtin(position) pos: vec4f,
    @location(0) uv: vec2f,
};

@vertex fn vs(@location(0) p: vec3f, @location(1) uv: vec2f) -> VSOut {
    var o: VSOut;
    o.pos = wc.vp * vec4f(p, 1.0);
    o.uv = uv;
    return o;
}

@fragment fn fs(i: VSOut) -> @location(0) vec4f {
    // 与 GL _WORLD_UI_FRAG 同式: texture(u_tex, v_uv)
    return textureSample(t_world, s_world, i.uv);
}
"""

_WORLD_VERT_BYTES = 20        # pos3f + uv2f


class VkWorldUIPipeline:
    """world Canvas 的世界 quad 管线 (离屏纹理 -> 主 pass, 带深度测试)."""

    def __init__(self, device, present_format, depth_format='depth32float'):
        self.device = device
        self.format = present_format
        d = device
        shader = d.create_shader_module(code=_WORLD_UI_WGSL)
        self.bgl = d.create_bind_group_layout(entries=[
            {'binding': 0,
             'visibility': wgpu.ShaderStage.VERTEX,
             'buffer': {'type': 'uniform'}},
            {'binding': 1, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'texture': {'sample_type': 'float', 'view_dimension': '2d'}},
            {'binding': 2, 'visibility': wgpu.ShaderStage.FRAGMENT,
             'sampler': {'type': 'filtering'}}])
        self.pipeline = d.create_render_pipeline(
            layout=d.create_pipeline_layout(bind_group_layouts=[self.bgl]),
            vertex={'module': shader, 'entry_point': 'vs', 'buffers': [{
                'array_stride': _WORLD_VERT_BYTES, 'step_mode': 'vertex',
                'attributes': [
                    {'shader_location': 0, 'offset': 0, 'format': 'float32x3'},
                    {'shader_location': 1, 'offset': 12, 'format': 'float32x2'}]}]},
            primitive={'topology': 'triangle-list', 'cull_mode': 'none'},
            # 与 GL 一致: 参与深度测试(可被遮挡), 但不写深度
            depth_stencil={'format': depth_format,
                           'depth_write_enabled': False,
                           'depth_compare': 'less'},
            fragment={'module': shader, 'entry_point': 'fs', 'targets': [{
                'format': present_format,
                'blend': {
                    # 与 GL world quad 的 ctx.blend_func (SRC_ALPHA /
                    # ONE_MINUS_SRC_ALPHA, RGB 与 alpha 同式) 一致.
                    'color': {'operation': 'add',
                              'src_factor': 'src-alpha',
                              'dst_factor': 'one-minus-src-alpha'},
                    'alpha': {'operation': 'add',
                              'src_factor': 'src-alpha',
                              'dst_factor': 'one-minus-src-alpha'}}}]})
        self.uniform_buf = d.create_buffer(
            size=64, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.sampler = d.create_sampler(
            mag_filter='linear', min_filter='linear',
            address_mode_u='clamp-to-edge', address_mode_v='clamp-to-edge')
        self._vbuf = None
        self._vcap = 0

    def group_for(self, view):
        return self.device.create_bind_group(layout=self.bgl, entries=[
            {'binding': 0, 'resource': {'buffer': self.uniform_buf,
                                        'offset': 0, 'size': 64}},
            {'binding': 1, 'resource': view},
            {'binding': 2, 'resource': self.sampler}])

    def set_view_proj(self, vp):
        arr = np.asarray(vp, dtype=np.float32).reshape(16)
        self.device.queue.write_buffer(self.uniform_buf, 0, arr.tobytes())

    def set_vertices(self, verts):
        arr = np.ascontiguousarray(verts, dtype=np.float32)
        nbytes = int(arr.nbytes)
        if self._vbuf is None or self._vcap < nbytes:
            self._vcap = max(4096, nbytes * 2)
            self._vbuf = self.device.create_buffer(
                size=self._vcap,
                usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self.device.queue.write_buffer(self._vbuf, 0, arr.tobytes())
        return arr.shape[0]

# ==================== R3: UI 输入桥 (2026-11-06) ====================
# GL 路径的输入分发 (editor._dispatch_ui_mouse / loom_glfw_window._on_key_cb /
# _on_char_cb) 与后端无关; Vk 播放器此前没把窗口事件接进 driver.ui.
# 本类把 GLFW 回调事件缓存成"每帧一次"的 UIManager 事件, 语义与 GL 逐条对齐:
#
#   鼠标: 帧首 dispatch_mouse(pos, 本帧新按下, 本帧新松开, wheel);
#         未消费时再 update_hover_only(pos) —— 与 editor._dispatch_ui_mouse 同序.
#   键盘: 按下沿立即 dispatch_key(pg_key, mods); 返回 True 时调用方**不得**再写
#         driver.key_state (GL _on_key_cb 的 "UI 优先" 分支).
#   文本: char callback -> dispatch_text (GL _on_char_cb -> _pending_chars -> UI).
#   相机: UI 消费了点击 / 正在拖动 / 仍有按下未松开 -> wants_camera()=False,
#         播放器本帧不喂 mouse_rel (UI 捕获鼠标时不同时转视角).
#   滚轮: last_wheel_consumed 只回答"本帧滚轮是否被 ScrollView 消费",
#         与 last_consumed (本帧鼠标事件整体) 分开, 见 _wheel_taken_by_scrollview.
_PENDING_UP_BUG_WARNED = False


def _wheel_taken_by_scrollview(ui, pos):
    """本帧滚轮是否真被 UI 的 ScrollView 吃掉 (滚轮专属判据).

    与 UIManager.dispatch_mouse 的滚轮分支同一判据: 指针命中的最近
    ScrollView 存在且可滚动。判不了时保守认为已被消费 (与 vk_player
    的旧助手同语义), 避免把可能被 UI 吃掉的滚轮再交给相机/脚本。
    """
    if ui is None:
        return False
    if not hasattr(ui, '_hit_scroll_view'):
        return True
    try:
        sv = ui._hit_scroll_view(pos)
    except Exception:
        return True
    if sv is None:
        return False
    try:
        return bool(sv.can_scroll())
    except Exception:
        return True


class UIInputBridge:
    """GLFW 事件 -> loom_ui.UIManager 的无 GPU 输入桥 (可 headless 单测)."""

    __slots__ = ('ui', 'pos', '_pressed', '_released', '_wheel',
                 'last_consumed', 'last_wheel', 'last_wheel_consumed',
                 'ui_active')

    def __init__(self, ui=None):
        self.ui = ui
        self.pos = (0.0, 0.0)
        self._pressed = set()
        self._released = set()
        self._wheel = 0
        self.last_consumed = False
        self.last_wheel = 0
        self.last_wheel_consumed = False
        self.ui_active = False

    # ---- GLFW 回调入口 (与 backend 无关, 只缓存数据) ----
    def on_cursor(self, x, y):
        self.pos = (float(x), float(y))

    def on_mouse_button(self, button, down):
        """button 用 pygame/GLEngine 语义: 1=左 2=中 3=右."""
        b = int(button)
        if down:
            self._pressed.add(b)
        else:
            self._released.add(b)

    def on_scroll(self, yoff):
        self._wheel += int(yoff)

    def on_key(self, pg_key, mods=0):
        """按下沿调用; 返回 True = 焦点元素消费, 调用方跳过 key_state."""
        return self.dispatch_key(pg_key, mods)

    def on_text(self, text):
        return self.dispatch_text(text)

    # ---- 帧首分发 ----
    def begin_frame(self):
        """把本帧缓存事件分发给 UI (每帧最多一次). 返回 consumed."""
        ui = self.ui
        pressed = set(self._pressed)
        released = set(self._released)
        wheel = int(self._wheel)
        self._pressed.clear()
        self._released.clear()
        self._wheel = 0
        self.last_wheel = wheel
        if ui is None:
            self.last_consumed = False
            self.last_wheel_consumed = False
            self.ui_active = False
            return False
        # 2026-11-07 R5: 滚轮专属判据在 dispatch 前取 —— dispatch 会改
        # scroll_pos, 先取可保证"这一帧滚轮进 UI 前"的命中状态与
        # UIManager.dispatch_mouse 的滚轮分支同源.
        wheel_taken = bool(wheel) and _wheel_taken_by_scrollview(ui, self.pos)
        try:
            consumed = bool(ui.dispatch_mouse(self.pos, pressed, released, wheel))
        except Exception as e:
            consumed = False
            # 兼容 loom_ui 当前版本的已知缺陷 (2026-11-06 实测):
            #   self._dragging_elem._dragging = False if ... else None
            # 赋值语句先求 RHS 再求 target, 非 Slider 松开时 _dragging_elem 为
            # None -> AttributeError, 导致其后的 _pressed_elem/_dragging_elem
            # 清理不执行, UI 会永久处于"按下"态并一直抢相机.
            # 不修改 loom_ui.py, 这里按它原本要执行的清理补完 (每进程只提示一次).
            if "_dragging" in repr(e):
                global _PENDING_UP_BUG_WARNED
                if not _PENDING_UP_BUG_WARNED:
                    _PENDING_UP_BUG_WARNED = True
                    print('[vk] loom_ui 非 Slider 松开清理缺陷: 已由 UI 输入桥兜底 '
                          '(不修改 loom_ui.py)')
                try:
                    pe = getattr(ui, '_pressed_elem', None)
                    if pe is not None:
                        try:
                            pe._pressed = False
                        except Exception:
                            pass
                    ui._pressed_elem = None
                    ui._dragging_elem = None
                    ui._last_pointer_down = None
                except Exception:
                    pass
            else:
                print('[vk] UI dispatch_mouse 异常 (跳过本帧):', repr(e))
        if not consumed:
            try:
                ui.update_hover_only(self.pos)
            except Exception:
                pass
        self.last_consumed = consumed
        # last_wheel_consumed 只回答"本帧滚轮是否被 UI 消费", 不再复用
        # 鼠标事件整体的 consumed: 同帧"点按钮 + 滚轮"时 consumed=True
        # 但滚轮并未被 ScrollView 吃掉, 旧语义会把滚轮一起标成已消费.
        self.last_wheel_consumed = bool(wheel) and consumed and wheel_taken
        # UI 捕获指针的判据 (任一成立): 本帧事件被消费 / 有元素被按住 /
        # 拖动中 / 有 pointer-down 尚未 up. 与 GL 的 ui_consumed 不同,
        # 这里覆盖"拖动跨帧"的情况, 避免拖动滑条时视角跟着转.
        active = bool(consumed)
        for attr in ('_pressed_elem', '_dragging_elem', '_last_pointer_down'):
            if getattr(ui, attr, None) is not None:
                active = True
        self.ui_active = active
        return consumed

    def wants_camera(self):
        """本帧是否允许把光标增量喂给相机 (UI 未捕获)."""
        return not self.ui_active

    # ---- 键盘/文本 (事件时刻立即分发, 与 GL 回调同序) ----
    def dispatch_key(self, pg_key, mods=0):
        if self.ui is None:
            return False
        try:
            return bool(self.ui.dispatch_key(pg_key, mods))
        except Exception:
            return False

    def dispatch_text(self, text):
        if self.ui is None or not text:
            return False
        try:
            return bool(self.ui.dispatch_text(text))
        except Exception:
            return False


