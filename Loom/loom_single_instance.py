# -*- coding: utf-8 -*-
"""loom_single_instance.py — Loom 编辑器单实例锁（2026-10-19）

背景：LoomHub 出现"连点开 17 个窗口"问题后，用户要求 Loom 也加单实例锁。

锁策略：
  - 仅 Qt 编辑器模式加锁（--open / 无参数走编辑器 / 插件编辑器）
  - --run（PlayerApp 运行时）不加锁（玩家可能想同时开多个游戏实例）
  - --benchmark 不加锁（纯计算）
  - 游戏配置.json 玩家模式不加锁（同 --run）
  - 多场景编辑器也算一实例（同一时间只允许一个编辑器）

用法（Loom.py 的编辑器分支）：
    from loom_single_instance import ensure_editor_single_instance
    ensure_editor_single_instance(scene_path=open_scene)
    # 若已有编辑器实例：
    #   - 如果第二次启动带了不同场景，会尝试激活已有编辑器并退出
    #   - 用户想编辑另一个场景时，请先关掉已有编辑器
"""
import ctypes
import sys
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183
EDITOR_WINDOW_TITLE = 'Loom — 编辑器 (Qt)'
EDITOR_MUTEX_NAME = 'Global\\Loom_Editor_SingleInstance'


def _find_window_by_title(title):
    """按窗口标题精确/模糊查找 HWND（只找可见的顶层窗口）."""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        return hwnd
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
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found[0]


def _activate_window(hwnd):
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)      # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return True


def ensure_editor_single_instance(scene_path=None):
    """编辑器单实例保护. 只应在进入 Qt 编辑器模式时调用.

    - 第一个编辑器实例：返回 True，程序继续
    - 已有编辑器：激活已有窗口，本进程 sys.exit(0)
    - 如果传入 scene_path 且已有编辑器运行的场景不同：提示用户后退出
    """
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, EDITOR_MUTEX_NAME)
    err = kernel32.GetLastError()

    if err == ERROR_ALREADY_EXISTS:
        hwnd = _find_window_by_title(EDITOR_WINDOW_TITLE)
        if hwnd:
            _activate_window(hwnd)
        if scene_path:
            try:
                print("[编辑器] 已有编辑器实例在运行。要打开新场景 %r，"
                      "请先关闭已有编辑器窗口后再启动。" % scene_path)
            except Exception:
                pass
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        sys.exit(0)
    return True
