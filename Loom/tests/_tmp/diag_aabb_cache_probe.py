# -*- coding: utf-8 -*-
"""diag_aabb_cache_probe.py — aabbs 行级缓存播放态真实性探针 v2 (任务5)

真 Qt 路径 + 时间窗驱动 (QTimer 节律由 processEvents 泵)。
每 2s 窗口打印: aabbs batched 调用形态 (n, 墙钟) / 缓存 changed 行数 /
stage 差分账。只读测量。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
BASE = sys.path[0]
os.chdir(BASE)
os.environ['LOOM_PROFILE'] = '1'
os.environ.setdefault('LOOM_NO_NUMBA', '1')

sys.argv[0] = os.path.join(BASE, 'Loom.py')

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtGui import QSurfaceFormat            # noqa: E402

fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setSamples(4)
fmt.setSwapInterval(0)
QSurfaceFormat.setDefaultFormat(fmt)

import numpy as np                                  # noqa: E402
from ui.loom_gui import LoomGUI                     # noqa: E402

scene = os.path.join(BASE, '保存', '压测500混合.json')
app = QApplication(sys.argv)
win = LoomGUI(scene_path=scene, width=1280, height=800)
win.show()
e = None
for _ in range(300):
    app.processEvents()
    if win.editor is not None and win.editor.ctx is not None:
        e = win.editor
        break
    time.sleep(0.02)
print("[probe] editor=%s models=%d" % ('OK' if e else 'FAIL',
                                       len(e.models) if e else 0), flush=True)

_orig_batched = e._aabbs_batched
calls = []


def counted_batched(models, fw, visible_only=True, _row_cache=True):
    t0 = time.perf_counter()
    r = _orig_batched(models, fw, visible_only, _row_cache)
    calls.append((len(models), (time.perf_counter() - t0) * 1000.0,
                  bool(visible_only)))
    return r


e._aabbs_batched = counted_batched

win._cmd_play()
t_end = time.perf_counter() + 3.0
while time.perf_counter() < t_end:      # 3s 预热
    app.processEvents()

st_prev = dict(e._stage_times)
fps_prev = e.frame_count
calls.clear()
t_end = time.perf_counter() + 12.0
win_i = 0
while time.perf_counter() < t_end:
    w0 = time.perf_counter()
    calls.clear()
    f0 = e.frame_count
    t0s = time.perf_counter()
    while time.perf_counter() - w0 < 2.0:
        app.processEvents()
    win_i += 1
    st_now = dict(e._stage_times)
    f_now = e.frame_count
    dt = time.perf_counter() - t0s
    frames = f_now - f0
    c = getattr(e, '_aabb_row_cache', None)
    nch = None
    if c is not None and c[3] is not None and e._frame_world is not None \
            and e._frame_world.shape == c[3].shape:
        nch = int(np.any(e._frame_world != c[3], axis=(1, 2)).sum())
    chunk = [(n, round(t, 2)) for n, t, _v in calls]
    tot = sum(t for _n, t, _v in calls)
    print("[w%d] frames=%d (%.1f fps) | changed=%s | batched n=%d tot=%.1fms "
          "chunks=%s | aabbs_d=%.2f logic_d=%.2f pipe_d=%.2f ms/帧"
          % (win_i, frames, frames / dt, nch, len(calls), tot,
             chunk[:10],
             (st_now.get('aabbs', 0) - st_prev.get('aabbs', 0)) / max(frames, 1),
             (st_now.get('logic_step', 0) - st_prev.get('logic_step', 0)) / max(frames, 1),
             (st_now.get('pipe_wait', 0) - st_prev.get('pipe_wait', 0)) / max(frames, 1)),
          flush=True)
    st_prev = st_now

if e.is_playing:
    win._cmd_play()
for _ in range(30):
    app.processEvents()
e._stop_parallel()
print("\n完成。", flush=True)
