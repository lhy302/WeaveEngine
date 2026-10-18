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
        # 2026-10-18 阶段2: 交互状态 (每帧由 UIManager 分发器更新, 不序列化)
        self._hover = False
        self._pressed = False       # 本元素当前被按下 (按钮/滑条/勾选)
        self._dragging = False      # 本元素正在被拖动 (滑条)

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

    # ---- 事件接口 (阶段2, 子类覆写) ----
    def on_mouse_enter(self):
        """鼠标进入 (hover 开始). 子类可覆写."""
        pass

    def on_mouse_leave(self):
        """鼠标离开. 子类可覆写."""
        pass

    def on_mouse_down(self, pos):
        """鼠标左键在本元素上按下. 返回 True = 已消费该事件 (阻止穿透)."""
        return False

    def on_mouse_up(self, pos):
        """鼠标左键松开 (不保证在本元素内). 返回 True = 已消费该事件."""
        return False

    def on_mouse_drag(self, pos):
        """按住时鼠标移动 (仅 _dragging=True 的滑条等). 返回 True = 已消费."""
        return False

    # ---- 渲染接口 ----
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
        # 2026-10-18 阶段2: 交互状态 (每帧由 dispatch_mouse 更新)
        self._hovered = None        # 当前鼠标悬停的元素
        self._pressed_elem = None   # 当前被按下的元素
        self._dragging_elem = None  # 当前拖动中的元素 (滑条)

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


    # ---- 鼠标事件分发 (阶段2) ----
    def dispatch_mouse(self, pos, pressed, released):
        """每帧分发鼠标事件到 UI 树. 返回 True = 本帧点击被 UI 消费.

        pressed / released 是「本帧新按下/松开」的键码集合 (engine 语义).
        只处理左键 (键码 1). 见契约 §6.
        """
        left_down = 1 in pressed
        left_up = 1 in released

        # 1) 命中测试 (只测 screen Canvas, 从最上层 Canvas 开始)
        hovered = None
        hit_canvas = None
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue
            hit = c.root.hit_test(pos, (0.0, 0.0,
                                        float(c.width), float(c.height)))
            if hit is not None:
                hovered = hit
                hit_canvas = c
                break

        # 2) hover 变化通知
        if hovered is not self._hovered:
            if self._hovered is not None:
                try:
                    self._hovered.on_mouse_leave()
                except Exception:
                    pass
            if hovered is not None:
                try:
                    hovered.on_mouse_enter()
                except Exception:
                    pass
            self._hovered = hovered

        consumed = False

        # 3) 按下
        if left_down and hovered is not None:
            try:
                if hovered.on_mouse_down(pos):
                    self._pressed_elem = hovered
                    consumed = True
            except Exception:
                pass

        # 4) 拖动 (滑条等)
        if self._dragging_elem is not None and hit_canvas is not None:
            try:
                sr = self._dragging_elem.screen_rect(
                    (0.0, 0.0, float(hit_canvas.width), float(hit_canvas.height)))
                if hasattr(self._dragging_elem, 'drag_to'):
                    self._dragging_elem.drag_to(pos, sr)
                    consumed = True
            except Exception:
                pass
        # 若当前 hover 的是 Slider 且已按下, 开始拖动
        if (self._pressed_elem is not None
                and self._pressed_elem.ctype == 'slider'
                and self._dragging_elem is None):
            self._pressed_elem._dragging = True
            self._dragging_elem = self._pressed_elem

        # 5) 松开
        if left_up:
            if self._pressed_elem is not None:
                try:
                    if self._pressed_elem.on_mouse_up(pos):
                        consumed = True
                except Exception:
                    pass
                self._pressed_elem._pressed = False
                if self._dragging_elem is not None:
                    self._dragging_elem._dragging = False
                self._pressed_elem = None
                self._dragging_elem = None

        return consumed

    def update_hover_only(self, pos):
        """仅更新 hover 状态 (无点击时每帧调, 用于按钮悬停效果)."""
        hovered = None
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue
            hit = c.root.hit_test(pos, (0.0, 0.0,
                                        float(c.width), float(c.height)))
            if hit is not None:
                hovered = hit
                break
        if hovered is not self._hovered:
            if self._hovered is not None:
                try:
                    self._hovered.on_mouse_leave()
                except Exception:
                    pass
            if hovered is not None:
                try:
                    hovered.on_mouse_enter()
                except Exception:
                    pass
            self._hovered = hovered

    def draw_all(self, engine):
        """渲染所有 screen Canvas 的元素树 (渲染层末尾调用). 父先于子."""
        for c in self.canvases:
            if c.canvas_type != 'screen':
                continue
            self._draw_elem(c.root, engine,
                            (0.0, 0.0, float(c.width), float(c.height)))

    @staticmethod
    def _draw_elem(elem, engine, parent_rect):
        if not elem.visible:
            return
        sr = elem.screen_rect(parent_rect)
        elem.draw(engine, sr)
        for child in list(elem.children):
            UIManager._draw_elem(child, engine, sr)

    def default_canvas(self):
        """返回第一个 screen Canvas (无则创建 1920x1080). 脚本便捷入口."""
        for c in self.canvases:
            if c.canvas_type == 'screen':
                return c
        c = Canvas(canvas_type='screen', width=1920, height=1080)
        self.add_canvas(c)
        return c



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


# =================== 阶段2 元素: Button / Slider / Toggle / ProgressBar ===================

class Button(UIElement):
    """按钮 (契约 §3.3). 按下+松开在同一元素内才触发 on_click (用户决策 1=B)."""

    ctype = 'button'

    def __init__(self, name='button', rect=(0, 0, 120, 36), text='',
                 font_size=16, text_color=(255, 255, 255),
                 normal_color=(70, 80, 100, 255),
                 hover_color=(90, 100, 125, 255),
                 pressed_color=(50, 60, 80, 255),
                 on_click=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.text = str(text)
        self.font_size = int(font_size)
        self.text_color = tuple(text_color)
        self.normal_color = tuple(normal_color)
        self.hover_color = tuple(hover_color)
        self.pressed_color = tuple(pressed_color)
        self.on_click = on_click

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False
        # 鼠标移出时清按下态 (移出再移回不触发)
        self._pressed = False

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        self._pressed = True
        return True

    def on_mouse_up(self, pos):
        if not self.enabled:
            return False
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed and self.on_click is not None:
            try:
                self.on_click()
            except Exception:
                pass
            return True
        return was_pressed

    def draw(self, engine, screen_rect):
        if self._pressed and self._hover:
            bg = self.pressed_color
        elif self._hover:
            bg = self.hover_color
        else:
            bg = self.normal_color
        engine.draw_screen_rect(screen_rect, bg)
        if self.text:
            lw = engine._measure_text(self.text, self.font_size)[0]
            lh = engine._measure_text('Mg', self.font_size)[1] or self.font_size
            x, y, w, h = screen_rect
            tx = int(x + (w - lw) / 2)
            ty = int(y + (h - lh) / 2)
            engine.draw_text_quad(self.text, tx, ty, self.text_color, self.font_size)


class Slider(UIElement):
    """滑条 (契约 §3.3). 拖拽锁定 + 边界钳制 (用户决策 2=C)."""

    ctype = 'slider'

    def __init__(self, name='slider', rect=(0, 0, 200, 24),
                 min_value=0.0, max_value=1.0, value=0.0,
                 direction='h',
                 track_color=(50, 55, 70, 255),
                 fill_color=(80, 140, 220, 255),
                 handle_color=(220, 225, 235, 255),
                 on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        self.direction = 'v' if direction == 'v' else 'h'
        self._value = self._clamp(float(value))
        self.track_color = tuple(track_color)
        self.fill_color = tuple(fill_color)
        self.handle_color = tuple(handle_color)
        self.on_change = on_change

    def _clamp(self, v):
        return max(self.min_value, min(self.max_value, v))

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._set_value(float(v), notify=False)

    def _set_value(self, v, notify=True):
        v = self._clamp(v)
        changed = (v != self._value)
        self._value = v
        if changed and notify and self.on_change is not None:
            try:
                self.on_change(v)
            except Exception:
                pass

    def _ratio(self):
        span = self.max_value - self.min_value
        return (self._value - self.min_value) / span if span > 0 else 0.0

    def _pos_to_value(self, pos, screen_rect):
        x, y, w, h = screen_rect
        if self.direction == 'h':
            t = (pos[0] - x) / w if w > 0 else 0.0
        else:
            t = (y + h - pos[1]) / h if h > 0 else 0.0
        t = max(0.0, min(1.0, t))
        return self.min_value + t * (self.max_value - self.min_value)

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        self._pressed = True
        self._dragging = True
        return True

    def on_mouse_up(self, pos):
        self._pressed = False
        self._dragging = False
        return False

    def on_mouse_drag(self, pos):
        # 阶段2 UIElement 签名是 on_mouse_drag(pos), 但滑条需 screen_rect 才能算值,
        # 由 UIManager 分发时额外传 screen_rect (见 UIManager.dispatch_mouse).
        return True

    def drag_to(self, pos, screen_rect):
        """UIManager 分发时调用: 用鼠标位置更新值 (边界钳制)."""
        if not self._dragging:
            return
        v = self._pos_to_value(pos, screen_rect)
        self._set_value(v, notify=True)

    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        engine.draw_screen_rect(screen_rect, self.track_color)
        ratio = self._ratio()
        if self.direction == 'h':
            fw = int(w * ratio)
            if fw > 0:
                engine.draw_screen_rect((x, y, fw, h), self.fill_color)
            hx = int(x + w * ratio) - 4
            engine.draw_screen_rect((hx, y - 2, 8, h + 4), self.handle_color)
        else:
            fh = int(h * ratio)
            if fh > 0:
                engine.draw_screen_rect((x, y + h - fh, w, fh), self.fill_color)
            hy = int(y + h - h * ratio) - 4
            engine.draw_screen_rect((x - 2, hy, w + 4, 8), self.handle_color)


class Toggle(UIElement):
    """勾选框 (契约 §3.3). 点击切换 is_on."""

    ctype = 'toggle'

    def __init__(self, name='toggle', rect=(0, 0, 160, 24),
                 is_on=False, label='',
                 box_color=(70, 80, 100, 255),
                 check_color=(80, 200, 120, 255),
                 label_color=(230, 230, 230),
                 label_size=16,
                 on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.is_on = bool(is_on)
        self.label = str(label)
        self.box_color = tuple(box_color)
        self.check_color = tuple(check_color)
        self.label_color = tuple(label_color)
        self.label_size = int(label_size)
        self.on_change = on_change

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False
        self._pressed = False

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        self._pressed = True
        return True

    def on_mouse_up(self, pos):
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed and self.enabled:
            self.is_on = not self.is_on
            if self.on_change is not None:
                try:
                    self.on_change(self.is_on)
                except Exception:
                    pass
            return True
        return was_pressed

    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        box = min(h, 20)
        engine.draw_screen_rect((x, y, box, box), self.box_color)
        if self.is_on:
            pad = 3
            engine.draw_screen_rect((x + pad, y + pad,
                                     box - 2 * pad, box - 2 * pad),
                                    self.check_color)
        if self.label:
            engine.draw_text_quad(self.label, x + box + 8, y, self.label_color,
                                  self.label_size)


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



