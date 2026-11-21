# -*- coding: utf-8 -*-
"""editor/ — 编辑器域包（目录重构 B4 批，2026-11-21，Q-B7-38-1 收口批）。

成员（原 3152 行 Loom/editor.py 按域拆）：
  core.py     _EditorCore（编辑器 ~140 方法的唯一实现，后端无关；含
              文件对话框记忆/场景读写/选择与 gizmo/检查器命令/播放态装配）
  app.py      EditorApp(_EditorCore, GLEngine) —— GL 编辑器装配入口
  vk_app.py   VkEditorApp(_EditorCore, SceneDriver) —— VK 编辑器装配（S4）
              + _VkGlStateShim（editor.render 帧首 GL 状态复位壳）
  undo/       撤销/重做包（原 1392 行 Loom/undo.py 按命令域拆，见 undo/__init__.py）
  viewport/   VK 编辑器视口（原 ui/vk_viewport.py，B6 建 B4 归位）+
              event_bridge.py —— ★后端无关视口事件桥唯一实现
              （GL gl_viewport / Remote remote_viewport / VK vk_viewport
              三端共用同一份 _ViewportEventBridge，S5 留痕收口）

旧名兼容：本包**沿用旧导入名 'editor'**（包 __init__ re-export 即门面）——
仓内/用户脚本 `from editor import EditorApp` 一行不改；与 B3/B6 的
sys.modules 别名先例不同：旧名 == 新包名，别名门面无处安放也不需要，
re-export 已保证读/写（类与函数对象同一份）语义。
模块级**可变常量**（DEFAULT_SAVE_DIR/_LEGACY_SAVE_DIR/STATE_FILE）的唯一
真源在 editor.core；monkeypatch 请指向 editor.core（仓内测试已同步改指）。
"""
# 旧 editor.py 的全部模块级公开名（含其 import 进来的 math/np/pygame/GLEngine/
# UndoManager... 名字面）由 core 原样承载，import * 逐名对齐旧命名空间。
from editor.core import *          # noqa: F401,F403
from editor.core import (          # noqa: F401  下划线名（import * 不带）——
    _EditorCore,                   # 后端无关编辑器中间基类（GL/VK 共用）
    _CameraProjCommand,            # 相机投影撤销命令（_EditorCore 内部用）
    _editor_skybox_provider,       # 天空 pass 绘制源（app.py 装配用）
    _LEGACY_SAVE_DIR,              # 旧「保存/」目录兼容（测试隔离用）
    _SCENE_FILTER, _PREFAB_FILTER, # 文件对话框筛选串（test_filedialog_helpers 读）
)
from editor.app import EditorApp       # noqa: F401  GL 编辑器装配
from editor.vk_app import (            # noqa: F401  VK 编辑器装配
    VkEditorApp,
    _VkGlStateShim,
)
