# -*- coding: utf-8 -*-
"""smoke_white_screen_fix.py — 白屏修复冒烟（P0 窗口 geometry + P1 readback fallback）

覆盖:
  A) P0-1 窗口尺寸钳制：LoomGUI.__init__ 有 QGuiApplication.primaryScreen 逻辑
  B) P0-2 show 增强：run_loom_gui 有 showNormal/raise_/activateWindow
  C) P0-3 LoomHub 隐藏 console：hub_commands/hub_controller 有 CREATE_NO_WINDOW
  D) P1 GL 诊断日志：GLViewport.paintGL 有 LOOM_GL_DEBUG 分支
  E) P1 RemoteViewport：类存在 + 关键方法齐全
  F) P1 --remote-mode 选择逻辑：LoomGUI.__init__ 有 _remote 分支
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ A) P0-1 窗口钳制 ============
gui_src = open(os.path.join(BASE, 'ui', 'loom_gui.py'), 'r', encoding='utf-8').read()
check('A1) LoomGUI 有 primaryScreen 钳制',
      'QGuiApplication.primaryScreen' in gui_src
      or 'self.resize(clamp_w, clamp_h)' in gui_src)
check('A2) 有 clamp_w / clamp_h 逻辑',
      'clamp_w' in gui_src and 'clamp_h' in gui_src)


# ============ B) P0-2 show 增强 ============
check('B1) show 后有 showNormal',
      'win.showNormal()' in gui_src)
check('B2) show 后有 raise_/activateWindow',
      'win.raise_()' in gui_src and 'win.activateWindow()' in gui_src)
check('B3) 有屏幕外强制移回',
      'g.x() < -1000' in gui_src or 'g.y() < -1000' in gui_src)


# ============ C) P0-3 console 隐藏 ============
hub_cmd_src = open(os.path.join(BASE, '..', 'LoomHub', 'hub_commands.py'),
                   'r', encoding='utf-8').read()
check('C1) hub_commands 有 CREATE_NO_WINDOW',
      'CREATE_NO_WINDOW' in hub_cmd_src)
hub_ctrl_src = open(os.path.join(BASE, '..', 'LoomHub', 'hub_controller.py'),
                    'r', encoding='utf-8').read()
check('C2) hub_controller 有 CREATE_NO_WINDOW',
      'CREATE_NO_WINDOW' in hub_ctrl_src)


# ============ D) P1 GL 诊断日志 ============
check('D1) GLViewport 有 LOOM_GL_DEBUG 分支',
      'LOOM_GL_DEBUG' in gui_src)
check('D2) 有 [GLDBG] 输出',
      '[GLDBG]' in gui_src)


# ============ E) P1 RemoteViewport ============
tree = ast.parse(gui_src)
remote_class = None
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'RemoteViewport':
        remote_class = node
        break
check('E1) RemoteViewport 类存在', remote_class is not None)

if remote_class is not None:
    methods = {n.name for n in ast.walk(remote_class)
               if isinstance(n, ast.FunctionDef)}
    required = [
        '_init_offscreen_gl', '_init_editor', '_tick',
        'makeCurrent', 'key_pressed_array',
        'mousePressEvent', 'mouseMoveEvent', 'mouseReleaseEvent',
        'wheelEvent', 'keyPressEvent', 'keyReleaseEvent',
        'set_mouse_locked',
    ]
    for m in required:
        check('E2) RemoteViewport 有 %s' % m, m in methods)


# ============ F) P1 --remote-mode 选择逻辑 ============
check('F1) 有 --remote-mode 判断',
      "'--remote-mode'" in gui_src)
check('F2) 有 LOOM_REMOTE_MODE 环境变量',
      'LOOM_REMOTE_MODE' in gui_src)
check('F3) 有 _remote 分支选择 RemoteViewport',
      'if _remote:' in gui_src and 'RemoteViewport(self' in gui_src)


# ============ G) import 可用性 ============
try:
    import ui.loom_gui as lg
    check('G1) loom_gui 可 import', True)
    check('G2) RemoteViewport 可从模块访问',
          hasattr(lg, 'RemoteViewport'))
except Exception as e:
    check('G1) loom_gui 可 import', False, repr(e))


print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
