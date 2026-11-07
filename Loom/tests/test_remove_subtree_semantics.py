# -*- coding: utf-8 -*-
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


"""test_remove_subtree_semantics.py — 删父=连子树删 (Q3=A) + 矩阵语义一致 (P-10).

缺陷: remove_model(父) 只删父节点, 子物体留在 models 且 parent 悬空 → 批量矩阵
(缺失父=根) 与 model_world_matrix(沿悬空父合成) 两套世界位置分叉。

裁决 Q3=A: 删除仍有子物体的父对象 = 连整棵子树一起删 (Unity 语义); 编辑入口
删除前提示子物体数量 N。本测试锁:
  · remove_model(父) 递归删子树, 无悬空 parent;
  · remove_subtree 全树删除, 剩余物体批量/递归矩阵一致;
  · DeleteObjectCommand 撤销/重做仍完整还原 (不回归);
  · EditorApp.delete_object 走子树删除, 且 _confirm_delete_callback 收到 N。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from editor import EditorApp                              # noqa: E402
from engine import GLEngine, GameObject, Point3D          # noqa: E402
import undo as U                                          # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _engine():
    e = GLEngine.__new__(GLEngine)
    e.models = []
    e.materials = []
    e.current_model_index = 0
    e._struct_gen = 0
    e._build_gpu = lambda m: None
    return e


def _add(e, name, pos):
    m = GameObject(None, pos, (0.0, 0.0, 0.0), name=name)
    e.models.append(m)
    e._bump_struct()
    return m


def tx(mat):
    return float(mat[0][3, 0])


def t_remove_model_parent_deletes_subtree():
    e = _engine()
    p = _add(e, 'P', (5.0, 0.0, 0.0))
    c = _add(e, 'C', (1.0, 0.0, 0.0))
    g = _add(e, 'G', (1.0, 0.0, 0.0))
    e.set_parent(c, p, preserve_world=False)
    e.set_parent(g, c, preserve_world=False)
    check('挂父后 P.children=[C], C.children=[G]',
          p.children == [c] and c.children == [g])

    e.remove_model(p)
    check('Q3=A remove_model(父) 连子树删', e.models == [], [m.name for m in e.models])
    check('子物体 parent 不悬空', c.parent is None and g.parent is None)
    check('父的 children 清空', p.children == [] and c.children == [])


def t_remove_subtree_and_matrix_agreement():
    e = _engine()
    p = _add(e, 'P', (5.0, 0.0, 0.0))
    c = _add(e, 'C', (1.0, 0.0, 0.0))
    s = _add(e, 'S', (2.0, 0.0, 0.0))
    e.set_parent(c, p, preserve_world=False)

    e.remove_subtree(p)
    check('remove_subtree 删光子树', [m.name for m in e.models] == ['S'])
    check('remove_subtree 后无悬空 parent', c.parent is None and p.parent is None)

    fw = e.compute_world_matrices(e.models)
    rec = e.model_world_matrix(s)
    check('P-10 剩余物体 批量/递归世界矩阵一致',
          abs(tx(fw) - float(rec[3, 0])) < 1e-12,
          'batch=%r rec=%r' % (tx(fw), float(rec[3, 0])))


def t_delete_command_undo_redo():
    e = _engine()
    p = _add(e, 'P', (5.0, 0.0, 0.0))
    c = _add(e, 'C', (1.0, 0.0, 0.0))
    e.set_parent(c, p, preserve_world=False)
    um = U.UndoManager()
    um.push(U.DeleteObjectCommand('删P子树', e, p))
    check('DeleteObjectCommand 删子树', e.models == [])
    um.undo()
    check('undo 还原父子',
          [m.name for m in e.models] == ['P', 'C'] and c.parent is p)
    um.redo()
    check('redo 再删子树', e.models == [])
    um.undo()
    check('二次 undo 仍还原', [m.name for m in e.models] == ['P', 'C'])


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


def t_editor_delete_confirmation():
    ed = _editor()
    p = _add(ed, 'P', (5.0, 0.0, 0.0))
    c = _add(ed, 'C', (1.0, 0.0, 0.0))
    ed.set_parent(c, p, preserve_world=False)
    calls = []

    ed._confirm_delete_callback = lambda m, n: (calls.append((m.name, n)) or False)
    ed.delete_object()
    check('删除前回调收到子物体数量 N=1', calls == [('P', 1)], calls)
    check('用户取消 → 场景不变', [m.name for m in ed.models] == ['P', 'C'])

    ed._confirm_delete_callback = lambda m, n: True
    ed.delete_object()
    check('用户确认 → 连子树删', ed.models == [])
    check('确认后压入删除命令 (可撤销)', ed.undo.can_undo)


def t_leaf_delete_still_single():
    e = _engine()
    a = _add(e, 'A', (0.0, 0.0, 0.0))
    b = _add(e, 'B', (2.0, 0.0, 0.0))
    e.remove_model(a)
    check('无子物体 remove_model 只删自己', [m.name for m in e.models] == ['B'])
    check('另一物体 parent 不受影响', b.parent is None)


t_remove_model_parent_deletes_subtree()
t_remove_subtree_and_matrix_agreement()
t_delete_command_undo_redo()
t_editor_delete_confirmation()
t_leaf_delete_still_single()
print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
