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

from loom_gl_version import GL_MIN_MAJOR, GL_MIN_MINOR   # 2026-11-09 A0: GL 地板 4.3 core


# ======================== GLFW 键码 -> pygame 常量 ========================
# 覆盖 loom_input._KEYMAP 全部键 + 引擎快捷键（F9/F10/F11/ESC/Z/Y/0）
_GLFW_TO_PG = {
    # 2026-11-07: 与 loom_input._KEYMAP 全量对齐 (字母/数字/F1-F12/编辑键/标点)
    glfw.KEY_A: pygame.K_a, glfw.KEY_B: pygame.K_b, glfw.KEY_C: pygame.K_c,
    glfw.KEY_D: pygame.K_d, glfw.KEY_E: pygame.K_e, glfw.KEY_F: pygame.K_f,
    glfw.KEY_G: pygame.K_g, glfw.KEY_H: pygame.K_h, glfw.KEY_I: pygame.K_i,
    glfw.KEY_J: pygame.K_j, glfw.KEY_K: pygame.K_k, glfw.KEY_L: pygame.K_l,
    glfw.KEY_M: pygame.K_m, glfw.KEY_N: pygame.K_n, glfw.KEY_O: pygame.K_o,
    glfw.KEY_P: pygame.K_p, glfw.KEY_Q: pygame.K_q, glfw.KEY_R: pygame.K_r,
    glfw.KEY_S: pygame.K_s, glfw.KEY_T: pygame.K_t, glfw.KEY_U: pygame.K_u,
    glfw.KEY_V: pygame.K_v, glfw.KEY_W: pygame.K_w, glfw.KEY_X: pygame.K_x,
    glfw.KEY_Y: pygame.K_y, glfw.KEY_Z: pygame.K_z, glfw.KEY_0: pygame.K_0,
    glfw.KEY_1: pygame.K_1, glfw.KEY_2: pygame.K_2, glfw.KEY_3: pygame.K_3,
    glfw.KEY_4: pygame.K_4, glfw.KEY_5: pygame.K_5, glfw.KEY_6: pygame.K_6,
    glfw.KEY_7: pygame.K_7, glfw.KEY_8: pygame.K_8, glfw.KEY_9: pygame.K_9,
    glfw.KEY_ESCAPE: pygame.K_ESCAPE, glfw.KEY_ENTER: pygame.K_RETURN, glfw.KEY_BACKSPACE: pygame.K_BACKSPACE,
    glfw.KEY_DELETE: pygame.K_DELETE, glfw.KEY_INSERT: pygame.K_INSERT, glfw.KEY_HOME: pygame.K_HOME,
    glfw.KEY_END: pygame.K_END, glfw.KEY_PAGE_UP: pygame.K_PAGEUP, glfw.KEY_PAGE_DOWN: pygame.K_PAGEDOWN,
    glfw.KEY_SPACE: pygame.K_SPACE, glfw.KEY_TAB: pygame.K_TAB, glfw.KEY_LEFT: pygame.K_LEFT,
    glfw.KEY_RIGHT: pygame.K_RIGHT, glfw.KEY_UP: pygame.K_UP, glfw.KEY_DOWN: pygame.K_DOWN,
    glfw.KEY_LEFT_SHIFT: pygame.K_LSHIFT, glfw.KEY_RIGHT_SHIFT: pygame.K_RSHIFT, glfw.KEY_LEFT_CONTROL: pygame.K_LCTRL,
    glfw.KEY_RIGHT_CONTROL: pygame.K_RCTRL, glfw.KEY_LEFT_ALT: pygame.K_LALT, glfw.KEY_RIGHT_ALT: pygame.K_RALT,
    glfw.KEY_MINUS: pygame.K_MINUS, glfw.KEY_EQUAL: pygame.K_EQUALS, glfw.KEY_LEFT_BRACKET: pygame.K_LEFTBRACKET,
    glfw.KEY_RIGHT_BRACKET: pygame.K_RIGHTBRACKET, glfw.KEY_BACKSLASH: pygame.K_BACKSLASH, glfw.KEY_SEMICOLON: pygame.K_SEMICOLON,
    glfw.KEY_APOSTROPHE: pygame.K_QUOTE, glfw.KEY_COMMA: pygame.K_COMMA, glfw.KEY_PERIOD: pygame.K_PERIOD,
    glfw.KEY_SLASH: pygame.K_SLASH, glfw.KEY_GRAVE_ACCENT: pygame.K_BACKQUOTE, glfw.KEY_F1: pygame.K_F1,
    glfw.KEY_F2: pygame.K_F2, glfw.KEY_F3: pygame.K_F3, glfw.KEY_F4: pygame.K_F4,
    glfw.KEY_F5: pygame.K_F5, glfw.KEY_F6: pygame.K_F6, glfw.KEY_F7: pygame.K_F7,
    glfw.KEY_F8: pygame.K_F8, glfw.KEY_F9: pygame.K_F9, glfw.KEY_F10: pygame.K_F10,
    glfw.KEY_F11: pygame.K_F11, glfw.KEY_F12: pygame.K_F12,
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


# ======================== Win32（私有 user32 + 显式 argtypes） ========================
# 与 VK 侧同值（不要改）：Win32 置顶常量与 SetWindowPos 标志
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040


def _user32():
    """**私有** user32 句柄（显式 argtypes）。

    2026-11-18 (Q-B7-36-2) 根因：本模块原先直接用 ctypes.windll.user32 调
    SetWindowPos 且**没有声明 argtypes**。第二个参数是 HWND（x64 上 8 字节指针），
    不声明 argtypes 时 ctypes 把 Python int 按 32 位传 -> HWND_TOPMOST(-1) 被截断
    -> SetWindowPos 返回 0（失败）-> WS_EX_TOPMOST 从未置位（"置顶"静默失效）。

    为什么 new 一个 WinDLL 而不是用 ctypes.windll.user32：后者是**全进程共享**的
    函数对象，给它设 argtypes 等于暗中改别人的行为；这里只影响本模块自己的函数指针。
    """
    try:
        from ctypes import wintypes
        u = ctypes.WinDLL('user32', use_last_error=True)
        sp = u.SetWindowPos
        sp.restype = wintypes.BOOL
        sp.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        gr = u.GetWindowRect
        gr.restype = wintypes.BOOL
        gr.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        return u
    except Exception:
        return None


def _window_rect_now(hwnd):
    """当前窗口矩形 (left, top, right, bottom)；取不到返回 None。

    坐标空间注意：这是 Win32 的**窗口矩形**（含边框），而 glfw.set_window_pos 的参数是
    **client 区**原点。本机实测：set_window_pos(73,102) -> client 原点 (73,102)、
    GetWindowRect=(64,64,...)，边框偏移 (9,38)。所以「记录用 GetWindowRect、还原用
    Win32 SetWindowPos 的原始窗口坐标」是自洽的一对（见 _place_fullscreen_window）。
    """
    u = _user32()
    if u is None or not hwnd:
        return None
    try:
        from ctypes import wintypes
        r = wintypes.RECT()
        if u.GetWindowRect(hwnd, ctypes.byref(r)):
            return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        pass
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
        """创建 GLFW 窗口 + **4.3 Core** 上下文 + 注册全部回调。

        2026-11-09 批次 A0（人类裁决 D1=B）：GL 地板 3.3 -> 4.3 core。
        理由：3.3 只够亮机卡；4.3 是「DX11 同级」的现代硬件前提（SSBO/compute/显式
        layout 也都在这一档可用）。现有着色器源码仍是 #version 330 —— 4.3 core 驱动
        能编 330，只有新增能力才写 430（见 loom_gl_version 模块头）。
        版本硬门在 engine 里 create_context() 之后立即执行（失败 -> 明确报错，不黑屏）。
        """
        if not glfw.init():
            raise RuntimeError("GLFW 初始化失败")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, GL_MIN_MAJOR)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, GL_MIN_MINOR)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)
        win = glfw.create_window(width, height,
                                 title or "Loom - OpenGL (GLFW) GPU 渲染",
                                 None, None)
        if not win:
            glfw.terminate()
            # 2026-11-09 A0: 建窗失败最常见原因 = 显卡/驱动给不了 4.3 core。
            # 必须把原因打出来（不能只抛一句「失败」让用户看到黑屏/闪退）。
            print("[GL] GLFW create_window 失败：可能是显卡或驱动不支持 OpenGL %d.%d core。"
                  % (GL_MIN_MAJOR, GL_MIN_MINOR))
            print("[GL] 提示: 先更新显卡驱动；若显卡确实不支持，改用 Vulkan 后端 "
                  "—— 启动参数 --backend vulkan（或设置 render_api=vulkan）。")
            raise RuntimeError(
                "GLFW create_window 失败 (需要 OpenGL %d.%d core)"
                % (GL_MIN_MAJOR, GL_MIN_MINOR))
        glfw.make_context_current(win)
        glfw.swap_interval(0)   # 关 vsync，与 Qt 编辑器行为一致（高帧率换潜在撕裂）

        self._glfw_win = win
        self.window = win                # 语义兼容（WindowMixin 的 self.window）
        self.window_size = (width, height)
        self.width = width
        self.height = height
        self.fullscreen = False
        self._window_rect = None            # 进入全屏前的窗口矩形 (l,t,r,b)
        self._window_client = None          # 进入全屏前的 client 尺寸 (w,h)
        self._fullscreen_warned = set()     # 全屏失败/降级已打印过（同一原因只打一次）
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
        # 2026-10-19 第1档序7：窗口最小化/恢复 -> on_became_invisible/visible
        try:
            glfw.set_window_iconify_callback(win, _on_window_iconify_cb)
        except (AttributeError, Exception):
            pass   # 老版 glfw-python 无此 API，静默降级

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
        """假全屏：无边框 + 铺满桌面 + 置顶（不切显示器分辨率）.

        P-07 修复 (2026-11-06): 外部 GL 上下文模式 (Qt 宿主 QOpenGLWidget /
        PlayerApp(ctx=...) 远程白屏修复路径) 没有 GLFW 窗口 —— _glfw_win
        只在 _init_glfw_window 里创建。旧实现直接 win = self._glfw_win，
        此时抛 AttributeError，F11 一按即崩 (玩家发布路径默认就是这个模式)。
        契约 (engine.py:265 "外部模式: 无 pygame 窗口 (Qt 宿主管窗口)") 决定了
        全屏必须由宿主窗口负责，引擎只维护自身状态位与视口，不做窗口操作。

        === 2026-11-18 修复 Q-B7-36-1：退出全屏必须**真还原** ===
        旧顺序（错）：先 set_window_size(桌面) + set_window_pos(0,0)，再在
        _place_fullscreen_window 里 GetWindowRect 记录 _window_rect —— 记到的是
        **全屏后**的矩形；而 window_size 这时已被 _on_window_size_cb 刷成全屏尺寸。
        于是退出时按全屏矩形"还原" -> 实测 1920x1055 @ (0,0)（原 640x400 @ (73,102)，
        用户报的现场）。
        新顺序（与 VK 侧 loom_vk_window.VkWindowMixin._set_fullscreen 逐项一致）：
          进全屏 ① 取桌面分辨率
                 ② **先**记录原窗口矩形 GetWindowRect + 原 client 尺寸
                 ③ DECORATED=FALSE -> set_window_size(桌面) -> set_window_pos(0,0)
                 ④ Win32 SetWindowPos(HWND_TOPMOST) 置顶
          退全屏 ① DECORATED=TRUE -> set_window_size(原 client) -> set_window_pos(原矩形)
                 ② Win32 SetWindowPos(HWND_NOTOPMOST, 原窗口坐标) 取消置顶并落回原位
                 ③ 清空记录（下次进全屏重新记录）
        两端语义必须一致（人类目标：后端可换、用户可观察结果不变）。
        """
        want = bool(fullscreen)
        win = getattr(self, '_glfw_win', None)
        if win is None:
            # 宿主管窗口: 只同步状态 + 视口, 不碰操作系统窗口
            self.fullscreen = want
            try:
                if want:
                    w, h = self._desktop_resolution()
                    self.width = max(320, int(w))
                    self.height = max(240, int(h))
                else:
                    _w, _h = self.window_size
                    self.width = max(320, int(_w))
                    self.height = max(240, int(_h))
                self.ctx.viewport = (0, 0, self.width, self.height)
            except Exception:
                pass
            return
        if want:
            w, h = self._desktop_resolution()
            dw, dh = max(320, int(w)), max(240, int(h))
            # ② **进入全屏之前**记录真实几何（Q-B7-36-1：这一步必须最早）
            if getattr(self, '_window_rect', None) is None:
                _client = self._client_size_now(win)      # 兼作句柄验活（假窗口直接跳过）
                self._window_client = _client
                if _client is not None:
                    self._window_rect = _window_rect_now(_make_hwnd(win))
                    if self._window_rect is None:
                        self._fullscreen_warn(
                            '拿不到原窗口矩形（GetWindowRect/glfwGetWin32Window 失败）'
                            ' -> 退出全屏时无法还原窗口位置')
            self.fullscreen = True
            glfw.set_window_attrib(win, glfw.DECORATED, glfw.FALSE)   # ③ 去边框
            glfw.set_window_size(win, dw, dh)                         #    铺满桌面
            glfw.set_window_pos(win, 0, 0)                            #    左上角
            self.width, self.height = dw, dh      # 窗口调用后再落字段（回调可能改写）
            self._place_fullscreen_window()                           # ④ 置顶
        else:
            # ---- 退全屏：边框 / client 尺寸 / 位置 / 非置顶 全部还原 ----
            rect = getattr(self, '_window_rect', None)
            cw, ch = getattr(self, '_window_client', None) or self.window_size
            cw, ch = max(320, int(cw)), max(240, int(ch))
            self.fullscreen = False
            glfw.set_window_attrib(win, glfw.DECORATED, glfw.TRUE)    # ① 还边框
            # 注意：还边框那一下 Windows 会同步发 WM_SIZE -> _on_window_size_cb ->
            # _on_resize 改写 self.width/height（实测被改成 1920x1055）。所以这里
            # **只用局部量**（进入前记录的 client 尺寸），绝不读 self.width/height。
            glfw.set_window_size(win, cw, ch)                         #    还原 client 尺寸
            if rect:
                glfw.set_window_pos(win, int(rect[0]), int(rect[1]))  #    还原位置
            self.width, self.height = cw, ch
            self._place_fullscreen_window()                           # ② 取消置顶 + 落回原位
            self._window_rect = None
            self._window_client = None
            # 还边框/改尺寸会触发 _on_window_size_cb，可能把 width/height 刷成过渡值；
            # 以真实 client 尺寸收口（两端 width/height 必须同值）。
            _real = self._client_size_now(win)
            if _real:
                self.width, self.height = _real
            self.window_size = (self.width, self.height)
        try:
            self.ctx.viewport = (0, 0, self.width, self.height)
        except Exception:
            pass

    def _client_size_now(self, win):
        """当前 client 尺寸 (w,h)（失败返回 None -> 调用方走 window_size 兜底）."""
        try:
            w, h = glfw.get_window_size(win)
            return (max(320, int(w)), max(240, int(h)))
        except Exception:
            return None

    def _fullscreen_warn(self, msg):
        """全屏失败/降级：**必须可见**（同一原因只打印一次，不刷屏、不静默）.

        旧实现整段包在 try/except Exception: pass 里 —— 置顶在 x64 上静默失败了
        没人知道（Q-B7-36-2）。这里把失败变成一行明确日志。
        """
        key = str(msg)
        seen = getattr(self, '_fullscreen_warned', None)
        if not isinstance(seen, set):
            seen = self._fullscreen_warned = set()
        if key in seen:
            return
        seen.add(key)
        print('[全屏] %s' % (key,))

    def _toggle_fullscreen(self):
        self._set_fullscreen(not self.fullscreen)

    def _place_fullscreen_window(self):
        """Win32 置顶 / 取消置顶（GLFW 没有 set_always_on_top API）.

        2026-11-18 修复 Q-B7-36-2：
          · 旧代码用 ctypes.windll.user32 且**没有 argtypes** -> x64 上第二参数
            HWND_TOPMOST(-1) 被按 32 位截断 -> SetWindowPos 返回 0（失败），
            WS_EX_TOPMOST 从未置位；外层 except: pass 让失败完全不可见。
          · 现在：私有 user32 + 显式 argtypes + c_void_p(-1)/(-2)（= 句柄宽度），
            失败**打一行**日志（同一原因只打一次）。
        取消置顶时用记录的**窗口矩形**坐标（Win32 窗口坐标，不是 glfw 的 client 坐标）
        —— 与 VK 侧同一对调用，保证两端退出后落到同一个像素。
        """
        u = _user32()
        if u is None:
            self._fullscreen_warn('拿不到私有 user32 句柄 -> 置顶/取消置顶不可用')
            return
        hwnd = _make_hwnd(self._glfw_win)
        if not hwnd:
            self._fullscreen_warn('拿不到 Win32 HWND（glfwGetWin32Window 失败）'
                                  ' -> 置顶/取消置顶不可用')
            return
        try:
            if self.fullscreen:
                ok = u.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_TOPMOST), 0, 0,
                                    int(self.width), int(self.height),
                                    _SWP_NOACTIVATE | _SWP_SHOWWINDOW)
            else:
                rect = getattr(self, '_window_rect', None)
                x, y = (int(rect[0]), int(rect[1])) if rect else (0, 0)
                ok = u.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_NOTOPMOST), x, y, 0, 0,
                                    _SWP_NOSIZE | _SWP_NOACTIVATE)
            if not ok:
                self._fullscreen_warn('SetWindowPos 失败 (GetLastError=%s)'
                                      % (ctypes.get_last_error(),))
        except Exception as e:
            self._fullscreen_warn('SetWindowPos 抛异常: %r' % (e,))

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
        # 2026-11-18（P0-3 步 2）：本泵是 GL 侧的**合法写者** —— 它是唯一掌握物理键
        # 真相的地方（窗口失焦时 GLFW 不发 KEYUP，只有轮询才知道键真的松开了）。
        # 所以 script_keys = _kp 的整表赋值**保持不变**（GL 行为零改动），但同一帧把
        # 同一份值写进 key_state（键码空间）：两套键空间永远同值，否则「宿主写键 ->
        # 脚本 is_key」这条链在两端会走出两个结果（P0-3 步 2 前的现场）。
        _kp = {}
        _ks = self.__dict__.get('key_state')
        if not isinstance(_ks, dict):
            _ks = self.key_state = {}
        for name, pg_key in self._key_map_items():
            gl_key = _PG_TO_GLFW.get(pg_key)
            if gl_key is None:
                _kp[name] = False
                _ks[pg_key] = False
                continue
            try:
                _down = (glfw.get_key(self._glfw_win, gl_key) == glfw.PRESS)
            except Exception:
                _down = False
            _kp[name] = _down
            _ks[pg_key] = _down
        self.key_state = _ks
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
        # 2026-10-18 阶段3: UI 输入框焦点优先接收（IME 中文从这里进 InputField）
        if self._pending_chars:
            # 2026-11-17 (S1): 文本入口统一走 handle_text_input（UI 优先 → 钩子），
            # 与 VK 播放器/打包游戏调的是同一个方法。
            from types import SimpleNamespace
            for text in self._pending_chars:
                self.handle_text_input(SimpleNamespace(type='TEXTINPUT', text=text))
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
    # 2026-11-17 (S1 事件面统一): 顺序编排全部收进 EngineCore.handle_key_event ——
    # 编辑器 / GL 播放器 / VK 播放器 / 打包游戏调的是**同一个**入口，
    # 后端只负责「把 GLFW 事件翻成 ev 递进去」。
    e.handle_key_event(_make_key_event(e, pg_key, action))


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
    # 2026-11-17 (S1): 统一走 handle_quit_request（钩子抛异常也按允许退出，防卡死）
    if e.handle_quit_request():
        e._running = False


def _on_window_iconify_cb(win, iconified):
    """2026-10-19 第1档序7：窗口最小化/恢复 -> on_became_invisible/visible。
    GLFW 3.4 签名：iconified=True 表示最小化，False 表示恢复。"""
    e = _get_engine(win)
    if e is None:
        return
    try:
        e._dispatch_visibility_changed(not iconified)
    except Exception:
        pass
