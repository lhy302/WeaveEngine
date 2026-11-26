# -*- coding: utf-8 -*-
"""test_eai_split.py — Q-B7-38-1 第 6 批 eai/ 包拆分结构门（2026-11-26）。

为什么需要本门（独立审核 agent-101 指出的缺口）：
  同批次另三个拆分都配了结构门（test_gui_split / test_ui_canvas_split /
  test_editor_core_split），而 eai/ 拆分只靠 import 期 `_assert_command_contract()`
  锁 106 命令名集 + 既有行为测试，缺「形状/身份/补丁面」的结构断言。
  本门补上，防止未来重构把 shim 身份、_PATCH_HOME 覆盖面或包面导出弄丢。

判据（全部为状态描述，不锁缺陷态）：
  A 身份：agent_commands is eai（同一模块对象）；shim 源码确含 sys.modules 替换
  B 契约：_COMMANDS 106 条且与 _EXPECTED_COMMANDS 逐字相同；_CMDS_DESC 同键集
  C 包面：拆分前被外部引用的公开名在 eai 包面都有（含 _LOG_SEQ / LOG_RING /
          _COMMANDS / _CMDS_DESC / dispatch / command / command_names / vec_set 等）
  D 补丁面：_PATCH_HOME 覆盖全仓实际被猴补丁的名字（grep tests 求集合，不许漏）
  E 分包：eai/ 目录下每个 .py 都在 __init__ 里被 import（防「文件存在但没接进去」）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_fail = []
_pass = 0


def check(name, cond, detail=""):
    global _pass
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(detail)) if detail else ""))
    if cond:
        _pass += 1
    else:
        _fail.append(name)


import agent_commands as ac
import eai

print("=== A. shim 身份 ===")
check("agent_commands is eai（同一模块对象，不是两份命名空间）", ac is eai, (id(ac) == id(eai)))
_shim = open(os.path.join(ROOT, "agent_commands.py"), encoding="utf-8").read()
check("shim 源码含 sys.modules 替换（不是把实现又抄回一份）",
      "sys.modules[__name__]" in _shim)
check("shim 是薄门面（< 40 行，不含 class 定义）",
      len(_shim.split(chr(10))) < 40 and not re.search(r"^class ", _shim, re.M),
      len(_shim.split(chr(10))))

print()
print("=== B. 命令契约 ===")
check("_COMMANDS 恰 106 条", len(eai._COMMANDS) == 106, len(eai._COMMANDS))
check("命令名集与 _EXPECTED_COMMANDS 逐字相同（双向空差）",
      set(eai._COMMANDS) == set(eai._EXPECTED_COMMANDS),
      (len(set(eai._EXPECTED_COMMANDS) - set(eai._COMMANDS)),
       len(set(eai._COMMANDS) - set(eai._EXPECTED_COMMANDS))))
check("_CMDS_DESC 与 _COMMANDS 键集相同",
      set(eai._CMDS_DESC) == set(eai._COMMANDS))

print()
print("=== C. 包面导出（拆分前外部引用名） ===")
_PUBLIC = [
    # 注册表与派发
    "_COMMANDS", "_CMDS_DESC", "dispatch", "command", "command_names",
    "current_scope", "log", "log_since", "last_log_seq", "LOG_RING", "_LOG_SEQ",
    # 参数助手 / 写路径白名单
    "as_bool", "as_float", "parse_color", "vec_set",
    "_write_roots", "_realpath", "_safe_write_path",
    # 目标解析 / 提交
    "_resolve", "_no_target", "_commit", "_apply_fields", "_undo_manager",
    # 命令体（抽样覆盖各域）
    "cmd_quit", "cmd_status", "cmd_screenshot", "cmd_scene_save", "cmd_scene_load",
    "cmd_object_add", "cmd_object_list", "cmd_object_delete", "cmd_undo", "cmd_redo",
    "cmd_agent_batch_begin", "cmd_agent_batch_end", "cmd_agent_batch_cancel",
    "cmd_play", "cmd_logic_pause", "cmd_logic_step", "cmd_light_add", "cmd_light_set",
    "cmd_skybox_set", "cmd_skybox_clear", "cmd_skybox_get",
    "cmd_camera_add", "cmd_camera_set", "cmd_camera_preview", "cmd_camera_proj",
    "cmd_materials", "cmd_set_material", "cmd_set_texture", "cmd_set_pbr", "cmd_set_lod",
    "cmd_collider", "cmd_rigidbody", "cmd_physics_simulate",
    "cmd_audio", "cmd_animator", "cmd_script_add", "cmd_script_remove", "cmd_scripts",
    "cmd_reparent", "cmd_import_obj", "cmd_prefab_save", "cmd_prefab_place",
    "cmd_assets", "cmd_asset_apply", "cmd_asset_place", "cmd_asset_list",
    "cmd_set_layer", "cmd_set_tag", "cmd_list_tags", "cmd_list_layers",
    "cmd_ui_add", "cmd_ui_set", "cmd_ui_list", "cmd_ui_remove",
    "cmd_raycast", "cmd_raycast_all", "cmd_raycast_screen", "cmd_send_message",
    "cmd_find_by_name", "cmd_find_by_script",
    "cmd_settings_get", "cmd_settings_set",
    "cmd_http_get", "cmd_http_post_json", "cmd_http_request",
    "cmd_plugins", "cmd_plugin_button", "cmd_key_binding", "cmd_render_api",
    # 服务面
    "port_file_path", "load_agent_info",
]
_missing = [n for n in _PUBLIC if not hasattr(eai, n)]
check("拆分前外部引用名在 eai 包面全部可见", not _missing, _missing)

print()
print("=== D. 猴补丁转发面 ===")
# 全仓 grep：测试里对 agent_commands/eai 的属性赋值（猴子补丁）
_patched = set()
_pat = re.compile(r"^(?:\s*)(?:ac|agent_commands|eai)\.([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]")
_tdir = os.path.join(ROOT, "tests")
for _fn in sorted(os.listdir(_tdir)):
    if not _fn.endswith(".py"):
        continue
    try:
        _src = open(os.path.join(_tdir, _fn), encoding="utf-8").read()
    except OSError:
        continue
    for _line in _src.split(chr(10)):
        _m = _pat.match(_line)
        if _m:
            _patched.add(_m.group(1))
check("仓内被猴补丁的名字都可转发（_PATCH_HOME 覆盖或包面赋值即真身）",
      all((n in eai._PATCH_HOME) or (hasattr(eai, n)) for n in _patched),
      sorted(_patched))
check("_PATCH_HOME 每个目标都是真子模块对象",
      all(hasattr(mod, n) for n, mod in eai._PATCH_HOME.items()),
      {n: getattr(mod, "__name__", "?") for n, mod in eai._PATCH_HOME.items()})

print()
print("=== E. 分包完整性 ===")
_pkgdir = os.path.join(ROOT, "eai")
_files = sorted(f[:-3] for f in os.listdir(_pkgdir)
                if f.endswith(".py") and f not in ("__init__.py",))
_init_src = open(os.path.join(_pkgdir, "__init__.py"), encoding="utf-8").read()
_not_imported = [f for f in _files if ("from .%s import" % f) not in _init_src
                 and ("from . import %s" % f) not in _init_src
                 and ("import eai.%s" % f) not in _init_src]
check("eai/ 下每个子模块都被 __init__ 显式 import（否则 @command 不注册）",
      not _not_imported, _not_imported)
check("eai/ 子模块数 >= 30（拆分粒度体检，防回潮成单文件）",
      len(_files) >= 30, len(_files))

print()
print("=" * 60)
print("PASS test_eai_split: %s (%d 项)" % ("全部通过" if not _fail else "有 FAIL", _pass))
if _fail:
    print("FAILED %d 条: %s" % (len(_fail), _fail))
sys.exit(0 if not _fail else 1)