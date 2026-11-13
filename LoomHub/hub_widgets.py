# -*- coding: utf-8 -*-
"""hub_widgets.py — LoomHub 通用小控件（2026-11-13）。

为什么单独成文件：
  · `hub_view_tk.py`（主窗口）与 `hub_install_ui.py`（安装对话框）都要显示
    「长度不可控的目录文本」（安装根、Hub 安装位置）；
  · 用户目录安装根（C:\\Users\\<user>\\AppData\\Local\\Programs\\Loom）比
    Program Files 长得多，直接贴进 Label 会把布局撑宽、把对话框按钮挤没；
  · 统一策略（人类裁决 2026-11-13）：**定长显示 + 中间省略（middle ellipsis），
    溢出时悬停用浮窗（overflow tooltip）显示完整路径，点击复制**。

提供的接口：
  elide_middle(text, max_chars)           字符级中间省略（给纯文本/提示用）
  class Tooltip                            通用浮窗（overrideredirect Toplevel）
  class ElidedPathLabel(tk.Label)           定长 + 中间省略 + 悬停浮窗 + 点击复制
"""
import tkinter as tk
import tkinter.font as tkfont


def elide_middle(text, max_chars=52):
    """字符级中间省略：保留头尾，中间用…（长路径的常规做法）。

    只用于**显示**；真实路径请另存。字符数而非像素，适合提示文本/日志式展示。
    """
    s = str(text or "")
    if len(s) <= max_chars:
        return s
    head = max(6, (max_chars - 1) // 2)
    tail = max(6, max_chars - 1 - head)
    return s[:head] + "…" + s[-tail:]


class Tooltip:
    """极简浮窗：把 overrideredirect 的 Toplevel 贴在鼠标右下。

    不用 ttk/tix 的 balloon，避免额外依赖与主题差异。
    """

    def __init__(self, widget, text_provider):
        self.widget = widget
        self.text_provider = text_provider   # callable -> str（每次显示时取，支持动态）
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, event=None):
        text = self.text_provider()
        if not text or self.tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            tk.Label(tip, text=text, justify="left",
                     bg="#ffffe0", fg="#333", relief="solid", bd=1,
                     padx=6, pady=3,
                     font=("Microsoft YaHei UI", 9)).pack()
            tip.geometry("+%d+%d" % (x, y))
            self.tip = tip
        except Exception:
            self.tip = None

    def _hide(self, event=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


class ElidedPathLabel(tk.Label):
    """定长路径标签：超长时**中间省略**，悬停显示完整路径，点击复制。

    用法：
        lb = ElidedPathLabel(parent, prefix="默认安装根: ", fg="#666")
        lb.pack(fill="x")
        lb.set_path(r"C:\\Users\\x\\AppData\\Local\\Programs\\Loom")

    实现要点：
      · 像素级测量（tkfont.measure）后从中间裁，直到放得下 → 不撑宽布局；
      · 只有**真的被省略**时才挂浮窗（overflow tooltip），没省略不打扰；
      · 点击把**完整路径**写进剪贴板，浮窗临时变成「已复制」。
    """

    def __init__(self, master, prefix="", max_chars=64, **kw):
        self._prefix = prefix
        self._full = ""
        self._max_chars = max_chars
        self._copied = False
        kw.setdefault("anchor", "w")
        kw.setdefault("justify", "left")
        super().__init__(master, text=prefix, **kw)
        self._tip = Tooltip(self, self._tooltip_text)
        self.bind("<Button-1>", self._copy, add="+")
        self.bind("<Configure>", lambda e: self._render(), add="+")

    # ---- 对外 ----
    def set_path(self, path):
        self._full = str(path or "")
        self._copied = False
        self._render()

    def full_path(self):
        return self._full

    # ---- 内部 ----
    def _tooltip_text(self):
        if self._copied:
            return "已复制到剪贴板：" + self._full
        return self._full

    def _copy(self, event=None):
        if not self._full:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._full)
            self._copied = True
        except Exception:
            pass

    def _fits(self, text, avail_px):
        try:
            f = tkfont.Font(font=self["font"])
            return f.measure(text) <= avail_px
        except Exception:
            return len(text) <= self._max_chars

    def _render(self):
        """按当前控件宽度重算显示文本（中间省略）。"""
        full = self._full
        if not full:
            super().config(text=self._prefix)
            return
        avail = self.winfo_width()
        if avail <= 1:
            avail = 380   # 首次 Configure 前给个保守值，后续事件会重算
        prefix_px = 0
        try:
            prefix_px = tkfont.Font(font=self["font"]).measure(self._prefix)
        except Exception:
            prefix_px = len(self._prefix) * 7
        avail_for_path = max(60, avail - prefix_px - 8)
        if self._fits(full, avail_for_path):
            super().config(text=self._prefix + full)
            return
        # 中间省略：保留头尾，二分收敛到放得下的最长形式
        lo, hi = 8, len(full)
        best = "…"
        while lo <= hi:
            keep = (lo + hi) // 2
            head = max(4, keep // 2)
            tail = max(4, keep - head)
            cand = full[:head] + "…" + full[-tail:]
            if self._fits(cand, avail_for_path):
                best = cand
                lo = keep + 1
            else:
                hi = keep - 1
        super().config(text=self._prefix + best)
