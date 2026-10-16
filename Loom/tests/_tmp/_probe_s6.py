# -*- coding: utf-8 -*-
"""_probe_s6.py — 独立探针: 不导入 engine, 复现 test_parallel.py 359-361 行 _s6 场景.
用于判定 "interval=0 仍做启动选核" FAIL 是否与 engine.py 改动有关。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # -> Loom 根
import parallel  # noqa: E402

print("engine imported? ->", 'engine' in sys.modules)

_topo_hyb = [(i, False) for i in range(8)] + [(i, True) for i in range(8, 12)]
_busy = {i: 30.0 + (20 if i == 1 else 0) for i in range(12)}
_busy[5] = 5.0

# 与 test_parallel.py 360 行完全同参 (真绑核, 不 disable_pin)
s6 = parallel.MainThreadCoreScheduler(_topo_hyb, busy_probe=lambda: _busy, interval=0)
print("real-pin   current_bit =", s6.current_bit())

# 对照: disable_pin=True 纯逻辑路径 (同 test_parallel.py 327-330 _mk_sched)
s1 = parallel.MainThreadCoreScheduler(_topo_hyb, busy_probe=lambda: _busy,
                                      disable_pin=True, margin=15.0, exclude_bits=0)
print("disable_pin current_bit =", s1.current_bit())
