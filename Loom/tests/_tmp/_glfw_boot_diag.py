# -*- coding: utf-8 -*-
"""_glfw_boot_diag.py — 诊断为什么循环 0 帧"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

_secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
print('argv=', sys.argv)
print('_secs=', _secs)

import runtime
eng = runtime.PlayerApp(None, 320, 240, scene_data={
    'models': [], 'materials': [], 'lights': [], 'cameras': [],
    'ui': {'canvases': []},
})
print('eng._running =', eng._running)
print('has _glfw_win =', hasattr(eng, '_glfw_win'))
print('last_frame_time =', getattr(eng, 'last_frame_time', 'N/A'))
print('perf_counter now =', time.perf_counter())

t0 = time.perf_counter()
print('loop condition: elapsed=%.4f < _secs=%.4f and eng._running=%r' % (
    time.perf_counter() - t0, _secs, eng._running))
print('loop condition eval =', (time.perf_counter() - t0 < _secs and eng._running))

eng._glfw_shutdown()
