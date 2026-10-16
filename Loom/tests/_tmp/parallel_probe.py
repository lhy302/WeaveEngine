# -*- coding: utf-8 -*-
"""临时探针: 验证 parallel.py 结构体/拓扑/策略 (用完可删)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import parallel

# 结构体大小核对
print("sizeof _CPU_SET =", parallel.ctypes.sizeof(parallel._CPU_SET),
      "(应 24)")
print("sizeof _SYSTEM_CPU_SET_INFORMATION =",
      parallel.ctypes.sizeof(parallel._SYSTEM_CPU_SET_INFORMATION), "(应 32)")

# 原始记录 dump: 首个 CPU set 记录各字段
k32 = parallel.ctypes.WinDLL('kernel32', use_last_error=True)
fn = k32.GetSystemCpuSetInformation
fn.restype = parallel.wintypes.BOOL
fn.argtypes = [parallel.ctypes.c_void_p, parallel.wintypes.DWORD,
               parallel.ctypes.POINTER(parallel.wintypes.DWORD),
               parallel.ctypes.c_void_p, parallel.wintypes.DWORD]
needed = parallel.wintypes.DWORD(0)
fn(None, 0, parallel.ctypes.byref(needed), None, 0)
buf = parallel.ctypes.create_string_buffer(needed.value)
used = parallel.wintypes.DWORD(0)
fn(buf, needed.value, parallel.ctypes.byref(used), None, 0)
rec0 = parallel._SYSTEM_CPU_SET_INFORMATION.from_buffer(buf, 0)
print("记录0: Size=%d Type=%d" % (rec0.Size, rec0.Type))
cs = rec0.CpuSet
print("  Id=%d Group=%d LogicalProcessorIndex=%d CoreIndex=%d "
      "EfficiencyClass=%d AllFlags=%d" % (cs.Id, cs.Group,
      cs.LogicalProcessorIndex, cs.CoreIndex, cs.EfficiencyClass, cs.AllFlags))
print("  原始字节:", bytes(buf[:rec0.Size]).hex(" "))

# 本机拓扑 (用 LogicalProcessorIndex)
sets = parallel._detect_cpu_sets()
print("_detect_cpu_sets 前 4 条 (Id, EffClass):", sets[:4])
topo = parallel.detect_topology()
print("拓扑 records:", len(topo), "前 4:", topo[:4])
eff = [i for i, e in topo if e]
print("E 核数:", len(eff), "P 核数:", len(topo) - len(eff))

# 策略 (本机应均质)
pol = parallel.compute_policy(topo, 2)
print("策略:", pol)
