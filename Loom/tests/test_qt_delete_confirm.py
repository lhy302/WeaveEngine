# -*- coding: utf-8 -*-

"""Qt 编辑器删除确认 (Q3=A 配套, 2026-11-07).

背景: F8 在 editor.py 的删除路径加了钩子
  self._confirm_delete_callback = None      # (model, n_children) -> bool
  delete_object(): n>0 时调用它, 返回 False 就不删
但 Qt 编辑器 (ui/loom_gui.py) 从来没注入过它 —— getattr 拿到 None, 于是
Qt 里删一个带子物体的父物体 = **静默连整棵子树删掉**, 没有任何提示。

本测试锁三件事:
  1) LoomGUI.attach() 真的把 _ask_delete_confirm 注入到 editor 上 (回归点);
  2) N>0: 弹框文案含子物体数, 取消 -> 场景不变, 确认 -> 连子树删;
  3) N=0: 文案是普通删除确认; 无子物体删除不被确认框卡住。

QMessageBox 用 monkeypatch 顶掉 (模态框无法在自动化里点), Qt 走 offscreen。
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
# 无头 Qt: 不需要真显示器 (本测试不会真的 exec() 模态框, QMessageBox 被顶掉)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

from PySide6.QtWidgets import QApplication, QMessageBox   # noqa: E402

_APP = QApplication.instance() or QApplication([])

from editor import EditorApp                             # noqa: E402
from engine import GameObject                            # noqa: E402
import undo as U                                          # noqa: E402
from ui import loom_gui                                   # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


# ---------------- 假 QMessageBox (记录调用 + 可控答案) ----------------
class _FakeMB:
    StandardButton = QMessageBox.StandardButton
    calls = []
    answer = QMessageBox.StandardButton.Yes

    @classmethod
    def question(cls, parent=None, title='', text='', buttons=None, default=None):
        cls.calls.append({'parent': parent, 'title': title, 'text': text,
                          'buttons': buttons, 'default': default})
        return cls.answer


# ---------------- editor 最小替身 (与 F8 的 test_remove_subtree_semantics 同款) ----------------
def _editor():
    ed = EditorApp.__new__(EditorApp)
    ed.models = []
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.is_playing = False
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.current_model_index = 0
    ed._struct_gen = 0
    ed._build_gpu = lambda m: None
    ed.undo = U.UndoManager()
    return ed


def _add(ed, name, pos=(0.0, 0.0, 0.0)):
    m = GameObject(None, pos, (0.0, 0.0, 0.0), name=name)
    ed.models.append(m)
    ed._bump_struct()
    return m


# ---------------- LoomGUI 最小替身: 只跑 attach() 的注入逻辑 ----------------
def _view():
    """LoomGUI.__new__ 不跑 __init__ (那要真 GL 窗口): attach() 只用 Python 属性,
    所以纯 Python 侧可用; QMessageBox 已被顶掉, 不会碰 C++ 模态框。"""
    v = loom_gui.LoomGUI.__new__(loom_gui.LoomGUI)
    v.editor = None
    return v


def _inject(ed):
    v = _view()
    loom_gui.LoomGUI.attach(v, ed)     # 走真实注入路径
    return v


_orig_mb = loom_gui.QMessageBox
loom_gui.QMessageBox = _FakeMB
try:
    # ============ 1. 注入点: attach() 必须挂上 _ask_delete_confirm ============
    ed0 = _editor()
    # 真实 EditorApp.__init__ 会把钩子置 None (F8); 这里是裸 __new__ 实例,
    # 只要"attach 之前拿不到可调用的确认钩子"就说明注入确实是 attach 干的。
    check('attach 之前 editor 上没有可用的删除确认回调 (回归点)',
          getattr(ed0, '_confirm_delete_callback', None) is None)
    v0 = _inject(ed0)
    cb = getattr(ed0, '_confirm_delete_callback', None)
    check('LoomGUI.attach() 注入了 _confirm_delete_callback (回归点: 之前是 None)',
          callable(cb))
    check('注入的确实是 LoomGUI._ask_delete_confirm',
          getattr(cb, '__func__', None) is loom_gui.LoomGUI._ask_delete_confirm,
          getattr(cb, '__func__', None))

    # ============ 2. N=1: 文案含子物体数, 取消 -> 不删 ============
    ed = _editor()
    _inject(ed)
    p = _add(ed, 'P', (5.0, 0.0, 0.0))
    c = _add(ed, 'C', (1.0, 0.0, 0.0))
    ed.set_parent(c, p, preserve_world=False)
    ed.selected_index = 0                    # 选中父物体 P
    _FakeMB.calls.clear()
    _FakeMB.answer = QMessageBox.StandardButton.No
    ed.delete_object()
    check('N=1 删除父物体 -> 弹了一次确认框', len(_FakeMB.calls) == 1,
          len(_FakeMB.calls))
    _txt = _FakeMB.calls[0]['text'] if _FakeMB.calls else ''
    check('N=1 文案含子物体数 (「该物体有 1 个子物体，删除将一并删除，是否继续？」)',
          '1 个子物体' in _txt and '一并删除' in _txt, _txt)
    check('确认框默认按钮 = 否 (防误按 Enter 删子树)',
          _FakeMB.calls and _FakeMB.calls[0]['default'] == QMessageBox.StandardButton.No,
          _FakeMB.calls[0]['default'] if _FakeMB.calls else None)
    check('取消 -> 父与子都还在 (没删)', [m.name for m in ed.models] == ['P', 'C'],
          [m.name for m in ed.models])

    # ============ 3. N=1: 确认 -> 连子树删 ============
    _FakeMB.calls.clear()
    _FakeMB.answer = QMessageBox.StandardButton.Yes
    ed.delete_object()
    check('确认 -> 连子树删 (P 与 C 都没了)', ed.models == [],
          [m.name for m in ed.models])
    check('确认删除压入撤销命令', ed.undo.can_undo)

    # ============ 4. N=3: 数字要跟着子物体数走 ============
    ed2 = _editor()
    _inject(ed2)
    par = _add(ed2, 'PAR', (0.0, 0.0, 0.0))
    for i in range(3):
        _add(ed2, 'kid%d' % i, (float(i + 1), 0.0, 0.0))
    for m in ed2.models[1:]:
        ed2.set_parent(m, par, preserve_world=False)
    ed2.selected_index = 0
    _FakeMB.calls.clear()
    _FakeMB.answer = QMessageBox.StandardButton.No
    ed2.delete_object()
    _txt2 = _FakeMB.calls[0]['text'] if _FakeMB.calls else ''
    check('N=3 文案写的是 3 个子物体', '3 个子物体' in _txt2, _txt2)
    check('N=3 取消后 4 个物体全在', len(ed2.models) == 4, len(ed2.models))

    # ============ 5. N=0: 文案是普通删除确认 ============
    ed3 = _editor()
    _inject(ed3)
    leaf = _add(ed3, 'LEAF')
    ed3.selected_index = 0
    _FakeMB.calls.clear()
    _FakeMB.answer = QMessageBox.StandardButton.No
    _ans = ed3._confirm_delete_callback(leaf, 0)
    _txt3 = _FakeMB.calls[0]['text'] if _FakeMB.calls else ''
    check('N=0 直接调用回调 -> 文案「确定删除该物体？」',
          _txt3 == '确定删除该物体？', _txt3)
    check('N=0 选否 -> 回调返回 False', _ans is False, _ans)
    check('N=0 选是 -> 回调返回 True',
          (setattr(_FakeMB, 'answer', QMessageBox.StandardButton.Yes)
           or ed3._confirm_delete_callback(leaf, 0)) is True)

    # 无子物体删除: editor 只在 N>0 时回调 (F8 门槛), 所以这里要么不弹, 要么是 N=0 文案;
    # 两种都算对 —— 关键是别被确认框卡住、别删错。
    _FakeMB.calls.clear()
    _FakeMB.answer = QMessageBox.StandardButton.Yes
    ed3.delete_object()
    check('无子物体删除 -> 真的删掉且不卡在确认框', ed3.models == [],
          [m.name for m in ed3.models])
    check('无子物体删除若弹框则用 N=0 文案',
          (not _FakeMB.calls) or _FakeMB.calls[0]['text'] == '确定删除该物体？',
          [c['text'] for c in _FakeMB.calls])

    # ============ 6. 光源/摄像机删除不弹框 (delete_object 提前 return) ============
    ed4 = _editor()
    _inject(ed4)
    _FakeMB.calls.clear()
    ed4.delete_object()          # 没有选中任何东西 -> 什么都不该发生
    check('无选中时删除 -> 不弹框不报错', _FakeMB.calls == [] and ed4.models == [],
          _FakeMB.calls)

    # ============ 7. 弹框异常不阻断删除 (兜底分支) ============
    class _BoomMB:
        StandardButton = QMessageBox.StandardButton

        @classmethod
        def question(cls, *a, **k):
            raise RuntimeError('no display')

    _saved = loom_gui.QMessageBox
    loom_gui.QMessageBox = _BoomMB
    try:
        ed5 = _editor()
        _inject(ed5)
        _add(ed5, 'X')
        ed5.selected_index = 0
        _ok5 = ed5._confirm_delete_callback(ed5.models[0], 2)
    finally:
        loom_gui.QMessageBox = _saved
    check('弹框本身异常 -> 返回 True (保持旧行为, 不阻断删除)', _ok5 is True, _ok5)

    # ============ 8. 顺序陷阱: attach 注入会被 editor.__init__ 的 None 覆盖 ============
    # editor.py:140 `view.attach(self)` 在 :158 `_confirm_delete_callback = None` 之前,
    # 所以只在 attach 里注入 = 白干。bind_editor 是 __init__ 返回后的第一个宿主回调。
    ed6 = _editor()
    _inject(ed6)                                    # 模拟 __init__ 里那次 attach
    ed6._confirm_delete_callback = None             # 模拟 editor.py:158 覆盖
    check('复现顺序陷阱: attach 期注入会被 __init__ 覆盖成 None',
          ed6._confirm_delete_callback is None)
    v6 = _view()
    v6._refresh_all = lambda: None                  # 裸实例, 跳过 UI 刷新
    loom_gui.LoomGUI.bind_editor(v6, ed6)           # __init__ 返回后宿主调用
    check('bind_editor 重新注入 -> 钩子真正生效 (顺序陷阱已修)',
          callable(ed6._confirm_delete_callback))

    # ============ 9. 删除入口 _cmd_del 也重挂 (不依赖启动顺序) ============
    ed7 = _editor()
    _add(ed7, 'PP', (0.0, 0.0, 0.0))
    _kid = _add(ed7, 'KK', (1.0, 0.0, 0.0))
    ed7.set_parent(_kid, ed7.models[0], preserve_world=False)
    ed7.selected_index = 0
    ed7._confirm_delete_callback = None             # 模拟被覆盖 / 从未注入
    v7 = _view()
    v7.editor = ed7
    v7._refresh_all = lambda: None
    _FakeMB.calls.clear()
    _FakeMB.answer = QMessageBox.StandardButton.No
    loom_gui.LoomGUI._cmd_del(v7)
    check('_cmd_del 会重挂钩子 -> N=1 时弹确认框', len(_FakeMB.calls) == 1,
          len(_FakeMB.calls))
    check('_cmd_del + 取消 -> 没删', [m.name for m in ed7.models] == ['PP', 'KK'],
          [m.name for m in ed7.models])
    _FakeMB.answer = QMessageBox.StandardButton.Yes
    loom_gui.LoomGUI._cmd_del(v7)
    check('_cmd_del + 确认 -> 连子树删', ed7.models == [],
          [m.name for m in ed7.models])
finally:
    loom_gui.QMessageBox = _orig_mb

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
