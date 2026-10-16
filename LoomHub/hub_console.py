# -*- coding: utf-8 -*-
"""
hub_console.py — LoomHub GUI 内嵌命令行控制台 (2026-08-27)
====================================================================
用户要求: GUI 保留, 命令行功能全部集成进 GUI —— 视图底部挂一个
"命令行"区 (输入行 + 输出区), 输入命令即执行; 与远程 HUB-EAI 命令
走同一 dispatch (单一事实: GUI / 远程 Agent / 控制台 三条路同一条命令).

用法 (视图构建末尾):
    import hub_console
    hub_console.attach_console(self.root)
  挂在根窗口 bottom, 两视图 (TkHubView / NovaHubGUI) 共用.

输入语法: <命令> [key=value ...]   (示例: interpreter_list / project_create path=D:\\a\\b.json)
输入为空回车: 显示命令清单 help.
"""
import json
import os
import sys
import tkinter as tk

try:
    import hub_commands as hc
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import hub_commands as hc

_HELP = ("用法: 命令名 key=value ...   （与 Hub-EAI 远程命令同表）\n"
         "命令: %s" % ' / '.join(sorted(hc.command_names())))


def parse_line(text):
    """'cmd key=value k=10' -> (cmd, {key: value}); 裸词并入 args['_']列表."""
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
    if '_' in args and not args['_']:
        del args['_']
    return parts[0], args


def attach_console(parent, height=8, label='命令行（Hub-EAI 命令表）'):
    """在 tk 窗口底部挂载控制台 (输入行 + 只读输出区). 返回 (entry, text).
    2026-08-28: ↑/↓ 翻历史 (与 Loom 编辑器命令行坞同手感)."""
    console = tk.Frame(parent)
    console.pack(side='bottom', fill='x', padx=8, pady=(2, 6), before=None)

    head = tk.Frame(console)
    head.pack(fill='x')
    tk.Label(head, text=label, fg='#666').pack(side='left')

    out = tk.Text(console, height=height, relief='sunken', wrap='word')
    out.pack(fill='both', expand=False)
    out.tag_configure('cmd', foreground='#6576a0')

    row = tk.Frame(console)
    row.pack(fill='x', pady=(3, 0))
    tk.Label(row, text='>', fg='#666').pack(side='left')
    entry = tk.Entry(row)
    entry.pack(side='left', fill='x', expand=True)
    tk.Button(row, text='执行', relief='groove',
              command=lambda: _run()).pack(side='right')
    tk.Button(row, text='帮助', relief='groove',
              command=lambda: _print(_HELP)).pack(side='right', padx=2)

    history = []           # 会话内历史命令 (↑↓ 翻)
    hist_pos = [0]

    def _print(text):
        out.config(state='normal')
        out.insert('end', text + '\n')
        out.see('end')
        out.config(state='disabled')

    def _run():
        text = entry.get().strip()
        entry.delete(0, 'end')
        if not text:
            return _print(_HELP)
        if not history or history[-1] != text:
            history.append(text)
        hist_pos[0] = len(history)
        cmd, args = parse_line(text)
        if cmd in ('help', '?'):
            return _print(_HELP)
        _print('> %s' % text)
        try:
            r = hc.dispatch(cmd, args)
            _print(json.dumps(r, ensure_ascii=False, indent=2))
        except Exception as e:
            _print('执行异常: %r' % e)

    def _history_move(delta):
        if not history:
            return
        hist_pos[0] = max(0, min(len(history), hist_pos[0] + delta))
        entry.delete(0, 'end')
        if hist_pos[0] < len(history):
            entry.insert(0, history[hist_pos[0]])

    entry.bind('<Return>', lambda ev: _run())
    entry.bind('<Up>', lambda ev: (_history_move(-1), 'break')[1])
    entry.bind('<Down>', lambda ev: (_history_move(1), 'break')[1])
    entry.focus_set()
    return entry, out
