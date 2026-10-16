# -*- coding: utf-8 -*-
"""
qt_eai_ui_probe.py — 真 Qt 窗口 EAI 端到端探针 (2026-08-27/28)
================================================================================
用户指令: "全部可 Agent 命令行操作自动化测试, 同时测试命令行本身有没有 BUG"。
test_eai_real.py 跑的是"逼真"的 EditorApp(真 GPU 窗口, 缺 Qt 宿主面板);
本探针补最后一段: 真 LoomGUI + 真命令行坞, 命令经控制台派发到真编辑器,
并断言 **GUI 面板跟着命令行命令刷新** (层级树/检查器/截图) +
**quit 脏场景自决断关闭, 不弹模态框卡死** (用户 2026-08-28 实测报告)。

注意: 真窗口必须子进程 + 超时 (记忆 fullscreen-fake-fullscreen-safe 教训)。
运行: py -3.12 tests\_tmp\qt_eai_ui_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

import ui.loom_gui as qv

FAILS = []
HARD_TIMEOUT = 9000      # 兜底关窗时间; quit 成功会在远早于此退出


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def tree_names(win):
    out = []
    for i in range(win.hierarchy.topLevelItemCount()):
        _collect(win.hierarchy.topLevelItem(i), out)
    return out


def _collect(item, out):
    out.append(item.text(0))
    for i in range(item.childCount()):
        _collect(item.child(i), out)


def run_on_win(win, line):
    """走命令行坞真实路径: 输入框 setText + run_line (与回车键同一方法)."""
    win.console.entry.setText(line)
    return win.console.run_line(line)


def main():
    app = QApplication(sys.argv)
    win = qv.LoomGUI(scene_path=None, width=1280, height=800)
    win.show()
    # HARD_TIMEOUT 兜底: 走到 = quit 没有自己关窗 (真失败)
    QTimer.singleShot(HARD_TIMEOUT, win.close)

    def step_status():
        r = run_on_win(win, "status")
        check("控制台 status -> ok 且含场景摘要", r and r['ok']
              and 'models' in r['result'] and len(r['result']['models']) >= 1,
              r.get('result', {}).get('models'))
        import agent_commands as ac
        check("命令行坞执行记录进日志环 (远程 Agent 可见)",
              any('status' in t for _, _, t in ac.LOG_RING))
        QTimer.singleShot(400, step_add_cube)

    def step_add_cube():
        run_on_win(win, "object_add type=cube")
        n = len(win.editor.models)
        r = run_on_win(win, "object_list")
        check("控制台 object_add -> 真场景物体数 +1", n >= 4 and r['ok'], (n, r))
        QTimer.singleShot(150, step_check_tree)

    def step_check_tree():
        names = tree_names(win)
        check("层级树已重建并含新立方体 (命令与 GUI 同义)",
              any('立方体' in nm for nm in names), names[-5:])
        run_on_win(win, "set_transform x=3 y=2 z=1")
        QTimer.singleShot(150, step_check_insp)

    def step_check_insp():
        sb = win._spins.get('pos.X')
        val = sb.value() if sb is not None else None
        check("检查器位置 X 行同步为 3.000 (spinbox 回写)", val is not None
              and abs(float(val) - 3.0) < 1e-3, val)
        QTimer.singleShot(150, step_f12)

    def step_f12():
        win.viewport.setFocus()
        win._btn_console.setChecked(False)   # 显式起点
        ev_down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F12,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(QApplication.focusWidget() or win, ev_down)
        QTimer.singleShot(50, lambda: check("F12 打开命令行坞 (状态栏按钮联动)",
                                            win.console.isVisible()
                                            and win._btn_console.isChecked()))
        QTimer.singleShot(150, step_screenshot)

    def step_screenshot():
        r = run_on_win(win, "screenshot file=%s" % os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'qt_eai_ui.png'))
        check("真 Qt 视口 grab 截图成功", r and r['ok'], r)
        QTimer.singleShot(300, step_quit_dirty)

    def step_quit_dirty():
        # 用户报告场景: 场景脏 (一路在改) -> 控制台手敲 quit (无 save=) ->
        # 命令层自决断 (有文件保存/无文件丢弃) 并挂 _suppress_confirm,
        # closeEvent 不再弹"是否保存"模态框, 窗口自行关闭 -> 事件循环退出.
        r = run_on_win(win, "quit after=0")
        check("quit 脏场景 (无 save=) -> 决断自关, 不弹框卡死",
              r and r['ok'] and r['result'].get('quitting') is True
              and r['result'].get('resolved') in ('save', 'discard'), r)
        # 窗口关闭后 app.exec 自动返回; 若 500ms 后还活着 = quit 没生效
        QTimer.singleShot(500, lambda: check("窗口已自行关闭 (事件循环退出)",
                                             not win.isVisible()))

    QTimer.singleShot(800, step_status)
    app.exec()
    if FAILS:
        print("探针结果: FAIL", FAILS)
        sys.exit(1)
    print("探针结果: ALL PASS")


if __name__ == "__main__":
    main()
