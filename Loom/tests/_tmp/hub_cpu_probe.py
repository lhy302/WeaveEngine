# -*- coding: utf-8 -*-
"""hub_cpu_probe.py — LoomHub 空闲 CPU 量化 (2026-08-15).

在主线程驱动 LoomHubGUI.run 同款循环, 测进程 CPU%:
  [idle]  无事件 (脏驱动: 应跳过重绘, 近似 0 CPU)
  [mouse] 每帧注入 MOUSEMOTION (文字缓存生效: 重绘只 blit 缓存表面, 便宜)
用法: py -3.12 tests\_tmp\hub_cpu_probe.py
"""
import ctypes
import os
import sys
import time

from ctypes import wintypes

# 工作区根 = Loom(py源代码)\  (本文件在 ...\Loom\tests\_tmp\, 上溯 4 层)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for p in (os.path.join(ROOT, 'LoomHub'), os.path.join(ROOT, 'Loom'),
          ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


class _FT(ctypes.Structure):
    _fields_ = [('lo', wintypes.DWORD), ('hi', wintypes.DWORD)]


def process_cpu_ms():
    """当前进程 (kernel+user) CPU ms."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.GetProcessTimes.argtypes = ([wintypes.HANDLE]
                                    + [ctypes.POINTER(_FT)] * 4)
    ct, et, kt, ut = _FT(), _FT(), _FT(), _FT()
    if not k32.GetProcessTimes(k32.GetCurrentProcess(),
                               ctypes.byref(ct), ctypes.byref(et),
                               ctypes.byref(kt), ctypes.byref(ut)):
        return 0.0
    def _ms(ft):
        return (ft.hi << 32 | ft.lo) / 10000.0
    return _ms(kt) + _ms(ut)


def measure(seconds, inject_motion):
    import pygame
    from LoomHubGUI import LoomHubGUI
    from hub_controller import HubController
    view = LoomHubGUI(HubController(), w=980, h=640)
    clock = pygame.time.Clock()
    view._last_err = None
    start = time.perf_counter()
    cpu0 = process_cpu_ms()
    frames = 0
    drawn = 0
    while time.perf_counter() - start < seconds:
        view._click = None
        view._wheel = None
        view._sb_released = False
        view._mouse_pos = pygame.mouse.get_pos()
        dirty = view._force_redraw
        view._force_redraw = False
        if inject_motion:
            # 每帧注入一次鼠标移动 -> 有事件 -> 走完整重绘 (文字缓存生效的代价)
            pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION,
                                                 {'pos': view._mouse_pos}))
        for ev in pygame.event.get():
            dirty = True
            if ev.type == pygame.MOUSEMOTION:
                view._mouse_pos = ev.pos
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                view._click = ev.pos
        if dirty:
            try:
                view._draw()
                drawn += 1
            except Exception:
                pass
            pygame.display.flip()
        frames += 1
        clock.tick(60)
    wall = time.perf_counter() - start
    cpu1 = process_cpu_ms()
    pct = (cpu1 - cpu0) / (wall * 1000.0) * 100.0
    view._done = True
    pygame.quit()
    return pct, frames, drawn


if __name__ == '__main__':
    # 先做一次冷启动 (字体加载等), 不计入
    p0, _, _ = measure(1.0, False)
    print("冷启动预热完成")
    p_idle, fr_i, dr_i = measure(3.0, False)
    print("[idle]  3s: CPU=%.1f%%  帧=%d 重绘=%d (脏驱动应跳过绝大部分重绘)"
          % (p_idle, fr_i, dr_i))
    p_mouse, fr_m, dr_m = measure(3.0, True)
    print("[mouse] 3s: CPU=%.1f%%  帧=%d 重绘=%d (每帧事件+重绘, 文字缓存代价)"
          % (p_mouse, fr_m, dr_m))
    print("结论: idle CPU 应从 ~60%% 降到接近 0%%; mouse 每帧重绘应为个位数%%")
