# -*- coding: utf-8 -*-
r"""
LoomHub.py — LoomHub 项目管理器入口 + pygame 自绘视图 (UI 模块化 2026-08-13)

架构: 本文件 = 视图层 (IHubView 的 pygame 默认实现). 业务逻辑全在
HubController (hub_controller.py) —— 换 UI 后端 (tkinter: `--ui tk`) 只需换
实现类, 不动业务. 详见 hub_controller.py 的 IHubView 契约.

启动: py -3.12 LoomHub.py            (pygame 自绘视图, 默认)
      py -3.12 LoomHub.py --ui tk     (极简 tkinter 视图, 演示 UI 可更换)
      (双击 .py 亦可, 已绑定 3.12.10)

功能:
  项目管理  : 新建/导入/打开/移除/扫描 项目.
              新建 = 系统文件管理器选目录 (默认=解释器保存文件夹, 免输入项目名,
              项目名取目录名), 创建空场景并写入 projects.json.
              导入 = 选一个含场景文件的目录, 发现项目并登记 (如同导入解释器).
              启动自动扫描解释器保存目录下的项目. 打开 = 用选定解释器 --open 启动编辑器.
  解释器管理: ① 扫描 C:\Program Files\Loom 多版本目录(按版本号分析已装解释器)
              ② 导入解释器目录(.py 源码 / .exe 封装, 读 解释器.json 分析版本)
              ③ .zip 安装(默认装到 C:\Program Files\Loom\<版本号>, 可改安装根)
              ④ 远程下载(预留接口, 未开放)
  启动 .py 解释器使用系统默认 Python 环境 (状态栏提醒当前默认版本).
"""
import os
import sys

import pygame

HUB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HUB_DIR)

from hub_controller import HubController, IHubView

BG = (28, 30, 34)
PANEL = (38, 41, 47)
TEXT = (220, 222, 228)
DIM = (140, 143, 152)
ACCENT = (230, 150, 60)
BTN = (60, 64, 74)
BTN_HI = (76, 82, 94)
LIST_HI = (70, 76, 88)
ERR = (235, 90, 90)

# 消息等级 -> 颜色 (controller 只给 'ok'/'err'/'dim', 颜色是显示层的事)
_MSG_COLORS = {'ok': TEXT, 'err': ERR, 'dim': DIM}


def _load_font(size):
    """加载系统字体 (微软雅黑优先, 回退默认字体).
    不走 pygame.font.SysFont —— 本机枚举 Windows 字体时遇到异常条目会崩
    (TypeError: expected str, not int), 直接指定字体文件路径绕过."""
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf",
              "C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(p):
            return pygame.font.Font(p, size)
    return pygame.font.Font(None, size)


def _input_string(prompt, initial="", title="LoomHub"):
    """tkinter 输入框. 弹出前临时隐藏 pygame 窗口, 输入完恢复.

    为什么: 搜狗/部分输入法会把 pygame 的 SDL 窗口误判为"游戏/全屏", 从而
    全局隐藏候选框和输入法悬浮窗 (用户实测打开 LoomHub 后输入法 UI 全没了).
    隐藏 pygame 窗口后, 前台变成普通 tkinter 输入框, 输入法候选框恢复正常.
    返回输入字符串, 取消返回 None."""
    import tkinter as tk
    from tkinter import simpledialog
    import ctypes
    hwnd = 0
    try:
        if pygame.display.get_init():
            hwnd = pygame.display.get_wm_info().get('window') or 0
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE 隐藏 pygame 窗口
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()          # 隐藏主窗口 (只显示 askstring 输入框, 不多余空框)
    root.attributes('-topmost', True)
    try:
        root.lift()
        root.focus_force()
        root.update()
        result = simpledialog.askstring(title, prompt, initialvalue=initial,
                                        parent=root)
    finally:
        root.destroy()
    try:
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)   # SW_SHOW 恢复 pygame 窗口
    except Exception:
        pass
    return result


class LoomHubGUI(IHubView):
    """LoomHub 主 GUI 界面组件 (IHubView 默认实现, pygame 自绘).
    换界面 = 新写一个 IHubView 实现替换本类. 业务全在 controller."""
    def __init__(self, controller=None, w=980, h=640):
        self.ctrl = controller or HubController()     # 业务/状态全走 controller
        self.w, self.h = w, h
        self.window_size = (w, h)      # 窗口模式尺寸 (全屏切换恢复用)
        self.fullscreen = False
        pygame.init()
        self.screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        pygame.display.set_caption("LoomHub — 项目管理器")
        # 直接加载字体文件 (绕过 SysFont 的本机字体枚举 bug)
        self.font = _load_font(16)
        self.font_s = _load_font(13)
        self.font_b = _load_font(20)
        self.sel_interp = None
        self.sel_project = None
        self._click = None         # 本帧按下位置
        self._wheel = None         # 本帧滚轮 (button 4=上/5=下; 面板绘制按鼠标位置消费)
        self._mouse_pos = (0, 0)   # 本帧鼠标位置 (MOUSEMOTION 更新, 滚动条拖拽用)
        self._sb_released = False  # 本帧左键已松开 (滚动条拖拽停止)
        self._sb_drag = None       # 当前拖拽的滚动条 uid
        self._sb_anchor = (0, 0)   # 滚动条拖拽锚点 (scroll, y)
        self._interp_scroll = 0    # 解释器列表垂直滚动偏移 (2026-08-14)
        self._project_scroll = 0   # 项目列表垂直滚动偏移
        self._show_settings = False   # 设置覆盖面板 (换 GUI / 打开项目 py-vs-exe, 2026-08-14)
        self._done = False
        # 2026-08-15 空闲 CPU 优化:
        self._text_cache = {}         # (text, color, font) -> Surface (font.render 只栅格化一次)
        self._force_redraw = True     # 首帧 + _input_string 返回后强制重绘 (脏驱动兜底)
        self._gui_list_cache = None   # 设置面板 GUI 列表 (scan_guis 只扫一次, 面板开着期间复用)
        # 2026-08-15 主线程核心调度: 启动器主线程锁到负载最低的大核 (避开静态负载最高的
        # CPU1 等), 每 20s 重测迁移. 只 pin 主线程, 不改进程亲和. Loom\parallel 已由
        # hub_controller 加入 sys.path; 失败静默跳过 (不崩启动器).
        self._main_core_sched = None
        try:
            from parallel import detect_topology, MainThreadCoreScheduler
            _topo = detect_topology()
            if _topo:
                # LoomHub 本身负载低, 周期跳核不影响 -> 保留 20s 重测迁移 (Loom 引擎关掉)
                self._main_core_sched = MainThreadCoreScheduler(_topo)
                _cb = self._main_core_sched.current_bit()
                print("[LoomHub] 主线程锁定到负载最低的大核 #%s (每 20s 重测迁移)"
                      % ("?" if _cb is None else _cb))
        except Exception:
            self._main_core_sched = None

    def attach(self, controller):
        self.ctrl = controller

    # ---------- 基础绘制 ----------
    def _text(self, s, x, y, color=TEXT, font=None, center=False):
        f = font or self.font
        # 2026-08-15: 文字表面缓存 —— font.render (SDL_ttf 栅格化) 是空闲 CPU 主源
        # (60FPS × 几十条字符串每帧重渲染 = 单核 ~60%). 相同 (text,color,font) 只渲染一次.
        key = (s, color, f)
        img = self._text_cache.get(key)
        if img is None:
            img = f.render(s, True, color)
            if len(self._text_cache) > 2000:   # 防动态文本无限膨胀
                self._text_cache.clear()
            self._text_cache[key] = img
        r = img.get_rect()
        if center:
            x -= r.width // 2
        self.screen.blit(img, (x, y))
        return r.width

    def _button(self, rect, label, enabled=True):
        bg = BTN_HI if (enabled and pygame.Rect(rect).collidepoint(pygame.mouse.get_pos())) else BTN
        pygame.draw.rect(self.screen, bg, rect, border_radius=4)
        if not enabled:
            col = DIM
        else:
            col = TEXT
        self._text(label, pygame.Rect(rect).centerx, pygame.Rect(rect).centery - 8,
                   col, self.font_s, center=True)
        if enabled and self._click and pygame.Rect(rect).collidepoint(self._click):
            self._click = None
            return True
        return False

    def _row(self, rect, text, selected, kind_tag=None, tag_color=None):
        rect = pygame.Rect(rect)   # tuple -> Rect (几何/碰撞检测用)
        if selected:
            pygame.draw.rect(self.screen, LIST_HI, rect, border_radius=4)
        pygame.draw.rect(self.screen, (60, 64, 74), rect, 1, border_radius=4)
        x = rect.x + 8
        if kind_tag:
            x += self._text(kind_tag, x, rect.y + 3, tag_color or DIM, self.font_s) + 8
        self._text(text, x, rect.y + 2, TEXT, self.font_s)

    def _msg_color(self):
        return _MSG_COLORS.get(self.ctrl.msg_level, TEXT)

    def _vscroll(self, uid, list_rect, total_h, scroll):
        """垂直滚动条 (2026-08-14, pygame 版): 列表内容超高时右侧出现,
        滚轮 / 拖拇指上下滚动. list_rect=(lx,ly,lw,lh) 列表可视区, total_h=内容总高.
        返回新 scroll (调用方存回 panel 状态)."""
        lx, ly, lw, lh = list_rect
        max_scroll = max(0, total_h - lh)
        scroll = max(0, min(max_scroll, scroll))
        # 滚轮: 鼠标在列表区内才消费 (两个面板互不抢)
        if self._wheel and pygame.Rect(list_rect).collidepoint(self._mouse_pos):
            scroll = max(0, min(max_scroll,
                                scroll + (42 if self._wheel[0] == 5 else -42)))
            self._wheel = None
        if max_scroll <= 0:
            return 0
        bar_w = 8
        track = pygame.Rect(lx + lw - bar_w - 3, ly + 2, bar_w, lh - 4)
        thumb_h = max(24, int(lh * (lh / max(1.0, total_h))))
        avail = max(1, track.h - thumb_h)
        thumb_y = track.y + int((scroll / max_scroll) * avail)
        # 按下轨道 -> 开始拖拽 (锚定当前 scroll + 按下 y; 按下帧不跳变)
        if self._click and track.collidepoint(self._click):
            self._sb_drag = uid
            self._sb_anchor = (scroll, self._click[1])
            self._click = None
        # 拖拽中: 用帧内鼠标位置 (MOUSEBUTTONUP 才停)
        if self._sb_drag == uid:
            if self._sb_released:
                self._sb_drag = None
                self._sb_released = False
            else:
                sv, sy = self._sb_anchor
                my = self._mouse_pos[1]
                scroll = max(0, min(max_scroll, sv + (my - sy) * (max_scroll / avail)))
        # 绘制 (轨道 + 拇指)
        pygame.draw.rect(self.screen, (60, 64, 74), track, border_radius=4)
        pygame.draw.rect(self.screen, (110, 118, 132),
                         (track.x, thumb_y, bar_w, thumb_h), border_radius=4)
        return scroll

    def _toggle_fullscreen(self):
        """F11: 全屏 / 窗口 切换 (视图层 pygame 专属)"""
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0),
                                                  pygame.FULLSCREEN | pygame.RESIZABLE)
            self.w, self.h = self.screen.get_size()
        else:
            self.w, self.h = self.window_size
            self.screen = pygame.display.set_mode(self.window_size,
                                                  pygame.RESIZABLE)

    # ---------- 主循环 ----------
    def run(self):
        clock = pygame.time.Clock()
        self._last_err = None
        while not self._done:
            self._click = None
            self._wheel = None
            self._sb_released = False
            self._mouse_pos = pygame.mouse.get_pos()
            dirty = self._force_redraw
            self._force_redraw = False
            had_event = False
            for ev in pygame.event.get():
                had_event = True
                dirty = True
                if ev.type == pygame.QUIT:
                    self._done = True
                elif ev.type == pygame.VIDEORESIZE:
                    self.w, self.h = ev.size
                    if not self.fullscreen:
                        self.window_size = (self.w, self.h)
                    self.screen = pygame.display.set_mode((self.w, self.h),
                                                          pygame.RESIZABLE)
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                    self._toggle_fullscreen()
                elif ev.type == pygame.MOUSEMOTION:
                    self._mouse_pos = ev.pos
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    self._click = ev.pos
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (4, 5):
                    self._wheel = (ev.button, ev.pos)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    self._sb_released = True
            # 2026-08-15 脏驱动: 无事件且未强制时跳过整帧重绘+flip (启动器空闲近似 0 CPU;
            # 文字已缓存, 绘制本身也便宜). 事件帧后强制再绘一帧: 本帧绘制顺序可能先于
            # 动作生效 (底部按钮改列表/默认, 滚轮改 scroll, 选行改选中), 让下一帧以最新
            # 状态补绘, 不会丢更新.
            if dirty:
                try:
                    self._draw()
                    self._last_err = None
                except Exception as e:
                    # 任何动作/绘制出错都不崩溃退出: 打印一次 + 状态栏提示
                    if str(e) != self._last_err:
                        import traceback
                        traceback.print_exc()
                        self._last_err = str(e)
                    self.ctrl.set_msg("发生错误: %s" % e, 'err')
                pygame.display.flip()
                self._force_redraw = had_event
            clock.tick(60)
        pygame.quit()

    # ---------- 绘制 ----------
    def _draw(self):
        self.screen.fill(BG)
        self._text("LoomHub", 14, 8, ACCENT, self.font_b)
        self._text("项目管理 + 解释器管理 (多版本共存)   [F11=全屏, 拖拽边缘=缩放]",
                   14, 34, DIM, self.font_s)
        # 右上"设置"按钮 (2026-08-14)
        if self._button((self.w - 74, 8, 60, 24), "设置"):
            self._show_settings = not self._show_settings
            if self._show_settings:
                self._gui_list_cache = None   # 重开设置时重新扫 GUI 列表
        if self._show_settings:
            self._draw_settings()
            return          # 模态: 设置打开时只画设置面板
        panel_w = max(320, (self.w - 40) // 2)     # 两面板各占一半
        panel_h = self.h - 58 - 120
        self._draw_interp_panel(14, 58, panel_w, panel_h)
        self._draw_project_panel(28 + panel_w, 58, panel_w, panel_h)
        self._draw_status(14, self.h - 96, self.w - 28, 92)

    def _draw_interp_panel(self, x, y, w, h):
        pygame.draw.rect(self.screen, PANEL, (x, y, w, h), border_radius=6)
        self._text("解释器 (Loom)", x + 12, y + 8, ACCENT, self.font)
        self._text("默认安装根: %s" % self.ctrl.install_root, x + 12, y + 30, DIM, self.font_s)
        by = y + 54
        bw = (w - 44) // 4                     # 4 个按钮等宽自适应
        if self._button((x + 12, by, bw, 24), "扫描"):
            self.ctrl.scan_interpreters()
        if self._button((x + 18 + bw, by, bw, 24), "导入目录"):
            self.ctrl.import_interpreter_dir()
        if self._button((x + 24 + 2 * bw, by, bw, 24), "安装 .zip"):
            version = _input_string("版本号 (如 1.0.0)", initial="")
            if version:
                self.ctrl.do_install_zip(version)
        if self._button((x + 30 + 3 * bw, by, bw, 24), "远程", enabled=False):
            pass
        lx, ly, lw, lh = x + 12, y + 88, w - 24, h - 150
        pygame.draw.rect(self.screen, (24, 26, 30), (lx, ly, lw, lh), border_radius=4)
        row_h = 24
        rows = self.ctrl.interpreters or [None]
        # 垂直滚动 (2026-08-14): 解释器多时下方不显示 -> 滚轮/拖条滚看
        total_h = max(0, (len(rows) - 1) * (row_h + 4) + row_h + 6)
        max_scroll = max(0, total_h - lh)
        sb_w = 12 if max_scroll > 0 else 0
        self.screen.set_clip((lx, ly, lw, lh))
        for i, it in enumerate(rows):
            ry = ly + 6 + i * (row_h + 4) - self._interp_scroll
            if ry + row_h < ly:
                continue
            if ry > ly + lh:
                break
            if it is None:
                self._text("(还没有解释器 — 扫描/导入/安装)", lx + 8, ry + 3, DIM, self.font_s)
                continue
            rect = (lx + 2, ry, lw - 4 - sb_w, row_h)
            selected = (self.sel_interp is not None
                        and it['dir'] == self.sel_interp['dir'])
            tag = "★ " if it.get('default') else ""
            self._row(rect, "%s%s  (v%s, %s)" % (tag, it['name'], it['version'], it['kind']),
                      selected)
            if self._click and pygame.Rect(rect).collidepoint(self._click):
                self.sel_interp = it
                self._click = None
        self.screen.set_clip(None)
        self._interp_scroll = self._vscroll('interp', (lx, ly, lw, lh), total_h,
                                            self._interp_scroll)
        by2 = y + h - 56
        bw2 = (w - 44) // 3                    # 3 个按钮等宽自适应
        if self._button((x + 12, by2, bw2, 24), "设为默认"):
            self.ctrl.set_default(self.sel_interp)
        if self._button((x + 18 + bw2, by2, bw2, 24), "移除"):
            self.ctrl.remove_interpreter(self.sel_interp)
        if self._button((x + 24 + 2 * bw2, by2, bw2, 24), "改安装根"):
            new_root = _input_string("安装根目录 (绝对路径)", initial=self.ctrl.install_root)
            if new_root is not None:
                self.ctrl.set_install_root(new_root)
        self._text("说明: .zip 解压到安装根/<版本号>; 版本目录下须含 解释器.json",
                   x + 12, by2 + 30, DIM, self.font_s)

    def _draw_project_panel(self, x, y, w, h):
        pygame.draw.rect(self.screen, PANEL, (x, y, w, h), border_radius=6)
        self._text("项目", x + 12, y + 8, ACCENT, self.font)
        by = y + 54
        bw = (w - 56) // 5                     # 5 个按钮等宽自适应 (新建/导入/打开/移除/扫描)
        bx = [x + 12 + i * (bw + 4) for i in range(5)]
        if self._button((bx[0], by, bw, 24), "新建"):
            self.ctrl.new_project()
        if self._button((bx[1], by, bw, 24), "导入"):
            self.ctrl.import_project_dir()
        if self._button((bx[2], by, bw, 24), "打开"):
            self.ctrl.open_project(self.sel_project)
        if self._button((bx[3], by, bw, 24), "移除"):
            self.ctrl.remove_project(self.sel_project)
        if self._button((bx[4], by, bw, 24), "扫描"):
            self.ctrl.scan_save_dir_projects()
        lx, ly, lw, lh = x + 12, y + 88, w - 24, h - 150
        pygame.draw.rect(self.screen, (24, 26, 30), (lx, ly, lw, lh), border_radius=4)
        row_h = 24
        rows = self.ctrl.projects or [None]
        # 垂直滚动 (2026-08-14): 项目多时下方不显示 -> 滚轮/拖条滚看
        total_h = max(0, (len(rows) - 1) * (row_h + 4) + row_h + 6)
        max_scroll = max(0, total_h - lh)
        sb_w = 12 if max_scroll > 0 else 0
        self.screen.set_clip((lx, ly, lw, lh))
        for i, p in enumerate(rows):
            ry = ly + 6 + i * (row_h + 4) - self._project_scroll
            if ry + row_h < ly:
                continue
            if ry > ly + lh:
                break
            if p is None:
                self._text("(还没有项目 — 新建/导入)", lx + 8, ry + 3, DIM, self.font_s)
                continue
            rect = (lx + 2, ry, lw - 4 - sb_w, row_h)
            selected = (self.sel_project is not None
                        and p['scene'] == self.sel_project['scene'])
            self._row(rect, "%s  —  %s" % (p['name'], os.path.basename(p['scene'])),
                      selected)
            if self._click and pygame.Rect(rect).collidepoint(self._click):
                self.sel_project = p
                self._click = None
        self.screen.set_clip(None)
        self._project_scroll = self._vscroll('project', (lx, ly, lw, lh), total_h,
                                             self._project_scroll)
        self._text("打开项目 = 用默认解释器启动编辑器 (--open)", x + 12, y + h - 28,
                   DIM, self.font_s)

    def _draw_status(self, x, y, w, h):
        pygame.draw.rect(self.screen, PANEL, (x, y, w, h), border_radius=6)
        self._text("状态", x + 12, y + 8, ACCENT, self.font)
        default = self.ctrl.default_interpreter()
        line1 = "默认解释器: " + (("%s v%s (%s)" % (default['name'], default['version'],
                                                    default['kind']))
                                 if default else "(无)")
        self._text(line1, x + 12, y + 30, TEXT, self.font_s)
        if self.ctrl.py_ver:
            warn = "启动 .py 解释器将使用系统默认 Python 环境 → %s" % self.ctrl.py_ver
        else:
            warn = "未检测到系统默认 python (启动 .py 可能失败, 请检查 PATH)"
        self._text(warn, x + 12, y + 50, (240, 200, 90), self.font_s)
        if self.ctrl.msg:
            self._text(self.ctrl.msg, x + 12, y + 72, self._msg_color(), self.font_s)

    def _draw_settings(self):
        """设置覆盖面板 (2026-08-14): GUI 选择 / 打开项目 .py-.exe / 默认解释器 / 关闭."""
        import guiloader
        w, h = self.w, self.h
        pw, ph = 480, 380
        x, y = (w - pw) // 2, (h - ph) // 2
        pygame.draw.rect(self.screen, PANEL, (x, y, pw, ph), border_radius=8)
        pygame.draw.rect(self.screen, (70, 74, 84), (x, y, pw, ph), 1, border_radius=8)
        self._text("设置", x + 16, y + 12, ACCENT, self.font)
        y0 = y + 54
        # —— GUI 界面 (官方 + GUI\ 下标识合法的自定义) ——
        self._text("GUI 界面（重启后生效）", x + 16, y0, DIM, self.font_s); y0 += 24
        cur = guiloader.load_settings('loomhub').get('gui', 'LoomHubGUI')
        # 2026-08-15: GUI 列表开面板时扫一次缓存 (每帧扫目录是磁盘 I/O)
        guis = self._gui_list_cache
        if guis is None:
            guis = self._gui_list_cache = list(guiloader.scan_guis('loomhub'))
        for gi in guis:
            mark = "●" if gi['id'] == cur else "○"
            if self._button((x + 16, y0, pw - 32, 24), "%s %s" % (mark, gi['name'])):
                s = guiloader.load_settings('loomhub')
                s['gui'] = gi['id']
                guiloader.save_settings('loomhub', s)
                self.ctrl.set_msg("已切换到「%s」，重启后生效" % gi['name'], 'ok')
            y0 += 30
        # —— 打开项目 .py / .exe (启动器设置) ——
        self._text("打开项目优先用", x + 16, y0 + 4, DIM, self.font_s)
        open_py = guiloader.load_settings('loomhub').get('open_py', True)
        if self._button((x + 16, y0 + 26, pw - 32, 26),
                        "用 .py 源码启动（开发）" if open_py else "用 .exe 封装启动（发布）"):
            s = guiloader.load_settings('loomhub')
            s['open_py'] = not open_py
            guiloader.save_settings('loomhub', s)
        y0 += 64
        dflt = self.ctrl.default_interpreter()
        self._text("默认解释器: " + (("%s v%s (%s)" % (dflt['name'], dflt['version'],
                                                       dflt['kind']))
                                    if dflt else "(无)"), x + 16, y0, DIM, self.font_s)
        # —— 关闭 ——
        if self._button((x + 16, y + ph - 42, pw - 32, 26), "关闭"):
            self._show_settings = False
            self._click = None

    # (输入改用 tkinter _input_string, 不再用 pygame 自绘模态框)


def main():
    """入口: 按 --ui 选择视图实现; 默认走 guiloader 读设置选 GUI
    (官方默认 = TkHubView (tkinter), 2026-08-17 起; 自定义 GUI 来自 GUI/ 文件夹,
    重启后生效; 加载失败自动回退官方). --ui pygame 强制本文件 (遗留, 仅参考:
    SDL 窗口会进程级污染中文输入法候选框, 见记忆 sdl-window-contaminates-ime)."""
    ui_name = None
    if '--ui' in sys.argv:
        i = sys.argv.index('--ui')
        if i + 1 < len(sys.argv):
            ui_name = sys.argv[i + 1]
    ctrl = HubController()
    if ui_name == 'pygame':
        view = LoomHubGUI(ctrl)               # 遗留 pygame 视图 (仅参考)
    else:
        from guiloader import resolve_gui
        view = resolve_gui('loomhub', ctrl)   # 官方 TkHubView / 自定义 (失败回退官方)
    view.run()


if __name__ == "__main__":
    main()
