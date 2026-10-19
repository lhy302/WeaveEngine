# -*- coding: utf-8 -*-
"""loom_log.py — 启动日志开关 (2026-10-19)

背景：用户从 LoomHub 双击启动时，控制台刷出 8+ 行 [parallel]/[sched]/[Qt]
启动信息，影响体验。命令行直接启动时这些信息有用。
用户拍板：LoomHub 启动 -> 静默；命令行启动 -> 保留。

方案：环境变量 LOOM_QUIET=1 时抑制启动信息（verbose）。
      LoomHub 启动 Loom 子进程时自动设 LOOM_QUIET=1（见 hub_commands.launch_spec
      和 hub_controller.open_project）。

保留原则：
  - 运行期错误（[脚本]出错 / [物理]异常）继续 print，用户必须能看到
  - 用户主动操作反馈（保存成功/加载成功）继续 print
"""
import os


def is_quiet():
    """当前是否静默模式（LoomHub 启动时为 True）."""
    return bool(os.environ.get('LOOM_QUIET'))


def verbose(*args, **kwargs):
    """启动阶段信息（可被 LOOM_QUIET 抑制的 print）.

    用法与 print 相同：verbose("[parallel] 初始化完成")
    """
    if is_quiet():
        return
    print(*args, **kwargs)


def verbose_enabled():
    """verbose 是否生效（用于需要条件判断的复杂场景）."""
    return not is_quiet()
