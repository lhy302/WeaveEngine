# -*- coding: utf-8 -*-
"""net/ — 网络助手（HTTP / HTTPS，纯标准库）。

目录重构 B1 批（Q-B7-38-1 裁决 20 顶层包，2026-11-21）。成员：
  net    原 loom_net.py —— 网络助手，与游戏脚本 / Agent 桥共用同一套实现

公开 API 重导出（显式列出，不用 import *，可静态分析）。
"""
from net.net import (DEFAULT_TIMEOUT, DEFAULT_MAX_BYTES, http_request,
                     http_get, http_post_json, HttpRequestAsync, http_async)

__all__ = [
    'DEFAULT_TIMEOUT', 'DEFAULT_MAX_BYTES', 'http_request', 'http_get',
    'http_post_json', 'HttpRequestAsync', 'http_async',
]
