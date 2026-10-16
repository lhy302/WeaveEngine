# -*- coding: utf-8 -*-
# gui: loomhub
# gui-name: 绿意 ColorHub
# gui-desc: 绿色系自定义配色视图 (测试 GUI 更换, 逻辑与官方 TkHubView 完全一致)
"""
ColorHubGUI.py — LoomHub 自定义配色视图 (IHubView 实现, 绿色系)
=============================================================
用于测试 LoomHub 可插拔 GUI 更换功能: 继承官方 TkHubView, 只整体换配色
(绿色系, 与官方默认灰蓝配色一眼可区分), 布局与业务逻辑全部继承不变.

接入标准 (见 Loom/guiloader.py):
  - 文件名以 HubGUI.py 结尾 (本文件 ColorHubGUI.py ✓)
  - 头部前 8 行内含标识 `# gui: loomhub` (仅文本解析, 不 import) ✓
  - 提供工厂 `build_gui(controller=None)` 返回视图实例 ✓
  - 视图类实现 IHubView 契约 (通过继承 TkHubView 获得 attach/run) ✓

启动验证: py -3.12 LoomHub.py  → 设置面板 "界面" 下拉选 "绿意 ColorHub" → 重启.
"""
import os
import sys

import tkinter as tk

# GUI/ 目录的父目录 = LoomHub 目录 (hub_view_tk / hub_controller 所在)
PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT)
sys.path.insert(0, os.path.join(PARENT, '..', 'Loom'))  # guiloader (设置.json 读写)

from hub_view_tk import TkHubView  # 官方默认 tkinter 视图 (业务逻辑 / 布局来源)


# 绿色系配色 (与官方默认灰蓝明显不同). 键名即用途.
PALETTE = {
    'bg':         '#0f241a',   # 全局背景 (root / Frame / Label / LabelFrame) 深绿
    'border':     '#3dcc82',   # 边框 / 高亮描边 (亮绿)
    'title_fg':   '#7be8a4',   # LabelFrame 标题 / 强调文字
    'fg':         '#dff5e8',   # 普通文字
    'dim':        '#82b596',   # 次要 / 中性文字
    'ok':         '#6fe9a3',   # 成功消息
    'err':        '#ff9191',   # 错误消息 (保留红色以醒目)
    'btn':        '#1e5c3b',   # 按钮背景
    'btn_fg':     '#eafff2',   # 按钮文字
    'btn_active': '#2f8a58',   # 按钮按下 / 悬停
    'list_bg':    '#091d13',   # Listbox 背景 (更暗, 区分列表区)
    'list_fg':    '#cbf2dc',   # Listbox 文字
    'select_bg':  '#33c578',   # Listbox 选中背景
    'select_fg':  '#04150c',   # Listbox 选中文字
    'scroll':     '#1e5c3b',   # 滚动条
    'trough':     '#091d13',   # 滚动条凹槽
}


class ColorHubView(TkHubView):
    """绿色系自定义配色视图: 布局与业务逻辑完全继承 TkHubView, 仅整体换配色."""

    PALETTE = PALETTE

    # ---------------- 仅覆盖配色相关钩子, 其余方法全部继承 ----------------
    def _build(self):
        super()._build()          # 复用官方全部布局 / 控件 / 事件绑定 (功能不变)
        self._apply_theme()       # 构建完成后整体重新上色

    def _apply_theme(self):
        self._restyle(self.root)

    def _restyle(self, w):
        """递归遍历控件树, 按控件类型套用绿色系配色."""
        P = self.PALETTE
        cls = w.winfo_class().lower()
        try:
            if cls in ('tk', 'frame'):
                w.configure(bg=P['bg'])
            elif cls == 'labelframe':
                # 标题色 fg + 亮绿描边 (tkinter 经典 Labelframe 无直接边框色,
                # 用 highlight 描边实现可见的绿色边框)
                w.configure(bg=P['bg'], fg=P['title_fg'],
                            highlightbackground=P['border'],
                            highlightcolor=P['border'],
                            highlightthickness=1, bd=2)
            elif cls == 'label':
                w.configure(bg=P['bg'], fg=P['dim'])
            elif cls == 'button':
                w.configure(bg=P['btn'], fg=P['btn_fg'],
                            activebackground=P['btn_active'],
                            activeforeground=P['btn_fg'],
                            highlightbackground=P['border'],
                            highlightcolor=P['border'],
                            highlightthickness=1, relief='raised')
            elif cls == 'listbox':
                w.configure(bg=P['list_bg'], fg=P['list_fg'],
                            selectbackground=P['select_bg'],
                            selectforeground=P['select_fg'],
                            highlightbackground=P['border'],
                            highlightcolor=P['border'],
                            highlightthickness=1, relief='flat')
            elif cls == 'scrollbar':
                w.configure(bg=P['scroll'], activebackground=P['btn_active'],
                            troughcolor=P['trough'], highlightthickness=0)
            elif cls == 'menubutton':   # OptionMenu (界面切换下拉)
                w.configure(bg=P['btn'], fg=P['btn_fg'],
                            activebackground=P['btn_active'],
                            activeforeground=P['btn_fg'],
                            highlightbackground=P['border'],
                            highlightthickness=1)
                m = w['menu']
                if m:
                    m.configure(bg=P['bg'], fg=P['fg'],
                                activebackground=P['select_bg'],
                                activeforeground=P['select_fg'])
            elif cls == 'checkbutton':
                w.configure(bg=P['bg'], fg=P['dim'],
                            activebackground=P['bg'],
                            activeforeground=P['fg'],
                            selectcolor=P['bg'])
        except tk.TclError:
            pass
        for child in w.winfo_children():
            self._restyle(child)

    def run(self):
        """进入事件循环. 覆盖只因官方在 _refresh_lists/run 里硬编码了状态文字
        颜色 (#222/#666/#c00), 这里按绿色系覆盖, 其余轮询 / 刷新逻辑一致."""
        P = self.PALETTE

        def _poll():
            self._refresh_lists()   # 继承: 刷新列表文本 + 安装根 / 默认解释器文本
            # 覆盖官方硬编码的状态文字颜色
            if self.ctrl.default_interpreter():
                self.interp_status.config(fg=P['ok'])
            else:
                self.interp_status.config(fg=P['dim'])
            self.status.config(text=self.ctrl.msg or " ",
                               fg=P.get(self.ctrl.msg_level, P['fg']))
            self.root.after(300, _poll)

        _poll()
        self.root.mainloop()


def build_gui(controller=None):
    """guiloader 调用的工厂: 返回绿色配色视图实例."""
    return ColorHubView(controller)


if __name__ == "__main__":
    ColorHubView().run()
