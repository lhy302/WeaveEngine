# -*- coding: utf-8 -*-
"""editor/viewport/ — 编辑器视口域（B4 批）。

  event_bridge.py  ★后端无关视口事件桥唯一实现（_ViewportEventBridge +
                   Qt 事件翻译常量）—— gui/gl_viewport.py、gui/remote_viewport.py
                   与本包 vk_viewport.py 三端共用同一份（S5 留痕收口）。
  vk_viewport.py   VkViewport（QRenderWidget bitmap + VkEditorApp 装配，
                   B6 建、B4 归位；旧名 ui.vk_viewport 经 sys.modules
                   别名门面保仓外）。

与 render/、scene/ 包同纪律：本包入口刻意不 re-export。
"""
