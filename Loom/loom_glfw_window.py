# -*- coding: utf-8 -*-
"""loom_glfw_window.py — GLEngine 的 GLFW 窗口子系统 (2026-10-18)

替代 loom_window.WindowMixin 的 pygame 窗口实现（决策 A2：彻底剥离 pygame 窗口）。

=== 为什么换 GLFW ===
  - 实测 pygame(SDL) 窗口会进程级污染系统输入法（见
    docs/audit/pygame窗口IME污染实测报告_20261018.md：候选框不弹 + 关窗后其他程序失灵）
  - 实测 GLFW 窗口不污染系统输入法（2026-10-18 用户手测确认）
  - Vulkan 后端 (vk_player.py) 已经是 GLFW，OpenGL 后端换 GLFW 后两条后端统一窗口技术栈，
    IME 支持代码只写一份（决策 C1）

=== A2 "彻底删 pygame 分支" 的精确边界 ===
本文件删除/替换的：pygame.display.set_mode / pygame.event.get / pygame.key.get_pressed
  / pygame.mouse.get_pressed / pygame.key.get_mods / pygame.display.flip / pygame.quit
  / pygame.TEXTINPUT / pygame.KEYDOWN / MOUSE* / MOUSEWHEEL / VIDEORESIZE 全部事件循环。
本文件**保留**的 pygame 用途（与窗口无关，删了会牵连其他子系统）：
  - pygame.K_* / pygame.KMOD_* 常量：纯 int，import 不触发 pygame.init()。
    loom_input._KEYMAP / editor.py / loom_render.py 全部引用这些常量做键码比较，
    替换成自定义枚举牵涉面过广（脚本层也认 pygame.K_w 这种）。
  - pygame.font / pygame.mixer：字体与音频后端（SDL_ttf / SDL_mixer），与窗口无关。

=== IME 支持（决策 B2：完整版）===
  - GLFW 3.4 char_callback   = pygame TEXTINPUT  （提交的最终文本）
  - GLFW 3.4 preedit_callback = pygame TEXTEDITING（预编辑串/拼音中间态）
  Python 包未暴露 preedit callback -> ctypes 从 glfw3.dll 手动绑定。
  预编辑串写入 self._ime_preedit 供 InputField 绘制（渲染留给 UI 层）。
  候选框定位由 Windows IME 自动锚定到窗口，无需像 SDL 那样 set_text_input_rect。

=== 与 WindowMixin 的接口约定 ===
完全同名的方法/属性，engine.py 切换 import 即可：
  _init_glfw_window(w, h)   # 新方法（替代 engine.py 里 pygame.display.set_mode 段）
  _on_resize / _desktop_resolution / _set_fullscreen / _toggle_fullscreen
  _place_fullscreen_window / _handle_events
  on_key_event / on_text_input / on_quit_request（三个子类可覆写钩子）
引擎侧需要维护的字段与 WindowMixin 完全一致：
  width / height / window / window_size / ctx / _external_ctx / fullscreen
  / allow_fullscreen / _window_rect / _desktop_size / _running / pressed / released
  / mouse_wheel / script_keys / mouse_pos / mouse_press_pos / buttons / _mods
  / _key / key_state / gui_dirty / mouse_rel
"""
import ctypes
import ctypes.util
import time

import glfw
import pygame   # 仅键码常量（K_* / KMOD_*）；import 不触发 pygame.init()


# ======================== GLFW 键码 -> pygame 常量 ========================
# 覆盖 loom_input._KEYMAP 全部键 + 引擎快捷键（F9/F10/F11/ESC/Z/Y/0）
_GLFW_TO_PG = {
    glfw.KEY_W: pygame.K_w, glfw.KEY_S: pygame.K_s,
    glfw.KEY_A: pygame.K_a, glfw.KEY_D: pygame.K_d,
    glfw.KEY_Q: pygame.K_q, glfw.KEY_E: pygame.K_e,
    glfw.KEY_I: pygame.K_i, glfw.KEY_K: pygame.K_k,
    glfw.KEY_J: pygame.K_j, glfw.KEY_L: pygame.K_l,
    glfw.KEY_U: pygame.K_u, glfw.KEY_O: pygame.K_o,
    glfw.KEY_LEFT: pygame.K_LEFT, glfw.KEY_RIGHT: pygame.K_RIGHT,
    glfw.KEY_UP: pygame.K_UP, glfw.KEY_DOWN: pygame.K_DOWN,
    glfw.KEY_SPACE: pygame.K_SPACE, glfw.KEY_TAB: pygame.K_TAB,
    glfw.KEY_LEFT_SHIFT: pygame.K_LSHIFT,
    glfw.KEY_RIGHT_SHIFT: pygame.K_RSHIFT,
    glfw.KEY_LEFT_CONTROL: pygame.K_LCTRL,
    glfw.KEY_RIGHT_CONTROL: pygame.K_RCTRL,
    glfw.KEY_LEFT_ALT: pygame.K_LALT,
    glfw.KEY_RIGHT_ALT: pygame.K_RALT,
    glfw.KEY_1: pygame.K_1, glfw.KEY_2: pygame.K_2,
    glfw.KEY_3: pygame.K_3, glfw.KEY_4: pygame.K_4,
    glfw.KEY_5: pygame.K_5, glfw.KEY_6: pygame.K_6,
    glfw.KEY_0: pygame.K_0,
    glfw.KEY_ESCAPE: pygame.K_ESCAPE,
    glfw.KEY_Z: pygame.K_z, glfw.KEY_Y: pygame.K_y,
    glfw.KEY_F9: pygame.K_F9, glfw.KEY_F10: pygame.K_F10,
    glfw.KEY_F11: pygame.K_F11,
}
# 反查表（script_keys 每个动作键都靠它查物理状态）
_PG_TO_GLFW = {pg: gl for gl, pg in _GLFW_TO_PG.items()}


def _glfw_to_pg(key):
    return _GLFW_TO_PG.get(key)


def _make_hwnd(win):
    """从 GLFW 窗口拿 Win32 HWND（全屏置顶等 Win32 调用要用）."""
    try:
        dll = ctypes.CDLL(ctypes.util.find_library('glfw3') or 'glfw3.dll')
        dll.glfwGetWin32Window.restype = ctypes.c_void_p
        dll.glfwGetWin32Window.argtypes = [ctypes.c_void_p]
        return dll.glfwGetWin32Window(win)
    except Exception:
        return None


# ======================== IME 说明（B1 决策） ========================
# GLFW 3.4 官方 API 没有 IME 预编辑串回调（实测 glfwSetPreeditCallback
# 在 glfw3.dll 中不存在，已用 _glfw_symbol_probe.py 验证）。
# 这是 GLFW 的已知设计取舍（维护者长期拒绝加入 IME 支持，把 IME 留给应用层）。
# 用户决策 B1（2026-10-18）：只做提交文本，不显示拼音中间态。
# 玩家打 "nihao" 时窗口内不显示拼音，按空格选词后 "你好" 一次性出现。
# 未来源码升级到 B2 时，可加轮询式 IMM32（ImmGetCompositionStringW）或
# WndProc 子类化截获 WM_IME_* 消息，不改 char_callback 路径。

class GlfwWindowMixin:
    """GLFW 窗口子系统（替代 WindowMixin）.

    使用方式（engine.py 在 ctx is None 分支调用）：
        self._init_glfw_window(width, height, title="...")
        # 之后 self.ctx = moderngl.create_context() 复用当前 GL 上下文
    """

    # ---------------- 初始化 ----------------
    def _init_glfw_window(self, width, height, title=None):
        """创建 GLFW 窗口 + 3.3 Core 上下文 + 注册全部回调。"""
        if not glfw.init():
            raise RuntimeError("GLFW 初始化失败")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)
        win = glfw.create_window(width, height,
                                 title or "Loom - OpenGL (GLFW) GPU 渲染",
                                 None, None)
        if not win:
            glfw.terminate()
            raise RuntimeError("GLFW create_window 失败")
        glfw.make_context_current(win)
        glfw.swap_interval(0)   # 关 vsync，与 Qt 编辑器行为一致（高帧率换潜在撕裂）

        self._glfw_win = win
        self.window = win                # 语义兼容（WindowMixin 的 self.window）
        self.window_size = (width, height)
        self.width = width
        self.height = height
        self.fullscreen = False
        self._window_rect = None
        self._desktop_size = self._desktop_resolution()
        self._running = True
        # 每帧瞬态（由回调写入，_handle_events 轮转）
        self._pending_pressed = set()
        self._pending_released = set()
        self._pending_wheel = 0
        self._pending_chars = []          # 本帧 char_callback 收到的文本（= TEXTINPUT）
        # B1 占位（无预编辑串）：未来 B2 升级时填真实拼音中间态
        self._ime_preedit = ''
        self._ime_active = False
        # 鼠标相对移动（GLFW 光标禁用模式下由窗口中心持续差出）
        self._prev_cursor = None

        # 光标 / 焦点
        glfw.set_window_user_pointer(win, self)

        # ---- 回调注册（全部用模块级函数 + user_pointer 反查实例）----
        glfw.set_key_callback(win, _on_key_cb)
        glfw.set_char_callback(win, _on_char_cb)
        glfw.set_cursor_pos_callback(win, _on_cursor_pos_cb)
        glfw.set_mouse_button_callback(win, _on_mouse_button_cb)
        glfw.set_scroll_callback(win, _on_scroll_cb)
        glfw.set_window_size_callback(win, _on_window_size_cb)
        glfw.set_window_close_callback(win, _on_window_close_cb)

        # B1: 无预编辑串回调（GLFW 3.4 无此 API）。中文靠 char_callback 一次提交。

    # ---------------- 尺寸/分辨率/全屏 ----------------
    def _on_resize(self, w, h):
        self.width = max(320, int(w))
        self.height = max(240, int(h))
        try:
            self.ctx.viewport = (0, 0, self.width, self.height)
        except Exception:
            pass
        ui = getattr(self, 'ui', None)
        if ui is not None:
            try:
                ui.resize(self.width, self.height)
            except Exception:
                pass

    def _desktop_resolution(self):
        if getattr(self, '_desktop_override', None):
            return self._desktop_override
        try:
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
        return getattr(self, '_desktop_size', (self.width, self.height))

    def _set_fullscreen(self, fullscreen):
        """假全屏：无边框 + 铺满桌面 + 置顶（不切显示器分辨率）."""
        self.fullscreen = bool(fullscreen)
        win = self._glfw_win
        if fullscreen:
            w, h = self._desktop_resolution()
            self.width = max(320, int(w))
            self.height = max(240, int(h))
            glfw.set_window_attrib(win, glfw.DECORATED, glfw.FALSE)
            glfw.set_window_size(win, self.width, self.height)
            glfw.set_window_pos(win, 0, 0)
            self._place_fullscreen_window()
        else:
            w, h = self.window_size
            self.width = max(320, int(w))
            self.height = max(240, int(h))
            glfw.set_window_attrib(win, glfw.DECORATED, glfw.TRUE)
            glfw.set_window_size(win, self.width, self.height)
            if self._window_rect:
                x, y = self._window_rect[0], self._window_rect[1]
                glfw.set_window_pos(win, x, y)
            self._place_fullscreen_window()
        try:
            self.ctx.viewport = (0, 0, self.width, self.height)
        except Exception:
            pass

    def _toggle_fullscreen(self):
        self._set_fullscreen(not self.fullscreen)

    def _place_fullscreen_window(self):
        """Win32 置顶/取消置顶（GLFW 无 set_always_on_top API）."""
        try:
            hwnd = _make_hwnd(self._glfw_win)
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0010, 0x0040
            if self.fullscreen:
                if self._window_rect is None:
                    from ctypes import wintypes
                    r = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                        self._window_rect = (r.left, r.top, r.right, r.bottom)
                user32.SetWindowPos(hwnd, -1, 0, 0, self.width, self.height,
                                    SWP_NOACTIVATE | SWP_SHOWWINDOW)
            else:
                x, y = (self._window_rect[0], self._window_rect[1]) if self._window_rect else (0, 0)
                user32.SetWindowPos(hwnd, -2, x, y, 0, 0,
                                    SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    # ---------------- 每帧事件轮转 ----------------
    def _handle_events(self):
        """GLFW: poll_events + 回调写入的 pending 状态转成引擎字段."""
        if self._external_ctx:
            return
        glfw.poll_events()

        # 瞬态清零（上一帧的 pressed/released/wheel 不跨帧）
        self.pressed.clear()
        self.released.clear()
        self.mouse_wheel = 0

        # 脚本按键快照（每帧轮询物理键盘状态，与 pygame.key.get_pressed 同语义）
        _kp = {}
        for name, pg_key in self._key_map_items():
            gl_key = _PG_TO_GLFW.get(pg_key)
            if gl_key is None:
                _kp[name] = False
                continue
            try:
                _kp[name] = (glfw.get_key(self._glfw_win, gl_key) == glfw.PRESS)
            except Exception:
                _kp[name] = False
        self.script_keys = _kp

        # pending -> 引擎字段
        if self._pending_pressed:
            self.pressed.update(self._pending_pressed)
            self._pending_pressed.clear()
        if self._pending_released:
            self.released.update(self._pending_released)
            self._pending_released.clear()
        if self._pending_wheel:
            self.mouse_wheel = self._pending_wheel
            self._pending_wheel = 0

        # char_callback 收到提交文本 -> on_text_input 钩子（兼容 pygame TEXTINPUT 语义）
        if self._pending_chars:
            for text in self._pending_chars:
                try:
                    from types import SimpleNamespace
                    self.on_text_input(
                        SimpleNamespace(type='TEXTINPUT', text=text))
                except Exception:
                    pass
            self._pending_chars.clear()

        # 鼠标三键状态
        try:
            self.buttons = (
                bool(glfw.get_mouse_button(self._glfw_win, glfw.MOUSE_BUTTON_LEFT)),
                bool(glfw.get_mouse_button(self._glfw_win, glfw.MOUSE_BUTTON_MIDDLE)),
                bool(glfw.get_mouse_button(self._glfw_win, glfw.MOUSE_BUTTON_RIGHT)),
            )
        except Exception:
            self.buttons = (0, 0, 0)

        # 修饰键
        mods = 0
        try:
            if (glfw.get_key(self._glfw_win, glfw.KEY_LEFT_SHIFT) == glfw.PRESS
                    or glfw.get_key(self._glfw_win, glfw.KEY_RIGHT_SHIFT) == glfw.PRESS):
                mods |= pygame.KMOD_SHIFT
            if (glfw.get_key(self._glfw_win, glfw.KEY_LEFT_CONTROL) == glfw.PRESS
                    or glfw.get_key(self._glfw_win, glfw.KEY_RIGHT_CONTROL) == glfw.PRESS):
                mods |= pygame.KMOD_CTRL
            if (glfw.get_key(self._glfw_win, glfw.KEY_LEFT_ALT) == glfw.PRESS
                    or glfw.get_key(self._glfw_win, glfw.KEY_RIGHT_ALT) == glfw.PRESS):
                mods |= pygame.KMOD_ALT
        except Exception:
            pass
        self._mods = mods

        # 鼠标相对位移（GLFW_CURSOR_DISABLED 下 cursor_pos 自动在窗口内循环）
        self._update_mouse_rel()

    def _key_map_items(self):
        try:
            from loom_input import _KEYMAP
            return _KEYMAP.items()
        except Exception:
            return ()

    def _update_mouse_rel(self):
        """光标禁用模式下（玩家运行时）用 cursor_pos 差值做相对移动；普通模式不更新."""
        try:
            mode = glfw.get_input_mode(self._glfw_win, glfw.CURSOR)
        except Exception:
            return
        if mode != glfw.CURSOR_DISABLED:
            self._prev_cursor = None
            return
        try:
            cx, cy = glfw.get_cursor_pos(self._glfw_win)
        except Exception:
            return
        if self._prev_cursor is None:
            self._prev_cursor = (cx, cy)
            self.mouse_rel = (0, 0)
            return
        dx = cx - self._prev_cursor[0]
        dy = cy - self._prev_cursor[1]
        self._prev_cursor = (cx, cy)
        # GLFW_CURSOR_DISABLED 模式会虚化坐标（光标每帧回中心），dx/dy 直接当相对位移
        self.mouse_rel = (int(dx), int(dy))

    # ---------------- 交换缓冲 / 关闭 ----------------
    def _glfw_swap_buffers(self):
        """渲染帧尾上屏（替代 pygame.display.flip）."""
        try:
            glfw.swap_buffers(self._glfw_win)
        except Exception:
            pass

    def _glfw_shutdown(self):
        """GLEngine.run 退出时调（替代 pygame.quit 的窗口部分）."""
        try:
            glfw.terminate()
        except Exception:
            pass

    # ---------------- 三个钩子（与 WindowMixin 同名） ----------------
    def on_key_event(self, ev):
        return False

    def on_text_input(self, ev):
        return False

    def on_quit_request(self):
        return True


# ======================== 回调（模块级，user_pointer 反查实例） ========================

def _get_engine(win):
    try:
        return glfw.get_window_user_pointer(win)
    except Exception:
        return None


def _on_key_cb(win, key, scancode, action, mods):
    e = _get_engine(win)
    if e is None:
        return
    if action not in (glfw.PRESS, glfw.RELEASE):
        return   # REPEAT 忽略（长按不重复触发）
    e.gui_dirty = True
    pg_key = _glfw_to_pg(key)
    if pg_key is None:
        return

    # F11 全屏（引擎层，先于 on_key_event 钩子）
    if action == glfw.PRESS and e.allow_fullscreen and pg_key == pygame.K_F11:
        e._toggle_fullscreen()
        return

    # F9 / F10 逻辑时钟（引擎层）
    if action == glfw.PRESS:
        if pg_key == pygame.K_F9:
            try:
                st = e.toggle_logic_paused()
                print("[逻辑时钟] %s" % ("已恢复" if st else "已暂停 (F10 步进)")
                      if st is not None else "")
            except Exception:
                pass
            return
        if pg_key == pygame.K_F10:
            try:
                if e.step_logic_once():
                    print("[逻辑时钟] 步进 1 逻辑帧")
            except Exception:
                pass
            return

    # on_key_event 钩子（编辑器输入框等可吞掉）
    try:
        ev = _make_key_event(e, pg_key, action)
        if e.on_key_event(ev):
            return
    except Exception:
        pass

    if action == glfw.PRESS:
        if pg_key == e._key.get('SELECT_NEXT_MODEL'):
            try:
                e.select_next_model()
            except Exception:
                pass
        elif pg_key in e.key_state:
            e.key_state[pg_key] = True
    elif action == glfw.RELEASE:
        if pg_key in e.key_state:
            e.key_state[pg_key] = False


def _make_key_event(e, pg_key, action):
    from types import SimpleNamespace
    return SimpleNamespace(
        type='KEYDOWN' if action == glfw.PRESS else 'KEYUP',
        key=pg_key,
        mod=getattr(e, '_mods', 0),
        unicode='',
    )


def _on_char_cb(win, codepoint):
    """GLFW char_callback = 提交的最终文本（等价 pygame TEXTINPUT）."""
    e = _get_engine(win)
    if e is None:
        return
    try:
        text = chr(codepoint)
    except Exception:
        return
    e.gui_dirty = True
    try:
        e._pending_chars.append(text)
    except Exception:
        pass


def _on_cursor_pos_cb(win, x, y):
    e = _get_engine(win)
    if e is None:
        return
    e.mouse_pos = (int(x), int(y))
    # 无按键时置脏（轨道/拖动期保持 GUI 帧）—— 对齐 pygame MOUSEMOTION 语义
    try:
        if not any(e.buttons):
            e.gui_dirty = True
    except Exception:
        pass


def _on_mouse_button_cb(win, button, action, mods):
    e = _get_engine(win)
    if e is None:
        return
    e.gui_dirty = True
    btn = {glfw.MOUSE_BUTTON_LEFT: 1,
           glfw.MOUSE_BUTTON_MIDDLE: 2,
           glfw.MOUSE_BUTTON_RIGHT: 3}.get(button)
    if btn is None:
        return
    try:
        x, y = glfw.get_cursor_pos(win)
    except Exception:
        x, y = 0, 0
    e.mouse_pos = (int(x), int(y))
    if action == glfw.PRESS:
        e._pending_pressed.add(btn)
        try:
            e.mouse_press_pos[btn] = e.mouse_pos
        except Exception:
            pass
    elif action == glfw.RELEASE:
        e._pending_released.add(btn)
        try:
            e.mouse_press_pos.pop(btn, None)
        except Exception:
            pass


def _on_scroll_cb(win, xoffset, yoffset):
    e = _get_engine(win)
    if e is None:
        return
    e.gui_dirty = True
    try:
        e._pending_wheel += int(yoffset)
    except Exception:
        pass


def _on_window_size_cb(win, w, h):
    e = _get_engine(win)
    if e is None:
        return
    e.window_size = (int(w), int(h))
    if not getattr(e, 'fullscreen', False):
        e._on_resize(w, h)
    e.gui_dirty = True


def _on_window_close_cb(win):
    e = _get_engine(win)
    if e is None:
        return
    try:
        if e.on_quit_request():
            e._running = False
    except Exception:
        e._running = False
