# -*- coding: utf-8 -*-
"""
gui.py — 即时模式 GUI (ImGui 风格, moderngl 手写, 零新依赖)

模型:
  - 每帧 begin_frame(鼠标状态) -> 构建控件 (window_begin/button/drag_float/text_field/...)
    -> end_frame() -> render()。
  - 控件按调用序注册矩形; 点击认领: 第一个按下的控件认领 (active_id + 吞掉 pressed),
    后面的重叠控件不再触发; 绘制序后面的 (上层) 控件优先生效。
  - 所有控件用显式 string id + 帧内计数器拼成唯一 id (ImGui 的 ## 约定), 持久状态
    (拖拽起点/输入框缓冲/焦点) 以唯一 id 为 key。
  - 绘制: 矩形走统一 rect 着色器 (每控件一次 unit-quad + uniform), 文字走
    engine.draw_text_quad (LRU 纹理缓存)。每控件记录当时的面板 scissor, render 时逐条应用。
"""
import moderngl

# 裁剪说明: moderngl 的 ctx.scissor 属性赋值即启用 GL_SCISSOR_TEST, 设 None 则关闭,
# 且状态会被 moderngl 的 scope 保存/恢复跟踪——不要用 ctypes 直接 glEnable/glDisable,
# 否则与 moderngl 内部状态脱节, scope 退出时会按旧状态把裁剪重新打开 (残影 bug)。

# ================ rect 着色器 (屏幕像素坐标, y 向下) ================
_RECT_VERT = """#version 330
in vec2 in_pos;      // 0..1 于矩形内
uniform vec2 u_origin;   // 像素左上角
uniform vec2 u_size;     // 像素宽高
uniform vec2 u_screen;   // 视口像素
out vec2 v_uv;
void main() {
    vec2 px = in_pos * u_size + u_origin;      // 像素坐标 (y 向下)
    vec2 ndc = vec2(px.x / u_screen.x * 2.0 - 1.0,
                    1.0 - px.y / u_screen.y * 2.0);  // y 向上翻转
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = in_pos;
}"""

_RECT_FRAG = """#version 330
in vec2 v_uv;
uniform vec4 u_color;
uniform vec2 u_size;
uniform float u_corner;    // 圆角半径 (0..0.5 于 min(u_size))
out vec4 frag_color;
void main() {
    // 简单圆角: 四个角距离
    vec2 c = vec2(u_corner * u_size.x, u_corner * u_size.y);
    if (u_corner > 0.0001) {
        vec2 d = min(v_uv * u_size, u_size - v_uv * u_size);
        vec2 d2 = d - c;
        float dist = length(max(d2, 0.0)) - min(c.x, c.y);
        if (dist > 0.0) discard;
    }
    frag_color = u_color;
}"""


def _in_rect(pos, rect):
    """pos=(x,y) 是否在 rect=(x,y,w,h) 内"""
    x, y = pos
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


class GUI:
    def __init__(self, engine):
        self.engine = engine
        self.ctx = engine.ctx
        self._rect_prog = self.ctx.program(vertex_shader=_RECT_VERT,
                                           fragment_shader=_RECT_FRAG)
        quad = __import__('numpy').array(
            [0, 0, 1, 0, 1, 1,  0, 0, 1, 1, 0, 1], dtype='f4')
        self._quad_vbo = self.ctx.buffer(quad.tobytes())
        self._quad_vao = self.ctx.vertex_array(self._rect_prog,
                                               [(self._quad_vbo, '2f', 'in_pos')])

        # 每帧瞬时状态
        self.mouse_pos = (0, 0)
        self.buttons = (0, 0, 0)
        self.pressed = set()
        self.released = set()
        self.press_pos = None          # 本帧按下点 (左键)
        self.wheel = 0
        self.click_captured = False    # 本帧 GUI 吞掉了点击 (面板/控件)
        self.active_id = None          # 当前活动控件 (拖拽/焦点)
        self.hot_id = None             # 悬停控件
        self._widget_rects = []        # [(uid, rect)]
        self._panel_rects = []         # [(rect)] 面板背景 (点空白也算吞点击)
        self._draw_cmds = []           # [(scissor, ('rect'|'text'), ...)]
        self._scissor = None           # 当前面板裁剪区 (None=不裁剪)
        self._scissor_stack = []

        # 持久状态 (以唯一 id 为 key)
        self._drag = {}                # id -> (start_value, start_x, start_y)
        self._input = {}               # id -> 输入缓冲
        self._focus = None             # 当前聚焦输入框 id
        self._num_focus = set()        # 数值输入模式控件 id (拖条单击进入, 只接受数字/./-)
        self._submit = {}              # 数值输入提交: id -> 解析后的 float (Enter 后下一帧取)
        self.notice = None             # 一次性提示消息 (数值输入非法等; editor 显示到状态栏)
        self._next_id = 0
        # 滚动条拖拽 (2026-08-14): uid -> (start_scroll, start_y/x)
        self._sb_drag = {}             # 垂直滚动条
        self._hsb_drag = {}            # 水平滚动条
        self.modal = None              # 模态面板 rect (None=无; 设置等覆盖面板打开时设,
                                       # 模态外点击不认领并吞掉, 防误操作底层面板/相机)

        # 样式
        self.s_col_bg = (0.13, 0.14, 0.17)
        self.s_col_panel = (0.17, 0.18, 0.22)
        self.s_col_btn = (0.24, 0.25, 0.30)
        self.s_col_btn_hot = (0.33, 0.35, 0.42)
        self.s_col_btn_active = (0.42, 0.45, 0.55)
        self.s_col_text = (0.88, 0.88, 0.90)
        self.s_col_border = (0.33, 0.34, 0.40)
        self.s_col_field = (0.09, 0.10, 0.12)
        self.s_col_accent = (0.42, 0.62, 0.95)
        self.s_font = 16

    # ================ 帧管理 ================
    def begin_frame(self, mouse_pos, buttons, pressed, released, wheel):
        self.mouse_pos = mouse_pos
        self.buttons = buttons
        self.pressed = set(pressed)
        self.released = set(released)
        self.press_pos = None
        if 1 in pressed:
            # 找 engine 记录的按下点
            self.press_pos = getattr(self.engine, 'mouse_press_pos', {}).get(1, mouse_pos)
        self.wheel = wheel
        self.click_captured = False
        self._widget_rects.clear()
        self._panel_rects.clear()
        self._draw_cmds.clear()
        self._scissor = None
        self._scissor_stack.clear()
        self._next_id = 0
        self.hot_id = None

    def end_frame(self):
        """帧构建结束: 面板空白点击也算 GUI 吞掉 (防误入视口点选)"""
        if self.press_pos is not None:
            if self.modal is not None and not _in_rect(self.press_pos, self.modal):
                self.click_captured = True   # 模态外按下: 吞掉, 防误操作相机/场景
            else:
                for rect in self._panel_rects:
                    if _in_rect(self.press_pos, rect):
                        self.click_captured = True
                        break
        # 治本防卡死: active_id/_focus 控件本帧若未渲染 (=已消失, 如挂脚本后按钮不再画),
        # 其释放事件永远无法被处理, 残留会让之后所有控件无法认领点击 -> 自动清掉.
        # (正常情况释放事件由控件自己处理; 这里只处理"控件消失"这种无法自清的情形)
        rendered = {uid for uid, _ in self._widget_rects}
        if self.active_id is not None and self.active_id not in rendered:
            self._drag.pop(self.active_id, None)
            self.active_id = None
        if self._focus is not None and self._focus not in rendered:
            self._input.pop(self._focus, None)
            self._focus = None
        # IME 开关跟随本帧聚焦结果 (2026-08-17): 命名框聚焦开启中文输入, 否则关闭
        self._sync_text_input()

    def reset_interaction(self):
        """清空跨帧交互状态. 系统模态对话框 (原生文件对话框等) 返回后调用,
        防止对话框吞掉鼠标释放事件导致 active_id/_focus 永久卡死."""
        self.active_id = None
        self._focus = None
        self._num_focus.clear()
        self._submit.clear()
        self._input.clear()
        self._drag.clear()
        self._sb_drag.clear()
        self._hsb_drag.clear()
        self.pressed.clear()
        self.released.clear()
        self._sync_text_input()   # 焦点清空 -> 关闭 IME (2026-08-17)

    def handle_key_event(self, ev):
        """键盘/文本事件路由 (EditorApp 在 on_key_event/on_text_input 里调用).
        聚焦输入框时处理. 返回 True = 已消费 (吞掉该键).
        数值输入模式 (拖条单击进入): 只接受数字/负号/小数点, Enter 提交解析值, Esc 取消."""
        import pygame
        if self._focus is None:
            return False
        if ev.type == pygame.TEXTINPUT:
            # IME 合成文本 (2026-08-17): 中文输入法提交的字符经 TEXTINPUT 送达.
            # 命名/文本框接收; 数值框不接收 (只收数字键, 其 IME 未开启).
            uid = self._focus
            if uid in self._num_focus:
                return True
            self._input[uid] = self._input.get(uid, '') + ev.text
            return True
        if ev.type != pygame.KEYDOWN:
            return True
        uid = self._focus
        buf = self._input.get(uid, '')
        num_mode = uid in self._num_focus
        if ev.key == pygame.K_RETURN or ev.key == pygame.K_KP_ENTER:
            if num_mode:
                import math
                try:
                    parsed = float(buf)
                    if not math.isfinite(parsed):
                        raise ValueError
                    self._submit[uid] = parsed
                except (ValueError, TypeError):
                    # 非法数值 (非数字/NaN/Inf/空) -> 提醒用户并改为 0 (2026-08-12)
                    self._submit[uid] = 0.0
                    self.notice = "无效数值「%s」，已设为 0" % (buf or "(空)")
                self._focus = None
                self._num_focus.discard(uid)
            else:
                self._focus = None
            return True
        elif ev.key == pygame.K_ESCAPE:
            self._input.pop(uid, None)     # 取消: 丢弃缓冲
            self._focus = None
            self._num_focus.discard(uid)
            return True
        elif ev.key == pygame.K_BACKSPACE:
            self._input[uid] = buf[:-1]
            return True
        elif ev.unicode and ev.unicode.isprintable():
            # 数值模式: IME 未开启, 字符走 KEYDOWN.unicode (数字/负号/小数点).
            # 命名(文本)模式: IME 已开启, 字符由 TEXTINPUT 送达, 这里忽略 unicode,
            # 避免与 TEXTINPUT 双写 (2026-08-17).
            if num_mode:
                if not buf:
                    self._input[uid] = ev.unicode   # 点开即输新值: 首个字符替换占位
                else:
                    self._input[uid] = buf + ev.unicode
            return True
        return True

    def _sync_text_input(self):
        """中文输入法 (IME) 开关 (2026-08-17): 仅当命名/文本框聚焦时开启合成.
        引擎启动时全局 stop_text_input 是为了避免 IME 吞掉字母/方向键的 KEYDOWN
        (游戏/快捷键依赖这些键); 但命名框需要输入中文, 故聚焦命名框时临时开启,
        失焦立即关闭. 数值框 (num_focus) 不开启 (只收数字键)."""
        import pygame
        try:
            if self._focus is not None and self._focus not in self._num_focus:
                # 把 IME 候选窗锚到聚焦输入框位置 (可选优化, 失败则用默认位置)
                for uid, r in self._widget_rects:
                    if uid == self._focus:
                        try:
                            pygame.key.set_text_input_rect(
                                pygame.Rect(int(r[0]), int(r[1]), int(r[2]), int(r[3])))
                        except Exception:
                            pass
                        break
                pygame.key.start_text_input()
            else:
                pygame.key.stop_text_input()
        except Exception:
            pass

    # ================ 控件 ================
    def _id(self, base):
        uid = "%s##%d" % (base, self._next_id)
        self._next_id += 1
        return uid

    def _register(self, uid, rect):
        """注册控件矩形 + 悬停/按下认领. 返回 (just_claimed).
        模态面板(self.modal)打开时: 模态外的点击不认领并吞掉(click_captured),
        防止底层面板控件在模态下误响应."""
        self._widget_rects.append((uid, rect))
        if self.modal is not None and not _in_rect(self.mouse_pos, self.modal):
            if 1 in self.pressed:
                self.click_captured = True
            return False
        if self.active_id is None and 1 in self.pressed and _in_rect(self.mouse_pos, rect):
            self.active_id = uid
            self.pressed.discard(1)
            self.click_captured = True
            return True
        return False

    def draw_rect(self, rect, color, corner=0.0):
        """记录一个填充矩形绘制命令 (render 时统一画)"""
        self._draw_cmds.append((self._scissor, 'rect', tuple(rect), color, corner))

    def draw_text(self, text, x, y, color=None, size=None):
        """记录一个文字绘制命令"""
        if color is None:
            color = self.s_col_text
        if size is None:
            size = self.s_font
        self._draw_cmds.append((self._scissor, 'text', text, x, y, color, size))

    def label(self, text, x, y, color=None, size=None):
        """纯文字 (无交互)"""
        self.draw_text(text, x, y, color, size)

    def window_begin(self, rect, title=None, bg=None, border=True):
        """面板开始: 画背景/标题, 推 scissor 裁剪区. 返回唯一面板 id (window_end 用)"""
        import numpy as np
        if bg is None:
            bg = self.s_col_panel
        self._panel_rects.append(tuple(rect))
        self.draw_rect(rect, bg)
        if border:
            x, y, w, h = rect
            b = self.s_col_border
            self.draw_rect((x, y, w, 1), b)
            self.draw_rect((x, y + h - 1, w, 1), b)
            self.draw_rect((x, y, 1, h), b)
            self.draw_rect((x + w - 1, y, 1, h), b)
        if title:
            self.draw_text(title, rect[0] + 6, rect[1] + 4,
                           self.s_col_text, self.s_font)
        # 推 scissor (面板内部, 留 2px 边框余量)
        self._scissor_stack.append(self._scissor)
        self._scissor = (rect[0] + 2, rect[1] + 2, max(rect[2] - 4, 1), max(rect[3] - 4, 1))
        return (rect[0] + 2, rect[1] + 2)   # 内容原点 (画内容时用它做基准)

    def window_end(self, panel_id=None):
        """面板结束: 恢复上一层 scissor"""
        if self._scissor_stack:
            self._scissor = self._scissor_stack.pop()

    def button(self, uid, rect, text=None, size=None):
        """按钮. 返回 True = 本帧被按下 (认领). 释放时清 active (避免卡住后续控件)."""
        claimed = self._register(uid, rect)
        if self.active_id == uid and 1 in self.released:
            self.active_id = None
        hot = (self.active_id is None and _in_rect(self.mouse_pos, rect))
        if self.active_id == uid:
            bg = self.s_col_btn_active
        elif hot:
            bg = self.s_col_btn_hot
            self.hot_id = uid
        else:
            bg = self.s_col_btn
        self.draw_rect(rect, bg, corner=0.12)
        if text:
            if size is None:
                size = self.s_font
            measure = getattr(self.engine, '_measure_text', None)   # M40: 回退感知宽度
            fw = measure(text, size)[0] if measure else self.engine._get_font(size).size(text)[0]
            fh = size
            self.draw_text(text, rect[0] + (rect[2] - fw) / 2,
                           rect[1] + (rect[3] - fh) / 2 - 2, self.s_col_text, size)
        return claimed

    def field_button(self, uid, rect, text, size=None):
        """可点击的"字段样式"文本 (左对齐, 深色底, 视觉同 text_field).
        返回 True = 本帧被点击 (认领). 用于命名等文本字段: 点击弹系统输入框 (tkinter),
        解决 IME 候选框被 SDL 窗口误判为游戏/全屏而隐藏的问题 (2026-08-17)."""
        claimed = self._register(uid, rect)
        if self.active_id == uid and 1 in self.released:
            self.active_id = None
        hot = (self.active_id is None and _in_rect(self.mouse_pos, rect))
        if self.active_id == uid:
            bg = self.s_col_accent
        elif hot:
            bg = self.s_col_btn_hot
            self.hot_id = uid
        else:
            bg = self.s_col_field
        self.draw_rect(rect, bg, corner=0.12)
        if size is None:
            size = self.s_font
        self.draw_text(text, rect[0] + 5, rect[1] + (rect[3] - size) / 2 - 2,
                       self.s_col_text, size)
        return claimed

    def drag_float(self, uid, rect, value, speed=0.01, fmt='%.2f'):
        """拖拽数值: 左键水平拖动改变值; **右键按下进入数值输入模式**,
        可直接键入数字, Enter 提交 / Esc 取消 / 点外部提交.
        返回 (新值, 是否正在拖拽). active 在拖拽/输入期间为 True (撤销记快照起点)."""
        # —— 数值输入提交 (Enter 后的下一帧: 此时 _focus 已清, 独立于 _focus 判断) ——
        if uid in self._submit:
            self._widget_rects.append((uid, rect))   # 注册矩形 (防 end_frame 误清)
            value = self._submit.pop(uid)
            self._num_focus.discard(uid)
            self._input.pop(uid, None)
            if self._focus == uid:
                self._focus = None
            bg = self.s_col_field
            self.draw_rect(rect, bg, corner=0.12)
            self.draw_text(fmt % value, rect[0] + 5,
                           rect[1] + (rect[3] - self.s_font) / 2 - 2,
                           self.s_col_text, self.s_font)
            return value, False
        # —— 数值输入模式 (右键进入): 注册矩形防 end_frame 误清 _focus ——
        if self._focus == uid:
            self._widget_rects.append((uid, rect))
            if 1 in self.pressed and not _in_rect(self.mouse_pos, rect):
                # 点输入框外部: 提交当前缓冲退出 (空缓冲 = 取消, 保持原值)
                try:
                    value = float(self._input.get(uid, ''))
                except (ValueError, TypeError):
                    pass
                self._focus = None
                self._num_focus.discard(uid)
                self._input.pop(uid, None)
                text = fmt % value
                active = False
            else:
                text = self._input.get(uid, '') or (fmt % value)   # 空缓冲显示占位
                active = True
            bg = self.s_col_accent if active else self.s_col_field
            self.draw_rect(rect, bg, corner=0.12)
            self.draw_text(text, rect[0] + 5, rect[1] + (rect[3] - self.s_font) / 2 - 2,
                           self.s_col_text, self.s_font)
            return value, active
        # —— 右键按下 -> 进入数值输入模式 (2026-08-12: 单击改右键, 不依赖移动阈值更可靠) ——
        if 3 in self.pressed and _in_rect(self.mouse_pos, rect):
            self._widget_rects.append((uid, rect))   # 注册矩形 (防 end_frame 误清)
            self._focus = uid
            self._num_focus.add(uid)
            self._input[uid] = ''
            self.pressed.discard(3)      # 吞右键 (防其它逻辑误用)
            bg = self.s_col_accent
            self.draw_rect(rect, bg, corner=0.12)
            self.draw_text(fmt % value, rect[0] + 5,
                           rect[1] + (rect[3] - self.s_font) / 2 - 2,
                           self.s_col_text, self.s_font)
            return value, True           # active=True: 调用方记撤销起点
        # —— 常规拖动 ——
        claimed = self._register(uid, rect)
        if claimed:
            self._drag[uid] = (value, self.mouse_pos[0], self.mouse_pos[1])
        active = (self.active_id == uid)
        if active and uid in self._drag:
            sv, sx, _sy = self._drag[uid]
            value = sv + (self.mouse_pos[0] - sx) * speed
        if active and 1 in self.released:
            self.active_id = None
            self._drag.pop(uid, None)
            active = False
        hot = (self.active_id is None and _in_rect(self.mouse_pos, rect))
        if self.active_id == uid:
            bg = self.s_col_accent
        elif hot:
            bg = self.s_col_btn_hot
            self.hot_id = uid
        else:
            bg = self.s_col_field
        self.draw_rect(rect, bg, corner=0.12)
        self.draw_text(fmt % value, rect[0] + 5, rect[1] + (rect[3] - self.s_font) / 2 - 2,
                       self.s_col_text, self.s_font)
        return value, active

    def text_field(self, uid, rect, value, size=None):
        """文本输入框 (聚焦后吃键盘, Enter 提交 / Esc 取消). 返回当前显示的文本."""
        claimed = self._register(uid, rect)
        if claimed:
            self._focus = uid
            self._input.setdefault(uid, value)
            self.click_captured = True
        # 释放时清 active_id (否则 active_id 卡死, 之后所有控件都无法认领点击)
        if self.active_id == uid and 1 in self.released:
            self.active_id = None
        buf = self._input.get(uid, value)
        if self._focus == uid and 1 in self.released and not _in_rect(self.mouse_pos, rect):
            # 点击外部: 提交 (Enter 同)
            self._input.pop(uid, None)
            self._focus = None
        focused = (self._focus == uid)
        hot = (not focused and self.active_id is None and _in_rect(self.mouse_pos, rect))
        if focused:
            bg = self.s_col_accent
        elif hot:
            bg = self.s_col_btn_hot
            self.hot_id = uid
        else:
            bg = self.s_col_field
        self.draw_rect(rect, bg, corner=0.12)
        if size is None:
            size = self.s_font
        self.draw_text(buf + ('|' if focused else ''), rect[0] + 5,
                       rect[1] + (rect[3] - size) / 2 - 2, self.s_col_text, size)
        return buf

    # ================ 滚动条 (2026-08-14: 面板内容超高/超宽时开放拉条) ================
    def push_scissor(self, rect):
        """推入一个子裁剪区 (面板内部再裁剪, 工具栏滚动内容区用). 与 pop_scissor 配对."""
        self._scissor_stack.append(self._scissor)
        self._scissor = tuple(rect)

    def pop_scissor(self):
        """恢复上一个裁剪区 (与 push_scissor 配对)."""
        if self._scissor_stack:
            self._scissor = self._scissor_stack.pop()

    def scrollbar_v(self, uid, panel_rect, content_h, scroll, bar_w=10):
        """垂直滚动条: 面板内容超高时出现, 滚轮 / 拖拇指上下滚动.
        panel_rect = 面板可视区, content_h = 内容总高. 返回新 scroll."""
        px, py, pw, ph = panel_rect
        max_scroll = max(0.0, content_h - (ph - 4))
        scroll = max(0.0, min(max_scroll, scroll))
        if self.wheel and _in_rect(self.mouse_pos, panel_rect):
            scroll = max(0.0, min(max_scroll, scroll - self.wheel * 42))
        if max_scroll <= 0:
            return 0.0
        track = (px + pw - bar_w - 2, py + 3, bar_w, ph - 6)
        thumb_h = max(24.0, (ph - 6) * ((ph - 4) / max(1.0, content_h)))
        avail = max(1.0, (ph - 6) - thumb_h)
        thumb_y = py + 3 + (scroll / max_scroll) * avail
        thumb = (track[0], thumb_y, bar_w, thumb_h)
        cid = "sb." + uid
        claimed = self._register(cid, track)
        if claimed:
            self._sb_drag[uid] = (scroll, self.mouse_pos[1])
        if self.active_id == cid and uid in self._sb_drag:
            sv, sy = self._sb_drag[uid]
            scroll = max(0.0, min(max_scroll, sv + (self.mouse_pos[1] - sy) * (max_scroll / avail)))
        if self.active_id == cid and 1 in self.released:
            self.active_id = None
            self._sb_drag.pop(uid, None)
        self.draw_rect(track, self.s_col_btn, corner=0.5)
        self.draw_rect(thumb, self.s_col_btn_active, corner=0.5)
        return scroll

    def scrollbar_h(self, uid, panel_rect, content_w, scroll, bar_h=3):
        """水平滚动条: 面板内容超宽时出现, 滚轮 / 拖拇指左右滚动.
        panel_rect = 面板可视区, content_w = 内容总宽. 返回新 scroll."""
        px, py, pw, ph = panel_rect
        max_scroll = max(0.0, content_w - (pw - 4))
        scroll = max(0.0, min(max_scroll, scroll))
        if self.wheel and _in_rect(self.mouse_pos, panel_rect):
            scroll = max(0.0, min(max_scroll, scroll - self.wheel * 48))
        if max_scroll <= 0:
            return 0.0
        track = (px + 3, py + ph - bar_h - 1, pw - 6, bar_h)
        thumb_w = max(24.0, (pw - 6) * ((pw - 4) / max(1.0, content_w)))
        avail = max(1.0, (pw - 6) - thumb_w)
        thumb_x = px + 3 + (scroll / max_scroll) * avail
        thumb = (thumb_x, track[1], thumb_w, bar_h)
        cid = "hsb." + uid
        claimed = self._register(cid, track)
        if claimed:
            self._hsb_drag[uid] = (scroll, self.mouse_pos[0])
        if self.active_id == cid and uid in self._hsb_drag:
            sv, sx = self._hsb_drag[uid]
            scroll = max(0.0, min(max_scroll, sv + (self.mouse_pos[0] - sx) * (max_scroll / avail)))
        if self.active_id == cid and 1 in self.released:
            self.active_id = None
            self._hsb_drag.pop(uid, None)
        self.draw_rect(track, self.s_col_btn, corner=0.5)
        self.draw_rect(thumb, self.s_col_btn_active, corner=0.5)
        return scroll

    # ================ 渲染 ================
    def render(self, target=None):
        """统一绘制所有矩形/文字 (每命令应用其创建时的 scissor). target 可指定离屏 FBO."""
        w, h = self.engine.width, self.engine.height
        with self.ctx.scope(framebuffer=target, enable_only=moderngl.BLEND):
            for cmd in self._draw_cmds:
                scissor = cmd[0]
                if scissor is not None:
                    sx, sy, sw, sh = scissor
                    # GL scissor 原点在左下: y_gl = height - (y+h)
                    # moderngl 的 ctx.scissor 赋值即启用裁剪; 设 None 则关闭
                    self.ctx.scissor = (int(sx), int(h - (sy + sh)), int(sw), int(sh))
                else:
                    self.ctx.scissor = None
                if cmd[1] == 'rect':
                    _, _, (rx, ry, rw, rh), color, corner = cmd
                    if rw <= 0 or rh <= 0:
                        continue
                    self._rect_prog['u_origin'].value = (rx, ry)
                    self._rect_prog['u_size'].value = (rw, rh)
                    self._rect_prog['u_screen'].value = (w, h)
                    self._rect_prog['u_color'].value = tuple(color) + (1.0,)
                    self._rect_prog['u_corner'].value = corner
                    self._quad_vao.render(moderngl.TRIANGLES)
                else:  # 'text'
                    _, _, text, tx, ty, color, size = cmd
                    self.engine.draw_text_quad(text, tx, ty, tuple(int(c * 255) for c in color),
                                               size=size)
            # 收尾务必关掉裁剪 (moderngl scope 退出按自身跟踪状态恢复,
            # 若不置 None 会把 GL_SCISSOR_TEST 泄漏到下一帧的 clear/场景, 造成残影)
            self.ctx.scissor = None
