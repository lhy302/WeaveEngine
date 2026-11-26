# -*- coding: utf-8 -*-
"""agent_commands.py — EAI 命令层「兼容 shim」(Q-B7-38-1 第 6 批, 2026-11-26)
====================================================================
原 4222 行单文件已按域拆成 eai/ 包 (一个功能一个文件 + 按层共享前置库)。
本文件只保留一个用途: 让全仓既有的 `import agent_commands as ac` /
`agent_commands.X` 继续按原样工作 —— 它把自身换成 eai 包模块对象
(`sys.modules[__name__] = eai`), 于是:
  · `agent_commands is eai` (同一个模块对象, 不是两份命名空间);
  · `ac.X` / `from agent_commands import X` 全部等价于 eai.X;
  · `ac._auto_focus_enabled = 替身` 这类猴补丁语义不变 (eai 包把赋值转发到真身模块)。

选「保留 shim」而不是「同步改全部调用点」的理由: 调用点分散在 gui/ hostenv/ ui/
tools/ 与 15 个测试文件里 (含 test_agent_commands.py 的桩层), 全改会把「纯搬家」
变成「搬家 + 大面积改调用点」, 违反 docs/guides/开发要求_功能解耦与模块化.md §3
「一次只搬一个域、行为零变化」。shim 只有一处 sys.modules 赋值; 将来若要彻底改名,
删掉本文件 + 改 20 处引用即可。

新代码请直接 `import eai`。
"""
import sys

import eai as _eai

sys.modules[__name__] = _eai
