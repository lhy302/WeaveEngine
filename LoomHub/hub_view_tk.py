# -*- coding: utf-8 -*-
"""
hub_view_tk.py — LoomHub 默认视图 (IHubView 实现, tkinter)
============================================================
2026-08-17 起为 LoomHub 默认视图 (原 pygame LoomHubGUI 因 SDL 窗口进程级污染
中文输入法候选框被弃用, 见记忆 sdl-window-contaminates-ime; pygame 视图保留
在 LoomHubGUI.py 供 --ui pygame 参考).

用同一个 HubController, 证明换 UI 只换实现类、业务逻辑 (hub_controller /
hub_config / hub_install) 完全不动. 功能与 pygame 视图对齐:
  解释器: 扫描 / 导入目录 / 安装 .zip / 设为默认 / 移除 / 改安装根
  项目  : 新建 / 导入 / 打开 / 移除 / 扫描
  设置  : 界面切换 (gui, 重启生效) / 打开项目用 .py/.exe (open_py)
  状态  : 默认解释器 / 系统 python 版本 / 动作消息

启动: py -3.12 LoomHub.py        (默认本视图)
      py -3.12 LoomHub.py --ui pygame   (遗留 pygame 视图, 仅参考)

实现约定 (见 hub_controller.py 的 IHubView 契约):
  - attach(controller): 绑定控制器
  - run(): 进入 tkinter 事件循环
  - 全部读写走 controller; 本文件 不 import hub_config 做业务.
  - 输入框用 tkinter.simpledialog (纯 tk 进程 IME 正常, 无 pygame 污染源).
"""
import os
import sys

import tkinter as tk

HUB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HUB_DIR)
sys.path.insert(0, os.path.join(HUB_DIR, '..', 'Loom'))  # guiloader (设置.json 读写)

from hub_controller import HubController, IHubView
import hub_install_ui
import hub_github as _gh

APP_TITLE = "LoomHub — 项目管理器"


class TkHubView(IHubView):
    def __init__(self, controller=None):
        self.ctrl = controller or HubController()
        self.attach(self.ctrl)
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("900x560")
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self._last_rows = None   # 列表内容签名缓存 (签名不变不重建, 保 Listbox 选中)

    def attach(self, controller):
        self.ctrl = controller

    # ---------------- 界面构建 ----------------
    def _build(self):
        # 左: 解释器
        left = tk.LabelFrame(self.root, text="解释器 (Loom)", padx=6, pady=6)
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        # 安装根 (动态刷新: _refresh_lists 更新文本)
        self.root_label = tk.Label(left, text="默认安装根: %s" % self.ctrl.install_root,
                                   anchor="w", fg="#666")
        self.root_label.pack(fill="x")
        self._btn_row(left, [("改安装根", self._change_root)])
        # 列表 + 原生滚动条 (标准配对: listbox.yscrollcommand=sb.set, sb.command=listbox.yview)
        frame = tk.Frame(left)
        frame.pack(fill="both", expand=True)
        self.interp_list = tk.Listbox(frame, height=13)
        self.interp_list.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(frame, command=self.interp_list.yview)
        sb.pack(side="right", fill="y")
        self.interp_list.config(yscrollcommand=sb.set)
        self._btn_row(left, [("扫描", self.ctrl.scan_interpreters),
                             ("导入目录", self.ctrl.import_interpreter_dir)])
        self._btn_row(left, [("安装 .zip", self._install_zip),
                             ("从 GitHub 安装", self._github_install)])
        self._btn_row(left, [("设为默认", self._set_default),
                             ("移除", self._remove_interp)])

        # 右: 项目
        right = tk.LabelFrame(self.root, text="项目", padx=6, pady=6)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        frame = tk.Frame(right)
        frame.pack(fill="both", expand=True)
        self.proj_list = tk.Listbox(frame, height=13)
        self.proj_list.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(frame, command=self.proj_list.yview)
        sb.pack(side="right", fill="y")
        self.proj_list.config(yscrollcommand=sb.set)
        self._btn_row(right, [("新建", self.ctrl.new_project),
                              ("导入", self.ctrl.import_project_dir),
                              ("打开", self._open_project)])
        self._btn_row(right, [("移除", self._remove_project),
                              ("扫描", self.ctrl.scan_save_dir_projects)])

        # 底部设置行: 界面切换 + 打开项目 .py/.exe
        import guiloader
        self.guiloader = guiloader
        s = guiloader.load_settings('loomhub')
        set_row = tk.Frame(self.root)
        set_row.pack(fill="x", padx=8)
        tk.Label(set_row, text="界面:", fg="#666").pack(side="left")
        self.gui_var = tk.StringVar(value=s.get('gui', 'TkHubView'))
        tk.OptionMenu(set_row, self.gui_var, *self._gui_choices(),
                      command=self._on_gui_change).pack(side="left")
        self.open_py_var = tk.BooleanVar(value=s.get('open_py', True))

        # 打开项目 .py/.exe: 单独一行, 位于 "界面" 下拉与 "默认解释器" 之间 (2026-08-20)
        tk.Checkbutton(self.root, text="打开项目用 .py 源码（开发）",
                       variable=self.open_py_var,
                       command=self._toggle_open_py).pack(fill="x", padx=8)

        # 底部状态: 默认解释器 + 动作消息
        self.interp_status = tk.Label(self.root, text="默认解释器: (无)",
                                      anchor="w", fg="#666")
        self.interp_status.pack(fill="x", padx=8)
        self.status = tk.Label(self.root, text="", anchor="w",
                               font=("Microsoft YaHei UI", 9), fg="#666")
        self.status.pack(fill="x", padx=8, pady=(0, 4))
        # 2026-08-27: GUI 内嵌命令行 (Hub-EAI 命令表, 输入即执行;
        # 与远程 Agent/HTTP 同一 dispatch)
        import hub_console
        hub_console.attach_console(self.root)

    def _btn_row(self, parent, pairs):
        """一行等宽按钮: pairs = [(文本, 命令), ...]"""
        row = tk.Frame(parent)
        row.pack(fill="x", pady=3)
        for text, cmd in pairs:
            tk.Button(row, text=text, command=cmd, relief="groove").pack(
                side="left", padx=2, fill="x", expand=True)

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
        """2026-10-19: 选 zip → 预览元数据 + 安装位置 → 确认安装."""
        import filedialog
        zp = filedialog.open_file(
            "选择 Loom 解释器安装包", initial_dir=None,
            filter_str="解释器安装包 (*.zip)\0*.zip\0所有文件 (*.*)\0*.*\0")
        if not zp:
            self.ctrl.set_msg("已取消安装", 'dim')
            return
        self._install_zip_path(zp)

    def _install_zip_path(self, zip_path):
        """统一入口：从任意来源（对话框/拖拽/GitHub 下载完）拿到 zip 后调这里."""
        hub_install_ui.show_zip_preview(
            self.root, self.ctrl, zip_path,
            on_success=lambda installed_dir: self.ctrl.set_msg(
                "安装完成: %s" % installed_dir))

    def _github_install(self):
        """从 GitHub Release 在线安装."""
        hub_install_ui.show_github_install(
            self.root, self.ctrl,
            on_success=lambda installed_dir: self.ctrl.set_msg(
                "安装完成: %s" % installed_dir))

    def _set_default(self):
        self.ctrl.set_default(self._selected(self.interp_list))

    def _remove_interp(self):
        """2026-10-19: 移除三选一（仅移除登记 / 彻底删除 / 取消）."""
        interp = self._selected(self.interp_list)
        if not interp:
            self.ctrl.set_msg("请先在列表中选择一个解释器", 'dim')
            return
        hub_install_ui.show_remove_interp(self.root, self.ctrl, interp)

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
        # 安装根 / 默认解释器 状态 (pygame 视图也实时显示, 保持一致)
        self.root_label.config(text="默认安装根: %s" % self.ctrl.install_root)
        dflt = self.ctrl.default_interpreter()
        if dflt:
            self.interp_status.config(
                text="默认解释器: %s v%s (%s)" % (dflt['name'], dflt['version'],
                                                dflt['kind']), fg="#222")
        else:
            self.interp_status.config(text="默认解释器: (无) — 请先扫描/导入/安装",
                                      fg="#666")

    def _close_splash(self):
        """2026-10-19: 关闭 PyInstaller --splash 启动图.
        pyi_splash 模块只在 PyInstaller 打包后存在（源码运行时 import 会失败，
        忽略即可）。必须在 mainloop 前调用，否则 splash 会一直盖在主窗口上。"""
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

    def run(self):
        colors = {'ok': '#222', 'err': '#c00', 'dim': '#666'}

        def _poll():
            self._refresh_lists()
            self.status.config(text=self.ctrl.msg or " ",
                               fg=colors.get(self.ctrl.msg_level, '#222'))
            self.root.after(300, _poll)

        # 主窗口即将进入事件循环 → 关闭启动 splash
        self._close_splash()
        _poll()
        self.root.mainloop()


if __name__ == "__main__":
    TkHubView().run()
