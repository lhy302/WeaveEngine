# -*- coding: utf-8 -*-
"""ui/loom_gui.py — 薄门面（目录重构 B4 批，2026-11-21）。

loom_gui 本体（4339 行，原 ui/loom_gui.py）已按类拆到 gui/ 包
（main_window / gl_viewport / remote_viewport / widgets / legacy_view）；
本文件把旧导入名 'ui.loom_gui' **别名**到新模块（sys.modules 换身），
仓外旧调用面一行不改:
  - 用户/仓外工具的 from ui.loom_gui import LoomGUI, run_loom_gui, ...
  - 历史探针脚本

仓内全部调用面已改指 gui.main_window（生产/测试逐文件重写，见 B4 提交说明）。
为什么用 sys.modules 别名而不是逐名 re-export: loom_gui 携带模块级可变状态
（_WINMM_PERIOD_SET 等）且测试有 lg.LoomGUI 类 attr 访问，别名保证读/写/
monkeypatch 全部落在**同一个模块对象**上，语义逐位不变（先例 = B3 engine /
B6 scripts 薄门面）。
"""
import sys as _sys

from gui import main_window as _main_window

_sys.modules[__name__] = _main_window
