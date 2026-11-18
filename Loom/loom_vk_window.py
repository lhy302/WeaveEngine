# -*- coding: utf-8 -*-
"""loom_vk_window.py — VK 宿主窗口的「假全屏」(F11)：**与 GL 同语义**的窗口层。

人类裁决 Q-B7-32-1 = ①（真做出来，2026-11-18）：
  「两个后端暴露给用户的 API 都是一样的，选择哪个后端在用户端就是换个配置，
    类似于 JVM 虚拟机：不管底层用的什么后端，往上暴露的接口都一样。」
  → 同一串输入事件（含按 F11）→ 两端同一串可观察结果。
  GL 侧这份实现在 loom_glfw_window.GlfwWindowMixin._set_fullscreen；VK 侧原先**没有**
  （SceneDriver 连 allow_fullscreen 属性都没有 -> 内核第①步的 getattr 恒 False -> F11 死键）。
  本文件把那份语义搬到 VK 侧；GL 侧一行未动（人类纪律：不许碰 GL 代码）。

假全屏三步（与 GL 逐项对齐，不切显示器分辨率）：
    进全屏  ① 取桌面分辨率
            ② glfw.set_window_attrib(win, DECORATED, FALSE)     去边框
            ③ glfw.set_window_size(win, 桌面宽, 桌面高)          铺满桌面
            ④ glfw.set_window_pos(win, 0, 0)                    左上角
            ⑤ Win32 SetWindowPos(HWND_TOPMOST=-1)               置顶
    退全屏  ① glfw.set_window_attrib(win, DECORATED, TRUE)      还边框
            ② glfw.set_window_size(win, 原 client 宽, 原 client 高)
            ③ glfw.set_window_pos(win, 原 x, 原 y)
            ④ Win32 SetWindowPos(HWND_NOTOPMOST=-2)             取消置顶

与 GL 的**已知差异**（都是实测出来的，见交付报告；要消除必须改 GL，本任务禁改）：
  · 退出还原：GL 的 _on_window_size_cb 会把 window_size 覆盖成全屏尺寸，且
    _window_rect 是在 set_window_pos(0,0) **之后**才记录 -> 实测 GL 退出后是
    1920x1055 @ (0,0)，**原尺寸/原位置并未还原**。本实现在进入前记录
    「client 尺寸 + 窗口矩形」，退出时真还原（640x400 @ 原位置）。
  · 置顶：GL 的 user32.SetWindowPos 未声明 argtypes，x64 上 HWND_TOPMOST(-1)
    作为 32 位 int 传入被截断 -> 实测返回 0（失败）、WS_EX_TOPMOST 从未置位；
    改成 c_void_p(-1) 后返回 1 且置位。本实现用**私有 WinDLL** + 显式 argtypes，
    置顶真的生效，且**不修改** ctypes.windll.user32 上那个 GL 也在用的共享函数对象。

宿主注入（vk_player.run_vk 的 _register_input 里做）：
    driver._vk_glfw_window = win     # rendercanvas 真正建的那个 GLFW 窗口
    driver._vk_canvas      = canvas  # 兜底：canvas._window
拿不到句柄 / 非 Windows -> **可见降级**（打印一行明确原因 + allow_fullscreen=False），
不许静默（内核第①步会因此彻底跳过 F11，用户能看见"本机不可用"的原因）。
"""
import ctypes
import os

# 与 GL 同值（不要改）：Win32 置顶常量与 SetWindowPos 标志
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040

# 平台判据（单测可 patch）
_WINDOWS = (os.name == 'nt')


def _glfw():
    """惰性取 glfw 模块（本模块 import 时不拉 glfw/pygame，scene_driver 导入保持轻）。"""
    import glfw
    return glfw


def _user32():
    """**私有** user32 句柄（显式 argtypes）。

    为什么不用 ctypes.windll.user32：那是全进程共享的函数对象，给它的 SetWindowPos
    设 argtypes 等于**暗中改了 GL 的行为**（GL 的 _place_fullscreen_window 用的是同一个
    对象）。这里 new 一个 WinDLL 实例，只影响本模块自己的函数指针。
    """
    if not _WINDOWS:
        return None
    try:
        from ctypes import wintypes
        u = ctypes.WinDLL('user32', use_last_error=True)
        sp = u.SetWindowPos
        sp.restype = wintypes.BOOL
        sp.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        gl = u.GetWindowLongW
        gl.restype = wintypes.LONG
        gl.argtypes = [wintypes.HWND, ctypes.c_int]
        gr = u.GetWindowRect
        gr.restype = wintypes.BOOL
        gr.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        gm = u.GetSystemMetrics
        gm.restype = ctypes.c_int
        gm.argtypes = [ctypes.c_int]
        return u
    except Exception:
        return None


def _make_hwnd(win):
    """GLFW 窗口 -> Win32 HWND。**同一份实现**：直接复用 loom_glfw_window._make_hwnd
    （filedialog.py 已有同样的跨模块复用先例），导入失败才本地兜底。"""
    try:
        from loom_glfw_window import _make_hwnd as _gl_make
        return _gl_make(win)
    except Exception:
        pass
    try:
        import ctypes.util
        dll = ctypes.CDLL(ctypes.util.find_library('glfw3') or 'glfw3.dll')
        dll.glfwGetWin32Window.restype = ctypes.c_void_p
        dll.glfwGetWin32Window.argtypes = [ctypes.c_void_p]
        return dll.glfwGetWin32Window(win)
    except Exception:
        return None


def _window_rect_now(u, hwnd):
    """当前窗口矩形 (left, top, right, bottom)；取不到返回 None。"""
    try:
        from ctypes import wintypes
        r = wintypes.RECT()
        if u.GetWindowRect(hwnd, ctypes.byref(r)):
            return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        pass
    return None


class VkWindowMixin:
    """VK 宿主窗口的假全屏（语义 = GL 的 GlfwWindowMixin._set_fullscreen）。

    只提供**下划线**成员：不进用户 API 面（test_user_api_parity 的公开成员集合不受影响）。
    需要的实例字段（SceneDriver.__init__ 建）：
        allow_fullscreen / fullscreen / width / height / _window_rect
    """

    # ---------------- 窗口句柄 ----------------
    def _host_window(self):
        """宿主真正在用的 GLFW 窗口句柄（验活后返回；拿不到返回 None）。

        来源优先级与 vk_player._resolve_glfw_window 一致：注入的句柄 -> canvas._window；
        用 glfw.get_window_size 验活（无效指针会抛）。
        """
        cand = getattr(self, '_vk_glfw_window', None)
        if cand is None:
            canvas = getattr(self, '_vk_canvas', None)
            cand = getattr(canvas, '_window', None)
        if cand is None:
            return None
        try:
            _glfw().get_window_size(cand)
        except Exception:
            return None
        return cand

    # ---------------- 桌面分辨率 ----------------
    def _desktop_resolution(self):
        """与 GL 同源：GetSystemMetrics(0/1) -> GLFW 主显示器视频模式 -> 当前窗口尺寸。

        GetSystemMetrics 给的是**物理像素**（GLFW 初始化时已把进程设成 DPI-aware，
        所以与 GL 侧拿到的是同一个数，两端"桌面尺寸"不会一个 1920 一个 1536）。
        """
        if getattr(self, '_desktop_override', None):
            return self._desktop_override
        u = _user32()
        if u is not None:
            try:
                w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
                if w > 0 and h > 0:
                    return (int(w), int(h))
            except Exception:
                pass
        try:
            vm = _glfw().get_video_mode(_glfw().get_primary_monitor())
            if vm is not None and vm.size.width > 0 and vm.size.height > 0:
                return (int(vm.size.width), int(vm.size.height))
        except Exception:
            pass
        return getattr(self, '_desktop_size', None) or (
            int(getattr(self, 'width', 1280) or 1280),
            int(getattr(self, 'height', 800) or 800))

    # ---------------- 降级（可见，不静默） ----------------
    def _fullscreen_unavailable(self, reason):
        """拿不到窗口 / 非 Windows：打一行明确原因，并把 F11 关掉（本局不再尝试）。"""
        if not getattr(self, '_fullscreen_degraded_logged', False):
            self._fullscreen_degraded_logged = True
            print('[全屏] %s -> F11 全屏在本机不可用（allow_fullscreen=False，本局不再尝试）'
                  % (reason,))
        self.allow_fullscreen = False
        self.fullscreen = False
        self._window_rect = None
        self._window_client = None
        return False

    # ---------------- 全屏 ----------------
    def _toggle_fullscreen(self):
        return self._set_fullscreen(not bool(getattr(self, 'fullscreen', False)))

    def _set_fullscreen(self, want):
        """假全屏开关（语义与 GL 的 _set_fullscreen 逐项一致）。

        返回 True=已执行窗口操作；False=可见降级（原因已打印）。
        """
        want = bool(want)
        win = self._host_window()
        if win is None:
            return self._fullscreen_unavailable(
                '拿不到宿主 GLFW 窗口句柄（rendercanvas 的 _window 不可用/已销毁）')
        if not _WINDOWS:
            return self._fullscreen_unavailable('当前平台不是 Windows（Win32 去边框/置顶不可用）')
        u = _user32()
        hwnd = _make_hwnd(win) if u is not None else None
        if not hwnd:
            return self._fullscreen_unavailable('拿不到 Win32 HWND（glfwGetWin32Window 失败）')
        try:
            glfw = _glfw()
        except Exception as e:
            return self._fullscreen_unavailable('glfw 不可用 (%r)' % (e,))

        if want:
            w, h = self._desktop_resolution()
            self.width = max(320, int(w))
            self.height = max(240, int(h))
            # 记录**进入前**的真实几何（GL 记在移动之后 -> 退出回 (0,0)；这里真还原）
            if getattr(self, '_window_rect', None) is None:
                self._window_rect = _window_rect_now(u, hwnd)
                try:
                    self._window_client = tuple(int(v) for v in glfw.get_window_size(win))
                except Exception:
                    self._window_client = (int(self.width), int(self.height))
            self.fullscreen = True
            glfw.set_window_attrib(win, glfw.DECORATED, glfw.FALSE)     # ② 去边框
            glfw.set_window_size(win, self.width, self.height)          # ③ 铺满桌面
            glfw.set_window_pos(win, 0, 0)                              # ④ 左上角
            self._place_fullscreen_window(u, hwnd)                      # ⑤ 置顶
            return True

        # ---- 退全屏：完整还原（边框 / 尺寸 / 位置 / 非置顶） ----
        rect = getattr(self, '_window_rect', None)
        cw, ch = getattr(self, '_window_client', None) or (
            int(getattr(self, 'width', 1280) or 1280),
            int(getattr(self, 'height', 800) or 800))
        self.fullscreen = False
        self.width = max(320, int(cw))
        self.height = max(240, int(ch))
        glfw.set_window_attrib(win, glfw.DECORATED, glfw.TRUE)          # ① 还边框
        glfw.set_window_size(win, self.width, self.height)              # ② 还原尺寸
        if rect:
            glfw.set_window_pos(win, int(rect[0]), int(rect[1]))        # ③ 还原位置
        self._place_fullscreen_window(u, hwnd)                          # ④ 取消置顶
        self._window_rect = None
        self._window_client = None
        return True

    def _place_fullscreen_window(self, u=None, hwnd=None):
        """Win32 置顶 / 取消置顶（GLFW 没有 set_always_on_top API）。

        与 GL 同常量、同标志；差异只在**参数宽度**：HWND_TOPMOST/HWND_NOTOPMOST 必须
        按 64 位句柄传（c_void_p(-1)/(-2)），否则 x64 上 SetWindowPos 直接失败。
        """
        try:
            if u is None:
                u = _user32()
            if u is None:
                return
            if hwnd is None:
                win = self._host_window()
                hwnd = _make_hwnd(win) if win is not None else None
            if not hwnd:
                return
            if self.fullscreen:
                u.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_TOPMOST), 0, 0,
                               int(self.width), int(self.height),
                               _SWP_NOACTIVATE | _SWP_SHOWWINDOW)
            else:
                rect = getattr(self, '_window_rect', None)
                x, y = (int(rect[0]), int(rect[1])) if rect else (0, 0)
                u.SetWindowPos(hwnd, ctypes.c_void_p(_HWND_NOTOPMOST), x, y, 0, 0,
                               _SWP_NOSIZE | _SWP_NOACTIVATE)
        except Exception:
            pass
