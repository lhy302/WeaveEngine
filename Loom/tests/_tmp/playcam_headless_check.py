# -*- coding: utf-8 -*-
"""playcam_headless_check.py — 播放态相机按键链无头回归 (2026-09-06)

背景 (用户报告, 播放态):
  ①按 WASD/QE 相机不动  ②按住键 TPS 冻结/全场冻结  ③松开恢复  ④编辑态正常.

根因 (已修):
  A) editor._update_camera 相机统一重构误删 `speed = 0.08*delta_time*120*cam_speed`
     定义行 -> 按下任意 WASD/QE 键即 NameError -> _on_tick 每渲染拍中断
     (viewport.update() 永不执行) = 不重画 + advance_logic 停摆 = TPS 冻结,
     松键恢复。症状①②③全解释 (症状④: 编辑态按 WASD 同样会炸, 但用户
     只在播放态大量用 WASD)。
  B) 附带缺口: Qt 宿主 (外部模式) _handle_events 直接 return, script_keys
     从不刷新 -> 玩家脚本 is_key/get_action 恒 False。补 sync_script_keys()。

断言 (EditorApp.__new__ 桩 + 真实 offscreen 渲染, 无窗口):
  P1 播放态 W 按住 -> camera_target 连续 N 帧推进 (方向=yaw 前方), 无异常
  P2 播放态 W+D 组合键位移 = 前方+右方矢量合成; S/E 反向
  P3 松键 -> target 停止变化 (无残留漂移)
  P4 方向键转 yaw/pitch
  P5 编辑态 W 同样工作 (统一后同一状态量 camera_target)
  P6 render(带键) 播放态 N 帧不崩 (原 BUG: render 前的 _update_camera 炎)
  P7 script_keys 同步: 按键注入后 is_key/get_action 为 True (外部模式)
  P8 speed 定义行回归锚: speed 与 cam_speed 倍率线性
  P9 轻/重帧下相机速率恒定 (2026-09-07: 增量∝dt 契约, 反"相机挂逻辑帧"回归)
  P10 steps=0 渲染帧相机+VP 仍连续 (反 20Hz 台阶锚)
"""
import os
import sys
import math
import time
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame
from editor import EditorApp
from engine import DEFAULT_ACTIONS


class _View:
    """极简 IEditorView 桩 (对齐 tests/test_camera_control.py)."""
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}

    def draw(self, ctl, delta_time):
        pass


class _Keys(dict):
    """按键快照替身: 键码 -> 0/1 (pygame 十亿级键码直接当 key)."""
    def __getitem__(self, i):
        return self.get(i, 0)


def _make_editor(playing):
    ed = EditorApp.__new__(EditorApp)
    ed._mods = 0
    ed.buttons = (0, 0, 0)
    ed.mouse_pos = (100, 100)
    ed._cam_prev_mouse = (100, 100)
    ed.selected_index = 0
    ed.selected_light_index = -1
    ed.mouse_wheel = 0
    ed.camera_distance = 10.0
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.preview_camera = None
    ed._preview_orbit = None
    ed.view = _View()
    ed._fov = math.radians(45.0)
    ed._in_viewport = lambda pos: True
    ed._cam_speed = 1.0
    ed.is_playing = playing
    ed.orbit_mode = True            # 相机统一后播放/编辑同轨道几何
    ed._keys = _Keys()
    ed._key_pressed = lambda: ed._keys
    ed.msg = ''
    ed._msg_until = 0.0
    ed.script_keys = {}
    ed.actions = dict(DEFAULT_ACTIONS)
    ed._external_ctx = False        # P7 才翻 True
    return ed


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


DT = 1.0 / 30.0           # 探针统一 30Hz 逻辑帧 (指令要求; 排除 logic_fps 残留)
W, S, A, D, Q, E_ = (pygame.K_w, pygame.K_s, pygame.K_a,
                     pygame.K_d, pygame.K_q, pygame.K_e)


# ---- P1 播放态 W 连续推进 (30 帧) ----
ed = _make_editor(playing=True)
y0 = ed.camera_yaw
fx, fz = math.sin(y0), math.cos(y0)
trail = []
try:
    ed._keys[W] = 1
    for _ in range(30):
        ed._update_camera(DT)
        trail.append(ed.camera_target)
    moved = math.hypot(trail[-1][0], trail[-1][2])
    per_frame = [math.hypot(trail[i][0] - trail[i - 1][0],
                            trail[i][2] - trail[i - 1][2])
                 for i in range(1, len(trail))]
    dir_ok = abs(trail[-1][0] / trail[-1][2] - fx / fz) < 1e-6
    check("P1 播放态 W: target 连续推进 30 帧", moved > 1.0,
          "moved=%.3f speed/帧=%.4f" % (moved, per_frame[0]))
    check("P1b 移动方向 = yaw 前方", dir_ok,
          "t=(%.3f,%.3f) f=(%.3f,%.3f)" % (trail[-1][0], trail[-1][2], fx, fz))
    check("P1c 每帧步长恒定 (帧率恒定语义)",
          max(per_frame) - min(per_frame) < 1e-9,
          "%.6f~%.6f" % (min(per_frame), max(per_frame)))
except Exception:
    check("P1 播放态 W: target 连续推进 30 帧", False, traceback.format_exc(limit=2))

# ---- P2 组合键 = 前方 + 右方矢量合成 ----
ed._keys.clear(); ed._keys[W] = 1; ed._keys[D] = 1
t0 = ed.camera_target
ed._update_camera(DT)
t1 = ed.camera_target
# W: +(sin,cos)*s ; D: right=(cos,-sin)*s -> x+=(f+s) s, z+=(f-s) s (f=sin, s=cos)
spd = 0.08 * DT * 120.0 * 1.0          # = _update_camera 内 speed 行
expect = (t0[0] + (fx + fz) * spd, t0[1], t0[2] + (fz - fx) * spd)
check("P2 W+D 组合位移 = 前方+右方 (矢量合成)",
      all(abs(a - b) < 1e-9 for a, b in zip(t1, expect)), str(t1))
ed._keys.clear(); ed._keys[S] = 1; ed._keys[E_] = 1
ed._update_camera(DT)
check("P2b S+E 反向 (z- y-)", ed.camera_target[2] < t1[2]
      and ed.camera_target[1] < t1[1], str(ed.camera_target))

# ---- P3 松键停止 ----
t_hold = ed.camera_target           # S+E 松开前的位置
ed._keys.clear()
for _ in range(5):
    ed._update_camera(DT)
check("P3 松键后 target 冻结 (无漂移)", ed.camera_target == t_hold,
      str(ed.camera_target))

# ---- P4 方向键转视角 ----
ed._keys.clear(); ed._keys[pygame.K_LEFT] = 1
ya = ed.camera_yaw; pa = ed.camera_pitch
ed._update_camera(DT)
check("P4 ← 键 yaw 减小 (rot=0.02*dt*120)", ed.camera_yaw < ya,
      "%.4f -> %.4f" % (ya, ed.camera_yaw))
ed._keys.clear(); ed._keys[pygame.K_UP] = 1
ed._update_camera(DT)
check("P4b ↑ 键 pitch 增大", ed.camera_pitch > pa,
      "%.4f -> %.4f" % (pa, ed.camera_pitch))

# ---- P5 编辑态 W 同一链 ----
ed5 = _make_editor(playing=False)
ed5._keys[W] = 1
ed5._update_camera(DT)
check("P5 编辑态 W 同样推进 target (统一后同状态量)",
      math.hypot(ed5.camera_target[0], ed5.camera_target[2]) > 0.05,
      str(ed5.camera_target))

# ---- P6 真实渲染: 播放态按住 W+Q 跑 _update_camera+advance_logic+render ----
# (对齐 Qt _on_tick 顺序: _update_camera -> paintGL(advance_logic+render))
try:
    import moderngl
    ctx = moderngl.create_standalone_context()
    import editor as editor_mod
    e6 = editor_mod.EditorApp(320, 240, ctx=ctx)
    e6._external_fb = ctx.detect_framebuffer()
    _og = e6.view.gui.render
    e6.view.gui.render = (lambda *a, **kw: _og(target=e6._external_fb))
    e6.toggle_play()
    e6._key_pressed = (lambda: _Keys({W: 1, Q: 1}))     # 注入 W+Q
    n_stps0 = getattr(getattr(e6, '_clock', None), 'steps', -1)
    t_t0 = e6.camera_target
    for _ in range(8):
        delta = 0.04                                    # >1/30: 每帧至少 1 逻辑步
        e6.last_frame_time = time.time()
        e6._update_camera(delta)                        # _on_tick 同链
        e6.advance_logic(delta)
        e6.render(delta)
    moved6 = math.hypot(e6.camera_target[0] - t_t0[0],
                        e6.camera_target[2] - t_t0[2])
    n_stps1 = getattr(getattr(e6, '_clock', None), 'steps', -1)
    check("P6 播放态渲染链按住 W+Q 8 帧不崩且 target 推进", moved6 > 0.5,
          "moved=%.3f" % moved6)
    check("P6b 逻辑帧持续推进 (TPS 不冻结)", n_stps1 > n_stps0,
          "steps %s -> %s" % (n_stps0, n_stps1))
    e6.toggle_play()
except Exception:
    check("P6 播放态渲染链按住 W+Q 8 帧不崩", False, traceback.format_exc(limit=3))

# ---- P7 script_keys 同步 (外部模式) ----
try:
    e7 = _make_editor(playing=True)
    e7._external_ctx = True
    e7.sync_script_keys()                      # 无键
    check("P7 外部模式无键: is_key('w')=False", e7.is_key('w') is False)
    e7._keys[W] = 1
    e7._keys[pygame.K_SPACE] = 1
    e7.sync_script_keys()
    check("P7b 注入 W/space 后 is_key/get_action=True",
          e7.is_key('w') is True and e7.get_action('向前') is True
          and e7.get_action('跳跃') is True,
          str({k: v for k, v in e7.script_keys.items() if v}))
except Exception:
    check("P7 script_keys 同步", False, traceback.format_exc(limit=2))

# ---- P8 cam_speed 倍率线性 ----
e8a = _make_editor(playing=True); e8a._keys[W] = 1
e8b = _make_editor(playing=True); e8b._cam_speed = 2.0; e8b._keys[W] = 1
e8a._update_camera(DT); e8b._update_camera(DT)
ma = math.hypot(e8a.camera_target[0], e8a.camera_target[2])
mb = math.hypot(e8b.camera_target[0], e8b.camera_target[2])
check("P8 cam_speed=2 位移=2x (speed 行回归锚)", abs(mb - 2 * ma) < 1e-9,
      "%.4f vs %.4f" % (ma, mb))

# ---- P9 混合帧长下相机速率恒定 (2026-09-07 相机卡顿排查回归锚) ----
# 背景: 用户报告"播放态相机一动就卡顿"。排查定案: 相机链每渲染帧连续
# (增量 ∝ 该帧 dt), 体感卡顿真身 = 逻辑步重帧造成的帧交付双峰, 非相机台阶。
# 本断言锁契约: 轻/重帧 (6ms/22ms 交替, 模拟 TPS20 落点) 下单位时间位移恒定
# —— 若未来重构把相机误挂逻辑帧, 此处必炸 (重帧 0 增量/轻帧全增量)。
try:
    import moderngl
    ctx9 = moderngl.create_standalone_context()
    e9 = editor_mod.EditorApp(320, 240, ctx=ctx9)
    e9._external_fb = ctx9.detect_framebuffer()
    _og9 = e9.view.gui.render
    e9.view.gui.render = (lambda *a, **kw: _og9(target=e9._external_fb))
    e9.toggle_play()
    e9._key_pressed = (lambda: _Keys({W: 1}))
    rates = []
    for dt in (0.006, 0.006, 0.022, 0.006, 0.006, 0.022):   # 轻/重帧节拍
        t9a = e9.camera_target
        e9._update_camera(dt)
        e9.advance_logic(dt)
        e9.render(dt)
        t9b = e9.camera_target
        mv = math.hypot(t9b[0] - t9a[0], t9b[2] - t9a[2])
        if dt > 0:
            rates.append(mv / dt)      # units/ms (单位时间位移)
    spread = max(rates) - min(rates)
    check("P9 轻/重帧下相机速率恒定 (增量∝dt, 不挂逻辑帧契约)",
          spread < 0.004, "rates=%s spread=%.5f"
          % (['%.4f' % r for r in rates], spread))
    e9.toggle_play()
except Exception:
    check("P9 轻/重帧下相机速率恒定", False, traceback.format_exc(limit=3))

# ---- P10 无逻辑步渲染帧相机+VP 仍连续 (反台阶锚) ----
# dt 不足一个逻辑帧 (steps=0) 时相机照常推进、view 矩阵照常变化
# —— 若相机被挂到逻辑帧, steps=0 帧 VP 恒等 = 20Hz 台阶回归。
try:
    ctx10 = moderngl.create_standalone_context()
    e10 = editor_mod.EditorApp(320, 240, ctx=ctx10)
    e10._external_fb = ctx10.detect_framebuffer()
    _og10 = e10.view.gui.render
    e10.view.gui.render = (lambda *a, **kw: _og10(target=e10._external_fb))
    e10.toggle_play()
    e10._key_pressed = (lambda: _Keys({W: 1}))
    e10._update_camera(0.001); e10.advance_logic(0.001); e10.render(0.001)
    vp0 = e10._vp.tobytes()
    t0x, t0y, t0z = e10.camera_target
    for _ in range(3):                 # 全部 steps=0 (3ms << 50ms)
        e10._update_camera(0.001)
        e10.advance_logic(0.001)
        e10.render(0.001)
    zero_steps = all(getattr(e10._clock, 'steps', 0) == 0
                     for _ in range(1))   # 末帧步数 (采样期累计无步)
    moved10 = math.hypot(e10.camera_target[0] - t0x,
                         e10.camera_target[2] - t0z)
    vp_changed = e10._vp.tobytes() != vp0
    check("P10 steps=0 渲染帧相机仍推进 (反 20Hz 台阶锚)", moved10 > 0.001,
          "moved=%.5f" % moved10)
    check("P10b steps=0 渲染帧 VP 矩阵仍变化", vp_changed)
    e10.toggle_play()
except Exception:
    check("P10 steps=0 渲染帧相机仍推进", False, traceback.format_exc(limit=3))

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
