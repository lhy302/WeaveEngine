# -*- coding: utf-8 -*-
"""smoke_glfw_boot.py — GLFW 引擎窗口开窗冒烟 (2026-10-18)

拉起真实 GLFW 窗口 + moderngl 渲染 N 秒后自动关闭。
验证：
  1) GLFW 窗口能创建 + GL 上下文可用
  2) moderngl.create_context() 复用成功
  3) PlayerApp 渲染循环不崩溃
  4) GLFW 窗口关闭后进程干净退出
用法: py -3.12 smoke_glfw_boot.py [秒数, 默认 3]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

_secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0

import runtime
from engine import GLEngine

# 建一个最小 PlayerApp（不加载场景：空场景也能渲染）
eng = runtime.PlayerApp(None, 960, 600, scene_data={
    'models': [], 'materials': [], 'lights': [], 'cameras': [],
    'ui': {'canvases': []},
})
print('[smoke] PlayerApp 已创建，窗口类型=%r' % type(eng.window))
print('[smoke] GL 版本:', eng.ctx.info.get('GL_VERSION', '?'))

# GLEngine.__init__ 末尾默认 _running=False（等 run() 方法里设 True 再进循环）。
# 冒烟脚本手动循环，需要显式启动。
eng._running = True
eng.last_frame_time = time.perf_counter()

t0 = time.perf_counter()
frames = 0
while time.perf_counter() - t0 < _secs and eng._running:
    eng._handle_events()
    now = time.perf_counter()
    dt = min(now - eng.last_frame_time, 0.1)
    eng.last_frame_time = now
    eng.move_camera(dt)
    eng.rotate_camera(dt)
    eng.render(dt)
    frames += 1
    time.sleep(0.001)   # 避免空转占 CPU

elapsed = time.perf_counter() - t0
print('[smoke] 跑了 %d 帧 / %.2f 秒 (%.1f FPS)' % (frames, elapsed, frames / elapsed))
print('[smoke] 关闭窗口...')

eng._glfw_shutdown()
try:
    eng._stop_parallel()
except Exception:
    pass
try:
    eng.audio.shutdown()
except Exception:
    pass
print('[smoke] SMOKE_PASS')
