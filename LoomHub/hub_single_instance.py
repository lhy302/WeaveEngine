# -*- coding: utf-8 -*-
"""hub_single_instance.py — LoomHub 单实例锁（2026-10-19）

背景：用户报告"双击启动后开 17 个 LoomHub 窗口"。根因：
  - PyInstaller --onefile 启动慢（2~5 秒解压+杀毒扫描）
  - 无单实例锁
  - 用户以为没反应，连点 17 次 -> 17 个独立进程

修复：Windows 命名 mutex + 第二次启动时激活已有窗口 + 退出。

用法（LoomHub.py 入口最顶部）：
    from hub_single_instance import ensure_single_instance
    ensure_single_instance('LoomHub — 项目管理器', 'Global\\LoomHub_SingleInstance')
    # 如果已有实例，本函数内部会激活它然后 sys.exit(0)
"""
import ctypes
import os
import sys
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183


def _find_window_by_title(title):
    """按窗口标题精确查找 HWND（只找可见的顶层窗口）."""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        return hwnd
    # 有些窗口会被加后缀（如 "标题 — Chrome"），用 EnumWindows 模糊匹配
    found = [None]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

    def _cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, buf, n + 1)
        if title in buf.value:
            found[0] = h
            return False   # 找到就停
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found[0]


def _activate_window(hwnd):
    """把窗口提到前台（绕过 Windows 前台锁）."""
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return True


def ensure_single_instance(window_title, mutex_name):
    """单实例保护入口.

    - 第一个实例：返回 True，程序继续
    - 已有实例：激活已有窗口后 sys.exit(0)，不返回
    """
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    err = kernel32.GetLastError()

    if err == ERROR_ALREADY_EXISTS:
        # 已有实例：激活 + 退出
        hwnd = _find_window_by_title(window_title)
        if hwnd:
            _activate_window(hwnd)
        # 关闭自己创建的 mutex handle（虽然要退了）
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        sys.exit(0)
    # 第一个实例：handle 保持打开（进程退出时系统自动关闭 = mutex 释放）
    return True
