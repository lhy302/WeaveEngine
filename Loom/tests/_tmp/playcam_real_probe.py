# -*- coding: utf-8 -*-
r"""playcam_real_probe.py — 真 Qt 生产循环相机节拍对拍 (2026-09-07, 常驻)

复刻用户真实路径: Loom.py --ui qt (LoomGUI 完整面板 + QTimer 驱动), 播放态
按住 W+D 恒速输入, monkeypatch paintGL 逐渲染帧记录:
  (perf_counter, camera_target, camera_yaw, vp bytes, clock.steps)

产出 (stdout + json):
  1. 帧间隔分布 (p10/p50/p90/p99/max/std) — 帧交付抖动量化
  2. VP 非零变化帧占比 — 相机 view 矩阵是否渲染帧连续 (台阶检测)
  3. 相机帧增量 vs 该帧逻辑步数 — 增量是否随逻辑步跳变
  4. 逐帧 CSV (tests/_tmp/playcam_real_frames.csv)

用法: py -3.12 tests/_tmp/playcam_real_probe.py [帧数] [场景.json]
"""
import os
import sys
import time
import json
import ctypes
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
BASE = sys.path[0]
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'
# guiloader.settings_path 用 sys.argv[0] 目录找 设置.json — 伪装 argv[0] 对齐真实路径
sys.argv[0] = os.path.join(BASE, 'Loom.py')

import faulthandler
faulthandler.enable()
ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
import pygame

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtGui import QSurfaceFormat            # noqa: E402

fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setSamples(4)
fmt.setSwapInterval(0)
QSurfaceFormat.setDefaultFormat(fmt)

from ui.loom_gui import LoomGUI                     # noqa: E402

args = [a for a in sys.argv[1:] if not a.isdigit()]
n_frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 300
scene = args[0] if args else os.path.join(BASE, '保存', '压测500混合.json')

app = QApplication(sys.argv)
t_build = time.perf_counter()
win = LoomGUI(scene_path=scene, width=1280, height=800)
win.show()
e = None
for _ in range(600):
    app.processEvents()
    if win.editor is not None and win.editor.ctx is not None:
        e = win.editor
        break
    time.sleep(0.02)
if e is None:
    print("[probe] editor 构建失败")
    sys.exit(2)
print("[probe] 构建 %.2fs models=%d fps_limit=%s logic_fps=%s" % (
    time.perf_counter() - t_build, len(e.models),
    getattr(win, '_fps_limit_mode', '?'),
    getattr(getattr(e, '_clock', None), 'logic_fps', '?')))

# ---- 播放态 (真按钮路径) ----
win._cmd_play()
for _ in range(60):
    app.processEvents()
print("[probe] is_playing=%s split=%s interp=%s" % (
    e.is_playing, getattr(e, '_split_enable', None),
    type(getattr(e, '_interp', None)).__name__))

# ---- 键盘注入: 按住 W+D (恒速输入) — 模拟用户 WASD 移动 ----
e.key_state[pygame.K_w] = True
e.key_state[pygame.K_d] = True

# ---- paintGL 逐帧记录 ----
vp = win.viewport
_orig_paint = vp.paintGL
rows = []
_state = {'t': time.perf_counter(), 'n': 0}
# advance/render 分解 (monkeypatch 引擎两段计时 — 只取证不改行为)
_e_advance = e.advance_logic
_e_render = e.render
_tadv = [0.0]
_tren = [0.0]


def _advance_patch(dt):
    _t = time.perf_counter()
    r = _e_advance(dt)
    _tadv[0] += time.perf_counter() - _t
    return r


def _render_patch(dt):
    _t = time.perf_counter()
    r = _e_render(dt)
    _tren[0] += time.perf_counter() - _t
    return r


e.advance_logic = _advance_patch
e.render = _render_patch


def rec_paint():
    now = time.perf_counter()
    _tadv[0] = _tren[0] = 0.0
    _orig_paint()
    c = getattr(e, '_clock', None)
    rows.append({
        't': now,
        'dt': now - _state['t'],
        'tx': e.camera_target[0], 'ty': e.camera_target[1],
        'tz': e.camera_target[2],
        'yaw': e.camera_yaw, 'pitch': e.camera_pitch,
        'camx': e.camera.x, 'camy': e.camera.y, 'camz': e.camera.z,
        'vp': bytes(e._vp.astype('f4').tobytes()) if getattr(e, '_vp', None) is not None else b'',
        'steps': getattr(c, 'steps', -1) if c is not None else -1,
        'adv_ms': _tadv[0] * 1000.0,
        'ren_ms': _tren[0] * 1000.0,
    })
    _state['t'] = now
    _state['n'] += 1


vp.paintGL = rec_paint

# 预热 60 帧 (载入/编译/GC 沉降)
target0 = _state['n'] + 60
while _state['n'] < target0:
    app.processEvents()

# ---- 正式采集 n_frames 帧 ----
rows.clear()
_state['t'] = time.perf_counter()
target1 = _state['n'] + n_frames
t0 = time.perf_counter()
while _state['n'] < target1:
    app.processEvents()
wall = time.perf_counter() - t0

# ---- 停止: 松键 + 退播放 ----
e.key_state[pygame.K_w] = False
e.key_state[pygame.K_d] = False
if e.is_playing:
    win._cmd_play()
for _ in range(30):
    app.processEvents()
e._stop_parallel()

# ================= 分析 =================
dts = [r['dt'] for r in rows]
sd = sorted(dts)
n = len(sd)


def pct(p):
    return sd[min(int(p * n), n - 1)] * 1000.0


print("\n[帧间隔] n=%d wall=%.2fs mean=%.2fms std=%.2fms | p10=%.2f p50=%.2f p90=%.2f p99=%.2f max=%.2f"
      % (n, wall, sum(dts) / n * 1000, statistics.pstdev(dts) * 1000,
         pct(0.10), pct(0.50), pct(0.90), pct(0.99), sd[-1] * 1000))
steps_hist = {}
for r in rows:
    steps_hist[r['steps']] = steps_hist.get(r['steps'], 0) + 1
print("[逻辑步落点] 每渲染帧步数分布:", dict(sorted(steps_hist.items())))

# VP 台阶检测
vp_moves = sum(1 for i in range(1, n) if rows[i]['vp'] != rows[i - 1]['vp'])
print("[VP 矩阵] 变化帧 %d/%d (%.1f%%)" % (vp_moves, n - 1, 100.0 * vp_moves / max(n - 1, 1)))

# 相机增量 vs 逻辑步数
import math as _math
t_incs = [(_math.hypot(rows[i]['tx'] - rows[i - 1]['tx'],
                       rows[i]['tz'] - rows[i - 1]['tz']), rows[i]['steps'])
          for i in range(1, n)]
y_incs = [(abs(rows[i]['yaw'] - rows[i - 1]['yaw']), rows[i]['steps'])
          for i in range(1, n)]
by_steps = {}
for inc, st in t_incs:
    by_steps.setdefault(st, []).append(inc)
print("[target 增量 by 逻辑步数]")
for st in sorted(by_steps):
    v = by_steps[st]
    print("  steps=%d: n=%d mean=%.5f min=%.5f max=%.5f"
          % (st, len(v), sum(v) / len(v), min(v), max(v)))

# 帧间隔 vs 步数 (重帧/轻帧实锤) + advance/render 分解
dt_by_steps = {}
for r in rows:
    dt_by_steps.setdefault(r['steps'], []).append(r['dt'])
print("[帧间隔 by 逻辑步数]")
for st in sorted(dt_by_steps):
    v = dt_by_steps[st]
    print("  steps=%d: n=%d mean=%.2fms min=%.2f max=%.2f"
          % (st, len(v), sum(v) / len(v) * 1000, min(v) * 1000, max(v) * 1000))
adv_by_steps = {}
for r in rows:
    adv_by_steps.setdefault(r['steps'], []).append((r['adv_ms'], r['ren_ms']))
print("[advance/render 分解 by 逻辑步数]")
for st in sorted(adv_by_steps):
    a = [x[0] for x in adv_by_steps[st]]
    rr = [x[1] for x in adv_by_steps[st]]
    print("  steps=%d: advance mean=%.2fms (max %.2f) | render mean=%.2fms (max %.2f)"
          % (st, sum(a) / len(a), max(a), sum(rr) / len(rr), max(rr)))

# 逐帧 CSV (行列: t_ms, dt_ms, steps, tx, ty, tz, yaw, camx, camy, camz)
csv = os.path.join(BASE, 'tests', '_tmp', 'playcam_real_frames.csv')
with open(csv, 'w', encoding='utf-8') as f:
    f.write("t_ms,dt_ms,steps,adv_ms,ren_ms,tx,ty,tz,yaw,camx,camy,camz\n")
    t_acc = 0.0
    for r in rows:
        t_acc += r['dt']
        f.write("%.3f,%.3f,%d,%.3f,%.3f,%.6f,%.6f,%.6f,%.6f,%.4f,%.4f,%.4f\n"
                % (t_acc * 1000, r['dt'] * 1000, r['steps'],
                   r['adv_ms'], r['ren_ms'],
                   r['tx'], r['ty'], r['tz'], r['yaw'],
                   r['camx'], r['camy'], r['camz']))
print("[csv] %s" % csv)

# 判定改为两点: ①VP 连续性 (排除停顿帧 dt>100ms 的离群)
moves_excl = sum(1 for i in range(1, n)
                 if rows[i]['vp'] != rows[i - 1]['vp']
                 and rows[i]['dt'] < 0.1)
pausable = sum(1 for r in rows if r['dt'] >= 0.1)
ok1 = (moves_excl >= n - 1 - pausable - 1)
print("[判定1] VP 连续 (排除 >100ms 停顿帧 %d): %s (%d/%d)"
      % (pausable, "PASS" if ok1 else "FAIL", moves_excl, n - 1 - pausable))
# ②双峰定量: steps=1 重帧均值 / steps=0 轻帧均值
a0 = [r['adv_ms'] for r in rows if r['steps'] == 0]
a1 = [r['adv_ms'] for r in rows if r['steps'] == 1]
d0 = [r['dt'] for r in rows if r['steps'] == 0]
d1 = [r['dt'] for r in rows if r['steps'] == 1]
if a0 and a1:
    ratio = (sum(d1) / len(d1)) / max(sum(d0) / len(d0), 1e-9)
    print("[判定2] 帧交付双峰: 重帧(steps=1)均值 %.2fms vs 轻帧 %.2fms = %.2f× "
          "(ATPS=%.1fHz)" % (sum(d1) / len(d1) * 1000, sum(d0) / len(d0) * 1000,
                             ratio, 1.0 / (sum(d1) / len(d1) + sum(d0) / len(d0))))
    ok2 = ratio > 1.5
    print("[判定2] 重帧显著更重 (双峰存在, ratio>1.5): %s" % ("PASS" if ok2 else "FAIL"))
ok = ok1
print("\n总判定:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
