# -*- coding: utf-8 -*-
"""一次性验证脚本 (子进程+超时运行, 崩也只死子进程, 不伤终端):
真实窗口 -> 渲染 1 帧 -> 切假全屏(NOFRAME, 不切分辨率) -> 渲染 5 帧
-> 切回窗口 -> 渲染 1 帧. 任何一步失败/崩溃都有非零退出码."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pygame
import engine as E

def main():
    eng = E.GLEngine(800, 600)
    eng._running = True
    eng.render(1 / 60)
    print("R1 windowed render OK", flush=True)
    eng._toggle_fullscreen()
    print("FS=on size=%dx%d window_size=%s" % (eng.width, eng.height, eng.window_size),
          flush=True)
    if eng.fullscreen:
        import ctypes
        user32 = ctypes.windll.user32
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        print("SYSTEM=%dx%d FSsize=%dx%d (FSsize 应等于系统桌面, 且 SYSTEM 不变=未切分辨率)"
              % (sw, sh, eng.width, eng.height), flush=True)
    eng.render(1 / 60)
    print("R2 fullscreen render OK  ctx alive", flush=True)
    for i in range(3):
        eng.render(1 / 60)
    print("R3-R5 fullscreen frames OK", flush=True)
    eng._toggle_fullscreen()
    print("FS=off size=%dx%d" % (eng.width, eng.height), flush=True)
    eng.render(1 / 60)
    print("R6 windowed render OK", flush=True)
    pygame.quit()
    print("ALL OK", flush=True)

try:
    main()
except SystemExit:
    raise
except Exception as e:
    print("PROBE ERROR:", repr(e), flush=True)
    try:
        pygame.quit()
    except Exception:
        pass
    sys.exit(2)
