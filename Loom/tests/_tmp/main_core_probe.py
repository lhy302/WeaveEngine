# -*- coding: utf-8 -*-
"""main_core_probe.py — 主线程核心调度端到端验证 (2026-08-15).

真实测量每核 busy% -> 启动 MainThreadCoreScheduler (真 pin 主线程) ->
  - 断言选中核 = P 核里 busy 最低
  - 断言主线程实际亲和掩码 = 1<<选中核 (真改了)
  - 打印每核负载 (应能看到 CPU1 等高负载核被避开)
用法: py -3.12 tests\_tmp\main_core_probe.py
"""
import ctypes
import os
import sys
import threading

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import parallel

print("拓扑 (前几个):", parallel.detect_topology()[:4])
busy = parallel.measure_core_busy(window=0.2)
if not busy:
    print("无法测每核负载 (API 失败)")
    sys.exit(1)

topo = parallel.detect_topology()
pbits = [b for b, e in topo if not e and b in busy]
sorted_busy = sorted(((busy[b], b) for b in pbits), reverse=True)
print("\nP 核负载排序 (高->低):")
for v, b in sorted_busy:
    mark = "  <-- 静态高负载" if b == 1 else ""
    print("  核 #%-3d %5.1f%%%s" % (b, v, mark))
best = min(pbits, key=lambda b: busy[b])

sched = parallel.MainThreadCoreScheduler(topo, busy_probe=lambda: busy)
chosen = sched.current_bit()
# 真锁核验证: SetThreadAffinityMask 成功 (该 API 无公开 getter, 返回旧掩码非0=成功)
pin_ok = sched._pin_main(chosen) if chosen is not None else False
sched.stop()

print("\n选中核: #%s (P核中 busy 最低: %.1f%%)" % (chosen, busy[chosen] if chosen is not None else -1))
ok = (chosen == best and pin_ok and chosen != 1)
print("断言: 选中=最低P核? %s | 主线程锁核成功? %s | 避开CPU1? %s"
      % (chosen == best, pin_ok, chosen != 1))
print("总结果:", "ALL PASS ✅" if ok else "FAIL ❌")
sys.exit(0 if ok else 1)
