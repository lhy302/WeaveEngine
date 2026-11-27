# -*- coding: utf-8 -*-
"""test_editor_core_split.py — Q-B7-38-1 第 9 批（agent-99）结构门：
editor/core.py（原 3100 行 / _EditorCore 146 方法）按能力域拆分为 11 个域文件 + 薄装配 core.py。

锁五件事：
  ① MRO 装配形状：_EditorCore(EngineCore, <各域 mixin>) —— EngineCore 必须第一个基类，
     能力属性不被 mixin 遮蔽；VkEditorApp/EditorApp 的 MRO 前三位不变（S4/S5 装配形状）。
  ② 防回潮：core.py 与各域文件行数上限（数字 = 拆完实测 + 余量）。
  ③ core.py 不再含被搬走方法的定义（AST 口径），留守 17 个契约锁定成员一个不少。
  ④ 146 方法零丢失：10 个 mixin + core.py 类体方法数总和 == 146，且与拆前名单逐一相符。
  ⑤ 编辑态零逻辑不回归：is_playing=False 连跑 N 帧，逻辑步 == 0（GL 引擎面；
     VK 面的编辑态零逻辑锁在 test_editor_backend_config_parity.py C 组，本门不重复）。
  另：monkeypatch 面（editor.core.STATE_FILE/apply_snapshot/frame_plan/...）仍在本模块命名空间。
"""
import ast
import atexit
import os
import sys
import tempfile

# ---- 失败退出码闸门（与其他测试同款：出 FAIL 行即 exit 1，不留假绿）----
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


_fail_gate = _FailGateStream(sys.stdout)
sys.stdout = _fail_gate


@atexit.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')
os.environ['LOOM_NO_DIALOG'] = '1'

import editor
import editor.core as editor_core
from core.engine_core import EngineCore

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)

# ---- 域清单：文件 -> (mixin 类名, 方法/属性名单)。与搬迁生成器同源提取。----
DOMAINS = {
    "core_commands": ("EditorUndoBridgeMixin", [
        "_history_op", "_undo_action", "_redo_action",
    ]),
    "core_viewport": ("EditorViewportMixin", [
        "_layout", "_in_viewport", "grid_geometry",
    ]),
    "core_selection": ("EditorSelectionMixin", [
        "_selected", "_select_model", "_selected_light", "_selected_camera",
        "_select_camera", "project_world", "_unproject", "_ray_from_mouse",
        "_ray_aabb", "_pick", "_reselect", "_clamp_selection",
        "_clamp_light_selection",
    ]),
    "core_gizmo": ("EditorGizmoMixin", [
        "_camera_forward", "_seg_dist", "_gizmo_basis", "_gizmo_circle_points",
        "_gizmo_hit", "_gizmo_ray_plane_hit", "_local_delta", "_gizmo_drag_apply",
        "_gizmo_start_drag", "_update_gizmo", "set_gizmo_mode", "_gizmo_target",
        "_target_world_pos", "_GIZMO_AXES", "_GIZMO_COLORS", "_GIZMO_LEN",
        "_GIZMO_RAD", "_GIZMO_SEGS", "_GIZMO_HIT_PX",
    ]),
    "core_camera": ("EditorCameraMixin", [
        "_camera_proj_state", "_camera_proj_from", "_apply_camera_proj", "set_camera_projection",
        "_orbit_view_state", "_apply_orbit_view", "set_orbit_view", "_camera_depth",
        "_apply_camera", "FOCUS_DURATION", "FOCUS_DISTANCE_FACTOR", "_focus_aabb",
        "focus_on_object", "_cancel_focus_anim", "_advance_focus_anim",
    ]),
    "core_object": ("EditorObjectMixin", [
        "_seed_scene", "_add_primitive", "_import_obj", "_add_light",
        "_delete_light", "_add_camera", "_delete_camera", "_hierarchy_rows",
        "duplicate_object", "delete_object", "toggle_visible", "new_material",
        "reparent", "detach", "reparent_camera", "detach_camera",
    ]),
    "core_inspector": ("EditorInspectorMixin", [
        "_notify", "_validate_object_name", "rename", "edit_model",
        "commit_model", "edit_light", "commit_light", "rename_light",
        "edit_camera", "commit_camera", "rename_camera", "toggle_collider",
        "toggle_trigger", "add_rigidbody", "remove_rigidbody", "toggle_rigidbody_gravity",
        "add_audio_source", "remove_audio_source", "toggle_audio_playing", "toggle_audio_loop",
        "set_audio_clip", "add_animator", "remove_animator", "play_anim",
        "toggle_anim_playing", "toggle_anim_loop", "set_anim_loop_mode", "set_anim_speed",
        "add_script", "remove_script", "set_script_var", "unlink_prefab",
        "toggle_cam_fov_locked", "set_active_camera", "toggle_camera_preview", "exit_camera_preview",
        "edit_camera_pitch_bound",
    ]),
    "core_asset": ("EditorAssetMixin", [
        "_scene_dir", "_project_root", "_asset_context", "asset_import",
        "_save_prefab", "_instantiate_prefab", "_scan_assets", "_asset_data",
        "_find_asset", "_mouse_to_ground", "_asset_drop_to_scene", "_apply_material_asset",
        "_hex_to_rgb", "_asset_file_by_guid", "_save_material_asset", "_save_mesh_asset",
        "_BUILTIN_MESHES",
    ]),
    "core_scene": ("EditorSceneIOMixin", [
        "_camera_dict", "_effective_skybox", "_refresh_effective_skybox", "_scene_digest",
        "mark_saved", "scene_is_dirty", "save_scene", "save_scene_as",
        "save_current_scene", "_confirm_unsaved", "new_scene_cmd", "load_scene_cmd",
        "_new_scene",
    ]),
    "core_playback": ("EditorPlaybackMixin", [
        "_refresh_play_matrices", "_exit_play_atomic",
    ]),
}
KEPT = [
    "_after_pass_prof", "_choose_scene_path", "_dispatch_ui_mouse", "_draw_selection_box",
    "_editor_shape", "_init_editor_state", "_load_scene", "_prepare_main_pass",
    "_render_dispatches_late", "_save_scene", "_update_camera", "choose_obj_to_import",
    "choose_scene_save_path", "choose_scene_to_open", "on_key_event", "on_quit_request",
    "on_text_input", "render", "toggle_play",
]

print('=== A. MRO 装配形状 ===')
EC = editor_core._EditorCore
mro = [c.__name__ for c in EC.__mro__]
# 上面按名字直取各域 mixin 类
mixins = [getattr(__import__('editor.' + d, fromlist=['x']), spec[0]) for d, spec in DOMAINS.items()]
mnames = sorted(c.__name__ for c in mixins)
check('A1 十个域 mixin 都在 _EditorCore.__bases__ 里',
      sorted(b.__name__ for b in EC.__bases__) == sorted(['EngineCore'] + mnames),
      [b.__name__ for b in EC.__bases__])
check('A2 EngineCore 是第一个基类（能力契约不被 mixin 遮蔽）', EC.__bases__[0] is EngineCore)
ei, mi = mro.index('EngineCore'), [mro.index(n) for n in mnames]
check('A3 MRO 里 EngineCore 先于全部 mixin（遮蔽方向正确）',
      all(ei < x for x in mi), (ei, mi))
vk = [c.__name__ for c in editor.VkEditorApp.__mro__]
gl = [c.__name__ for c in editor.EditorApp.__mro__]
check('A4 VkEditorApp -> _EditorCore -> SceneDriver 装配形状（前三位）',
      vk[:3] == ['VkEditorApp', '_EditorCore', 'SceneDriver'], vk[:4])
check('A5 EditorApp -> _EditorCore -> GLEngine 装配形状（前三位）',
      gl[:3] == ['EditorApp', '_EditorCore', 'GLEngine'], gl[:4])
check('A6 四面同源：GL/VK 编辑器是同一份方法对象（render/toggle_play/_update_camera）',
      editor.EditorApp.render is editor.VkEditorApp.render
      and editor.EditorApp.toggle_play is editor.VkEditorApp.toggle_play
      and editor.EditorApp._update_camera is editor.VkEditorApp._update_camera)
check('A7 编辑器形状标记仍在（_render_dispatches_late/_editor_shape）',
      EC._render_dispatches_late is True and EC._editor_shape is True)

print()
print('=== B. 防回潮：行数上限（= 拆完实测 + 余量）===')
CAPS = {
    "core_contract.py": 67,
    "core_commands.py": 128,
    "core_viewport.py": 79,
    "core_selection.py": 176,
    "core_gizmo.py": 357,
    "core_camera.py": 278,
    "core_object.py": 296,
    "core_inspector.py": 380,
    "core_asset.py": 389,
    "core_scene.py": 243,
    "core_playback.py": 119,
    "core.py": 1201,
}
for fname, cap in sorted(CAPS.items()):
    path = os.path.join(ROOT, 'editor', fname)
    n = len(open(path, encoding='utf-8', newline='').read().splitlines())
    check('B %s 行数 %d <= 上限 %d' % (fname, n, cap), n <= cap, n)

print()
print('=== C. core.py 不再含被搬走方法的定义（AST）===')


def _class_defs(path, cls_name):
    tree = ast.parse(open(path, encoding='utf-8', newline='').read())
    cl = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name]
    if not cl:
        return []
    names = []
    for node in cl[0].body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


moved_all = sorted(n for spec in DOMAINS.values() for n in spec[1])   # 含类属性
core_defs = _class_defs(os.path.join(ROOT, 'editor', 'core.py'), '_EditorCore')
core_defs = [n for n in core_defs if n != '<class-docstring>']
leftover = sorted(set(core_defs) & set(moved_all))
check('C1 core.py 类体没有再出现被搬走的方法/属性定义', not leftover, leftover[:8])
missing_kept = sorted(set(KEPT) - set(core_defs))
check('C2 core.py 类体留守成员齐全（17 方法 + 2 类属性，共 %d）' % len(KEPT),
      not missing_kept, missing_kept[:8])
for dom, (cls_name, names) in sorted(DOMAINS.items()):
    got = _class_defs(os.path.join(ROOT, 'editor', dom + '.py'), cls_name)
    extra = sorted(set(got) - set(names))
    lack = sorted(set(names) - set(got))
    check('C3 %-24s 定义面与名单一致（%d 个）' % (dom, len(names)),
          not extra and not lack, (extra[:5], lack[:5]))

print()
print('=== D. 146 方法零丢失（mixin + core.py 类体总和 == 拆前名单）===')
total = len(moved_all) + len(KEPT)
ATTRS = {'_GIZMO_AXES', '_GIZMO_COLORS', '_GIZMO_LEN', '_GIZMO_RAD',
         '_GIZMO_SEGS', '_GIZMO_HIT_PX', '_BUILTIN_MESHES', 'FOCUS_DURATION',
         'FOCUS_DISTANCE_FACTOR', '_render_dispatches_late', '_editor_shape'}
moved_m = [n for n in moved_all if n not in ATTRS]
kept_m = [n for n in KEPT if n not in ATTRS]
total = len(moved_m) + len(kept_m)
check('D1 方法总数 %d == 146（搬走 %d + 留守 %d；类属性 11 = 搬走 9 + 留守 2）'
      % (total, len(moved_m), len(kept_m)),
      total == 146 and len(moved_all) + len(KEPT) - total == 11, total)
overlap = sorted(set(moved_all) & set(KEPT))
check('D2 搬走/留守名单无重叠', not overlap, overlap[:8])
# 运行期解析面：_EditorCore 上（不含 EngineCore 一侧）能取到全部 146 个
engine_side = set()
for c in EngineCore.__mro__:
    engine_side |= set(c.__dict__)
member146 = moved_m + kept_m
resolvable = {n for n in member146 if hasattr(EC, n)}
check('D3 146 个方法全部可在 _EditorCore 运行期解析（装配后同一 self）',
      len(resolvable) == 146, len(resolvable))

print()
print('=== E. 编辑态零逻辑不回归（GL 引擎面，is_playing=False 跑 %d 帧）===' % 8)
try:
    from core.clock import clock_from_settings
    from core.interp import InterpState
    e = editor.EditorApp.__new__(editor.EditorApp)
    e.is_playing = False
    e._split_enable = True
    e._clock = clock_from_settings({'logic_fps': 30, 'physics_fps': 60})
    e._logic_steps_seen = []
    e._clock.on_logic_step.append(lambda dt: e._logic_steps_seen.append(dt))
    e._interp = InterpState([])
    e._interp.alpha = 0.7
    e._logic_async = False
    e._external_ctx = False
    e._logic_paused = False
    e._advanced_this_frame = False
    e._logic_wall_last = None
    for _ in range(8):
        e._advanced_this_frame = False
        e.advance_logic(1.0 / 60.0)
    check('E1 EditorApp 编辑态 8 帧可跑且逻辑步 == 0',
          e._clock.steps == 0 and len(e._logic_steps_seen) == 0,
          (e._clock.steps, len(e._logic_steps_seen)))
except Exception as exc:
    check('E1 EditorApp 编辑态 8 帧可跑且逻辑步 == 0', False, repr(exc))
try:
    e2 = editor.EditorApp.__new__(editor.EditorApp)
    e2.is_playing = False
    e2._split_enable = True
    e2._clock = clock_from_settings({'logic_fps': 30, 'physics_fps': 60})
    e2._interp = InterpState([])
    e2._interp.alpha = 0.7
    e2._logic_async = False
    e2._external_ctx = False
    e2._logic_paused = False
    e2._advanced_this_frame = False
    e2._logic_wall_last = None
    for _ in range(4):
        e2._advanced_this_frame = False
        e2.advance_logic(1.0 / 60.0)
    check('E2 编辑态 4 帧后插值 alpha 仍为 0（零逻辑不破坏渲染插值面）',
          float(e2._interp.alpha) == 0.0, e2._interp.alpha)
except Exception as exc:
    check('E2 编辑态 4 帧后插值 alpha 仍为 0', False, repr(exc))

print()
print('=== F. monkeypatch 面：常量/函数仍在 editor.core 命名空间 ===')
import render.contract.frame_plan as _fp
import editor.undo as _undo
need = ['STATE_FILE', 'DEFAULT_SAVE_DIR', '_LEGACY_SAVE_DIR', 'APP_DIR',
        'save_last_dir', 'load_last_dir', 'load_last_scene', 'initial_dir',
        'unique_default_name', '_SCENE_FILTER', '_PREFAB_FILTER',
        'apply_snapshot', 'frame_plan', '_editor_skybox_provider',
        '_CameraProjCommand', '_OrbitViewCommand']
lack = [n for n in need if not hasattr(editor_core, n)]
check('F1 editor.core 命名空间成员齐全（patch 目标全在）', not lack, lack)
check('F2 editor.core.frame_plan is render.contract.frame_plan.frame_plan',
      editor_core.frame_plan is _fp.frame_plan)
check('F3 editor.core.apply_snapshot is editor.undo.apply_snapshot',
      editor_core.apply_snapshot is _undo.apply_snapshot)
tmp = os.path.join(tempfile.mkdtemp(), 'state.json')
old = editor_core.STATE_FILE
try:
    editor_core.STATE_FILE = tmp
    check('F4 patch editor.core.STATE_FILE -> load_last_dir() 读到新真源（返回 None）',
          editor_core.load_last_dir() is None, editor_core.load_last_dir())
finally:
    editor_core.STATE_FILE = old
check('F5 旧导入名不变：editor.EditorApp / editor.VkEditorApp 可用',
      hasattr(editor, 'EditorApp') and hasattr(editor, 'VkEditorApp'))

print()
print('总结果:', 'ALL PASS ✅' if not _fails else '有 FAIL ❌')
sys.exit(0 if not _fails else 1)
