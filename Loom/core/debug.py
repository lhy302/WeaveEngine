# -*- coding: utf-8 -*-
"""loom_debug.py — 崩溃可见性（2026-11-10 编译版「开后处理必崩」排查用）。

faulthandler 默认把崩溃栈打印到 stderr；编译版 release 是 `--windows-console-mode=disable`，
stderr 看不见。因此支持两种形式：
  LOOM_FAULTHANDLER=1            -> 打到 stderr（dev/带控制台账）
  LOOM_FAULTHANDLER=<路径.txt>   -> 追加写文件（release 档取证）

只在显式设置环境变量时启用：发布档零开销、零行为变化（不改变任何渲染路径）。
"""
import faulthandler
import os

_off = ("0", "off", "false", "no", "")
_on = ("1", "on", "true", "yes")


def enable_if_requested():
    v = (os.environ.get("LOOM_FAULTHANDLER") or "").strip()
    if v.lower() in _off:
        return None
    try:
        if v.lower() in _on:
            faulthandler.enable(all_threads=True)
            return None
        f = open(v, "w", encoding="utf-8", buffering=1)
        faulthandler.enable(file=f, all_threads=True)
        return f
    except Exception as e:
        print("[debug] faulthandler 启用失败: %r" % (e,))
        return None
