# -*- coding: utf-8 -*-
"""EAI 可视化 GUI 侧 (B/E, 2026-11-07).

锁住 ui/loom_gui.py 对 AgentService 的四个钩子与步进模式 UI:
  1) _agent_progress(cmd,args,done,total) -> 状态栏 'AI: ... (3/10)';
  2) _agent_busy(True) -> 工具栏红点可见 + 状态栏文字变色;
  3) _agent_after_command() -> viewport.update() + repaint() 各一次;
  4) [下一步] 按钮仅 step_mode 可见, 点击调用 service.resume_step().

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
    """AgentService 契约最小桩: step_mode / paused / resume_step()."""

    def __init__(self, step_mode=False):
        self.step_mode = bool(step_mode)
        self.paused = False
        self.resume_calls = 0
        self.pace_ms = 120.0

    def resume_step(self):
        self.resume_calls += 1
        self.paused = False

    def progress(self):
        return (0, 0)

    def last_info(self):
        return ('', True, 0.0)


def _make_win(step_mode=False):
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
    win._bind_agent_service(_StubService(step_mode=step_mode))
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

# ---------------- 4) 步进模式按钮 ----------------
win_norm = _make_win(step_mode=False)
_APP.processEvents()
check('非步进模式 [下一步] 按钮隐藏', not win_norm._act_agent_step.isVisible())
check('非步进模式 等待提示隐藏', not win_norm._lbl_agent_step_hint.isVisible())

win_step = _make_win(step_mode=True)
_APP.processEvents()
check('step_mode=True [下一步] 按钮可见',
      win_step._act_agent_step.isVisible()
      and win_step._btn_agent_step.isVisible(), win_step._btn_agent_step.text())
win_step._agent_service.paused = True
win_step._update_agent_step_ui()
_APP.processEvents()
check('步进模式 paused 时显示 AI 等待下一步',
      win_step._lbl_agent_step_hint.isVisible()
      and '等待下一步' in win_step._lbl_agent_step_hint.text(),
      win_step._lbl_agent_step_hint.text())
win_step._btn_agent_step.click()
_APP.processEvents()
check('点击 [下一步] 调用 resume_step', win_step._agent_service.resume_calls == 1,
      win_step._agent_service.resume_calls)
check('resume_step 后等待提示隐藏', not win_step._lbl_agent_step_hint.isVisible())

# ---------------- 5) 契约属性齐全 ----------------
check('LoomGUI 实现 _agent_progress/_agent_busy/_agent_after_command',
      all(hasattr(loom_gui.LoomGUI, n) for n in
          ('_agent_progress', '_agent_busy', '_agent_after_command')))

for w in (win, win_norm, win_step):
    w.hide()
    w.deleteLater()
_APP.processEvents()

print('=' * 60)
print('agent UI indicator: %s' % ('ALL PASS' if ok else 'FAILED'))
sys.exit(0 if ok else 1)
