# -*- coding: utf-8 -*-
"""undo.py — 薄门面（目录重构 B4 批，2026-11-21）。

undo 本体（1392 行，原 Loom/undo.py）已按命令域拆到 editor/undo/ 包
（registry / cmd_object / cmd_light / cmd_camera / cmd_scene）；
本文件把旧导入名 'undo' **别名**到新包（sys.modules 换身），仓外旧调用面一行不改:
  - 用户游戏脚本 / 仓外工具的 import undo / from undo import UndoManager, ...
  - 历史探针脚本

仓内全部调用面已改指 editor.undo（生产/测试逐文件重写，见 B4 提交说明）。
为什么用 sys.modules 别名而不是逐名 re-export: 别名保证读/写/monkeypatch
全部落在**同一个包对象**上，语义逐位不变（先例 = B2 sceneio / B3 engine /
B6 scripts 薄门面）。注：同目录普通包会遮蔽同名 .py —— 旧名 == 新包首段
不同名（undo ≠ editor.undo），本门面正常可被 import 机制选中。
"""
import sys as _sys

from editor import undo as _undo

_sys.modules[__name__] = _undo
