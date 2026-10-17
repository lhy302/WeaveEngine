# -*- coding: utf-8 -*-
r"""numba_spin_probe.py — 只读探针: 实证 numba prange 线程池 spin-wait 空转 (2026-08-31).

用户问题: CPU 满载 18 核但负载是"无效的" — 18 倍核心占用只换来 +20 帧。
假设: aabbs_minmax 每次 prange 调用后 numba 线程池 worker 在 spin-wait 空烧 CPU
     (OMP_WAIT_POLICY=active 默认 / tbb busy loop), 空烧时间 >> 真实工作时间。

方法 (全程只读, 不改引擎任何文件):
  1. 直接构造 51 球规模的 aabbs_minmax 调用 (V=2035, 同 stress 场景), 循环调用
     模拟每帧一次 -> 测量窗口内每线程 GetThreadTimes, 看 worker 线程 CPU%。
  2. 对比: 工作总量 = 单次调用耗时 x 次数 (真工作量); worker 烧掉的 CPU 总量
     (GetThreadTimes) 应 >> 工作量 x 核数比 => spin 空转定量实锤。
  3. 顺便测 threading layer 与 NUMBA_NUM_THREADS 环境变量不改状态下的默认值报告。
"""
import os
import sys
import ctypes
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

from ctypes import wintypes
import numpy as np

# ---- numba 环境报告 (只读) ----
import numba
print("numba 版本:", numba.__version__)
try:
    from numba.np.ufunc import parallel
    print("threading layer:", parallel.get_threading_layer())
except Exception as e:
    print("threading layer: <查询失败>", e)
print("NUMBA_NUM_THREADS 默认 =", numba.config.NUMBA_NUM_THREADS)
print("NUMBA_NUM_THREADS 环境变量 =", os.environ.get('NUMBA_NUM_THREADS', '<未设置>'))
print("OMP_WAIT_POLICY =", os.environ.get('OMP_WAIT_POLICY', '<未设置>'))
print()

try:
    from numba.core import config as _nbcfg
    _ = _nbcfg  # noqa
except Exception:
    pass
import fastpath
rng = np.random.default_rng(42)

# 51 模型 x V=2035 顶点 (压测球规模), f64
N, V = 51, 2035
vh = rng.standard_normal((N, V, 4))
vh[:, :, 3] = 1.0
m3 = rng.standard_normal((N, 4, 3))
mn = np.empty((N, 3)); mx = np.empty((N, 3))

# 预热 (JIT 编译 + 线程池建好)
fastpath.aabbs_minmax(vh, m3, mn, mx)
fastpath.aabbs_minmax(vh, m3, mn, mx)

TH32CS_SNAPTHREAD = 4
tids = [t.ident for t in threading.enumerate()]


def thread_cpu_ms():
    """{tid: kernel+user ms} 本进程全部线程."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    class _TE(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                    ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD)]
    class _FT(ctypes.Structure):
        _fields_ = [('lo', wintypes.DWORD), ('hi', wintypes.DWORD)]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = _TE(); te.dwSize = ctypes.sizeof(_TE)
    out = {}
    pid = os.getpid()
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            h = k32.OpenThread(0x0040, False, te.th32ThreadID)
            if h:
                ct, et, kt, ut = _FT(), _FT(), _FT(), _FT()
                if k32.GetThreadTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                      ctypes.byref(kt), ctypes.byref(ut)):
                    out[te.th32ThreadID] = ((kt.hi << 32 | kt.lo) + (ut.hi << 32 | ut.lo)) / 1e4
                k32.CloseHandle(h)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return out


# ---- 实验 A: 连续调用模式 (模拟每帧一次 prange, 中间无间隔) ----
CALLS = 300
main_t0 = threading.get_ident()
c0 = thread_cpu_ms()
t0 = time.perf_counter()
for _ in range(CALLS):
    fastpath.aabbs_minmax(vh, m3, mn, mx)
wall = time.perf_counter() - t0
c1 = thread_cpu_ms()

per_call_us = wall / CALLS * 1e6
work_ms = wall * 1000.0                    # 全部调用总墙钟 (单调用是串行入口)
cpu_by_tid = {tid: (c1.get(tid, 0) - c0.get(tid, 0)) for tid in set(c1) | set(c0)}
total_cpu = sum(v for k, v in cpu_by_tid.items())
n_workers = sum(1 for v in cpu_by_tid.values() if v > wall * 1000.0 * 0.3)

print("========== 实验 A: %d 次 aabbs_minmax 连续调用 (51球x%d顶点) ==========" % (CALLS, V))
print("墙钟: %.1f ms | 单次调用: %.1f us | 每帧工作量(组3报告)=~104us 量级" % (wall * 1000, per_call_us))
print("窗口内全进程 CPU 总耗时: %.1f ms (墙钟 %.1f ms => 相当于 %.1f 个核全程烧满)"
      % (total_cpu, wall * 1000, total_cpu / (wall * 1000)))
print()

print("每线程 CPU ms (窗口 %.1f ms):" % (wall * 1000,))
main_tid = None
for tid in sorted(cpu_by_tid, key=lambda k: -cpu_by_tid[k]):
    v = cpu_by_tid[tid]
    if v < 1.0:
        continue
    is_main = "  <= 主线程(调用线程)" if tid == main_t0 else ""
    print("  tid=%-6d %8.1f ms  (%5.1f%% 墙钟)%s" % (tid, v, v / (wall * 10), is_main))

# ---- 实验 B: 间隔调用 (模拟真实帧节奏 ~6.8ms 帧间隔), spin 是否持续烧 ----
GAP = 0.0068
c0 = thread_cpu_ms()
t0 = time.perf_counter()
for _ in range(60):
    fastpath.aabbs_minmax(vh, m3, mn, mx)
    time.sleep(GAP)
wall_b = time.perf_counter() - t0
c1 = thread_cpu_ms()
cpu_by_tid_b = {tid: (c1.get(tid, 0) - c0.get(tid, 0)) for tid in set(c1) | set(c0)}
total_cpu_b = sum(cpu_by_tid_b.values())
real_work = 60 * per_call_us / 1000.0
print()
print("========== 实验 B: 60 次调用 + 每次 6.8ms 间隔 (模拟帧节奏) ==========")
print("墙钟: %.1f ms | 真实工作总量: %.1f ms | 全进程 CPU 消耗: %.1f ms (%.1f 核全程)"
      % (wall_b * 1000, real_work, total_cpu_b, total_cpu_b / wall_b / 1000))
print("=> 若 CPU 消耗 >> 真实工作量, 差值即 spin-wait 空烧")
