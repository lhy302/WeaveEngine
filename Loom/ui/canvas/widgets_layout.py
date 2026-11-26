# -*- coding: utf-8 -*-
"""ui/canvas/widgets_layout.py — 布局控件 (ScrollView / ProgressBar / GridLayout)

我负责: 滚动容器 (裁剪 + 滚动偏移)、进度条、网格自动排布。
我不负责: 基础可视控件 (widgets_basic.py)、交互输入控件 (widgets_input.py)、元素基类 (element.py)。
拆分: Q-B7-38-1 第 7 批 (2026-11-26), 原文 Loom/loom_ui.py 1277-1400 + 1680-1727 逐字搬入。
"""

from .element import UIElement

class ScrollView(UIElement):
    """可滚动容器 (契约 §3.3). 超出内容区的子元素被裁剪, 右侧滚动条可选."""

    ctype = 'scroll_view'

    def __init__(self, name='scroll', rect=(0, 0, 300, 200),
                 content_size=(300, 800),
                 bg_color=(30, 34, 44, 255),
                 bar_color=(120, 130, 150, 255),
                 bar_width=8,
                 show_bar=True,
                 scroll_step=30,
                 **kw):
        super().__init__(name=name, rect=rect, **kw)
        self._content_size = (max(0.0, float(content_size[0])),
                              max(0.0, float(content_size[1])))
        self.scroll_pos = (0.0, 0.0)   # (x, y), y 为负时向上滚 (看下方内容)
        self.bg_color = tuple(bg_color)
        self.bar_color = tuple(bar_color)
        self.bar_width = int(bar_width)
        self.show_bar = bool(show_bar)
        self.scroll_step = int(scroll_step)

    @property
    def content_size(self):
        return self._content_size

    @content_size.setter
    def content_size(self, v):
        try:
            w, h = (float(t) for t in v)
        except (TypeError, ValueError):
            return
        self._content_size = (max(0.0, w), max(0.0, h))
        self._clamp_scroll()

    def _clamp_scroll(self):
        """滚动范围钳制: scroll_x ∈ [-(cw-w), 0], scroll_y ∈ [-(ch-h), 0]."""
        x, y, w, h = self.rect
        cw, ch = self._content_size
        max_sx = max(0.0, cw - w)
        max_sy = max(0.0, ch - h)
        sx = max(-max_sx, min(0.0, self.scroll_pos[0]))
        sy = max(-max_sy, min(0.0, self.scroll_pos[1]))
        self.scroll_pos = (sx, sy)

    def can_scroll(self):
        x, y, w, h = self.rect
        cw, ch = self._content_size
        return cw > w or ch > h

    def scroll_by(self, dx, dy):
        sx, sy = self.scroll_pos
        self.scroll_pos = (sx + dx, sy + dy)
        self._clamp_scroll()

    def on_mouse_wheel(self, delta):
        """滚轮事件: delta > 0 向上滚 (看更上面), delta < 0 向下滚 (看更下面).

        scroll_pos.y 语义: 0 = 内容顶部, 负值 = 向下滚.
        向上滚 -> y 趋向 0; 向下滚 -> y 趋向 -(content_h - view_h).
        """
        if not self.can_scroll():
            return False
        self.scroll_by(0, delta * self.scroll_step)
        return True

    def child_offset(self):
        """子元素绘制/命中时的坐标偏移 (叠加 scroll_pos)."""
        return self.scroll_pos

    def draw(self, engine, screen_rect):
        engine.draw_screen_rect(screen_rect, self.bg_color)
        x, y, w, h = screen_rect
        cw, ch = self._content_size
        if self.show_bar and ch > h:
            bar_x = x + w - self.bar_width
            engine.draw_screen_rect((bar_x, y, self.bar_width, h),
                                    (self.bar_color[0], self.bar_color[1],
                                     self.bar_color[2], 60))
            frac = h / ch
            block_h = max(20, int(h * frac))
            max_sy = max(1.0, ch - h)
            ratio = -self.scroll_pos[1] / max_sy
            block_y = int(y + (h - block_h) * ratio)
            engine.draw_screen_rect((bar_x, block_y, self.bar_width, block_h),
                                    self.bar_color)


class ProgressBar(UIElement):
    """只读进度条 (契约 §3.3). value: 0~1."""

    ctype = 'progress_bar'

    def __init__(self, name='progress', rect=(0, 0, 200, 18),
                 value=0.0,
                 bg_color=(40, 44, 54, 255),
                 fill_color=(80, 220, 120, 255), **kw):
        super().__init__(name=name, rect=rect, **kw)
        self._value = max(0.0, min(1.0, float(value)))
        self.bg_color = tuple(bg_color)
        self.fill_color = tuple(fill_color)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = max(0.0, min(1.0, float(v)))

    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        engine.draw_screen_rect(screen_rect, self.bg_color)
        fw = int(w * self._value)
        if fw > 0:
            engine.draw_screen_rect((x, y, fw, h), self.fill_color)


class GridLayout(UIElement):
    """网格布局 (契约 §3.3). 按 columns/cell_size/spacing 自动排列子元素.

    自身仅绘制背景 (可选); 子元素 rect 由 _reflow 自动计算.
    """

    ctype = 'grid_layout'

    def __init__(self, name='grid', rect=(0, 0, 400, 300),
                 cell_size=(64, 64), spacing=(8, 8), columns=4,
                 bg_color=(0, 0, 0, 0), **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.cell_w, self.cell_h = cell_size
        self.spacing_x, self.spacing_y = spacing
        self.columns = max(1, int(columns))
        self.bg_color = tuple(bg_color)

    def add_child(self, child):
        super().add_child(child)
        self._reflow()
        return child

    def remove_child(self, child):
        r = super().remove_child(child)
        self._reflow()
        return r

    def _reflow(self):
        for i, c in enumerate(self.children):
            row = i // self.columns
            col = i % self.columns
            cx = col * (self.cell_w + self.spacing_x)
            cy = row * (self.cell_h + self.spacing_y)
            c.rect = (cx, cy, self.cell_w, self.cell_h)

    def content_height(self):
        rows = (len(self.children) + self.columns - 1) // self.columns
        return rows * self.cell_h + max(0, rows - 1) * self.spacing_y

    def draw(self, engine, screen_rect):
        if len(self.bg_color) > 3 and self.bg_color[3] == 0:
            return
        engine.draw_screen_rect(screen_rect, self.bg_color)
