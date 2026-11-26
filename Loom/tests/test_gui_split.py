# -*- coding: utf-8 -*-
"""test_gui_split.py — Q-B7-38-1 第 8 批门：LoomGUI 按面板域拆 mixin（gui/panels/）。

背景（人类 2026-11-18 裁定「按域拆到底 / 一个功能一个文件」+
docs/guides/开发要求_功能解耦与模块化.md §1 六条硬规则）：
  拆前 gui/main_window.py = 4129 行 / LoomGUI 单类 131 方法（工具栏/层级/检查器/
  资源/控制台/设置/状态栏全混在一个类里）。本批逐域纯搬迁到 gui/panels/ 的 12 个
  mixin，LoomGUI 改为 (…Mixin, QMainWindow) 装配，类体只留装配与主窗口职责。

六组门：
  A. 防回潮：每个 mixin 文件行数不得超过本批拆完时的上限。
  B. 纯搬迁：被搬走的 108 个方法不得再出现在 gui/main_window.py 类体（AST 判定）。
  C. 计数不变：main 类体 23 + 12 mixin 108 = 131，名字集合与拆前基线逐项一致。
  D. 混入契约：mixin 之间不得互相 import（§1 规则 2，只经 self 互调）；
     gui/panels/__init__.py __all__ 汇总导出 12 个 mixin 类。
  E. 门强度不降：test_gui_command_unification.D1 的禁集扫描原本只扫 gui/main_window.py，
     方法搬进 gui/panels/ 后本门用**同一份** _FORBIDDEN_CALLS（从该门 AST 取字面量，
     不复制清单）对 main_window + 12 个 mixin 重扫同一谓词（<attr>( 直调即红）。
  F. MRO：LoomGUI.__mro__ 含全部 12 个 mixin + QMainWindow，顺序 = 基类声明顺序，
     且 mixin 全部排在 QMainWindow 之前（否则 mixin 方法被 Qt 遮蔽）。
     （F 需要真 import gui.main_window，故放最后；导入失败也只红 F 组，不影响 A~E。）
"""

import ast
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                     # = Loom/
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MW_REL = os.path.join("gui", "main_window.py")
PANELS_REL = os.path.join("gui", "panels")

_fails = []
_pass_n = 0


def check(name, cond, detail=""):
    global _pass_n
    line = ("PASS " if cond else "FAIL ") + name
    if detail and not cond:
        line += "  " + str(detail)
    print(line)
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


# 12 个 mixin（= gui/main_window.py 基类声明顺序，左→右）
MIXINS = [
    ("cmd_bridge_mixin", "CmdBridgeMixin"),
    ("actions_mixin", "ActionsMixin"),
    ("toolbar_mixin", "ToolbarMixin"),
    ("hierarchy_mixin", "HierarchyMixin"),
    ("gizmo_mixin", "GizmoMixin"),
    ("asset_mixin", "AssetMixin"),
    ("console_mixin", "ConsoleMixin"),
    ("publish_mixin", "PublishMixin"),
    ("inspector_mixin", "InspectorMixin"),
    ("uitree_mixin", "UitreeMixin"),
    ("status_mixin", "StatusMixin"),
    ("settings_mixin", "SettingsMixin"),
]

# A 组行数上限（本批拆完实测 + 约 5% 余量；防「再变胖回潮」）
LINE_CAPS = {
    "actions_mixin": 230,
    "asset_mixin": 105,
    "cmd_bridge_mixin": 214,
    "console_mixin": 50,
    "gizmo_mixin": 245,
    "hierarchy_mixin": 305,
    "inspector_mixin": 950,
    "publish_mixin": 160,
    "settings_mixin": 590,
    "status_mixin": 300,
    "toolbar_mixin": 180,
    "uitree_mixin": 305,
}

# C 组基线：拆前 LoomGUI 的 131 个方法（gui/main_window.py @ 99d2349，AST 计数）
BASELINE_METHODS = (
    "__init__", "_on_vk_late_init_error", "_handle_vk_init_failure", "_vk_failure_message", "attach", "_inject_delete_confirm",
    "bind_editor", "input_state", "handle_key_event", "key_pressed_array", "reset_interaction", "draw",
    "_preframe_in_gap", "_on_tick", "_build_central", "_apply_fps_limit", "_wait_until", "eventFilter",
    "_refresh_all", "_ask_save_dirty", "_ask_delete_confirm", "closeEvent", "changeEvent", "_notify_or_print",
    "_invoke_cmd", "_invoke_ui_cmd", "_log_gui_cmd", "_spin_session_begin", "_spin_session_end", "_cmd_vec_set",
    "_gl_guard", "_report_history_result", "_cmd_play", "_cmd_tps_pause", "_cmd_tps_step", "_cmd_scene_name",
    "_cmd_prefab_name", "_cmd_save", "_cmd_save_as", "_cmd_load", "_cmd_new", "_cmd_undo",
    "_cmd_redo", "_cmd_gizmo", "_cmd_add", "_cmd_import_obj", "_cmd_dup", "_cmd_del",
    "_cmd_add_light", "_cmd_add_camera", "_cmd_toggle_visible", "_cmd_prefab_save", "_cmd_prefab_put", "_build_toolbar",
    "_add_tb_menu", "_rebuild_plugin_menu", "_run_plugin_cb", "_add_tb_btn", "_build_hier_tools", "_hier_data",
    "_rebuild_hierarchy", "_hier_arrow_zone", "_hier_item_at", "_select_by_kind", "_hier_drop", "_is_ancestor",
    "_hier_menu", "_ask_text", "_rename_obj", "_rename_light", "_rename_camera", "_hier_digest",
    "_insp_target", "_insp_key_of", "_rebuild_inspector", "_spin", "_spin_focused", "_btn_row",
    "_insp_input_focused", "_insp_line_edits", "_insp_component_digest", "_sync_inspector_values", "_build_obj_inspector", "_build_light_inspector",
    "_build_camera_inspector", "_on_app_focus_changed", "_draw_gizmo", "_icon_size", "_direction_cone", "_draw_light_icons",
    "_draw_directional_dir", "_draw_camera_icons", "_rebuild_resources", "_res_item_data", "_res_double", "_cmd_apply_asset",
    "_cmd_place_asset", "_res_digest", "_build_console", "_cmd_console", "_build_tool_cmd", "_cmd_publish_game",
    "_poll_publish", "_cmd_settings", "_cmd_set_render_api", "_cmd_set_parallel", "_build_statusbar", "_refresh_status",
    "_agent_args_summary", "_agent_progress", "_agent_gui_alive", "_agent_gui_warn_once", "_agent_idle", "_agent_tb_visible",
    "_agent_busy", "_agent_batch_status", "_agent_after_command", "_bind_agent_service", "_build_ui_tree_dock", "_cmd_uitree",
    "_ui_tree_set_selection", "_ui_tree_add_dialog", "_ui_tree_add_canvas_dialog", "_build_ui_inspector", "_ui_attr_spin", "_ui_attr_check",
    "_ui_attr_line", "_ui_apply_attr", "_build_canvas_inspector", "_canvas_spin", "_canvas_apply_attr",
)

# B 组：被搬走的 108 个方法（= 基线 131 − main 类体 23 个主窗口职责方法）
MAIN_KEPT = (
    "__init__", "_on_vk_late_init_error", "_handle_vk_init_failure", "_vk_failure_message",
    "attach", "_inject_delete_confirm", "bind_editor", "input_state", "handle_key_event",
    "key_pressed_array", "reset_interaction", "draw", "_preframe_in_gap", "_on_tick",
    "_build_central", "_apply_fps_limit", "_wait_until", "eventFilter", "_refresh_all",
    "_ask_save_dirty", "_ask_delete_confirm", "closeEvent", "changeEvent",
)
MOVED_METHODS = tuple(n for n in BASELINE_METHODS if n not in MAIN_KEPT)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _class_methods(src):
    """(类名, 类体内方法名列表)；无 ClassDef 时 (None, [])。"""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            return (node.name, [s.name for s in node.body
                                if isinstance(s, (ast.FunctionDef,
                                                   ast.AsyncFunctionDef))])
    return (None, [])


def _load_forbidden_calls():
    """从 test_gui_command_unification.py 的 AST 取同一份 _FORBIDDEN_CALLS 字面量。
    （该门 import 会跑全部门，故只 parse 不 import；清单不复制，保持单点。）"""
    src = _read(os.path.join("tests", "test_gui_command_unification.py"))
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_FORBIDDEN_CALLS"):
            return set(ast.literal_eval(node.value))
    return None


def _scan_forbidden(rel, forbidden):
    """同一谓词：出现 <attr>( 且 attr 在禁集 -> 命中（AST 精确判定）。"""
    hits = []
    for node in ast.walk(ast.parse(_read(rel))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden):
            hits.append((node.func.attr, node.lineno))
    return hits


def main():
    print("---- A. 防回潮：mixin 文件行数 ----")
    for fname, _cname in MIXINS:
        rel = os.path.join(PANELS_REL, fname + ".py")
        if not os.path.exists(os.path.join(ROOT, rel)):
            check("A %s.py 存在" % fname, False, rel)
            continue
        n = len(_read(rel).splitlines())
        cap = LINE_CAPS[fname]
        check("A %-20s %4d 行 (上限 %d)" % (fname, n, cap), n <= cap,
              "%d > %d" % (n, cap) if n > cap else n)

    print("---- B. 纯搬迁：main_window.py 不再含被搬走的方法 ----")
    cname, mw_methods = _class_methods(_read(MW_REL))
    check("B main_window.py 主类名仍是 LoomGUI", cname == "LoomGUI", cname)
    left = [m for m in mw_methods if m in MOVED_METHODS]
    check("B 类体残留的被搬方法 = 0", not left, left[:8])
    check("B main 类体方法数 = 23（装配 + 主窗口职责）",
          len(mw_methods) == 23, len(mw_methods))

    print("---- C. 计数不变：131（23 main + 108 mixin）----")
    total = list(mw_methods)
    for fname, _cname in MIXINS:
        total.extend(_class_methods(_read(os.path.join(PANELS_REL, fname + ".py")))[1])
    dup = sorted(n for n in set(total) if total.count(n) > 1)
    check("C 方法总数 = 131", len(total) == 131, len(total))
    check("C 无重复方法名（同名定义只许一处）", not dup, dup[:8])
    missing = [n for n in BASELINE_METHODS if n not in set(total)]
    extra = [n for n in total if n not in set(BASELINE_METHODS)]
    check("C 基线 131 方法一个不少（防方法丢失）", not missing, missing[:8])
    check("C 无基线外新增方法（本批纯搬迁）", not extra, extra[:8])

    print("---- D. 混入契约：mixin 之间不互相 import / __init__ 汇总导出 ----")
    for fname, _cname in MIXINS:
        src = _read(os.path.join(PANELS_REL, fname + ".py"))
        bad = [ln.strip() for ln in src.splitlines()
               if ("import gui.panels" in ln or "from gui.panels" in ln
                   or "from gui import panels" in ln or "from ." in ln)]
        check("D %-20s 不 import 兄弟 mixin（只经 self 互调）" % fname, not bad,
              bad[:3])
    init_src = _read(os.path.join(PANELS_REL, "__init__.py"))
    missing_exp = [c for _f, c in MIXINS if (chr(39) + c + chr(39)) not in init_src]
    check("D gui/panels/__init__.py __all__ 汇总 12 个 mixin 类", not missing_exp,
          missing_exp)

    print("---- E. 门强度不降：禁集直调扫描覆盖 gui/panels（补偿 D1 扫描面）----")
    forbidden = _load_forbidden_calls()
    check("E 取到 test_gui_command_unification 的 _FORBIDDEN_CALLS 禁集",
          forbidden is not None and len(forbidden) > 20, len(forbidden or ()))
    if forbidden:
        rels = [MW_REL] + [os.path.join(PANELS_REL, _f + ".py") for _f, _c in MIXINS]
        all_hits = []
        for rel in rels:
            h = _scan_forbidden(rel, forbidden)
            all_hits.extend([(rel, a, ln) for a, ln in h])
            check("E %-46s 禁集直调 = 0" % rel, not h, h[:3])
        check("E 禁集直调总数 = 0（main_window + 12 mixin 全扫）", not all_hits,
              all_hits[:6])

    print("---- F. MRO：LoomGUI = (12 mixin, QMainWindow) ----")
    try:
        from gui.main_window import LoomGUI
    except Exception as exc:
        check("F 可导入 gui.main_window.LoomGUI", False, repr(exc))
        LoomGUI = None
    if LoomGUI is not None:
        mro = [c.__name__ for c in LoomGUI.__mro__]
        bases = [c.__name__ for c in LoomGUI.__bases__]
        for _f, cname in MIXINS:
            check("F MRO 含 %s" % cname, cname in mro, mro)
        check("F MRO 含 QMainWindow", "QMainWindow" in mro)
        check("F LoomGUI 直接基类数 = 13（12 mixin + QMainWindow）",
              len(bases) == 13, bases)
        check("F 12 个 mixin 全部排在 QMainWindow 之前（否则被 Qt 遮蔽）",
              all(mro.index(c) < mro.index("QMainWindow") for _f, c in MIXINS), mro)
        check("F 基类声明顺序 = MIXINS 列表顺序（可审计）",
              bases[:-1] == [c for _f, c in MIXINS], bases)
        sample = ["_build_toolbar", "_rebuild_hierarchy", "_rebuild_inspector",
                  "_rebuild_resources", "_build_console", "_cmd_settings",
                  "_refresh_status", "_build_ui_tree_dock", "_cmd_play",
                  "_draw_gizmo", "_invoke_cmd", "_wait_until"]
        check("F 代表性面板方法确实绑定到 LoomGUI（MRO 可调）",
              all(callable(getattr(LoomGUI, n, None)) for n in sample),
              [n for n in sample if not callable(getattr(LoomGUI, n, None))])

    print("")
    if _fails:
        print("FAIL test_gui_split: %d 项未通过" % len(_fails))
        for f in _fails:
            print("  FAIL " + f)
        return 1
    print("PASS test_gui_split: 全部通过 (" + str(_pass_n) +
          " 项) —— LoomGUI 已按域拆 mixin，131 方法不减")
    return 0


if __name__ == "__main__":
    sys.exit(main())
