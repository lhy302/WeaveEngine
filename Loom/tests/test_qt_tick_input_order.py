# -*- coding: utf-8 -*-

"""Qt 编辑器 tick 输入顺序回归 (2026-11-07 P1-5).

背景: ui/loom_gui.py 的 _on_tick 原本在 e._update_camera() **之前**
清空 e.pressed / e.released。

  _on_tick():
      e.pressed.clear()      <-- 事件回调攒的"本帧新按下"被抹掉
      e.released.clear()
      e.mouse_pos = ...
      e._update_camera()     <-- 内部 _dispatch_ui_mouse() 读 pressed/released

editor._update_camera() 第一件事就是 _dispatch_ui_mouse(), 也就是 UI 树的
唯一输入入口。清空在前 = UI 每帧都收到空集合 -> Qt 编辑器里 HUD 按钮/滑条/
输入框全部点不动 (pygame 主线自己轮询鼠标, 所以只有 Qt 版本坏)。

本测试是源码级顺序守卫 (不启动 Qt, 可无头跑): 断言 _on_tick 里两个 clear()
都出现在 e._update_camera() 之后, 且 _update_camera 确实会分发 UI 输入。
回退到旧顺序 -> 立刻 FAIL。
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


import io
import os
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _read(rel):
    with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
        return f.read()


def _def_body(src, name):
    """取模块里 `def name(` 到下一个同级 def 之前的源码 (含缩进整体保留)."""
    lines = src.splitlines()
    start = None
    indent = 0
    for i, ln in enumerate(lines):
        m = re.match(r'^(\s*)def\s+' + re.escape(name) + r'\s*\(', ln)
        if m:
            start = i
            indent = len(m.group(1))
            break
    if start is None:
        return None
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            break
        out.append(ln)
    return '\n'.join(out)


gui_src = _read(os.path.join('ui', 'loom_gui.py'))
tick = _def_body(gui_src, '_on_tick')
check('ui/loom_gui.py 有 _on_tick', tick is not None)

if tick:
    p_clear = tick.find('e.pressed.clear()')
    r_clear = tick.find('e.released.clear()')
    cam = tick.find('e._update_camera()')
    check('_on_tick 里仍清 pressed (没被顺手删掉)', p_clear >= 0, p_clear)
    check('_on_tick 里仍清 released (没被顺手删掉)', r_clear >= 0, r_clear)
    check('_on_tick 里调用 e._update_camera()', cam >= 0, cam)
    check('pressed.clear() 在 _update_camera() 之后 (UI 先拿输入)',
          cam >= 0 and p_clear > cam, 'clear@%d cam@%d' % (p_clear, cam))
    check('released.clear() 在 _update_camera() 之后',
          cam >= 0 and r_clear > cam, 'clear@%d cam@%d' % (r_clear, cam))

# RemoteViewport._tick (远程/虚拟显示 readback 模式) 必须与 GLViewport 对齐:
# 原来它既不调 _update_camera(), 也不清 pressed/released —— 远程模式下相机与
# UI 树收不到任何输入, 且 pressed 只增不减 (按下一次永远'按下态')。
rtick = _def_body(gui_src, '_tick')
check('ui/loom_gui.py 有 RemoteViewport._tick', rtick is not None)
if rtick:
    r_cam = rtick.find('e._update_camera()')
    r_p = rtick.find('e.pressed.clear()')
    r_r = rtick.find('e.released.clear()')
    check('RemoteViewport._tick 调 e._update_camera() (相机/UI 输入入口)',
          r_cam >= 0, r_cam)
    check('RemoteViewport._tick 清 pressed (与 _on_tick 同时机)', r_p >= 0, r_p)
    check('RemoteViewport._tick 清 released', r_r >= 0, r_r)
    check('RemoteViewport._tick: clear 在 _update_camera() 之后',
          r_cam >= 0 and r_p > r_cam and r_r > r_cam,
          'cam@%d p@%d r@%d' % (r_cam, r_p, r_r))
    check('RemoteViewport._tick 读后清 mouse_wheel',
          'e.mouse_wheel = 0' in rtick)

# 顺序修复只有在 _update_camera 内部真的分发 UI 输入时才有意义 —— 锁住这条依赖。
ed_src = _read('editor.py')
uc = _def_body(ed_src, '_update_camera')
check('editor._update_camera 存在', uc is not None)
if uc:
    check('editor._update_camera 内部调用 _dispatch_ui_mouse (UI 唯一输入入口)',
          '_dispatch_ui_mouse()' in uc)

disp = _def_body(ed_src, '_dispatch_ui_mouse')
check('editor._dispatch_ui_mouse 存在', disp is not None)
if disp:
    check('_dispatch_ui_mouse 读 self.pressed', 'pressed' in disp)
    check('_dispatch_ui_mouse 读 self.released', 'released' in disp)
    check('_dispatch_ui_mouse 调 ui.dispatch_mouse', 'dispatch_mouse' in disp)

# 语法可用性: 两个文件都能正常 compile (防止注释搬动弄坏缩进)
for rel in (os.path.join('ui', 'loom_gui.py'), 'editor.py', 'loom_ui.py',
            'agent_commands.py', 'loom_mcp.py'):
    try:
        compile(_read(rel), rel, 'exec')
        _fine = True
    except SyntaxError as e:
        _fine = False
    check('%s 语法可编译' % rel, _fine)

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
