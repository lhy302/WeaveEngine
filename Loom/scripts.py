# -*- coding: utf-8 -*-
"""scripts.py — 薄门面（目录重构 B6 批，2026-11-21）。

scripts 本体（828 行，原 Loom/scripts.py）已整体搬到 script/scripts.py；
本文件把旧导入名 'scripts' **别名**到新模块（sys.modules 换身），仓外旧调用面一行不改:
  - 用户游戏脚本（Projects/ 等仓外工程的 from scripts import Script, register）
  - 已发布游戏包里的脚本（register_sources exec 的源码）

仓内全部调用面已改指 script.scripts（生产/测试/示例逐文件重写，见 B6 提交说明）；
script/scripts.py 尾部另有一道 setdefault 别名兜底（Nuitka 打包版 dist 不含本门面，
靠那道别名安装旧名）。为什么用 sys.modules 别名而不是逐名 re-export: scripts 携带
模块级可变状态（SCRIPTS 注册表等），别名保证读/写/monkeypatch 全部落在**同一个
模块对象**上，语义逐位不变（先例 = B3 批 engine.py 薄门面）。
"""
import sys as _sys

from script import scripts as _scripts

_sys.modules[__name__] = _scripts
