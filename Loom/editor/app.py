# -*- coding: utf-8 -*-
"""editor/app.py — GL 编辑器装配（目录重构 B4 批，2026-11-21）。

EditorApp 本体（原 Loom/editor.py 尾段的 GL 装配类，Q-B7-47-1 五阶段·阶段 2）
按域归位到 editor/ 包；编辑器能力全部在 editor.core._EditorCore（后端无关
中间基类，GL/VK 同一份），本类只保留 __init__（装配入口），其余成员全部继承。

旧导入名 'editor' 由 editor/ 包本身沿用（包 __init__ re-export 即门面，
from editor import EditorApp 一行不改）。
"""
from engine import GLEngine

from editor.core import _EditorCore, _editor_skybox_provider


class EditorApp(_EditorCore, GLEngine):
    """GL 编辑器入口（Q-B7-47-1 五阶段·阶段 2，行为零变化）。

    编辑器能力在 _EditorCore（后端无关中间基类）；GL 装配在 GLEngine。本类只保留
    __init__（装配入口），其余成员全部继承自 _EditorCore。
    S4：编辑器状态装配收进 _EditorCore._init_editor_state（GL/VK 同一份）；
    VK 编辑器 = VkEditorApp(_EditorCore, SceneDriver)（本类下方）。
    """

    def __init__(self, width=1280, height=800, scene_path=None, view=None, ctx=None):
        # ctx 注入 = 嵌入式模式 (Qt 宿主): 见 GLEngine.__init__ 注释 (IME 污染修复)
        super().__init__(width, height, ctx=ctx)
        # 2026-11-10 阶段 2A: 天空 pass 的绘制源用编辑器版（失败每帧打印, 与迁移前一致）
        self._frame_executor.draws['skybox'] = _editor_skybox_provider
        # S4: 编辑器状态装配 = _EditorCore._init_editor_state（唯一实现，GL/VK 共用）
        self._init_editor_state(scene_path=scene_path, view=view)
