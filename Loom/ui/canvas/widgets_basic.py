# -*- coding: utf-8 -*-
"""ui/canvas/widgets_basic.py — 基础可视控件 (Shape / Panel / Text / Image)

我负责: Shape (2D 图形, 含 _SHAPE_* 每进程上报去重)、Panel (容器背景)、
        Text (文本, 含自动换行)、Image (贴图, 含缩放适配)。
我不负责: 交互输入控件 (widgets_input.py)、布局控件 (widgets_layout.py)、元素基类 (element.py)。
拆分: Q-B7-38-1 第 7 批 (2026-11-26), 原文 Loom/loom_ui.py 113-115 + 828-1043 逐字搬入。
"""

import math

from .element import UIElement

# 2026-11-16 B14: Shape 绘制失败上报去重（每进程各只报一次）。
_SHAPE_FILL_ERR_REPORTED = False
_SHAPE_STROKE_ERR_REPORTED = False


class Shape(UIElement):
    """2D 图形元素 (2026-10-20 沙盘支持).

    支持 4 种形状，用 shape_type 区分：
      - 'line'     两点直线段
      - 'polyline' 折线（不闭合）
      - 'polygon'  多边形（自动闭合，可填充）
      - 'circle'   圆（近似 32 段）

    坐标约定:
      - points 是元素内相对坐标 [(px, py), ...]，需转成绝对像素后绘制。
      - circle 只用 rect 的边界（填满矩形），radius > 0 时按 radius 覆盖 rect 中心。
      - polygon 的填充用三角形扇（从第 0 点扇出），对凸多边形精确；凹多边形会有瑕疵。

    颜色: (r, g, b) 或 (r, g, b, a) 0~255。
    线宽: stroke_width 像素（>=1）。
    """

    ctype = 'shape'

    def __init__(self, name='shape', rect=(0, 0, 100, 100),
                 shape_type='line', points=None, radius=0.0,
                 stroke_color=(255, 255, 255, 255), stroke_width=2,
                 fill_color=None, segments=32, close=False, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.shape_type = str(shape_type)
        if self.shape_type not in ('line', 'polyline', 'polygon', 'circle'):
            self.shape_type = 'line'
        self.points = list(points or [])
        self.radius = float(radius)
        self.stroke_color = tuple(stroke_color) if stroke_color else None
        self.stroke_width = max(1, int(stroke_width))
        self.fill_color = tuple(fill_color) if fill_color else None
        self.segments = max(8, int(segments))
        # close: 是否在 polyline 上自动闭合（polygon 恒闭合，不需此字段）
        self.close = bool(close)

    def _resolve_points_px(self):
        """返回绝对像素坐标列表（元素内坐标 + 屏幕位置）。"""
        x, y, w, h = self._screen_rect_cached
        if self.shape_type == 'circle':
            import math
            r = self.radius if self.radius > 0 else min(w, h) / 2.0
            cx, cy = x + w / 2.0, y + h / 2.0
            out = []
            for i in range(self.segments + 1):
                a = 2 * math.pi * i / self.segments
                out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            return out
        # 其它形状：points 是元素内坐标 (0..w, 0..h)
        return [(x + float(px), y + float(py)) for (px, py) in self.points]

    def draw(self, engine, screen_rect):
        # 保存屏幕 rect（供 _resolve_points_px 用）
        self._screen_rect_cached = screen_rect
        pts_px = self._resolve_points_px()
        if not pts_px:
            return
        # 填充（polygon / circle 支持）
        if self.fill_color and len(pts_px) >= 3:
            try:
                engine.draw_screen_polygon(pts_px, self.fill_color)
            except Exception as e:      # 2026-11-16 B14: 失败必须可见（原为 except: pass）
                global _SHAPE_FILL_ERR_REPORTED
                if not _SHAPE_FILL_ERR_REPORTED:
                    _SHAPE_FILL_ERR_REPORTED = True
                    print('[ui] Shape 填充失败(本进程只报一次): %r' % (e,))
        # 描边
        if self.stroke_color and len(pts_px) >= 2:
            close = (self.shape_type == 'polygon' or
                     self.shape_type == 'circle' or
                     self.close)
            try:
                engine.draw_screen_lines(pts_px, self.stroke_color,
                                         width=self.stroke_width,
                                         close=close)
            except Exception as e:      # 2026-11-16 B14: 失败必须可见（原为 except: pass）
                global _SHAPE_STROKE_ERR_REPORTED
                if not _SHAPE_STROKE_ERR_REPORTED:
                    _SHAPE_STROKE_ERR_REPORTED = True
                    print('[ui] Shape 描边失败(本进程只报一次): %r' % (e,))


class Panel(UIElement):
    """纯色矩形 (契约 §3.3). bg_color=(r,g,b) 或 (r,g,b,a) 0~255."""

    ctype = 'panel'

    def __init__(self, name='panel', rect=(0, 0, 100, 30),
                 bg_color=(0, 0, 0, 128), **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.bg_color = tuple(bg_color)

    def draw(self, engine, screen_rect):
        engine.draw_screen_rect(screen_rect, self.bg_color)


class Text(UIElement):
    """文字元素 (契约 §3.3). 支持自动换行 (wrap_width > 0) 与 UTF-8 全字符集
    (走 engine.draw_text_quad -> loom_font.FontChain 多字体回退)."""

    ctype = 'text'

    def __init__(self, name='text', rect=(0, 0, 200, 30), text='',
                 font_size=16, color=(255, 255, 255),
                 align='left', wrap_width=0, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.text = str(text)
        self.font_size = int(font_size)
        self.color = tuple(color)
        self.align = align if align in ('left', 'center', 'right') else 'left'
        self.wrap_width = max(0, int(wrap_width))

    def _wrap_lines(self, engine):
        """自动换行: 按测量宽度累计切行 (中英混排/emoji 安全)."""
        if not self.text:
            return []
        if self.wrap_width <= 0:
            return self.text.split('\n')
        lines = []
        cur = []
        cur_w = 0
        for ch in self.text:
            if ch == '\n':
                lines.append(''.join(cur))
                cur, cur_w = [], 0
                continue
            w = engine._measure_text(ch, self.font_size)[0]
            if cur_w + w > self.wrap_width and cur:
                lines.append(''.join(cur))
                cur, cur_w = [ch], w
            else:
                cur.append(ch)
                cur_w += w
        if cur:
            lines.append(''.join(cur))
        return lines

    def draw(self, engine, screen_rect):
        if not self.text:
            return
        x, y, w, h = screen_rect
        lines = self._wrap_lines(engine)
        line_h = engine._measure_text('Mg', self.font_size)[1] or self.font_size
        for i, line in enumerate(lines):
            if not line:
                continue
            lw = engine._measure_text(line, self.font_size)[0]
            if self.align == 'center':
                tx = x + (w - lw) / 2
            elif self.align == 'right':
                tx = x + w - lw
            else:
                tx = x
            engine.draw_text_quad(line, int(tx), int(y + i * line_h),
                                  self.color, self.font_size)


class Image(UIElement):
    """图片元素 (契约 §3.3). fit: stretch 拉伸 / contain 等比装入 / cover 等比填满."""

    ctype = 'image'

    def __init__(self, name='image', rect=(0, 0, 100, 100),
                 texture_path='', tint=(255, 255, 255, 255),
                 fit='stretch', **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.texture_path = str(texture_path or '')
        self.tint = tuple(tint) + ((255,) if len(tint) == 3 else ())
        self.fit = fit if fit in ('stretch', 'contain', 'cover') else 'stretch'
        self._tex = None
        self._tex_size = (0, 0)
        self._tex_loaded = False

    def _load(self, engine):
        """惰性加载图片 -> moderngl 纹理. 失败时 _tex 保持 None (画占位灰底)."""
        if self._tex_loaded:
            return
        self._tex_loaded = True
        if not self.texture_path:
            return
        try:
            import pygame
            # 不用 convert_alpha(): 它要求 display 已初始化, 无头环境会抛异常;
            # PNG 载入后本身带 SRCALPHA, _surf_to_tex 走 array_alpha 可正常处理
            # (与 draw_text_quad 里 font.render(True, color) 的表面同款).
            surf = pygame.image.load(self.texture_path)
            self._tex = engine._surf_to_tex(surf)
            self._tex_size = surf.get_size()
        except Exception:
            self._tex = None

    def _fit_rect(self, rect):
        """按 fit 策略计算实际绘制矩形 (相对于 screen_rect)."""
        x, y, w, h = rect
        tw, th = self._tex_size
        if tw <= 0 or th <= 0:
            return rect
        if self.fit == 'stretch':
            return (x, y, w, h)
        if self.fit == 'contain':
            s = min(w / tw, h / th)
        else:               # cover
            s = max(w / tw, h / th)
        dw, dh = tw * s, th * s
        return (x + (w - dw) / 2, y + (h - dh) / 2, dw, dh)

    def draw(self, engine, screen_rect):
        self._load(engine)
        if self._tex is None:
            engine.draw_screen_rect(screen_rect, (80, 80, 80, 255))
            return
        engine.draw_texture_quad(self._tex, self._fit_rect(screen_rect), self.tint)
