# -*- coding: utf-8 -*-
"""
editor_ui.py — IEditorView 契约: Loom 编辑器 UI 接口标准 (UI 模块化 2026-08-13)

Loom 编辑器三层解耦 (依赖单向向下):
    UI 实现层  ui/LoomGUI.py (默认) / ui/minimal_editor_view.py (极简)  [可替换]
    UI 接口层  IEditorView (本文件)
    控制器层   editor.py EditorController (引擎能力 + 编辑命令 + 状态 + 撤销)
    引擎/数据层 engine.py / sceneio.py / scripts.py / gui.py / ...

控制器 (EditorController) 每帧驱动 UI:
    render():   view.draw(self, delta)        # UI 画全部面板 + 视口叠加
    on_key:     view.handle_key_event(ev)     # UI 键盘输入, True=已消费
    toggle_play: view.reset_interaction()     # 播放边界清 UI 交互残留
    _update_gizmo/_update_camera: view.input_state()  # UI 当前输入/焦点/点击捕获

换 UI = 新写一个类实现本契约, 注入 EditorController (构造参数 ui=...).
约定: UI 通过 controller 的公开 API 读写 (只读状态 / 命令), 不 import
undo/sceneio 等逻辑细节; 引擎对象引用仅用于只读显示与作为命令参数.
"""
import abc


class IEditorView(abc.ABC):
    """Loom 编辑器视图契约. 任何 UI 后端实现本接口即可被 Loom 编辑器使用.

    UI 通过 controller 的公开 API 读写一切:
      只读: controller.selected_* / .models / .lights / .cameras / .materials /
            .scene_name / .prefab_name / .gizmo_mode / .is_playing / .camera* /
            ._selected() / ._selected_light() / ._selected_camera() /
            .layout() / ._scan_assets() 等
      命令: controller._add_primitive(typ) / ._import_obj() / ._add_light(kind) /
            ._add_camera() / .duplicate_object() / .delete_object() /
            .toggle_play() / ._save_scene() / ._load_scene() / ._new_scene() /
            ._save_prefab() / ._instantiate_prefab() / ._undo_action() /
            ._redo_action() / ._save_mesh_asset() / ._save_material_asset() /
            .select_model() / .set_gizmo_mode() / .edit_model() / .commit_model() /
            .rename() / .edit_light() / .commit_light() / .rename_light() /
            .edit_camera() / .commit_camera() / .rename_camera() / .toggle_visible() /
            .play_anim() / .add_script() / .set_script_var() / .remove_script() 等
    所有"会改变引擎状态"的写操作必须经 controller 命令 (内部自动走撤销),
    UI 不直接 push undo.
    """

    def attach(self, controller):
        """绑定控制器 (EditorController). 通常在 __init__ 完成."""
        raise NotImplementedError

    def input_state(self):
        """返回 UI 当前输入/交互状态 dict:
            {mouse_pos, buttons, pressed, released, wheel,
             click_captured, focus_id}
        供控制器判断 gizmo/相机交互是否被 UI 抢占 (原本读 gui 内部状态)."""
        raise NotImplementedError

    def handle_key_event(self, ev):
        """UI 键盘事件 (输入框聚焦时吃键). 返回 True = 已消费."""
        raise NotImplementedError

    def reset_interaction(self):
        """清空跨帧交互状态 (播放边界 / 系统模态对话框返回后)."""
        raise NotImplementedError

    def draw(self, controller, delta_time):
        """画全部 UI (视口叠加 + 各面板). 控制器 render() 每帧调用."""
        raise NotImplementedError
