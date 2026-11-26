# -*- coding: utf-8 -*-
"""ui/canvas/widgets_input.py — 交互输入控件 (Button / Slider / Toggle / InputField / Dropdown)

我负责: 可点击 / 可拖动 / 可输入控件及其事件触发 (经 manager._fire_binding 派发声明式绑定)。
我不负责: 基础可视控件 (widgets_basic.py)、布局控件 (widgets_layout.py)、元素基类 (element.py)。
拆分: Q-B7-38-1 第 7 批 (2026-11-26), 原文 Loom/loom_ui.py 1045-1215 + 1401-1678 逐字搬入。
"""

from .element import UIElement
from .manager import _fire_binding

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
        if was_pressed:
            # 2026-10-19 P0-5: Python callable 与声明式绑定并存
            if self.on_click is not None:
                try:
                    self.on_click()
                except Exception:
                    pass
            _fire_binding(self, 'click')
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


class InputField(UIElement):
    """单行文本输入框 (契约 §3.3). 键盘焦点 + IME 支持（B1：不显示拼音中间态）.

    焦点由 UIManager 统一管理：点击本元素 -> UIManager.focused = self；
    点击其他元素 -> UIManager.focused = None。
    """

    ctype = 'input_field'

    def __init__(self, name='input', rect=(0, 0, 200, 32),
                 text='', placeholder='',
                 max_length=200,
                 bg_color=(50, 55, 70, 255),
                 focus_bg_color=(60, 70, 90, 255),
                 text_color=(255, 255, 255),
                 placeholder_color=(140, 140, 150),
                 cursor_color=(220, 220, 230),
                 font_size=16,
                 on_submit=None, on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.text = str(text)
        self.placeholder = str(placeholder)
        self.max_length = max(0, int(max_length))
        self.bg_color = tuple(bg_color)
        self.focus_bg_color = tuple(focus_bg_color)
        self.text_color = tuple(text_color)
        self.placeholder_color = tuple(placeholder_color)
        self.cursor_color = tuple(cursor_color)
        self.font_size = int(font_size)
        self.on_submit = on_submit
        self.on_change = on_change
        # 2026-10-18 阶段3: 光标位置 (字符索引, 0..len(text))
        # _focused 由 UIManager 设置 (不在此初始化, 避免与焦点系统竞态)
        self._cursor = len(self.text)
        self._focused = False

    # ---- 焦点回调 (UIManager 调) ----
    def on_focus(self):
        self._focused = True
        self._cursor = min(self._cursor, len(self.text))

    def on_blur(self):
        self._focused = False

    # ---- 文本编辑 ----
    def _set_text(self, new_text, notify=True):
        old = self.text
        if self.max_length > 0:
            new_text = new_text[:self.max_length]
        self.text = new_text
        self._cursor = max(0, min(self._cursor, len(self.text)))
        if notify and new_text != old:
            # 2026-10-19 P0-5: Python callable 与声明式绑定并存
            if self.on_change is not None:
                try:
                    self.on_change(new_text)
                except Exception:
                    pass
            _fire_binding(self, 'change', new_text)

    def _insert(self, s):
        """在光标处插入字符串 (支持多字符)"""
        if not s:
            return
        cur = self._cursor
        new = self.text[:cur] + s + self.text[cur:]
        self._set_text(new)
        self._cursor = min(cur + len(s), len(self.text))

    def _backspace(self):
        if self._cursor > 0:
            cur = self._cursor
            new = self.text[:cur - 1] + self.text[cur:]
            self._set_text(new)
            self._cursor = cur - 1

    def _delete(self):
        if self._cursor < len(self.text):
            cur = self._cursor
            new = self.text[:cur] + self.text[cur + 1:]
            self._set_text(new)
            # 光标不动

    def _submit(self):
        # 2026-10-19 P0-5: Python callable 与声明式绑定并存
        if self.on_submit is not None:
            try:
                self.on_submit(self.text)
            except Exception:
                pass
        _fire_binding(self, 'submit', self.text)

    # ---- 键盘事件 (UIManager 分发, 只在 focused=True 时) ----
    def on_key_down(self, key_name):
        """接收按键名 ('Backspace'/'Delete'/'Left'/'Right'/'Home'/'End'/'Return').

        返回 True = 消费按键; False = 未处理（UIManager 转给其他逻辑）。
        普通字符走 on_text_input, 不走这里。
        """
        if key_name == 'Backspace':
            self._backspace()
            return True
        if key_name == 'Delete':
            self._delete()
            return True
        if key_name == 'Left':
            if self._cursor > 0:
                self._cursor -= 1
            return True
        if key_name == 'Right':
            if self._cursor < len(self.text):
                self._cursor += 1
            return True
        if key_name == 'Home':
            self._cursor = 0
            return True
        if key_name == 'End':
            self._cursor = len(self.text)
            return True
        if key_name == 'Return':
            self._submit()
            return True
        if key_name == 'Escape':
            # ESC 在输入框内不消费，让上层处理（UIManager 会转给引擎）
            return False
        return False

    def on_text_input(self, text):
        """IME 提交的文本 (含中文/emoji/普通字母). 由 UIManager 分发."""
        if not text:
            return False
        self._insert(text)
        return True

    # ---- 鼠标交互 ----
    def on_mouse_down(self, pos):
        """返回 True = 请求焦点 (UIManager 处理后设置焦点 + 清空 pressed)."""
        if not self.enabled:
            return False
        # 简化: 点击任意位置把光标放到末尾（不做字符位置点击定位）
        self._cursor = len(self.text)
        return True

    def on_mouse_up(self, pos):
        return True    # 消费点击 (防止穿透到 3D)

    # ---- 绘制 ----
    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        bg = self.focus_bg_color if self._focused else self.bg_color
        engine.draw_screen_rect(screen_rect, bg)
        # 文字 (空时显示 placeholder)
        pad = 6
        ty = int(y + (h - self.font_size * 1.2) / 2)
        if self.text:
            engine.draw_text_quad(self.text, x + pad, ty,
                                  self.text_color, self.font_size)
        elif self.placeholder:
            engine.draw_text_quad(self.placeholder, x + pad, ty,
                                  self.placeholder_color, self.font_size)
        # 光标 (只在有焦点时画，绘制在 _cursor 字符位置的 x)
        if self._focused:
            # 光标前的文本宽度
            prefix = self.text[:self._cursor]
            prefix_w = engine._measure_text(prefix, self.font_size)[0] if prefix else 0
            cx = x + pad + prefix_w
            engine.draw_screen_rect((cx, y + 4, 2, h - 8), self.cursor_color)


class Dropdown(UIElement):
    """下拉菜单 (契约 §3.3). 点击展开 -> 列表显示在框下方; 选中项后收起.

    展开列表始终在 draw 时直接画出 (不依赖子元素树, 保证画在最上层).
    """

    ctype = 'dropdown'

    def __init__(self, name='dropdown', rect=(0, 0, 200, 32),
                 options=None, selected_index=0,
                 bg_color=(70, 80, 100, 255),
                 hover_color=(90, 100, 125, 255),
                 list_bg=(50, 55, 70, 255),
                 list_hover=(80, 140, 220, 255),
                 text_color=(255, 255, 255),
                 font_size=14,
                 item_height=28,
                 on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.options = list(options or [])
        self.selected_index = (max(0, min(len(self.options) - 1,
                                          int(selected_index)))
                               if self.options else -1)
        self.bg_color = tuple(bg_color)
        self.hover_color = tuple(hover_color)
        self.list_bg = tuple(list_bg)
        self.list_hover = tuple(list_hover)
        self.text_color = tuple(text_color)
        self.font_size = int(font_size)
        self.item_height = int(item_height)
        self.on_change = on_change
        self._expanded = False
        self._hover_item = -1

    def _list_rect(self, screen_rect):
        x, y, w, h = screen_rect
        return (x, y + h, w, self.item_height * len(self.options))

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False
        self._hover_item = -1

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        if self._expanded:
            # 展开态: 点击由 UIManager 转发给 handle_expanded_click
            return True
        self._expanded = True
        return True

    def on_mouse_up(self, pos):
        return self._expanded

    def handle_expanded_click(self, pos, screen_rect):
        """展开时 UIManager 调: 判断点击的是哪一项. 返回 True=消费."""
        lx, ly, lw, lh = self._list_rect(screen_rect)
        if lx <= pos[0] < lx + lw and ly <= pos[1] < ly + lh:
            idx = int((pos[1] - ly) // self.item_height)
            if 0 <= idx < len(self.options):
                self.selected_index = idx
                self._expanded = False
                if self.on_change is not None:
                    try:
                        self.on_change(self.options[idx])
                    except Exception:
                        pass
                return True
        # 点击列表外 -> 收起
        self._expanded = False
        return True

    @property
    def selected_value(self):
        if 0 <= self.selected_index < len(self.options):
            return self.options[self.selected_index]
        return ''

    def draw(self, engine, screen_rect):
        """画 box 本身 + 选中值. 展开列表由 _draw_expanded_list 单独绘制
        (UIManager.draw_all 第 2 轮调, 保证列表画在所有元素之上)."""
        x, y, w, h = screen_rect
        bg = self.hover_color if self._hover else self.bg_color
        engine.draw_screen_rect(screen_rect, bg)
        txt = self.selected_value
        if txt:
            lh = engine._measure_text('Mg', self.font_size)[1] or self.font_size
            ty = int(y + (h - lh) / 2)
            engine.draw_text_quad(txt, x + 8, ty, self.text_color, self.font_size)

    def _draw_expanded_list(self, engine, screen_rect):
        """展开列表绘制 (单独入口: UIManager.draw_all 在所有元素之后调)."""
        if not self._expanded or not self.options:
            return
        lx, ly, lw, lh = self._list_rect(screen_rect)
        engine.draw_screen_rect((lx, ly, lw, lh), self.list_bg)
        for i, opt in enumerate(self.options):
            iy = ly + i * self.item_height
            if i == self._hover_item:
                engine.draw_screen_rect((lx, iy, lw, self.item_height),
                                        self.list_hover)
            lh2 = engine._measure_text('Mg', self.font_size)[1] or self.font_size
            ty = int(iy + (self.item_height - lh2) / 2)
            engine.draw_text_quad(opt, lx + 8, ty, self.text_color, self.font_size)
