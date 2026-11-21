# -*- coding: utf-8 -*-
"""gui/ — 编辑器 Qt 视图层包（目录重构 B4 批，2026-11-21）。

成员（原 4339 行 ui/loom_gui.py 按类拆 + 遗留视图归位）：
  main_window.py     LoomGUI 主窗口（工具栏/层级/检查器/资源浏览器/状态栏/
                     控制台坞 全部面板方法 + run_loom_gui 入口）—— LoomGUI 是
                     单一类（面板均为其方法，无独立面板类），故不再拆 panels/
                     子包（留痕：拆 mixin 超出本批「纯搬家」纪律）
  gl_viewport.py     GLViewport（QOpenGLWidget + moderngl）
  remote_viewport.py RemoteViewport（离屏 GL readback 兜底）
  widgets/           自定义控件（AssetListWidget / DraggableSpin / DragBlock）
  legacy_view.py     即时模式遗留视图（原 Loom/gui.py，仅 2 个测试引用，历史保留）

视口事件桥（鼠标/键盘 -> 引擎状态字段）的唯一实现在
editor/viewport/event_bridge.py —— GL/Remote/VK 三端共用（B4 收口）。

与 render/、scene/ 包同纪律：本包入口刻意不 eager re-export（main_window 拖
全量 PySide6/moderngl/agent_commands）；需要谁就显式
"from gui.main_window import LoomGUI" 导入。旧名兼容：ui/loom_gui.py 薄门面
以 sys.modules 别名指向 gui.main_window，仓外 'from ui.loom_gui import ...'
一行不改。

注（Windows 大小写不敏感）：磁盘目录名为大写 GUI/（插件 GUI 边界目录，
2026-08-20 安全加固文档所留），与包名 gui 同指一个目录；import gui 一律
解析到本包（GUI/__init__.py 存在后普通包优先级高于同名 gui.py 模块）。
"""
from gui import legacy_view as _legacy_view   # noqa: F401  显式带出遗留视图


def __getattr__(name):
    # PEP 562 惰性兼容：旧代码 'from gui import GUI' 仍可用（gui.py 时代的
    # 即时模式 GUI 类，现居 gui.legacy_view）。
    if name == 'GUI':
        return _legacy_view.GUI
    raise AttributeError('module %r has no attribute %r' % (__name__, name))
