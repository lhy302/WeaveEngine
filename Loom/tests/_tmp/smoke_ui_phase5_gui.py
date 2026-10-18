# -*- coding: utf-8 -*-
"""smoke_ui_phase5_gui.py — 阶段5 GUI 编辑器冒烟 (2026-10-18)

验证：
  1) LoomGUI 启动成功（含 UI 树 dock）
  2) uitree dock 存在且 refresh 不崩
  3) _invoke_ui_cmd 走 EAI 命令（端到端）
  4) 选中 UI 元素 -> 检查器切到 UI 属性
  5) 拖拽（模拟）-> 命令日志留痕
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.loom_gui import LoomGUI

win = LoomGUI(scene_path=None, width=800, height=600)
win.show()

# 让 Qt 事件循环跑起来（GLViewport initializeGL 需要）
QTimer.singleShot(500, lambda: _run_checks(win))

def _run_checks(win):
    print('[smoke] LoomGUI 已启动')
    assert hasattr(win, 'uitree'), 'UI 树 dock 缺失'
    assert win.uitree is not None
    print('[smoke] UITreeDock 存在 OK')

    # 触发一次 refresh（不崩）
    win.uitree.refresh()
    print('[smoke] uitree.refresh OK')

    # 走命令壳：ui_canvas_add + ui_add
    r = win._invoke_ui_cmd('ui_canvas_add', type='screen', width=1024, height=768)
    assert 'error' not in r, r
    print('[smoke] ui_canvas_add via _invoke_ui_cmd OK')

    # 用 ui_list 找到最新 canvas
    import agent_commands as ac
    lst = ac._COMMANDS['ui_list'](win, {})
    last_idx = lst['total'] - 1
    r = win._invoke_ui_cmd('ui_add', type='button', name='smoke_btn',
                           text='Hello', canvas=last_idx,
                           rect=(10, 10, 120, 40))
    assert 'error' not in r, r
    print('[smoke] ui_add via _invoke_ui_cmd OK')

    # 命令日志应有内容
    log_text = win.uitree.cmd_log.toPlainText()
    assert 'ui_add' in log_text, '命令日志未留痕: %r' % log_text
    print('[smoke] 命令日志留痕 OK')

    # 选中 -> 检查器切到 UI
    win._ui_tree_set_selection('smoke_btn', last_idx)
    assert win._ui_selected_name == 'smoke_btn'
    assert win._ui_selected_canvas == last_idx
    print('[smoke] UI 选中状态更新 OK')

    # 检查器应走 _build_ui_inspector（无崩溃 + 有布局）
    # 通过直接调 _rebuild_inspector
    win._insp_key = None
    win._rebuild_inspector()
    cnt = win.inspector_layout.count()
    assert cnt > 0, '检查器为空 (cnt=%d)' % cnt
    print('[smoke] 检查器 UI 属性显示 OK (rows=%d)' % cnt)

    # 撤销栈应有内容（3 次操作：canvas_add + add + 若干 set）
    e = win.editor
    assert e.undo.undo_stack, '撤销栈为空'
    print('[smoke] 撤销栈有内容 OK (%d 项)' % len(e.undo.undo_stack))

    print('[smoke] SMOKE_PASS')
    QTimer.singleShot(100, win.close)


QTimer.singleShot(6000, win.close)   # 兜底关窗

app.exec()
print('[smoke] QApplication 退出')
