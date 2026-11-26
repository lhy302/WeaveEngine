# -*- coding: utf-8 -*-
"""editor/core_contract.py — 编辑器常量/纯工具函数单点（契约层）。

Q-B7-38-1 第 9 批（agent-99）：从 editor/core.py 抽出的**契约/常量单点**
（开发要求_功能解耦与模块化.md 规则 1 的「契约/常量单点」例外）：只有目录常量、
文件对话框筛选串、默认文件名去重纯函数。

我负责：APP_DIR / DEFAULT_SAVE_DIR / _LEGACY_SAVE_DIR / STATE_FILE /
        _SCENE_FILTER / _PREFAB_FILTER / unique_default_name。
我不负责：任何读写行为（state 文件读写与对话框记忆仍在 editor/core.py：
          monkeypatch 目标 = editor.core.<name>，消费点必须在 core 模块全局解析）。

editor/core.py 以 from editor.core_contract import ... 按名绑定，故
editor.core.STATE_FILE / DEFAULT_SAVE_DIR 等的读与 patch 语义不变；
本模块不 import editor.core（无循环依赖）。
"""
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2026-10-19 用户拍板 B2: 项目目录改名 "保存" -> "Projects"（Unity 习惯）
# 兼容：首次启动时如果旧 "保存/" 存在且 "Projects/" 不存在，自动 rename
DEFAULT_SAVE_DIR = os.path.join(APP_DIR, 'Projects')  # 默认项目文件夹 (未选过目录时)
_LEGACY_SAVE_DIR = os.path.join(APP_DIR, '保存')
STATE_FILE = os.path.join(APP_DIR, 'editor_state.json')  # 记忆上次保存目录

def unique_default_name(directory, base, ext):
    """默认文件名冲突时自动加数字: base -> base1 -> base2 ... (ext 含点, 如 '.json').
    返回第一个不存在的文件名 (不含扩展名). base 若自带扩展名会被去掉."""
    base = os.path.splitext((base or '场景').strip())[0] or '场景'
    for i in range(1000):
        name = base if i == 0 else '%s%d' % (base, i)
        if not os.path.exists(os.path.join(directory, name + ext)):
            return name
    return base + '999'

_SCENE_FILTER = "场景文件 (*.json)\0*.json\0所有文件 (*.*)\0*.*\0"
_PREFAB_FILTER = "Prefab 文件 (*.prefab)\0*.prefab\0所有文件 (*.*)\0*.*\0"
