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


"""test_editor_load_reject_keeps_scene.py — 加载非法场景不得先清空旧场景 (F7/F8).

背景: editor._load_scene 旧顺序是"先 remove_model 全部 + undo.clear, 再
sceneio.scene_from_dict"; 而 sceneio 的父链成环校验在 scene_from_dict 内部。
加载成环场景 -> 旧场景已被清空 -> 用户直接丢当前工作。

修复: 清空之前先 sceneio._validate_object_graph(data['objects']); 失败则
_notify 提示并原样保留旧场景 (也不改 _scene_path / 上次打开记录)。
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import engine as E                                       # noqa: E402
import editor                                            # noqa: E402
from undo import UndoManager                             # noqa: E402

E.GLEngine._build_gpu = lambda self, m: None             # 无头桩

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


class _View:
    def reset_interaction(self):
        pass


def _new_ed():
    ed = editor.EditorApp.__new__(editor.EditorApp)
    ed.models = []
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.current_model_index = 0
    ed.script_keys = {}
    ed.undo = UndoManager()
    ed.is_playing = False
    ed.active_camera = None
    ed.gravity = -9.8
    ed._skybox = None
    ed.ui = None
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.orbit_mode = True
    ed._fov = 0.785
    ed._scene_path = None
    ed.last_dir = None
    ed.scene_name = '场景'
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.msg = ''
    ed.msg_color = (220, 222, 228)
    ed._msg_until = 0.0
    ed.view = _View()
    ed.mark_saved = lambda: None
    return ed


def _write(tmp, name, data):
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    return p


def t_valid_then_cycle_keeps_scene():
    old_save = editor.save_last_dir
    editor.save_last_dir = lambda state_file, path: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            a_path = _write(tmp, 'A.json', {
                'version': 8,
                'objects': [{'id': 'a', 'name': 'A', 'primitive': 'cube',
                             'position': [1.0, 0.0, 0.0],
                             'rotation': [0.0, 0.0, 0.0],
                             'scale': [1.0, 1.0, 1.0]}]})
            b_path = _write(tmp, 'B_cycle.json', {
                'version': 8,
                'objects': [
                    {'id': 'x', 'name': 'X', 'primitive': 'cube',
                     'parent_id': 'y'},
                    {'id': 'y', 'name': 'Y', 'primitive': 'cube',
                     'parent_id': 'x'}]})

            ed = _new_ed()
            ed._load_scene(a_path)
            check('合法场景 A 加载成功', len(ed.models) == 1 and ed.models[0].name == 'A',
                  [m.name for m in ed.models])
            check('A 加载后 _scene_path=A', ed._scene_path == a_path, ed._scene_path)
            a_model = ed.models[0]
            a_materials = list(ed.materials)

            ed._load_scene(b_path)   # 成环: 必须拒绝且保留 A

            check('成环场景被拒绝, A 仍在', ed.models == [a_model],
                  [m.name for m in ed.models])
            check('A 的材质库未被清空', ed.materials == a_materials)
            check('失败加载不改 _scene_path', ed._scene_path == a_path, ed._scene_path)
            check('失败加载有错误提示 (msg)',
                  bool(ed.msg) and ('成环' in ed.msg or '加载失败' in ed.msg), ed.msg)
            check('错误提示用红色', tuple(ed.msg_color) == (235, 90, 90), ed.msg_color)

            # 非 dict 顶层同样不得清空旧场景
            bad_path = _write(tmp, 'bad.json', [1, 2, 3])
            ed._load_scene(bad_path)
            check('非对象场景被拒绝, A 仍在', ed.models == [a_model],
                  [m.name for m in ed.models])
            check('非对象场景有错误提示', bool(ed.msg), ed.msg)
    finally:
        editor.save_last_dir = old_save


t_valid_then_cycle_keeps_scene()
print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
