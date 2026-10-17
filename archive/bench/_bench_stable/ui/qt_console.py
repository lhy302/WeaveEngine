# -*- coding: utf-8 -*-
"""
ui/qt_console.py — Loom 编辑器内嵌命令行坞 (2026-08-27, EAI P2①)
================================================================================
与 LoomHub 侧 `hub_console.py` 同款思路: GUI 保留, 命令行能力集成进 GUI ——
编辑器主窗口底部挂一个 QDockWidget "命令行", 输入命令即执行; 与远程 EAI
(HTTP /cmd) 走**同一张命令表** agent_commands._COMMANDS (单一事实:
工具栏按钮 / GUI 控制台 / 远程 Agent 三条路同一条命令)。

用法 (LoomGUI 构建末尾):
    from ui import qt_console
    self.console = qt_console.ConsoleDock(self)
    self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console)

输入语法: <命令> [key=value ...]
    示例:  status
           object_add type=sphere
           camera_look yaw=45 pitch=-20
    空行回车 / help / ? -> 命令清单。
    ↑ ↓ = 历史命令 (会话内)。

输出区两类内容:
  ①命令回显与 JSON 结果 (自己敲的命令);
  ②引擎日志环 agent_commands.LOG_RING 的增量 (远程 Agent 下的命令、
    错误、插件事件都在这里可见) —— 500ms 轮询拉取, 与 /logs?after=N 同源。
"""
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton,
)

import agent_commands as ac


def parse_line(text):
    """'cmd key=value k=10' -> (cmd, {key: value}); 裸词并入 args['_'] 列表.

    与 hub_console.parse_line 同语法 (两端控制台输入手感一致)。
    值一律是字符串, 由各命令自己 float()/int() 转换 (命令层本来就要容错
    远程 JSON 的字符串数值)。
    """
    parts = text.split()
    if not parts:
        return '', {}
    args = {}
    for p in parts[1:]:
        if '=' in p:
            k, v = p.split('=', 1)
            args[k.strip()] = v.strip()
        else:
            args.setdefault('_', []).append(p)
    return parts[0], args


def help_text():
    """命令清单 (名字 + 用途), 取自命令表本身 —— 新增命令自动出现在帮助里."""
    names = ac.command_names()
    lines = ["用法: 命令名 key=value ...   （与远程 EAI 命令表同一份）",
             "命令 (%d 条):" % len(names)]
    for k in sorted(names):
        lines.append("  %-18s %s" % (k, names[k]))
    return "\n".join(lines)


class ConsoleDock(QDockWidget):
    """编辑器底部命令行坞 (默认隐藏, 状态栏 [命令行] 按钮开关)."""

    def __init__(self, win):
        super().__init__("命令行（EAI 命令表）", win)
        self.win = win
        self._history = []          # 会话内历史命令 (↑↓ 翻)
        self._hist_pos = 0
        self._log_seq = ac.last_log_seq()   # 只显示挂载之后的新日志

        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea |
                             Qt.DockWidgetArea.TopDockWidgetArea)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(4)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)      # 与日志环同量级, 防无限增长
        self.output.setFont(QFont("Consolas", 9))
        self.output.setStyleSheet(
            "QPlainTextEdit{background:#1e1e1e;color:#d6d6d6;border:1px solid #3a3a3a;}")
        lay.addWidget(self.output, 1)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addWidget(QLabel(">"))
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("输入命令, 回车执行；help 看清单；↑↓ 翻历史")
        self.entry.returnPressed.connect(self.run_current)
        rl.addWidget(self.entry, 1)
        for text, fn in (("执行", self.run_current),
                         ("帮助", lambda: self.write(help_text())),
                         ("清空", self.output.clear)):
            b = QPushButton(text)
            b.setFixedWidth(52)
            b.clicked.connect(fn)
            rl.addWidget(b)
        lay.addWidget(row)
        self.setWidget(body)

        # ↑↓ 历史: 装在输入框上 (QLineEdit 自身不处理方向键翻历史)
        self.entry.installEventFilter(self)

        # 日志泵: 引擎日志环增量 -> 输出区 (远程 Agent 的命令也可见)
        self._pump = QTimer(self)
        self._pump.timeout.connect(self._pump_logs)
        self._pump.start(500)

        self.write("Loom 命令行已就绪 —— 输入 help 查看 %d 条命令。"
                   % len(ac.command_names()))

    # ---------------- 输出 ----------------
    def write(self, text):
        self.output.appendPlainText(str(text))
        self.output.verticalScrollBar().setValue(
            self.output.verticalScrollBar().maximum())

    def _pump_logs(self):
        """拉取日志环增量 (与远程 GET /logs?after=N 同源, 不重复不丢行)."""
        try:
            rows = ac.log_since(self._log_seq)
        except Exception:
            return
        for seq, ts, text in rows:
            self._log_seq = max(self._log_seq, seq)
            self.write("[%s] %s" % (ts, text))

    # ---------------- 执行 ----------------
    def run_current(self):
        text = self.entry.text().strip()
        self.entry.clear()
        self.run_line(text)

    def run_line(self, text):
        """执行一行输入 (测试可直接调). 返回 dispatch 结果 dict 或 None."""
        if not text:
            self.write(help_text())
            return None
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._hist_pos = len(self._history)
        cmd, args = parse_line(text)
        if cmd in ('help', '?'):
            self.write(help_text())
            return None
        if cmd == 'clear':
            self.output.clear()
            return None
        self.write("> " + text)
        # dispatch 自身已捕获命令异常 (返回 ok=False), 这里只兜住派发层意外
        try:
            r = ac.dispatch(cmd, args, self.win)
        except Exception as e:
            self.write("执行异常: %r" % e)
            return None
        self.write(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return r

    # ---------------- 历史 (↑↓) ----------------
    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.entry and ev.type() == QEvent.Type.KeyPress \
                and self._history:
            k = ev.key()
            if k == Qt.Key.Key_Up:
                self._hist_pos = max(0, self._hist_pos - 1)
                self.entry.setText(self._history[self._hist_pos])
                return True
            if k == Qt.Key.Key_Down:
                self._hist_pos = min(len(self._history), self._hist_pos + 1)
                self.entry.setText('' if self._hist_pos >= len(self._history)
                                   else self._history[self._hist_pos])
                return True
        return super().eventFilter(obj, ev)
