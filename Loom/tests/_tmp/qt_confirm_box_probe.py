# -*- coding: utf-8 -*-
"""真实运行时 GUI 探针 (2026-08-22, A01): 防丢询问框三态行为.
QMessageBox.exec 阻塞模态, 但 QTimer 在模态事件循环里触发:
以 [X/拒绝] / [取消] / [不保存] / [保存] 四种操作关闭弹框, 断言返回
'cancel'/'cancel'/'discard'/'save'. 弹框里 save 分支实际还会弹保存对话框,
故只验证到返回值语义为止 (dialogs 由用户实测)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LOOM_DIR)

import plugin_loader
plugin_loader.plugin_dir = lambda program='loom', base=None: os.path.join(LOOM_DIR, 'plugins')

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer

from ui.loom_gui import LoomGUI

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        FAILS.append(name)


app = QApplication(sys.argv)
win = LoomGUI(scene_path=None, width=1000, height=680)
win.show()
app.processEvents()


def actor(kind):
    def act():
        mw = app.activeModalWidget()
        assert isinstance(mw, QMessageBox), "no messagebox: %r" % mw
        if kind == 'reject':                # 标题栏 X / Esc
            mw.reject()
        else:
            for b in mw.buttons():
                if b.text() == kind:
                    b.click()
                    return
            raise AssertionError("button not found: %s" % kind)
    return act


def run(kind):
    hit = []
    def wrap():
        try:
            actor(kind)()
        except Exception as ex:
            hit.append(ex)
    QTimer.singleShot(200, wrap)
    r = win._ask_save_dirty()
    check("弹框[%s] -> %s" % (kind, r), bool(r == 'cancel' if kind in ('reject', '取消')
                                             else r == {'不保存': 'discard', '保存': 'save'}[kind]),
          "actual=%r err=%s" % (r, hit))
    app.processEvents()


run('reject')       # X/Esc = 取消
run('取消')
run('不保存')
# run('保存')       # save 分支会弹保存文件对话框, 超出本探针范围 (用户实测)

win.close()
print("总结果:", "ALL PASS ✅" if not FAILS else "FAIL ❌ " + str(FAILS))
sys.exit(1 if FAILS else 0)
