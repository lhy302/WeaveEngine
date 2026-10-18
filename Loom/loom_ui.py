# -*- coding: utf-8 -*-
"""loom_ui.py — Canvas/UI 系统数据模型与布局 (2026-10-18)

契约: docs/design/CanvasUI系统契约_20261018.md
本文件只做「数据模型 + 布局计算 + 树操作 + 查找」, 不依赖 moderngl/pygame,
便于无头单测。渲染由 loom_ui_render.py (阶段1第4步) 接; 输入由阶段2 接。

层次:
  UIManager  多 Canvas 容器 (渲染/命中入口)
  Canvas     单个 UI 画布 (screen / world)
  UIElement  UI 元素基类 (Panel/Text/Button... 的父类)
"""
import math


class UIElement:
    """UI 元素基类.

    坐标约定: rect=(x, y, w, h) 是相对父容器的偏移与尺寸 (像素, y 向下).
    anchor: 锚点 (0~1), 决定元素「贴父容器哪个位置」;
    pivot:  轴心 (0~1), 决定元素「自身哪个点对齐到锚点」.
    默认 (0,0)+(0,0) = 左上对齐; (1,1)+(1,1) = 右下对齐; (0.5,0.5)+(0.5,0.5) = 居中.
    """

    ctype = 'element'

    def __init__(self, name='element', rect=(0, 0, 100, 30),
                 anchor=(0.0, 0.0), pivot=(0.0, 0.0),
                 visible=True, enabled=True, z_order=0):
        self.name = name
        # 通过 property 赋值, 让 rect/anchor/pivot 的钳制校验生效
        self.rect = rect
        self.anchor = anchor
        self.pivot = pivot
        self.visible = bool(visible)
        self.enabled = bool(enabled)
        self.z_order = int(z_order)
        self.parent = None
        self.children = []

    # ---- 字段校验 (钳制到合法范围) ----
    @property
    def rect(self):
        return self._rect

    @rect.setter
    def rect(self, v):
        try:
            x, y, w, h = (float(t) for t in v)
        except (TypeError, ValueError):
            return                    # 非法值静默忽略 (保留原值)
        self._rect = (x, y, max(0.0, w), max(0.0, h))

    @property
    def anchor(self):
        return self._anchor

    @anchor.setter
    def anchor(self, v):
        try:
            ax, ay = (float(t) for t in v)
        except (TypeError, ValueError):
            return
        self._anchor = (max(0.0, min(1.0, ax)), max(0.0, min(1.0, ay)))

    @property
    def pivot(self):
        return self._pivot

    @pivot.setter
    def pivot(self, v):
        try:
            px, py = (float(t) for t in v)
        except (TypeError, ValueError):
            return
        self._pivot = (max(0.0, min(1.0, px)), max(0.0, min(1.0, py)))

    # ---- 树操作 ----
    def add_child(self, child):
        """挂子元素 (自动脱原父). 返回 child."""
        if child is self:
            return child
        # 防环: 往上检查 child 不是 self 的祖先
        cur = self
        while cur is not None:
            if cur is child:
                return child
            cur = cur.parent
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        self.children.append(child)
        return child

    def remove_child(self, child):
        """移除子元素 (返回被移除者或 None)."""
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            return child
        return None

    def clear_children(self):
        for c in list(self.children):
            c.parent = None
        self.children.clear()

    def find(self, name):
        """深度优先按 name 查找 (含自身). 找不到返回 None."""
        if self.name == name:
            return self
        for c in self.children:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None

    def find_all(self, name):
        """深度优先找出所有同名元素 (重名允许, 返回列表)."""
        out = []
        if self.name == name:
            out.append(self)
        for c in self.children:
            out.extend(c.find_all(name))
        return out

    def walk(self):
        """深度优先遍历 (含自身), 父先于子, 同级按 children 顺序."""
        yield self
        for c in list(self.children):
            yield from c.walk()

    # ---- 布局计算 ----
    def screen_rect(self, parent_rect):
        """由父屏幕矩形计算本元素的屏幕矩形.

        parent_rect: (px, py, pw, ph) 父容器屏幕矩形 (Canvas 根为 (0,0,W,H)).
        语义: 元素的 pivot 点对齐到父容器的 anchor 点.
        公式 (契约 §4.1):
            x = px + pw * ax - rw * pvx + rx
            y = py + ph * ay - rh * pvy + ry
        """
        px, py, pw, ph = parent_rect
        rx, ry, rw, rh = self._rect
        ax, ay = self._anchor
        pvx, pvy = self._pivot
        x = px + pw * ax - rw * pvx + rx
        y = py + ph * ay - rh * pvy + ry
        return (x, y, rw, rh)

    def screen_rect_recursive(self, parent_rect):
        """返回 {id(element): screen_rect} 全树屏幕矩形映射 (先序, 父先算)."""
        out = {}
        stack = [(self, parent_rect)]
        while stack:
            elem, pr = stack.pop()
            sr = elem.screen_rect(pr)
            out[id(elem)] = sr
            # 逆序压栈, 保证输出顺序与 children 一致 (可选, 便于调试)
            for c in reversed(elem.children):
                stack.append((c, sr))
        return out

    # ---- 命中测试 ----
    @staticmethod
    def _point_in_rect(pos, rect):
        x, y = pos
        rx, ry, rw, rh = rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    def hit_test(self, pos, parent_rect):
        """命中测试 (从最上层往下). 返回命中的 UIElement 或 None.

        规则 (契约 §6.2):
          - 自身不可见/禁用 -> 整个子树跳过
          - 子元素优先于父 (后加的画在上面, 先测后面的)
          - 命中 ScrollView 时, 超出内容区的子元素不参与 (阶段3 实现, 当前跳过)
        """
        if not self.visible:
            return None
        sr = self.screen_rect(parent_rect)
        if not self._point_in_rect(pos, sr):
            return None
        # 子元素后加的画在上面 -> 逆序测
        for c in reversed(self.children):
            hit = c.hit_test(pos, sr)
            if hit is not None:
                return hit
        if not self.enabled:
            return None
        return self

    # ---- 渲染接口 (阶段1第4步实现具体绘制, 当前空实现) ----
    def draw(self, engine, screen_rect):
        """绘制自身 (子类覆写). engine 提供 draw_screen_rect / draw_text_quad 等."""
        pass


class Canvas:
    """UI 画布 (契约 §3.2). screen = 屏幕空间; world = 世界空间 (阶段4 实现)."""

    def __init__(self, canvas_type='screen', width=1920, height=1080,
                 target=None, world_scale=1.0, z_order=0):
        self.canvas_type = 'world' if canvas_type == 'world' else 'screen'
        self.width = int(width)
        self.height = int(height)
        self.target = target            # world 模式的宿主 GameObject
        self.world_scale = float(world_scale)
        self.z_order = int(z_order)
        # 根元素 (Panel 在阶段1第3步实现; 当前用 UIElement 占位)
        self.root = UIElement(name='root', rect=(0, 0, self.width, self.height))

    def resize(self, width, height):
        """窗口变化时同步 (契约 §4.3: 不自动缩放元素尺寸, 仅更新根矩形)."""
        self.width = int(width)
        self.height = int(height)
        self.root.rect = (0, 0, self.width, self.height)

    def find(self, name):
        return self.root.find(name)

    def screen_rects(self):
        """返回本 Canvas 全树屏幕矩形 {id: (x,y,w,h)}."""
        return self.root.screen_rect_recursive((0.0, 0.0,
                                                float(self.width),
                                                float(self.height)))


class UIManager:
    """多 Canvas 容器 (渲染/命中入口)."""

    def __init__(self):
        self.canvases = []

    def add_canvas(self, canvas):
        if canvas not in self.canvases:
            self.canvases.append(canvas)
            self.canvases.sort(key=lambda c: c.z_order)
        return canvas

    def remove_canvas(self, canvas):
        if canvas in self.canvases:
            self.canvases.remove(canvas)
            return canvas
        return None

    def clear(self):
        self.canvases.clear()

    def find(self, name):
        """跨 Canvas 查找 (按 z_order 从小到大找, 返回第一个命中)."""
        for c in self.canvases:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None

    def resize(self, width, height):
        """窗口 resize: screen Canvas 全同步; world Canvas 不受影响."""
        for c in self.canvases:
            if c.canvas_type == 'screen':
                c.resize(width, height)

    def hit_test(self, pos):
        """从最上层 Canvas 往下测, 返回 (canvas, element) 或 (None, None)."""
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue          # world Canvas 命中留到阶段4
            hit = c.root.hit_test(pos, (0.0, 0.0,
                                        float(c.width), float(c.height)))
            if hit is not None:
                return c, hit
        return None, None


# =================== 阶段1 元素: Panel / Text (2026-10-18) ===================

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


