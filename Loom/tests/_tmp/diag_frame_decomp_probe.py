# -*- coding: utf-8 -*-
"""diag_frame_decomp_probe.py — 播放态主线程帧成本分解 (任务5 残段定位)

进程内真 Qt 路径, monkeypatch 只计时 (不改行为):
  L (logic_step 内): update_scripts / _logic_prep(aabbs/bounds/collide) / pipe
  R (render 帧):     world_matrices / interp / buckets / _render_shadow_maps /
                     _draw_main_buckets / view.draw(Qt UI) / _consume_xform_gen /
                     sync_script_keys / _update_fps
  宿主:              _on_tick 单次成本 (QCursor/_update_camera/update)
设置: 临时写 unlimited/30 (备份还原)。
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
BASE = sys.path[0]
os.chdir(BASE)
os.environ['LOOM_PROFILE'] = '1'
os.environ.setdefault('LOOM_NO_NUMBA', '1')
sys.argv[0] = os.path.join(BASE, 'Loom.py')

# ---- 设置: 临时 unlimited/30 ----
_sp = os.path.join(BASE, '设置.json')
_sh = _sp + '.diagbak'
with open(_sp, 'r', encoding='utf-8') as f:
    _orig = f.read()
shutil.copyfile(_sp, _sh)
_s = json.loads(_orig)
_s.update({'fps_limit': 'unlimited', 'logic_fps': 30,
           'frame_buffer_tps': False, 'frame_buffer_fps': False})
with open(_sp, 'w', encoding='utf-8') as f:
    json.dump(_s, f, ensure_ascii=False, indent=2)

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtGui import QSurfaceFormat, QCursor    # noqa: E402

fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setSamples(4)
fmt.setSwapInterval(0)
QSurfaceFormat.setDefaultFormat(fmt)

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

# ================= monkeypatch 计时 =================
T = {}


def _wrap(obj, name, key):
    fn = getattr(obj, name)

    def w(*a, **kw):
        t0 = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            T[key] = T.get(key, 0.0) + (time.perf_counter() - t0)
    setattr(obj, name, w)
    return fn


o_scripts = _wrap(e, 'update_scripts', 'scripts')
o_prep = _wrap(e, '_logic_prep', 'logic_prep_total')
o_shadowmaps = _wrap(e, '_render_shadow_maps', 'gl_shadow_maps')
o_drawbuckets = _wrap(e, '_draw_main_buckets', 'gl_main_draw')
o_viewdraw = _wrap(e.view, 'draw', 'qt_view_draw')
o_ucam = _wrap(e, '_update_camera', 'on_tick_update_camera')
o_xform = _wrap(e, '_consume_xform_gen', 'consume_xform_gen')
o_sync = _wrap(e, 'sync_script_keys', 'sync_script_keys')

# paintGL 整体
vp = win.viewport
o_paint = vp.paintGL
paint_t = [0.0]
paint_n = [0]


def timed_paint():
    t0 = time.perf_counter()
    o_paint()
    paint_t[0] += time.perf_counter() - t0
    paint_n[0] += 1


vp.paintGL = timed_paint

# _on_tick 整体
o_tick = win._on_tick
tick_t = [0.0]
tick_n = [0]


def timed_tick():
    t0 = time.perf_counter()
    o_tick()
    tick_t[0] += time.perf_counter() - t0
    tick_n[0] += 1


win._on_tick = timed_tick

# QCursor.pos 单独计
o_qcursor = QCursor.pos
qc_t = [0.0]
qc_n = [0]


def timed_pos():
    t0 = time.perf_counter()
    r = o_qcursor()
    qc_t[0] += time.perf_counter() - t0
    qc_n[0] += 1
    return r


QCursor.pos = staticmethod(timed_pos)

win._cmd_play()
t_end = time.perf_counter() + 4.0
while time.perf_counter() < t_end:
    app.processEvents()

# ---- 测量窗 10s ----
T.clear()
paint_t[0] = paint_n[0] = 0
tick_t[0] = tick_n[0] = 0
qc_t[0] = qc_n[0] = 0
st0 = dict(e._stage_times)
f0 = e.frame_count
w0 = time.perf_counter()
t_end = w0 + 10.0
while time.perf_counter() < t_end:
    app.processEvents()
wall = time.perf_counter() - w0
st1 = dict(e._stage_times)
f1 = e.frame_count

frames = f1 - f0
print("\n===== 10s 窗: 墙钟 %.2fs, 渲染帧 %d (%.1f FPS), tick %d ====="
      % (wall, frames, frames / wall, tick_n[0]), flush=True)
print("-- monkeypatch 段 (ms/s 墙钟 | ms/渲染帧) --", flush=True)
order = ['scripts', 'logic_prep_total', 'on_tick_update_camera',
         'qt_view_draw', 'gl_shadow_maps', 'gl_main_draw',
         'consume_xform_gen', 'sync_script_keys']
for k in order:
    v = T.get(k, 0.0)
    print("  %-20s %8.1f ms/s  %7.2f ms/帧" % (k, v / wall, v / max(frames, 1)),
          flush=True)
print("  paintGL 总墙钟        %8.1f ms/s  %7.2f ms/帧"
      % (paint_t[0] / wall, paint_t[0] / max(paint_n[0], 1)), flush=True)
print("  _on_tick 总墙钟       %8.1f ms/s  %7.3f ms/次 (n=%d)"
      % (tick_t[0] / wall, tick_t[0] / max(tick_n[0], 1), tick_n[0]), flush=True)
print("  QCursor.pos           %8.1f ms/s  %7.4f ms/次 (n=%d)"
      % (qc_t[0] / wall, qc_t[0] / max(qc_n[0], 1), qc_n[0]), flush=True)
print("-- stage 差分 (ms/渲染帧) --", flush=True)
for k in ('logic_step', 'aabbs', 'pipe_wait', 'world_matrices', 'interp',
          'buckets', 'shadow_prep', 'collide_pairs', 'dispatch',
          'shadow_bounds'):
    d = (st1.get(k, 0.0) - st0.get(k, 0.0)) / max(frames, 1)
    print("  %-20s %7.2f" % (k, d), flush=True)

if e.is_playing:
    win._cmd_play()
for _ in range(30):
    app.processEvents()
e._stop_parallel()

with open(_sp, 'w', encoding='utf-8') as f:
    f.write(_orig)
try:
    os.remove(_sh)
except OSError:
    pass
print("\n[settings] 已还原。完成。", flush=True)
