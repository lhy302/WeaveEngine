# -*- coding: utf-8 -*-
"""
qt_play_stop_probe.py — P4 复现探针: 真 Qt 窗口 播放→停止 连转, 抓弹窗风暴 (2026-08-30)
================================================================================
用户实测: "按下播放后停止播放会弹出一堆小窗口然后快速关闭"。
本探针:
  - 真 LoomGUI + 跳台试炼场景 (真 GL 窗口), QTimer 驱动播放/停止循环
  - EnumWindows 轮询线程记录"新出现的顶层窗口" (类名/标题/PID) → 识别弹窗
  - sys.excepthook + faulthandler 抓异常/C 崩溃栈
  - 10 轮播放(2s)→停止, 观察有无弹窗/崩溃
运行 (必须子进程): py -3.12 tests\\_tmp\\qt_play_stop_probe.py
"""
import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import faulthandler
faulthandler.enable()

EXCEPTIONS = []


def _excepthook(t, v, tb):
    import traceback
    EXCEPTIONS.append((t, v))
    print("!! 未捕获异常:", t.__name__, v)
    traceback.print_exception(t, v, tb)


sys.excepthook = _excepthook

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


# ---------------- 顶层窗口观察线程 ----------------
class WindowWatcher:
    def __init__(self):
        self.seen = {}
        self.hits = []
        self._stop = False
        self._t = None
        self._OWN_MAIN = None

    _EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(self, hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        key = (title.value, cls.value, pid.value)
        if key not in self.seen:
            self.seen[key] = True
            self.hits.append((time.time(), hwnd, key))
            print("[弹窗观察] 新顶层窗口: title=%r class=%r pid=%d hwnd=%x"
                  % (key[0], key[1], key[2], hwnd))
        return True

    def start(self):
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while not self._stop:
            try:
                user32.EnumWindows(self._EnumProc(self._cb), 0)
            except Exception as e:
                print("[弹窗观察] EnumWindows 出错:", e)
            time.sleep(0.1)

    def stop(self):
        self._stop = True


def main():
    app = None
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtCore import QTimer
    import ui.loom_gui as qv
    import guiloader

    # 与 run_loom_gui 相同 QSurfaceFormat (samples=4/无 vsync) — 记忆铁律
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    scene = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jt_scene.json")
    if not os.path.exists(scene):
        print("!! 场景不存在:", scene)
        sys.exit(2)
    print("场景:", scene)

    win = qv.LoomGUI(scene_path=scene, width=1280, height=800)
    win.show()
    watcher = WindowWatcher()
    watcher.start()

    state = {"round": 0, "n": 10}
    t0 = time.time()

    def now():
        return time.time() - t0

    def _stat(e):
        try:
            me = next((m for m in e.models if m.name == '玩家'), None)
            if me is not None:
                return "玩家 y=%.3f vy=%.3f" % (me.position.y, me.rigidbody.velocity.y)
        except Exception as ex:
            return "stat-err %r" % ex
        return "no-player"

    def do_stop():
        e = win.editor
        if e is not None and e.is_playing:
            win._cmd_play()                      # 停止
        print("[playloop] #%d 停止 (%.2fs) bridge=%s %s active=%s"
              % (state["round"], now(),
                 "on" if (e is not None and e._phys_bridge is not None) else "off",
                 _stat(e),
                 e._phys_bridge.active_count if (e is not None and e._phys_bridge) else "-"))
        QTimer.singleShot(1200, do_play)

    def do_play():
        e = win.editor
        state["round"] += 1
        if state["round"] > state["n"]:
            finish()
            return
        if not e.is_playing:
            win._cmd_play()                      # 播放
        print("[playloop] #%d 播放 (%.2fs) bridge=%s %s active=%s"
              % (state["round"], now(),
                 "on" if e._phys_bridge is not None else "off",
                 _stat(e),
                 e._phys_bridge.active_count if e._phys_bridge is not None else "-"))
        QTimer.singleShot(500, do_play_mid)

    def do_play_mid():
        e = win.editor
        print("[playloop] #%d 播放中 (%.2fs) %s active=%s"
              % (state["round"], now(), _stat(e),
                 e._phys_bridge.active_count if e._phys_bridge is not None else "-"))
        QTimer.singleShot(1500, do_stop)

    def finish():
        watcher.stop()
        print("=== 播放-停止 循环结束: %d 轮, 未捕获异常=%d, 弹窗数=%d, 耗时 %.1fs ==="
              % (state["n"], len(EXCEPTIONS), len(watcher.hits), now()))
        for t, v in EXCEPTIONS:
            print("  EXC:", t.__name__, v)
        win._suppress_confirm = True
        win.close()
        QTimer.singleShot(1500, app.quit)

    QTimer.singleShot(2500, do_play)             # 等 GLViewport 初始化 EditorApp
    QTimer.singleShot(200000, app.quit)          # 兜底 200s
    app.exec()
    print("探针退出. 异常=%d 弹窗=%d" % (len(EXCEPTIONS), len(watcher.hits)))
    if EXCEPTIONS:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
