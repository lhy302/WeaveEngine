# -*- coding: utf-8 -*-
"""EAI 可视化 GUI 侧 (B, 2026-11-07).

锁住 ui/loom_gui.py 对 AgentService 的三个钩子:
  1) _agent_progress(cmd,args,done,total) -> 状态栏 'AI: ... (3/10)';
  2) _agent_busy(True) -> 工具栏红点可见 + 状态栏文字变色;
  3) _agent_after_command() -> viewport.update() + repaint() 各一次;

Qt 走 offscreen; LoomGUI 用 __new__ + QMainWindow.__init__ 跳过真实 GL 视口,
只构建工具栏/状态栏 (不初始化 GLViewport)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

from PySide6.QtWidgets import QApplication, QMainWindow   # noqa: E402

_APP = QApplication.instance() or QApplication([])

from ui import loom_gui                                   # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


class _FakeViewport:
    """只记录 update/repaint 次数 (不碰 GL)."""

    def __init__(self):
        self.updates = 0
        self.repaints = 0

    def update(self):
        self.updates += 1

    def repaint(self):
        self.repaints += 1


class _StubService:
    """AgentService 契约最小桩: progress / last_info."""

    def __init__(self):
        self.pace_ms = 120.0

    def progress(self):
        return (0, 0)

    def last_info(self):
        return ('', True, 0.0)


def _make_win():
    """真实 QMainWindow 骨架 + 真实工具栏/状态栏, 无 GL 视口/无 editor."""
    win = loom_gui.LoomGUI.__new__(loom_gui.LoomGUI)
    QMainWindow.__init__(win)
    win.editor = None
    win.viewport = _FakeViewport()
    win._agent_service = None
    win._agent_status_active = False
    win._agent_busy_active = False
    win._agent_idle_token = 0
    win._build_toolbar()
    win._build_statusbar()
    # 复刻真机顺序: 构造 -> 绑定 -> show() (--agent 分支在 win.show() 之前绑定)
    win._bind_agent_service(_StubService())
    win.show()                       # offscreen 窗口, 只用于可见性断言
    _APP.processEvents()             # 处理 _bind 的 singleShot(0) 首拍重同步
    return win


# ---------------- 1) 状态栏进度 ----------------
win = _make_win()
svc = win._agent_service
win._agent_progress('add_cube', {'name': '方块', 'pos': [1, 2, 3]}, 3, 10)
txt = win.statusBar().currentMessage()
check('_agent_progress 状态栏含 AI: cmd', 'AI: add_cube' in txt, txt)
check('_agent_progress 状态栏含 (3/10)', '(3/10)' in txt, txt)
check('参数摘要用 k=v 拼接', 'name=方块' in txt, txt)

long_sum = loom_gui.LoomGUI._agent_args_summary({'path': 'x' * 200})
check('参数摘要 <= 40 字且截断', len(long_sum) <= 40 and long_sum.endswith('…'),
      (len(long_sum), long_sum))

# 空闲恢复: 手动触发 1.5s 定时器回调 (editor=None -> 默认空文本)
win._agent_idle(win._agent_idle_token)
check('空闲后状态栏恢复默认文本', win.statusBar().currentMessage() == '',
      repr(win.statusBar().currentMessage()))

# ---------------- 2) 忙态红点 + 变色 ----------------
win._agent_busy(True)
_APP.processEvents()
check('_agent_busy(True) 工具栏红点可见',
      win._act_agent_busy.isVisible() and win._lbl_agent_busy.isVisible(),
      win._lbl_agent_busy.text())
check('_agent_busy(True) 状态栏文字变色',
      '#e06c75' in win.statusBar().styleSheet(), win.statusBar().styleSheet())
win._agent_busy(False)
_APP.processEvents()
check('_agent_busy(False) 红点隐藏', not win._act_agent_busy.isVisible())
check('_agent_busy(False) 状态栏颜色复位',
      '#e06c75' not in win.statusBar().styleSheet(), win.statusBar().styleSheet())

# ---------------- 3) 每条命令后强制重绘 ----------------
u0, r0 = win.viewport.updates, win.viewport.repaints
win._agent_after_command()
check('_agent_after_command 调用了 viewport.update',
      win.viewport.updates == u0 + 1, win.viewport.updates)
check('_agent_after_command 调用了 viewport.repaint',
      win.viewport.repaints == r0 + 1, win.viewport.repaints)

# ---------------- 4) 契约属性齐全 ----------------
check('LoomGUI 实现 _agent_progress/_agent_busy/_agent_after_command',
      all(hasattr(loom_gui.LoomGUI, n) for n in
          ('_agent_progress', '_agent_busy', '_agent_after_command')))

# ---------------- 5) U-02: 窗口销毁后定时器不反复抛 ----------------
print('=== 5) 窗口销毁后 _agent_idle 静默 + 单次告警 (U-02) ===')
import contextlib
import io


def _raise_deleted(*a, **k):
    raise RuntimeError('Internal C++ object already deleted')


# 真 LoomGUI 实例 + 把 QWidget 入口换成"已销毁"行为 (等价于 deleteLater 之后)
dead = _make_win()
dead.statusBar = _raise_deleted
dead._refresh_status = _raise_deleted
dead._agent_status_active = True
_tok = dead._agent_idle_token          # 用当前令牌, 否则 _agent_idle 会当成作废回调早退
err = io.StringIO()
raised = None
with contextlib.redirect_stderr(err):
    try:
        loom_gui.LoomGUI._agent_idle(dead, _tok)   # 第一次: 告警一次
        loom_gui.LoomGUI._agent_idle(dead, _tok)   # 第二次: 静默
    except Exception as e:                          # 修前: 这里会捕到 RuntimeError
        raised = e
check('U-02 窗口销毁后 _agent_idle 不抛异常', raised is None, repr(raised))
check('U-02 标记窗口已死 (之后静默停表)', getattr(dead, '_agent_gui_dead', None) is True,
      getattr(dead, '_agent_gui_dead', None))
warn = err.getvalue()
check('U-02 只告警一次且带原因',
      warn.count('GUI 状态栏不可用') == 1 and 'RuntimeError' in warn, warn.strip()[:90])
tok0 = dead._agent_idle_token
tok_raised = None
with contextlib.redirect_stderr(io.StringIO()):
    try:
        loom_gui.LoomGUI._agent_progress(dead, 'object_add', {}, 1, 1)
    except Exception as e:
        tok_raised = e
check('U-02 窗口已死后 _agent_progress 不再碰 QWidget',
      tok_raised is None and dead._agent_idle_token == tok0,
      repr(tok_raised))
check('U-02 窗口已死后不再排新的空闲定时器', dead._agent_idle_token == tok0,
      dead._agent_idle_token)

for w in (win, dead):
    w.hide()
    w.deleteLater()
_APP.processEvents()

print('=' * 60)
print('agent UI indicator: %s' % ('ALL PASS' if ok else 'FAILED'))
sys.exit(0 if ok else 1)
