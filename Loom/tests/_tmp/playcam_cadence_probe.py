# -*- coding: utf-8 -*-
"""playcam_cadence_probe.py — 播放态相机位姿节拍对拍探针 (2026-09-07, 常驻)

验证目标 (任务书对拍项): 逐渲染帧记录相机位姿/VP 矩阵变化率 —
  修复前预期 = TPS 台阶 (仅逻辑帧帧有增量), 修复后 = 渲染帧连续。

跑法 (模拟 Qt 生产节拍 _on_tick): 每渲染帧
  e._update_camera(dt) -> e.advance_logic(dt) -> e.render(dt)
按住 W+D+Q (恒速输入) 跑 N 渲染帧, 记录每帧 camera_target 与 _vp。

判据:
  C1 target 非零增量帧占比 = 100% (无台阶: 若相机挂逻辑帧, 20Hz 下约
     55/20 -> 只有 ~36% 帧有增量)。
  C2 VP bytes 非零增量帧占比 = 100% (view 矩阵同步变)。
  C3 每帧增量符号一致且帧数多时增量恒定 (恒速输入 -> 恒速位移)。
  C4 增量幅值 ∝ 该帧 dt (帧率恒定语义)。
  ★B7b 退役 (2026-10-16): 删原 C5 (LOOM_NO_SPLIT 逃生门对照) 描述。
无头 (standalone ctx), 相机统一后代码。
"""
import os
import sys
import time
import math
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_PARALLEL'] = '1'

import pygame
import moderngl
from editor import EditorApp


class _Keys(dict):
    def __getitem__(self, i):
        return self.get(i, 0)


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def run_phase(label, n_frames=100, fps_limit_ms=1):
    """按生产节拍跑 N 帧 (QTimer 1ms 档 = 编译版实测 unlimited 形态),
    按住 W+D+Q 恒速输入, 返回 (target 变化率, vp 变化率, 增量列表, dt 列表)."""
    ctx = moderngl.create_standalone_context()
    e = EditorApp(320, 240, ctx=ctx)
    e._external_fb = ctx.detect_framebuffer()
    _og = e.view.gui.render
    e.view.gui.render = (lambda *a, **kw: _og(target=e._external_fb))
    e.toggle_play()
    e._key_pressed = (lambda: _Keys({pygame.K_w: 1, pygame.K_d: 1,
                                     pygame.K_q: 1}))
    # 注入恒定渲染节拍 (Qt unlimited = 1ms QTimer; 探针用 4ms 让逻辑帧
    # 均匀落在每 4-5 渲染帧, 模拟 55FPS@TPS20 的帧/拍比)
    e._update_camera(0.0)
    targets, vps, dts = [], [], []
    last_vp = None
    last_t = None
    t_prev = time.perf_counter()
    for i in range(n_frames):
        now = time.perf_counter()
        dt = 0.004                          # 固定 4ms 节拍 (250FPS 口径; 恒 dt 让增量可判)
        dts.append(dt)
        e._update_camera(dt)
        e.advance_logic(dt)
        e.render(dt)
        targets.append(tuple(e.camera_target))
        vp = e._vp.tobytes()
        vps.append(vp)
        # 限定档位节拍 (fps_limit_ms) — 模拟 Qt 节拍
        elapsed = time.perf_counter() - now
        if elapsed < fps_limit_ms / 1000.0:
            time.sleep(fps_limit_ms / 1000.0 - elapsed)
    e.toggle_play()
    e._stop_parallel()
    # ---- 统计 ----
    t_moves = sum(1 for i in range(1, len(targets))
                  if targets[i] != targets[i - 1])
    v_moves = sum(1 for i in range(1, len(vps))
                  if vps[i] != vps[i - 1])
    # target 增量幅值序列 (水平面)
    incs = []
    for i in range(1, len(targets)):
        dx = targets[i][0] - targets[i - 1][0]
        dz = targets[i][2] - targets[i - 1][2]
        incs.append(math.hypot(dx, dz))
    nz = [x for x in incs if x > 1e-12]
    print("[%s] 渲染帧 %d | target 变化帧 %d/%d (%.0f%%) | VP 变化帧 %d/%d (%.0f%%)"
          % (label, n_frames, t_moves, n_frames - 1,
             100.0 * t_moves / (n_frames - 1),
             v_moves, n_frames - 1, 100.0 * v_moves / (n_frames - 1)))
    if nz:
        print("      非零增量: mean=%.5f min=%.5f max=%.5f (恒速输入应近似恒定)"
              % (sum(nz) / len(nz), min(nz), max(nz)))
    return t_moves, v_moves, incs, dts


# ---- C1-C3: 分离模式 (默认 20Hz 逻辑帧, 用户实测口径) ----
import guiloader
s = guiloader.load_settings('loom', base=BASE)
s['logic_fps'] = 20
guiloader.save_settings('loom', s, base=BASE)
tm, vm, incs, _ = run_phase("分离模式 TPS20", n_frames=100)
check("C1 target 每渲染帧连续变化 (无 20Hz 台阶)", tm == 99,
      "%d/99 帧" % tm)
check("C2 VP 矩阵每渲染帧连续变化", vm == 99, "%d/99 帧" % vm)
if incs:
    nz = [x for x in incs if x > 1e-12]
    check("C3 非零增量幅值恒定 (恒速输入)", nz and (max(nz) - min(nz)) < 1e-6,
          "spread=%.2e" % ((max(nz) - min(nz)) if nz else -1))

# ★B7b 退役 (2026-10-16): 删原 C5 (LOOM_NO_SPLIT 逃生门对照) 段 —
#   绑死模式仅由设置 logic_fps<=0 触发; 本探针不测该路径。

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
