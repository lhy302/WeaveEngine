# -*- coding: utf-8 -*-
"""test_clock_pause_restart.py — 时钟暂停恢复 (P1-A) 与逻辑线程启停 (P1-B) 的定向断言。

白盒契约 (被审代码自身声明):
  · engine.toggle_logic_paused 注释: 「暂停边界: 清 accumulator 余量 (恢复时从整拍
    开始, **不补暂停期欠账**)」；
  · loom_logic_thread._stop_logic_thread 注释: 「停逻辑线程 (幂等)」；
    _start_logic_thread 注释: 「启动逻辑帧线程 (幂等)」。
审计缺陷 (2026-11-09):
  P1-A _clock_advance 的墙钟锚点只在推进时更新, 暂停三条路径都在调用前 return
       → 恢复首帧 wall_dt=停顿时长(截 0.333s) → 一帧连跑 9~10 步 (补欠账)。
  P1-B _stop 先置 self._logic_stop=None 再 ev.set(), 而循环读 self._logic_stop
       → 线程永不退出 (join 卡满 2s, 孤儿线程继续推时钟, 再 start 变双线程)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

import engine as E                                # noqa: E402
from core_clock import clock_from_settings        # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def make_engine():
    """无 GL 桩: 只装 advance_logic / toggle_logic_paused / 线程启停所需字段。"""
    e = E.GLEngine.__new__(E.GLEngine)
    e.is_playing = True
    e._split_enable = True
    e._clock = clock_from_settings({'logic_fps': 30, 'physics_fps': 60})
    e._steps = []
    e._clock.on_logic_step.append(lambda dt: e._steps.append(dt))
    e._interp = None
    e._logic_async = False          # 走同步路径 (无头/测试同款)
    e._external_ctx = False
    e._logic_paused = False
    e._step_requested = False
    e._advanced_this_frame = False
    e._render_world = None
    e._logic_gen = 0
    e._logic_steps = 0
    # 逻辑线程循环里会发布这组快照 (缺字段会让线程打 traceback)
    e._prep_pairs = None
    e._prep_light_vps = None
    e._prep_pub = None
    return e


def frame(e, dt=1.0 / 60.0):
    e._advanced_this_frame = False
    e.advance_logic(dt)
    return len(e._steps)


# ============ A. 暂停恢复不补欠账 (P1-A) ============
def t_pause_no_debt():
    print("=== A. 暂停 0.5s 恢复首帧步数 <= 1 (P1-A) ===")
    e = make_engine()
    for _ in range(8):                       # 稳态: 每 2 帧 1 步 (1/60*2=1/30)
        frame(e)
        time.sleep(1.0 / 60.0)
    n0 = len(e._steps)
    check("稳态推进有步可跑", n0 >= 2, n0)

    check("进入暂停 (toggle_logic_paused)", e.toggle_logic_paused() is True)
    nb = len(e._steps)
    for _ in range(6):                       # 暂停期渲染帧照跑, 逻辑应为零步
        frame(e)
        time.sleep(1.0 / 60.0)
    check("暂停期零逻辑步", len(e._steps) == nb, len(e._steps) - nb)

    time.sleep(0.5)                          # 停 0.5s (远大于 0.333s 截断)
    check("恢复暂停 (toggle_logic_paused)", e.toggle_logic_paused() is False)
    n1 = len(e._steps)
    frame(e)                                 # 恢复首帧
    first = len(e._steps) - n1
    check("恢复首帧步数 <= 1 (不补暂停期欠账)", first <= 1, first)

    # 连续跑 10 帧总步数也不该出现"补偿性爆发"
    n2 = len(e._steps)
    for _ in range(10):
        frame(e)
        time.sleep(1.0 / 60.0)
    total = len(e._steps) - n2
    check("恢复后 10 帧总步数 <= 6 (30fps 目标, 无补欠账)", total <= 6, total)


def t_set_logic_paused_path():
    print("=== A2. set_logic_paused(True/False) 同一口径 ===")
    e = make_engine()
    for _ in range(4):
        frame(e)
        time.sleep(1.0 / 60.0)
    e.set_logic_paused(True)
    nb = len(e._steps)
    time.sleep(0.5)
    e.set_logic_paused(False)
    frame(e)
    check("set_logic_paused 路径恢复首帧步数 <= 1", len(e._steps) - nb <= 1,
          len(e._steps) - nb)


# ============ B. 逻辑线程启停 (P1-B) ============
def t_thread_stop_restart():
    print("=== B. 逻辑线程 stop 能停 / 再 start 只有一个 (P1-B) ===")
    e = make_engine()
    e._logic_thread = None
    e._logic_stop = None
    t1 = e._start_logic_thread(e._clock)
    check("_start_logic_thread 返回线程对象", t1 is not None)
    time.sleep(0.2)
    check("start 后线程存活", t1.is_alive())
    n_before = len(e._steps)
    time.sleep(0.2)
    check("线程确实在推进时钟", len(e._steps) > n_before, len(e._steps) - n_before)

    t0 = time.perf_counter()
    ok = e._stop_logic_thread()
    stop_dt = time.perf_counter() - t0
    check("stop 返回 True (停干净)", ok is True, ok)
    check("stop 在 100ms 内返回 (join 不卡满 2s)", stop_dt < 0.1, "%.3fs" % stop_dt)
    check("stop 后线程 alive=False", not t1.is_alive())

    n0 = len(e._steps)
    time.sleep(0.3)
    check("stop 后无孤儿线程继续推时钟", len(e._steps) == n0, len(e._steps) - n0)

    t2 = e._start_logic_thread(e._clock)
    time.sleep(0.15)
    alive = [t for t in threading.enumerate() if t.name == 'loom-logic']
    check("再 start 后只有 1 个 loom-logic 线程", len(alive) == 1, [t.name for t in alive])
    check("再 start 起的是新线程", t2 is not t1)
    e._stop_logic_thread()
    alive2 = [t for t in threading.enumerate() if t.name == 'loom-logic']
    check("收尾 stop 后无 loom-logic 线程", len(alive2) == 0, [t.name for t in alive2])


def t_vk_driver_pause_no_debt():
    """P1-A 的 VK 侧对称用例 (2026-11-09): scene_driver 暂停 0.5s 后恢复首帧步数 <= 1.

    VK 驱动的时钟吃的是调用方 render_dt（不是墙钟），本就不会追帧；本用例锁住
    "暂停早退路径也做了重锚"这一形状（换时钟实现/改墙钟口径时不会退化）。
    """
    print("=== C. VK driver 暂停重锚 (恢复首帧不补欠账) ===")
    import scene_driver
    d = scene_driver.SceneDriver()
    d.load_from_data({'version': 10,
                      'camera': {'target': [0, 1, 0], 'distance': 8.0,
                                 'yaw': 0.5, 'pitch': -0.3},
                      'objects': [], 'lights': [], 'materials': [],
                      'cameras': [], 'active_camera': None})
    d.set_logic_paused(True)
    for _ in range(5):
        d.advance_logic(1 / 60.0)
    time.sleep(0.5)                     # 真实停顿时长（旧实现恢复首帧会补欠账）
    d.set_logic_paused(False)
    first = d.advance_logic(1 / 60.0)
    n_first = 0 if first is None else int(first[0] or 0)
    check("VK: 暂停 0.5s 后恢复首帧逻辑步数 <= 1", n_first <= 1, n_first)
    steps = []
    for _ in range(6):
        r = d.advance_logic(1 / 60.0)
        steps.append(0 if r is None else int(r[0] or 0))
    check("VK: 恢复后仍在正常推进 (6 帧总步数 >= 2)", sum(steps) >= 2, steps)


if __name__ == "__main__":
    print("========== 时钟暂停恢复 / 逻辑线程启停 定向测试 ==========")
    t_pause_no_debt()
    t_set_logic_paused_path()
    t_thread_stop_restart()
    t_vk_driver_pause_no_debt()
    print("=" * 50)
    if _fails:
        print("总结果: %d 项失败 ❌" % len(_fails))
        for f in _fails:
            print("  FAIL:", f)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
