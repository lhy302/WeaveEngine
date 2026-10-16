# -*- coding: utf-8 -*-
r"""qt_play_probe.py — 真 Qt 编辑器播放态帧率探针 (诊断批, 2026-09-05).

复刻用户真实路径: LoomHub -> Loom.py --ui qt (LoomGUI 完整面板 + QTimer 驱动).
真窗口 (Qt offscreen 不支持 QOpenGLWidget), QTimer 档位按 设置.json fps_limit
(unlimited=1ms) -> _on_tick -> viewport.update() -> paintGL -> advance_logic+render.
只取证不改引擎: paintGL/pipe 用实例 monkeypatch 包计时.

用法: py -3.12 tests/_tmp/qt_play_probe.py [帧数]
  ★B7b 退役 (2026-10-16): 删 --nosplit 分支 (LOOM_NO_SPLIT 逃生门退役)。
"""
import os
import sys
import time
import ctypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
BASE = sys.path[0]
os.chdir(BASE)

os.environ['LOOM_PROFILE'] = '1'

args = [a for a in sys.argv[1:] if not a.isdigit()]
n_frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 300
mode = args[0] if args else ''
# ★B4c 退役 (2026-10-16): --nopipe 分支已删 (LOOM_NO_PIPE 逃生门退役)。
# ★B7b 退役 (2026-10-16): --nosplit 分支已删 (LOOM_NO_SPLIT 逃生门退役)。

import faulthandler
faulthandler.enable()
ctypes.windll.user32.SetProcessDPIAware()
# guiloader.settings_path 用 sys.argv[0] 目录找 设置.json —— 探针在 tests/_tmp
# 会读不到根目录设置 (回默认 30/60); 伪装 argv[0] 到根目录对齐用户真实路径
sys.argv[0] = os.path.join(BASE, 'Loom.py')

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtGui import QSurfaceFormat            # noqa: E402
from PySide6.QtCore import QTimer                   # noqa: E402

# 与 run_loom_gui 相同 QSurfaceFormat (samples=4/无 vsync) — 记忆铁律
fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setSamples(4)
fmt.setSwapInterval(0)
QSurfaceFormat.setDefaultFormat(fmt)

from ui.loom_gui import LoomGUI                     # noqa: E402

scene = os.path.join(BASE, 'tests', '_tmp',
                     (args[1] if len(args) > 1 else 'stress_500spheres.json'))

app = QApplication(sys.argv)
t_build = time.perf_counter()
win = LoomGUI(scene_path=scene, width=1280, height=800)
win.show()
e = None
for _ in range(300):
    app.processEvents()
    if win.editor is not None and win.editor.ctx is not None:
        e = win.editor
        break
    time.sleep(0.02)
print("[probe] LoomGUI 构建 %.2fs, editor=%s models=%d fps_limit=%s" % (
    time.perf_counter() - t_build,
    'OK' if e else 'FAIL', len(e.models) if e else 0,
    os.environ.get('_FL', '?')))

vp = win.viewport
_orig_paint = vp.paintGL
_paint_t = [0.0]
_paint_n = [0]
_last_paint = [time.perf_counter()]
_frame_gaps = []


def timed_paint():
    now = time.perf_counter()
    _frame_gaps.append(now - _last_paint[0])
    _last_paint[0] = now
    _t = now
    _orig_paint()
    _paint_t[0] += time.perf_counter() - _t
    _paint_n[0] += 1
    # 精确口径: 在 paintGL 内累计本帧步数 (paintGL = advance_logic+render 同拍)
    c = getattr(e, '_clock', None)
    if c is not None:
        _steps_l[0] += c.steps
        _steps_p[0] += c.phys_steps


_steps_l = [0]
_steps_p = [0]


vp.paintGL = timed_paint

# ---- 编辑态: 事件循环跑 120 paintGL 帧 ----
while _paint_n[0] < 120:
    app.processEvents()
edit_wall = time.perf_counter() - t_build
edit_fps = _paint_n[0] / _paint_t[0]
st_edit = dict(e._stage_times)
print("\n[编辑态] %d paint 帧, paintGL 合计 %.2fs -> 纯渲染 FPS=%.1f (帧均 %.2f ms)"
      % (_paint_n[0], _paint_t[0], edit_fps, _paint_t[0] / _paint_n[0] * 1000))
for k in ('logic_step', 'interp', 'physics', 'pipe_wait', 'world_matrices',
          'aabbs', 'shadow_prep', 'collide_pairs', 'buckets'):
    print("  %-18s %7.2f ms/帧" % (k, st_edit.get(k, 0.0) / max(_paint_n[0], 1)))

# ---- 进入播放 (真按钮路径) ----
print("\n[probe] _cmd_play() (toggle_play 真路径) ...")
_t = time.perf_counter()
win._cmd_play()
app.processEvents()
print("[probe] toggle_play %.2fs | split=%s clock=%s(%sHz/%sHz) interp=%s pipe=%s bridge=%s" % (
    time.perf_counter() - _t,
    getattr(e, '_split_enable', None),
    type(getattr(e, '_clock', None)).__name__,
    getattr(getattr(e, '_clock', None), 'logic_fps', '?'),
    getattr(getattr(e, '_clock', None), 'physics_fps', '?'),
    type(getattr(e, '_interp', None)).__name__,
    'ON' if getattr(e, '_phys_pipe', None) is not None else 'OFF',
    'ON' if getattr(e, '_phys_bridge', None) is not None else 'OFF'))

# ---- pipe 计时 (monkeypatch) ----
pipe = getattr(e, '_phys_pipe', None)
_post_t = [0.0]
_wait_t = [0.0]
_wc = [0]
if pipe is not None:
    _op, _ow = pipe.post, pipe.wait

    def tp(*a, **kw):
        _t = time.perf_counter()
        r = _op(*a, **kw)
        _post_t[0] += time.perf_counter() - _t
        return r

    def tw(*a, **kw):
        _t = time.perf_counter()
        r = _ow(*a, **kw)
        _wait_t[0] += time.perf_counter() - _t
        _wc[0] += 1
        return r

    pipe.post = tp
    pipe.wait = tw

# 预热 40 帧
target = _paint_n[0] + 40
while _paint_n[0] < target:
    app.processEvents()

# ---- 播放态: 跑 n_frames 帧 ----
e._stage_times.clear()
_post_t[0] = _wait_t[0] = _wc[0] = 0.0
_paint_t[0] = 0.0
_steps_l[0] = _steps_p[0] = 0
_g0 = len(_frame_gaps)
_n0 = _paint_n[0]
t0 = time.perf_counter()
while (_paint_n[0] - _n0) < n_frames:
    app.processEvents()
wall = time.perf_counter() - t0
play_frames = _paint_n[0] - _n0
play_fps = play_frames / wall
st_play = dict(e._stage_times)

print("\n[播放态] %d 帧 FPS=%.1f (帧间隔 %.2f ms)  paintGL 合计 %.2fs (纯渲染帧均 %.2f ms)" % (
    play_frames, play_fps, wall / play_frames * 1000,
    _paint_t[0], _paint_t[0] / play_frames * 1000))
print("  逻辑步合计=%d (%.2f/帧) 物理步合计=%d (%.2f/帧)" % (
    _steps_l[0], _steps_l[0] / play_frames, _steps_p[0], _steps_p[0] / play_frames))
keys = ('logic_step', 'interp', 'physics', 'pipe_wait', 'phys_bridge_ensure',
        'phys_bridge_pre', 'phys_bridge_step', 'phys_bridge_post',
        'world_matrices', 'aabbs', 'shadow_prep', 'shadow_bounds',
        'shadow_cornerfill', 'shadow_matmul', 'collide_pairs', 'shadow_jobs',
        'dispatch', 'buckets')
tot = 0.0
for k in keys:
    v = st_play.get(k, 0.0) / play_frames
    tot += v
    print("  %-22s %7.2f ms/帧" % (k, v))
rest = sum(v for k, v in st_play.items() if k not in keys) / play_frames
if rest > 0.01:
    print("  %-22s %7.2f ms/帧" % ('(其他)', rest))
    tot += rest
print("  %-22s %7.2f ms/帧 (帧间隔 %.2f)" % ('已插桩合计', tot, wall / play_frames * 1000))
if pipe is not None:
    sph = max(_steps_p[0], 1)
    print("[pipe 实测] wait=%.2f ms/帧 (%d 次, %.2f ms/物理步) post=%.3f ms/物理步" % (
        _wait_t[0] / play_frames * 1000, _wc[0],
        _wait_t[0] / sph * 1000, _post_t[0] / sph * 1000))
# 帧间隔分布
g = sorted(_frame_gaps[_g0:])
if g:
    print("帧间隔: p10=%.2f p50=%.2f p90=%.2f p99=%.2f max=%.2f ms" % (
        g[int(0.1 * len(g))] * 1000, g[len(g) // 2] * 1000,
        g[int(0.9 * len(g))] * 1000, g[min(int(0.99 * len(g)), len(g) - 1)] * 1000,
        g[-1] * 1000))

# ---- 退出播放 + 清理 ----
if e.is_playing:
    win._cmd_play()
for _ in range(30):
    app.processEvents()
e._stop_parallel()
print("\n完成。")
