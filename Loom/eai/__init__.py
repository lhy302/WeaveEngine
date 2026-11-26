# -*- coding: utf-8 -*-
"""eai — EAI 命令层包 (Loom 引擎 Agent 接口, 2026-08-27; 包化 Q-B7-38-1, 2026-11-26)
======================================================================
按域拆成「一个功能一个文件」, 本文件只做三件事:
  ① 显式 import 每个子模块 —— @command 装饰器在 import 期注册命令,
     注册不依赖导入顺序 (本文件列出全部子模块, 漏一个命令表就少一条, 契约门会红);
  ② 重导出全部符号 —— 对外 eai.X / agent_commands.X 与拆分前逐名等价;
  ③ 命令表契约门 —— 106 条命令 + 命令名逐字快照。

拆法 = 按域 (灯光/相机/UI/资产/…) × 按层: 注册表 / 写路径白名单 / 参数助手 /
目标寻址 / 提交前置 / 撤销前置 / UI 前置 是 7 个共享前置库, 命令文件只 import 它们。
不负责: 命令背后的编辑器/引擎实现 (editor/ scene/ render/ …)。
"""

import sys as _sys
import types as _types


# ---- ① 显式导入每个子模块 (顺序 = 依赖拓扑; 装饰器在 import 期注册命令) ----
from .helpers import (  # noqa: F401
    _FALSE_WORDS, as_bool, as_float, _COLOR_FIELDS,
    parse_color, _coerce_color_args, _VEC_FIELDS, _as_vec,
    _coerce_vec_args, vec_set
)
from .target import _find_all, _find, _find_model_by_name  # noqa: F401
from .commit import _resolve, _Ambiguous, _no_target, _commit, _apply_fields  # noqa: F401
from .undo_base import _undo_manager  # noqa: F401
from .registry import (  # noqa: F401
    LOG_RING, _LOG_LOCK, _LOG_SEQ, _COMMANDS, _CMDS_DESC,
    _CommandScope, _CMD_SCOPE, current_scope, log,
    log_since, last_log_seq, command, command_names,
    dispatch
)
from .animator_ops import cmd_animator  # noqa: F401
from .whitelist import _write_roots, _realpath, _safe_write_path  # noqa: F401
from .app_ops import cmd_quit, cmd_status, cmd_screenshot  # noqa: F401
from .asset_ops import (  # noqa: F401
    cmd_assets, _asset_of, cmd_asset_apply, cmd_asset_place,
    cmd_asset_save, _resolve_asset_input, cmd_asset_import, cmd_asset_get,
    cmd_asset_user_override, cmd_asset_list, cmd_scene_assets_check
)
from .audio_ops import cmd_audio, cmd_set_audio_3d, cmd_get_audio_3d  # noqa: F401
from .inspector import (  # noqa: F401
    cmd_engine_metrics, cmd_inspect, cmd_set_transform, cmd_set_visible,
    cmd_set_saturation, cmd_set_color, cmd_set_normal_mode
)
from .camera_ops import (  # noqa: F401
    cmd_camera_add, cmd_camera_active, cmd_camera_move, cmd_camera_proj,
    cmd_camera_look, cmd_camera_set, cmd_camera_preview
)
from .hierarchy_ops import cmd_reparent  # noqa: F401
from .http_ops import cmd_http_get, cmd_http_post_json, cmd_http_request  # noqa: F401
from .keybind_ops import cmd_key_binding  # noqa: F401
from .layer_tag_ops import (  # noqa: F401
    cmd_set_layer, cmd_set_tag, cmd_get_layer_tag, cmd_list_tags,
    cmd_register_tag, cmd_list_layers
)
from .light_ops import cmd_light_add, cmd_light_set  # noqa: F401
from .material_ops import (  # noqa: F401
    cmd_materials, cmd_set_material, cmd_material_new, cmd_set_texture,
    cmd_set_pbr, cmd_set_lod, cmd_set_env
)
from .object_ops import (  # noqa: F401
    cmd_object_add, _auto_focus_enabled, _auto_focus, cmd_object_list,
    cmd_object_select, cmd_object_rename, cmd_object_delete, cmd_object_duplicate
)
from .physics_ops import cmd_collider, cmd_rigidbody, cmd_physics_simulate  # noqa: F401
from .plugin_ops import cmd_plugins, cmd_plugin_button  # noqa: F401
from .prefab_ops import (  # noqa: F401
    cmd_import_obj, cmd_prefab_save, cmd_prefab_place, cmd_prefab_unlink
)
from .query_ops import (  # noqa: F401
    cmd_raycast, cmd_raycast_all, cmd_raycast_screen, _model_brief,
    cmd_find_by_name, cmd_find_all_by_name, cmd_find_by_script
)
from .render_backend_ops import cmd_render_api  # noqa: F401
from .scene_ops import cmd_scene_new, cmd_scene_save, cmd_scene_load  # noqa: F401
from .script_ops import (  # noqa: F401
    cmd_script_add, cmd_script_remove, cmd_script_reload, cmd_scripts,
    cmd_script_var, cmd_send_message
)
from .service import (  # noqa: F401
    port_file_path, _write_port_file, _CmdHandler, _env_float,
    AgentService, load_agent_info
)
from .settings_ops import cmd_settings_get, cmd_settings_set  # noqa: F401
from .skybox_ops import (  # noqa: F401
    _skybox_source, _skybox_describe, cmd_skybox_set, cmd_skybox_clear,
    _vk_skybox_info, cmd_skybox_get
)
from .ui_common import _push_ui_undo, _ui_canvas  # noqa: F401
from .ui_canvas_ops import cmd_ui_canvas_add, cmd_ui_canvas_set  # noqa: F401
from .ui_element_ops import (  # noqa: F401
    _UI_TYPE_NAMES, _ui_parent, _ui_auto_name, _ui_to_dict,
    cmd_ui_add, cmd_ui_set, cmd_ui_remove, cmd_ui_list,
    cmd_ui_reparent, cmd_ui_move_child
)
from .ui_event_ops import cmd_ui_bind_event, cmd_ui_unbind_event  # noqa: F401
from .undo_ops import (  # noqa: F401
    cmd_undo, cmd_redo, _history_result, _batch_status_hook,
    cmd_agent_batch_begin, cmd_agent_batch_end, cmd_agent_batch_cancel
)
from .view_ops import (  # noqa: F401
    cmd_view_focus, cmd_gizmo, cmd_play, cmd_logic_pause,
    cmd_logic_step
)


# ---- ③ 命令表契约门 (拆分前 agent_commands.py 的命令名逐字快照) ----
_EXPECTED_COMMANDS = (
    'agent_batch_begin', 'agent_batch_cancel', 'agent_batch_end', 'animator',
    'asset_apply', 'asset_get', 'asset_import', 'asset_list',
    'asset_place', 'asset_save', 'asset_user_override', 'assets',
    'audio', 'camera_active', 'camera_add', 'camera_look',
    'camera_move', 'camera_preview', 'camera_proj', 'camera_set',
    'collider', 'engine_metrics', 'find_all_by_name', 'find_by_name',
    'find_by_script', 'get_audio_3d', 'get_layer_tag', 'gizmo',
    'http_get', 'http_post_json', 'http_request', 'import_obj',
    'inspect', 'key_binding', 'light_add', 'light_set',
    'list_layers', 'list_tags', 'logic_pause', 'logic_step',
    'material_new', 'materials', 'object_add', 'object_delete',
    'object_duplicate', 'object_list', 'object_rename', 'object_select',
    'physics_simulate', 'play', 'plugin_button', 'plugins',
    'prefab_place', 'prefab_save', 'prefab_unlink', 'quit',
    'raycast', 'raycast_all', 'raycast_screen', 'redo',
    'register_tag', 'render_api', 'reparent', 'rigidbody',
    'scene_assets_check', 'scene_load', 'scene_new', 'scene_save',
    'screenshot', 'script_add', 'script_reload', 'script_remove',
    'script_var', 'scripts', 'send_message', 'set_audio_3d',
    'set_color', 'set_env', 'set_layer', 'set_lod',
    'set_material', 'set_normal_mode', 'set_pbr', 'set_saturation',
    'set_tag', 'set_texture', 'set_transform', 'set_visible',
    'settings_get', 'settings_set', 'skybox_clear', 'skybox_get',
    'skybox_set', 'status', 'ui_add', 'ui_bind_event',
    'ui_canvas_add', 'ui_canvas_set', 'ui_list', 'ui_move_child',
    'ui_remove', 'ui_reparent', 'ui_set', 'ui_unbind_event',
    'undo', 'view_focus',
)


def _assert_command_contract():
    """命令表契约门: 106 条命令, 且命令名集合与拆分前逐字相同.

    拆分纪律 (docs/guides/开发要求_功能解耦与模块化.md §3): 公开符号不许改名/丢失.
    命令表是 GUI 控制台 + HTTP + MCP 的单一事实, 少一条或改一个名字都是契约破坏;
    新增命令时同步改 _EXPECTED_COMMANDS 与本函数里的 106 计数 (两者一起改 = 显式契约变更).
    """
    got = tuple(sorted(_COMMANDS))
    if len(got) != 106 or got != _EXPECTED_COMMANDS:
        raise RuntimeError(
            'EAI 命令表契约破裂: 期望 106 条, 实得 %d 条; 缺 %s; 多 %s'
            % (len(got),
               [n for n in _EXPECTED_COMMANDS if n not in _COMMANDS],
               [n for n in got if n not in _EXPECTED_COMMANDS]))


_assert_command_contract()


# ---- 猴补丁转发 (保持拆分前"模块属性赋值即生效"的语义) ----
# 拆分前 agent_commands 是单模块, 测试/工具用 ac._auto_focus_enabled = 替身 猴补丁;
# 包化后该名字的真身在 object_ops 模块里, 直接给包赋值不会影响调用点 —— 这里把赋值
# 转发到真正定义它的子模块, 让 ac.X = 替身 与拆分前完全等价 (见 tests/test_editor_focus.py).
# 补丁转发面 = _PATCH_HOME 里的名字（2026-11-26 终审 agent-101 C-2：明确登记）：
# 拆分前单模块一切属性赋值都生效；拆分后**只有列在这里的名字**的包级赋值会转发到真身子模块。
# 其他名字包级赋值只改包面（不影响 dispatch 等内部消费——内部一律经子模块真身）。
# 新增被测试猴补丁的公开名时必须同步登记到这里。
_PATCH_HOME = {'_auto_focus_enabled': _sys.modules['eai.object_ops']}


class _EaiPackage(_types.ModuleType):
    """包模块本体: 赋值时同步转发到定义该名字的子模块 (只转发 _PATCH_HOME 里的名字)."""

    def __setattr__(self, name, value):
        home = _PATCH_HOME.get(name)
        if home is not None:
            setattr(home, name, value)
        _types.ModuleType.__setattr__(self, name, value)


_sys.modules[__name__].__class__ = _EaiPackage
