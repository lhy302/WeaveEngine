# -*- coding: utf-8 -*-
"""真实运行时 GUI 探针 (2026-08-20): 设置对话框插件挂载区 —— 每插件行 [加载][卸载]
两按钮. 流程: 起 Qt 编辑器窗口 → 打开设置对话框 (exec 替换为无阻塞) → 断言两插件
已加载 → 点 blink_demo 的[卸载] → 断言脚本 blink 从 SCRIPTS 消失、行变 ○ 未加载
→ 点[加载] → 断言脚本回来、行变 ● 已加载. 全无头不需要截图 (程序化读控件)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))      # ...\Loom\tests\_tmp
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))      # 上两层 = Loom\
sys.path.insert(0, LOOM_DIR)

import plugin_loader
from scripts import SCRIPTS

# 真实插件目录 (探针在 tests\_tmp 下, 程序目录解析会错位 → 直接钉到 Loom\plugins)
REAL_PLUGINS = os.path.join(LOOM_DIR, 'plugins')
plugin_loader.plugin_dir = lambda program='loom', base=None: REAL_PLUGINS

from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QLabel, QPushButton

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


import ui.loom_gui as qv
from ui.loom_gui import LoomGUI

app = QApplication(sys.argv)
win = LoomGUI(scene_path=None, width=900, height=640)
win.show()

# 打开设置对话框 (exec 改无阻塞, 保持对话框存活)
orig_exec = qv.QDialog.exec


def fake_exec(self):
    self.show()
    return 0


qv.QDialog.exec = fake_exec
win._cmd_settings()

dlg = None
for w in app.topLevelWidgets():
    if w.windowTitle() == "设置":
        dlg = w
        break
check("设置对话框已打开", dlg is not None)


def find_plug_list():
    for lw in dlg.findChildren(QListWidget):
        if lw.count() > 0 and lw.itemWidget(lw.item(0)) is not None:
            return lw
    return None


def dump_rows():
    lw = find_plug_list()
    out = []
    if lw is None:
        return out
    for i in range(lw.count()):
        w = lw.itemWidget(lw.item(i))
        if w is None:
            out.append(([], {}))
            continue
        labels = [x.text() for x in w.findChildren(QLabel)]
        btns = {}
        for b in w.findChildren(QPushButton):
            btns[b.text()] = b
        out.append((labels, btns))
    return out


rows = dump_rows()
texts = [" ".join(l) for l, _ in rows]
check("插件区列出两个已加载插件 (blink_demo + color_cycle)",
      any('blink_demo' in t for t in texts) and any('color_cycle' in t for t in texts),
      texts)
check("两行都是 ● 已加载 且 [加载] 禁用",
      all('已加载' in t for t in texts) and
      all(not r[1]['加载'].isEnabled() and r[1]['卸载'].isEnabled() for r in rows),
      texts)

# ---- 卸载 blink_demo ----
blink_row = [r for r in rows if r[0] and any('blink_demo' in l for l in r[0])][0]
blink_row[1]['卸载'].click()
app.processEvents()
check("点[卸载]后脚本 blink 从 SCRIPTS 移除", 'blink' not in SCRIPTS,
      "blink in SCRIPTS: %s" % ('blink' in SCRIPTS))
rows2 = dump_rows()
texts2 = [" ".join(l) for l, _ in rows2]
check("行变为 ○ 未加载 且 [加载] 可用",
      any('未加载' in t and 'blink_demo' in t for t in texts2),
      texts2)
check("color_cycle 不受卸载影响 (仍已加载)",
      any('已加载' in t and 'color_cycle' in t for t in texts2), texts2)

# ---- 重新加载 blink_demo ----
row2 = [r for r in rows2 if r[0] and any('blink_demo' in l for l in r[0])][0]
row2[1]['加载'].click()
app.processEvents()
check("点[加载]后脚本 blink 回到 SCRIPTS", 'blink' in SCRIPTS)
rows3 = dump_rows()
texts3 = [" ".join(l) for l, _ in rows3]
check("行变回 ● 已加载",
      any('已加载' in t and 'blink_demo' in t for t in texts3), texts3)

# ---- 坐标输出 (供 GUI 自动化脚本/DSH 模拟使用) ----
from PySide6.QtWidgets import QToolButton
for sb in win.statusBar().findChildren(QToolButton):
    if sb.text() == "设置":
        c = sb.mapToGlobal(sb.rect().center())
        print("COORD 设置按钮:", c.x(), c.y())
for i, (labels, btns) in enumerate(dump_rows()):
    if labels and any('blink_demo' in l for l in labels):
        for name in ('加载', '卸载'):
            b = btns.get(name)
            if b:
                c = b.mapToGlobal(b.rect().center())
                print("COORD blink_demo[%s]:" % name, c.x(), c.y())

dlg.close()
win.close()
qv.QDialog.exec = orig_exec
print("总结果:", "ALL PASS ✅" if not FAILS else "FAIL ❌ " + str(FAILS))
sys.exit(1 if FAILS else 0)
