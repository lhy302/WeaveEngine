# -*- coding: utf-8 -*-
"""test_scene_driver_physics_log.py — 物理桥持续异常时日志只打印一次 (不刷屏).

背景 (_fix_summary §5 遗留 1)
----------------------------
SceneDriver._step_physics 旧实现每帧 except 都 print 一条
"[驱动] 物理桥步进异常 ... -> 本帧跳过"。桥一旦持续异常 (坏 DLL/坏体/脚本
把桥状态搞坏), 播放器每秒刷 60 条日志, 控制台不可读、日志文件暴涨。

修复: 每场只在**首次**异常打印 1 条, 后续只累加 _bridge_err_count; 换场景
(load_from_data) 重置, 新场景仍会得到自己的那一条。

本文件断言:
  A: 假桥每帧抛异常, 5 帧只出 1 条日志 (验收项)。
  B: 首条日志含异常 repr 且明确"后续只计数"。
  C: _bridge_err_count 累计每次异常 (5 帧 = 5 次调用)。
  D: advance_logic 路径 (逻辑子步/物理帧多次调 _step_physics) 同样只 1 条。
  E: 换场景后重置 -> 新场景再出 1 条 (每场一条)。
  F: 健康桥不产生任何日志, 计数为 0。

运行: python tests\test_scene_driver_physics_log.py   (无头, 无 GPU)
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import scene_driver as SD

MARK = "[驱动] 物理桥步进异常"
_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


class _BadBridge:
    """三段全通, step 持续抛异常 (模拟坏桥)."""

    def __init__(self, where='step'):
        self.where = where
        self.calls = 0

    def ensure_models(self, models):
        self.calls += 1
        if self.where == 'ensure_models':
            raise RuntimeError('boom-ensure')

    def pre_step(self, dt, gravity):
        if self.where == 'pre_step':
            raise RuntimeError('boom-pre')

    def step(self, dt):
        if self.where == 'step':
            raise RuntimeError('boom-step')

    def post_step(self):
        if self.where == 'post_step':
            raise RuntimeError('boom-post')


class _GoodBridge:
    def __init__(self):
        self.calls = 0

    def ensure_models(self, models):
        self.calls += 1

    def pre_step(self, dt, gravity):
        pass

    def step(self, dt):
        pass

    def post_step(self):
        pass


def _scene(n=1):
    return {"version": 10, "materials": [], "lights": [], "cameras": [],
            "camera": {"target": [0, 0, 0], "distance": 10.0,
                       "yaw": 0.0, "pitch": 0.0},
            "objects": [{"id": "o%d" % i, "name": "o%d" % i, "type": "cube",
                         "params": {"size": 1.0}, "position": [i, 0, 0],
                         "rotation": [0, 0, 0], "scale": [1, 1, 1],
                         "color": "#808080", "visible": True,
                         "scripts": []} for i in range(n)]}


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def _new_driver(bridge, data=None):
    d = SD.SceneDriver()
    if data is not None:
        d.load_from_data(data)
    d._bridge = bridge            # 跳过惰性建桥, 直接注入假桥
    return d


# ====================================================================
# A/B/C: 5 帧持续异常 -> 1 条日志 + 计数
# ====================================================================
def t_five_frames_one_log():
    print("=== A/B/C: 5 帧持续异常 -> 1 条日志 ===")
    d = _new_driver(_BadBridge())
    logs = _capture(lambda: [d._step_physics(1 / 60.0) for _ in range(5)])
    n = logs.count(MARK)
    check("[A] 5 帧只出 1 条日志", n == 1, "日志条数=%d" % n)
    check("[B] 首条日志含异常 repr", 'RuntimeError' in logs and 'boom-step' in logs,
          logs.strip()[:100])
    check("[B] 首条日志说明后续只计数", ('只计数' in logs) or ('不打印' in logs),
          logs.strip()[:100])
    check("[C] _bridge_err_count 累计 5 次", d._bridge_err_count == 5,
          d._bridge_err_count)
    check("[C] _bridge_err_logged 已置位", d._bridge_err_logged is True)


def t_each_stage_throttled():
    print("=== A2: ensure_models/pre_step/post_step 异常同样限一次 ===")
    for where in ('ensure_models', 'pre_step', 'post_step'):
        d = _new_driver(_BadBridge(where))
        logs = _capture(lambda: [d._step_physics(1 / 60.0) for _ in range(5)])
        n = logs.count(MARK)
        check("  %s 异常: 5 帧 1 条" % where, n == 1, "日志条数=%d" % n)


# ====================================================================
# D: advance_logic 路径 (一帧可能多次步进) 仍只 1 条
# ====================================================================
def t_advance_logic_path():
    print("=== D: advance_logic 5 帧 -> 仍 1 条 ===")
    d = _new_driver(_BadBridge(), data=_scene(2))
    logs = _capture(lambda: [d.advance_logic(1 / 60.0) for _ in range(5)])
    n = logs.count(MARK)
    check("[D] advance_logic 5 帧只出 1 条", n == 1, "日志条数=%d" % n)
    check("[D] 计数 >= 1 (确实步进过)", d._bridge_err_count >= 1,
          d._bridge_err_count)


# ====================================================================
# E: 换场景重置 (每场一条)
# ====================================================================
def t_scene_reset():
    print("=== E: 换场景重置, 新场景再出 1 条 ===")
    d = _new_driver(_BadBridge(), data=_scene(1))
    first = _capture(lambda: [d._step_physics(1 / 60.0) for _ in range(5)])
    d.load_from_data(_scene(2))          # 新场景: 计数/已打印标志重置
    check("[E] 换场景后计数清零", d._bridge_err_count == 0, d._bridge_err_count)
    check("[E] 换场景后未打印标志复位", d._bridge_err_logged is False)
    second = _capture(lambda: [d._step_physics(1 / 60.0) for _ in range(5)])
    check("[E] 第一场 1 条", first.count(MARK) == 1, first.count(MARK))
    check("[E] 第二场 1 条", second.count(MARK) == 1, second.count(MARK))


# ====================================================================
# F: 健康桥零日志
# ====================================================================
def t_good_bridge_silent():
    print("=== F: 健康桥不打印 ===")
    br = _GoodBridge()
    d = _new_driver(br)
    logs = _capture(lambda: [d._step_physics(1 / 60.0) for _ in range(5)])
    check("[F] 健康桥 0 条异常日志", logs.count(MARK) == 0, repr(logs[:60]))
    check("[F] 健康桥计数为 0", d._bridge_err_count == 0, d._bridge_err_count)
    check("[F] 健康桥确实被调用 5 次", br.calls == 5, br.calls)


if __name__ == "__main__":
    print("========== 物理桥异常日志限流 (_fix_summary §5 遗留 1) ==========")
    t_five_frames_one_log()
    t_each_stage_throttled()
    t_advance_logic_path()
    t_scene_reset()
    t_good_bridge_silent()
    print()
    if _fails:
        print("总结果: FAIL", _fails)
        sys.exit(1)
    print("总结果: ALL PASS")
