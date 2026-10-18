# -*- coding: utf-8 -*-
"""loom_window.py — GLEngine 窗口/事件子系统 (尺寸/全屏/事件循环/输入钩子)。

从 engine.py 抽出 (作为 WindowMixin 供 GLEngine 继承):
  _on_resize / _desktop_resolution / _set_fullscreen / _toggle_fullscreen
  _place_fullscreen_window / _handle_events
  on_key_event / on_text_input / on_quit_request  (三个可被子类覆写的钩子)

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self.width / self.height / self.window / self.window_size / self.ctx / self._external_ctx
  self.fullscreen / self.allow_fullscreen / self._window_rect / self._desktop_override
  self._desktop_size / self._running / self.gui_dirty
  self.pressed / self.released / self.mouse_wheel / self.script_keys / self.mouse_pos
  self.mouse_press_pos / self.buttons / self._mods / self._key / self.key_state
  self.select_next_model / self.toggle_logic_paused / self.step_logic_once
"""
import pygame

from loom_input import _KEYMAP


class WindowMixin:
    def _on_resize(self, w, h):
        """窗口尺寸变化 (拖拽缩放): 更新 GL viewport + 布局.
        不重设窗口 —— SDL 已把 GL drawable 缩放好, 重复 set_mode 只是多闪一次屏."""
        self.width = max(320, int(w))
        self.height = max(240, int(h))
        self.ctx.viewport = (0, 0, self.width, self.height)
        # 2026-10-18: Canvas UI 跟随窗口尺寸 (screen Canvas 重算根矩形)
        ui = getattr(self, 'ui', None)
        if ui is not None:
            try:
                ui.resize(self.width, self.height)
            except Exception:
                pass

    def _desktop_resolution(self):
        """当前桌面分辨率 (主显示器全屏覆盖用).
        优先 GetSystemMetrics (窗口存在与否都返回真桌面尺寸; Info() 在有窗口时
        只返回窗口尺寸, 不可信); 失败回退 init 时抓的 _desktop_size;
        测试用 _desktop_override 固定."""
        if getattr(self, '_desktop_override', None):
            return self._desktop_override
        try:
            import ctypes
            w = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN
            h = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
        return getattr(self, '_desktop_size', (self.width, self.height))

    def _set_fullscreen(self, fullscreen):
        """F11: 全屏 / 窗口 切换.
        用「无边框窗口铺满桌面分辨率」的假全屏, 不切显示分辨率 (pygame.FULLSCREEN
        独占模式会真实切换显示器分辨率, 触发 GPU 驱动模式切换/可能重置, 还容易把
        GPU 加速的终端窗口一起带崩). SDL 复用同一窗口+GL 上下文 (OPENGL flag 不变)."""
        self.fullscreen = bool(fullscreen)
        if fullscreen:
            w, h = self._desktop_resolution()   # 桌面分辨率 (不改变显示模式)
            flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE | pygame.NOFRAME
        else:
            w, h = self.window_size
            flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
        self.width = max(320, int(w))
        self.height = max(240, int(h))
        self.window = pygame.display.set_mode((self.width, self.height), flags)
        self.ctx.viewport = (0, 0, self.width, self.height)
        self._place_fullscreen_window()

    def _toggle_fullscreen(self):
        """F11: 全屏 / 窗口 切换 (假全屏, 不切分辨率)"""
        self._set_fullscreen(not self.fullscreen)

    def _place_fullscreen_window(self):
        """假全屏的窗口定位 (Win32; pygame 不暴露窗口位置/置顶).
        进全屏: 移 (0,0) 铺满 + 置顶盖住任务栏; 退出: 取消置顶 + 恢复原位置.
        全屏前记下窗口矩形, 退出时还原. 失败静默 (非关键路径)."""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = pygame.display.get_wm_info()['window']
            user32 = ctypes.windll.user32
            SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0010, 0x0040
            if self.fullscreen:
                # 首次进全屏时记住窗口矩形 (退出还原位置用)
                if self._window_rect is None:
                    r = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                        self._window_rect = (r.left, r.top, r.right, r.bottom)
                # HWND_TOPMOST=-1: 置顶盖住任务栏; 移到 (0,0) 铺满整个桌面
                user32.SetWindowPos(hwnd, -1, 0, 0, self.width, self.height,
                                    SWP_NOACTIVATE | SWP_SHOWWINDOW)
            else:
                # HWND_NOTOPMOST=-2: 取消置顶 + 恢复原位置 (尺寸已由 set_mode 管理)
                x, y = (self._window_rect[0], self._window_rect[1]) if self._window_rect else (0, 0)
                user32.SetWindowPos(hwnd, -2, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _handle_events(self):
        """pygame 事件 -> 按键状态/动作.
        嵌入式模式 (Qt 宿主) 不用本方法: 事件由宿主直接写入引擎状态并调钩子."""
        if self._external_ctx:
            return
        # 每帧批处理开始清零瞬时状态 (pressed/released/wheel)
        self.pressed.clear()
        self.released.clear()
        self.mouse_wheel = 0
        # 脚本/游戏输入: 直接读硬件键盘快照 (脚本不依赖事件流, 查询更稳定)
        try:
            _kp = pygame.key.get_pressed()
            self.script_keys = {name: bool(_kp[k]) for name, k in _KEYMAP.items()}
        except Exception:
            self.script_keys = {}
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if self.on_quit_request():   # 2026-08-13: 退出拦截钩子 (编辑器防丢)
                    self._running = False
            elif ev.type == pygame.VIDEORESIZE:
                if not self.fullscreen:
                    self.window_size = (ev.size[0], ev.size[1])
                self._on_resize(ev.size[0], ev.size[1])
                self.gui_dirty = True                    # 异步GUI: 尺寸变化置脏(FBO 尺寸驱动重建)
            elif ev.type == pygame.KEYDOWN:
                self.gui_dirty = True                    # 异步GUI: 按键置脏 (含被吞掉的按键)
                # F11 全屏切换 (引擎层, 先于 on_key_event 钩子).
                # 编辑器禁 F11 (allow_fullscreen=False): 输入法会把 SDL 窗口误判为
                # 游戏/全屏而隐藏候选框, 且开发场景几乎不用全屏, 干脆关闭, 只留
                # 最大化+自由缩放; 封装游戏 (PlayerApp) 仍允许假全屏 (2026-08-17).
                if self.allow_fullscreen and ev.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue
                # 分离批5: F9 暂停逻辑时钟 / F10 步进 1 逻辑帧 (MC 同款,
                # 2026-09-05 用户需求; 仅播放态+分离开时生效)
                if ev.key == pygame.K_F9:
                    new_state = self.toggle_logic_paused()
                    if new_state is not None:
                        state = "已暂停 (F10 步进)" if new_state else "已恢复"
                        print("[逻辑时钟] %s" % state)
                    continue
                if ev.key == pygame.K_F10:
                    if self.step_logic_once():
                        print("[逻辑时钟] 步进 1 逻辑帧")
                    continue
                # on_key_event 钩子: 返回 True 则吞掉 (编辑器输入框/自定义按键)
                if self.on_key_event(ev):
                    continue
                k = ev.key
                if k == self._key['SELECT_NEXT_MODEL']:
                    self.select_next_model()
                elif k in self.key_state:
                    self.key_state[k] = True
            elif ev.type == pygame.KEYUP:
                self.gui_dirty = True                    # 异步GUI: 按键置脏
                k = ev.key
                if self.on_key_event(ev):
                    continue
                if k in self.key_state:
                    self.key_state[k] = False
            elif ev.type == pygame.MOUSEMOTION:
                self.mouse_pos = ev.pos
                if not any(pygame.mouse.get_pressed()):  # 无按键才置脏(轨道/拖动期保持GUI帧)
                    self.gui_dirty = True
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                self.gui_dirty = True                    # 异步GUI: 按下置脏 (面板必消费输入)
                self.mouse_pos = ev.pos
                self.pressed.add(ev.button)
                self.mouse_press_pos[ev.button] = ev.pos
            elif ev.type == pygame.MOUSEBUTTONUP:
                self.gui_dirty = True                    # 异步GUI: 松开置脏
                self.mouse_pos = ev.pos
                self.released.add(ev.button)
                self.mouse_press_pos.pop(ev.button, None)
            elif ev.type == pygame.MOUSEWHEEL:
                self.gui_dirty = True                    # 异步GUI: 滚轮置脏
                self.mouse_wheel = ev.y
            elif ev.type == pygame.TEXTINPUT:
                # IME 合成文本 (2026-08-17): 中文输入法提交的字符经 TEXTINPUT 送达
                # (KEYDOWN.unicode 在 start_text_input 后不再可靠). 交给钩子转发输入框.
                self.gui_dirty = True
                self.on_text_input(ev)
        self.buttons = pygame.mouse.get_pressed()
        self._mods = pygame.key.get_mods()

    def on_key_event(self, ev):
        """按键钩子: 子类可覆写吞掉特定按键 (编辑器输入框). 返回 True = 吞掉."""
        return False

    def on_text_input(self, ev):
        """文本输入钩子 (IME 合成结果, 2026-08-17). 子类(编辑器)转发给视图/输入框.
        默认忽略 (无输入框场景)."""
        return False

    def on_quit_request(self):
        """窗口关闭请求 (QUIT) 钩子 (2026-08-13): 返回 True = 允许退出.
        编辑器覆写为"有未保存改动先询问" (统一防丢)."""
        return True
