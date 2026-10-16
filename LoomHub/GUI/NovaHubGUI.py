# -*- coding: utf-8 -*-
# gui: loomhub
# gui-name: 星辉 Nova
# gui-desc: 深色卡片式视觉升级 (功能对齐官方 TkHubView; 双击项目行直接打开)
"""
NovaHubGUI.py — LoomHub 自定义视图 (IHubView 实现, 深色卡片式)
==============================================================
2026-08-21: 用户要求优化 LoomHub 视觉 (当时默认界面 = TkHubView tkinter
极简视图, 被戏称"毛胚房")。本文件 = 全新布局的 tkinter 视图, 功能与官方
TkHubView 完全对齐 (解释器 / 项目 / 设置 / 状态), 视觉全面升级:
  - 深色卡片式布局 (品牌橙点缀, 延续 LoomHub 原色板)
  - 卡头彩条 + 分组按钮 + 按钮 hover + 列表空态提示
  - 双击项目行 = 直接打开编辑器 (显示层增强, 不碰 controller)
  - 两个列表各自保留选中 (exportselection=False): 官方 tk 版两个 Listbox
    共享 X selection, 点项目列表会把解释器选中顶掉 (隐藏小坑, 一并修掉)

注意: 不用 pygame —— SDL 窗口进程级污染中文输入法候选框 (记忆
sdl-window-contaminates-ime, pygame 版 LoomHubGUI 被弃用的原因)。

接入标准 (见 Loom/guiloader.py):
  - 文件名以 HubGUI.py 结尾 (本文件 NovaHubGUI.py ✓)
  - 头部 8 行内含标识 `# gui: loomhub` (仅文本解析, 不 import) ✓
  - 工厂 `build_gui(controller=None)` 返回视图实例 ✓
  - 视图类实现 IHubView 契约 (attach/run) ✓

启动验证: py -3.12 LoomHub.py → 界面下拉选 "星辉 Nova" → 重启.
"""
import os
import sys

import tkinter as tk

# GUI/ 目录的父目录 = LoomHub 目录 (hub_view_tk / hub_controller 所在)
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT)
sys.path.insert(0, os.path.join(PARENT, '..', 'Loom'))  # guiloader (设置.json 读写)

from hub_controller import HubController, IHubView

APP_TITLE = "LoomHub — 项目管理器"

# 配色: 延续 LoomHub 品牌橙 (230,150,60) + 深灰蓝底 (与 pygame 版同源色板)
C = {
    'bg':           '#1c1e22',   # 全局背景
    'panel':        '#262a30',   # 卡片面板
    'panel_border': '#464a54',   # 卡片描边
    'text':         '#dcdee4',   # 普通文字
    'dim':          '#8c8f98',   # 次要文字
    'accent':       '#e6963c',   # 品牌橙 (卡头彩条 / 列表焦点描边)
    'btn':          '#3c404a',   # 按钮底
    'btn_hover':    '#4c5260',   # 按钮悬停
    'btn_text':     '#e8eaee',   # 按钮文字
    'list_bg':      '#16181c',   # 列表底 (更深, 与卡片区分)
    'list_border':  '#34383f',   # 列表描边
    'select_bg':    '#3d4450',   # 选中行底
    'err':          '#ff7a7a',   # 错误消息
    'warn':         '#f0c85a',   # 警告 (系统 python 版本提示)
    'ok':           '#8fd694',   # 成功消息
}


class NovaHubView(IHubView):
    """LoomHub 深色卡片式视图 (IHubView 实现, tkinter).
    功能对齐官方 TkHubView; 显示层增强: 卡片布局 / 按钮 hover / 空态提示 /
    双击项目行打开 / 两列表选中互不干扰."""

    def __init__(self, controller=None):
        self.ctrl = controller or HubController()     # 业务/状态全走 controller
        self.attach(self.ctrl)
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1024x700")
        self.root.minsize(880, 620)
        self.root.configure(bg=C['bg'])
        # 字体 (雅黑 UI 优先, 与系统观感一致)
        self.f_title = ("Microsoft YaHei UI", 17, "bold")
        self.f_hdr = ("Microsoft YaHei UI", 11, "bold")
        self.f_body = ("Microsoft YaHei UI", 10)
        self.f_small = ("Microsoft YaHei UI", 9)
        self._last_rows = None   # 列表内容签名缓存 (签名不变不重建, 保选中)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def attach(self, controller):
        self.ctrl = controller

    # ---------------- 基础构件 ----------------
    def _button(self, parent, text, cmd, enabled=True):
        """扁平按钮 + 悬停高亮 (tkinter 无原生 hover, bind Enter/Leave 换底).
        禁用按钮灰色且无命令 (仍显示, 布局占位)."""
        if enabled:
            bg, fg, active = C['btn'], C['btn_text'], C['btn_hover']
        else:
            bg, fg, active, cmd = C['btn_disabled'], C['dim'], C['btn_disabled'], None
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=active, activeforeground=fg,
                      disabledforeground=C['dim'], relief='flat', bd=0,
                      padx=10, pady=4, font=self.f_body, cursor='hand2')
        if enabled:
            b.bind('<Enter>', lambda e, bb=b: bb.config(bg=C['btn_hover']))
            b.bind('<Leave>', lambda e, bb=b: bb.config(bg=C['btn']))
        return b

    def _btn_row(self, parent, pairs):
        """一行等宽按钮 (grid 均分): pairs = [(文本, 命令), ...]."""
        row = tk.Frame(parent, bg=C['panel'])
        row.pack(fill='x', padx=12, pady=3)
        for i, (text, cmd) in enumerate(pairs):
            row.columnconfigure(i, weight=1)
            self._button(row, text, cmd).grid(row=0, column=i, sticky='ew', padx=2)

    def _card(self, parent, title, note=""):
        """卡片容器: 深色面板 + 描边 + 卡头 (橙色竖条 + 标题 + 右侧小注).
        返回 (card, note_label) —— note_label 供 _refresh_lists 动态改字."""
        card = tk.Frame(parent, bg=C['panel'],
                        highlightbackground=C['panel_border'], highlightthickness=1)
        head = tk.Frame(card, bg=C['panel'])
        head.pack(fill='x', padx=12, pady=(10, 4))
        tk.Frame(head, width=3, height=14, bg=C['accent']).pack(side='left', pady=2)
        tk.Label(head, text=title, bg=C['panel'], fg=C['text'],
                 font=self.f_hdr).pack(side='left', padx=(6, 0))
        note_label = tk.Label(head, text=note, bg=C['panel'], fg=C['dim'],
                              font=self.f_small)
        note_label.pack(side='right')
        return card, note_label

    def _list_area(self, parent):
        """深色列表 + 原生滚动条. exportselection=False: 两个列表各保留选中.
        返回 (listbox, scrollbar)."""
        frame = tk.Frame(parent, bg=C['panel'])
        frame.pack(fill='both', expand=True, padx=12, pady=4)
        lb = tk.Listbox(frame, bg=C['list_bg'], fg=C['text'], bd=0, relief='flat',
                        highlightthickness=1, highlightbackground=C['list_border'],
                        highlightcolor=C['accent'],       # 获得焦点时橙描边
                        selectbackground=C['select_bg'], selectforeground='#ffffff',
                        font=self.f_body, activestyle='none',   # 去掉虚线激活框
                        exportselection=False, height=10)
        sb = tk.Scrollbar(frame, command=lb.yview, bg=C['btn'],
                          activebackground=C['btn_hover'], troughcolor=C['list_bg'],
                          bd=0, relief='flat', width=10)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        return lb, sb

    def _hint(self, parent, kind):
        """列表空态/提示行 (有数据时也给用途提示, 高度稳定不跳动)."""
        label = tk.Label(parent, text="", bg=C['panel'], fg=C['dim'], font=self.f_small)
        label.pack(fill='x', padx=14, pady=(0, 2), anchor='w')
        if kind == 'interp':
            self.interp_hint = label
        else:
            self.proj_hint = label

    def _note(self, parent, text):
        tk.Label(parent, text=text, bg=C['panel'], fg=C['dim'],
                 font=self.f_small).pack(fill='x', padx=14, pady=(0, 8), anchor='w')

    # ---------------- 界面构建 ----------------
    def _build(self):
        self._build_header()
        self._build_footer()          # 先占底部空间 (side=bottom): 保证 footer
                                      # 不被 expand 的 body 挤出窗口 (布局顺序坑)
        body = tk.Frame(self.root, bg=C['bg'])
        body.pack(side='top', fill='both', expand=True, padx=10, pady=6)
        self._build_card_interp(body)
        self._build_card_project(body)
        # 2026-08-27: GUI 内嵌命令行 (Hub-EAI 命令表; 与远程 Agent 同 dispatch)
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        import hub_console
        hub_console.attach_console(self.root, height=5)

    def _build_header(self):
        """顶栏: 橙竖条 + 大标题 + 副标题."""
        hd = tk.Frame(self.root, bg=C['bg'])
        hd.pack(fill='x', padx=16, pady=(12, 4))
        tk.Frame(hd, width=4, height=22, bg=C['accent']).pack(side='left', pady=2)
        txt = tk.Frame(hd, bg=C['bg'])
        txt.pack(side='left', padx=(8, 0))
        tk.Label(txt, text="LoomHub", bg=C['bg'], fg=C['text'],
                 font=self.f_title, anchor='w').pack(anchor='w')
        tk.Label(txt, text="项目管理 · 解释器管理 · 多版本共存",
                 bg=C['bg'], fg=C['dim'], font=self.f_small, anchor='w').pack(anchor='w')

    def _build_card_interp(self, parent):
        card, note = self._card(parent, "解释器", "")
        self.root_label = note        # 动态刷新 (改安装根后更新)
        card.pack(side='left', fill='both', expand=True, padx=6, pady=4)
        self._btn_row(card, [("扫描", self.ctrl.scan_interpreters),
                             ("导入目录", self.ctrl.import_interpreter_dir),
                             ("安装 .zip", self._install_zip)])
        self.interp_list, _ = self._list_area(card)
        self._hint(card, 'interp')
        self._btn_row(card, [("设为默认", self._set_default),
                             ("移除", self._remove_interp),
                             ("改安装根", self._change_root)])
        self._note(card, "说明: .zip 解压到安装根/<版本号>; 版本目录下须含 解释器.json")

    def _build_card_project(self, parent):
        card, _ = self._card(parent, "项目", "新建 = 系统保存对话框 (免输入项目名)")
        card.pack(side='left', fill='both', expand=True, padx=6, pady=4)
        self._btn_row(card, [("新建", self.ctrl.new_project),
                             ("导入", self.ctrl.import_project_dir),
                             ("打开", self._open_project),
                             ("移除", self._remove_project),
                             ("扫描", self.ctrl.scan_save_dir_projects)])
        self.proj_list, _ = self._list_area(card)
        self._hint(card, 'project')
        self.proj_list.bind('<Double-Button-1>', self._on_project_double)
        self._note(card, "打开项目 = 用默认解释器启动编辑器 (--open)")

    def _build_footer(self):
        """底栏: 界面切换 + open_py + 默认解释器状态 / 消息 + python 版本提示."""
        import guiloader
        self.guiloader = guiloader
        s = guiloader.load_settings('loomhub')
        foot = tk.Frame(self.root, bg=C['bg'])
        foot.pack(side='bottom', fill='x', padx=16, pady=(6, 12))
        tk.Frame(foot, height=1, bg=C['panel_border']).pack(fill='x', pady=(0, 6))
        # 行1: 界面下拉 + open_py 复选框 ... 右侧默认解释器
        row1 = tk.Frame(foot, bg=C['bg'])
        row1.pack(fill='x')
        tk.Label(row1, text="界面:", bg=C['bg'], fg=C['dim'],
                 font=self.f_small).pack(side='left')
        self.gui_var = tk.StringVar(value=s.get('gui', 'TkHubView'))
        m = tk.OptionMenu(row1, self.gui_var, *self._gui_choices(),
                          command=self._on_gui_change)
        m.config(bg=C['btn'], fg=C['btn_text'], activebackground=C['btn_hover'],
                 activeforeground=C['btn_text'], relief='flat', bd=0,
                 font=self.f_small, highlightthickness=0, cursor='hand2')
        menu = m['menu']
        menu.config(bg=C['panel'], fg=C['text'], activebackground=C['select_bg'],
                    activeforeground=C['text'], bd=0)
        m.pack(side='left', padx=(4, 16))
        self.open_py_var = tk.BooleanVar(value=s.get('open_py', True))
        # 复选框配色坑 (2026-08-21): 经典 tk Checkbutton 勾符号跟随 fg 颜色, 与
        # selectcolor 同亮度时勾隐身 (fg=#8c8f98 浅灰 + selectcolor=#8a8f9a 中灰
        # 同色系, 用户实测"勾不显示") —— fg 调亮 + selectcolor 调深, 亮勾深底
        tk.Checkbutton(row1, text="打开项目用 .py 源码（开发）",
                       variable=self.open_py_var, command=self._toggle_open_py,
                       bg=C['bg'], fg=C['text'], activebackground=C['bg'],
                       activeforeground=C['text'], selectcolor=C['panel'],
                       font=self.f_small, highlightthickness=0,
                       cursor='hand2').pack(side='left')
        self.interp_status = tk.Label(row1, text="默认解释器: (无)", bg=C['bg'],
                                      fg=C['dim'], font=self.f_small)
        self.interp_status.pack(side='right')
        # 行2: 动作消息 ... 右侧系统 python 版本提示
        row2 = tk.Frame(foot, bg=C['bg'])
        row2.pack(fill='x', pady=(4, 0))
        self.status = tk.Label(row2, text="", bg=C['bg'], fg=C['dim'],
                               font=self.f_body, anchor='w')
        self.status.pack(side='left')
        self.pywarn = tk.Label(row2, text="", bg=C['bg'], fg=C['warn'],
                               font=self.f_small, anchor='e')
        self.pywarn.pack(side='right')

    def _gui_choices(self):
        """界面可选列表: 官方 (TkHubView) + GUI\\ 下标识合法的自定义."""
        try:
            return [g['id'] for g in self.guiloader.scan_guis('loomhub')]
        except Exception:
            return ['TkHubView']

    # ---------------- 动作转发 (选中 -> controller) ----------------
    def _change_root(self):
        from tkinter import simpledialog
        v = simpledialog.askstring("改安装根", "安装根目录 (绝对路径):",
                                   initialvalue=self.ctrl.install_root,
                                   parent=self.root)
        if v is not None:
            self.ctrl.set_install_root(v)

    def _install_zip(self):
        from tkinter import simpledialog
        v = simpledialog.askstring("安装 .zip", "版本号 (如 1.0.0)",
                                   parent=self.root)
        if v:
            self.ctrl.do_install_zip(v)

    def _set_default(self):
        self.ctrl.set_default(self._selected(self.interp_list))

    def _remove_interp(self):
        self.ctrl.remove_interpreter(self._selected(self.interp_list))

    def _open_project(self):
        self.ctrl.open_project(self._selected(self.proj_list))

    def _remove_project(self):
        self.ctrl.remove_project(self._selected(self.proj_list))

    def _on_gui_change(self, gui_id):
        s = self.guiloader.load_settings('loomhub')
        s['gui'] = gui_id
        self.guiloader.save_settings('loomhub', s)
        self.ctrl.set_msg("已切换到「%s」，重启后生效" % gui_id)

    def _toggle_open_py(self):
        s = self.guiloader.load_settings('loomhub')
        s['open_py'] = self.open_py_var.get()
        self.guiloader.save_settings('loomhub', s)
        self.ctrl.set_msg("打开项目将优先用 %s 启动"
                          % (".py 源码" if s['open_py'] else ".exe 封装"))

    def _on_project_double(self, ev):
        """双击项目行 = 直接打开编辑器 (显示层增强; 双击空白不触发)."""
        if not self.ctrl.projects:
            return
        i = self.proj_list.nearest(ev.y)
        b = self.proj_list.bbox(i) if i >= 0 else None
        if b and b[1] <= ev.y <= b[1] + b[3]:
            self.ctrl.open_project(self.ctrl.projects[i])

    def _selected(self, listbox):
        sel = listbox.curselection()
        if not sel:
            return None
        i = sel[0]
        if listbox is self.interp_list:
            return self.ctrl.interpreters[i] if i < len(self.ctrl.interpreters) else None
        return self.ctrl.projects[i] if i < len(self.ctrl.projects) else None

    # ---------------- 刷新 ----------------
    def _refresh_lists(self):
        """列表 + 状态刷新. 关键 (2026-08-18): 列表内容签名不变时不重建 ——
        全清重建 (delete+insert) 会重置 Listbox 选中, 用户点击项目后 300ms 内
        被轮询重建 -> 选中瞬间丢失 (点击项目瞬间取消选中根因). 状态文本每轮更新."""
        ips = tuple((it.get('default'), it['name'], it['version'], it['kind'])
                    for it in self.ctrl.interpreters)
        pps = tuple((p['name'], os.path.basename(p['scene'])) for p in self.ctrl.projects)
        if (ips, pps) != self._last_rows:
            self._last_rows = (ips, pps)
            self.interp_list.delete(0, tk.END)
            for it in self.ctrl.interpreters:
                tag = "★ " if it.get('default') else ""
                self.interp_list.insert(tk.END, "%s%s  (v%s, %s)"
                                        % (tag, it['name'], it['version'], it['kind']))
            self.proj_list.delete(0, tk.END)
            for p in self.ctrl.projects:
                self.proj_list.insert(tk.END, "%s  —  %s"
                                     % (p['name'], os.path.basename(p['scene'])))
        # 卡头安装根 / 列表提示行 (有数据时也给用途提示, 高度稳定)
        self.root_label.config(text="默认安装根: %s" % self.ctrl.install_root)
        if self.ctrl.interpreters:
            self.interp_hint.config(text="★ = 默认解释器 · 滚轮可滚动")
        else:
            self.interp_hint.config(text="还没有解释器 — 扫描 / 导入目录 / 安装 .zip")
        if self.ctrl.projects:
            self.proj_hint.config(text="双击项目行 = 直接打开")
        else:
            self.proj_hint.config(text="还没有项目 — 新建 / 导入 / 扫描")
        # 默认解释器 / 系统 python 版本
        dflt = self.ctrl.default_interpreter()
        if dflt:
            self.interp_status.config(
                text="默认解释器: %s v%s (%s)" % (dflt['name'], dflt['version'],
                                                  dflt['kind']), fg=C['text'])
        else:
            self.interp_status.config(text="默认解释器: (无) — 请先扫描/导入/安装",
                                      fg=C['dim'])
        if self.ctrl.py_ver:
            self.pywarn.config(text="启动 .py 解释器使用系统默认 Python → %s"
                               % self.ctrl.py_ver)
        else:
            self.pywarn.config(text="未检测到系统默认 python (启动 .py 可能失败)")

    def run(self):
        """进入事件循环: 300ms 轮询刷新列表/状态 (与官方 TkHubView 同节奏)."""
        colors = {'ok': C['ok'], 'err': C['err'], 'dim': C['dim']}
        prefix = {'ok': '√ ', 'err': '✗ ', 'dim': '· '}   # 等级图标 (雅黑含 √/✗/·)

        def _poll():
            self._refresh_lists()
            msg = self.ctrl.msg
            self.status.config(
                text=(prefix.get(self.ctrl.msg_level, '') + msg) if msg else " ",
                fg=colors.get(self.ctrl.msg_level, C['text']))
            self.root.after(300, _poll)

        _poll()
        self.root.mainloop()


def build_gui(controller=None):
    """guiloader 调用的工厂: 返回深色卡片式视图实例."""
    return NovaHubView(controller)


if __name__ == "__main__":
    NovaHubView().run()
