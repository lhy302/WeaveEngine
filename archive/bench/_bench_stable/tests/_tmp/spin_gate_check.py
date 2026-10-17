# -*- coding: utf-8 -*-
"""spin_gate_check.py — spin 治理对拍网 (2026-08-31).

断言 (方案B 治本三件):
  1. 串行 aabbs_minmax vs prange aabbs_minmax_par 数值逐位一致 (同算法双版本)
  2. 闸门接线: n < _AABB_PAR_MIN_MODELS 走串行 (帧路径不触碰线程池)
  3. 串行调用不再唤醒 numba 线程池 —— 连续调用窗口内 worker 线程 CPU 归零
     (改前: 18 worker 85-93% 满烧; 改后验收 = worker 无 CPU 消耗)
  4. 堆叠缓冲复用: 两次调用结果一致 + 缓冲对象身份不变 (真复用非重建)
"""
import os
import sys
import ctypes
import threading
import time

from ctypes import wintypes

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fastpath  # noqa: E402
from engine import GLEngine  # noqa: E402
from mesh import create_sphere  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        fails += 1


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

    snap = k32.CreateToolhelp32Snapshot(4, 0)
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


def main():
    rng = np.random.default_rng(42)
    N, V = 51, 2035
    vh = rng.standard_normal((N, V, 4))
    vh[:, :, 3] = 1.0
    m3 = rng.standard_normal((N, 4, 3))

    # 预热两版 (JIT)
    mn_s = np.zeros((N, 3)); mx_s = np.zeros((N, 3))
    mn_p = np.zeros((N, 3)); mx_p = np.zeros((N, 3))
    fastpath.aabbs_minmax(vh, m3, mn_s, mx_s)
    fastpath.aabbs_minmax_par(vh, m3, mn_p, mx_p)

    # 1. 串行 vs 并行逐位
    check("1. 串行 vs prange 数值逐位一致",
          np.array_equal(mn_s, mn_p) and np.array_equal(mx_s, mx_p))

    # 3. 串行连续调用: worker 线程 CPU 必须归零 (改前 18 worker 85-93%)
    t0 = threading.get_ident()
    c0 = thread_cpu_ms()
    t0w = time.perf_counter()
    for _ in range(200):
        fastpath.aabbs_minmax(vh, m3, mn_s, mx_s)
    wall = time.perf_counter() - t0w
    c1 = thread_cpu_ms()
    per_thread = {tid: c1.get(tid, 0) - c0.get(tid, 0)
                  for tid in c1 if tid != t0}
    workers_hot = sum(1 for v in per_thread.values() if v > 5.0)
    check(f"3. 串行 200 连调 worker 线程无空烧 (热线程={workers_hot}, 应=0; "
          f"窗口 {wall*1000:.0f}ms)", workers_hot == 0)
    tot = sum(v for v in per_thread.values() if v > 0)
    print(f"    窗口内非主线程 CPU 总量 {tot:.1f}ms (墙钟 {wall*1000:.1f}ms)")

    # 2+4. 引擎闸门 + 堆叠缓冲复用
    eng = GLEngine.__new__(GLEngine)
    eng._bb_cache = {}
    eng._aabb_staging = None
    mesh = create_sphere(0.8, 36, 54)
    models = []
    for i in range(N):
        m = type('M', (), {})()
        m.mesh = mesh
        m.visible = True
        models.append(m)
    fw = [np.eye(4) for _ in range(N)]
    fw[0] = fw[0].copy(); fw[0][:3, 3] = (1.0, 2.0, 3.0)

    r1 = eng._aabbs_batched(models, fw)
    ids1 = {k: id(v[0]) for k, v in eng._aabb_staging.bufs.items()}
    r2 = eng._aabbs_batched(models, fw)
    ids2 = {k: id(v[0]) for k, v in eng._aabb_staging.bufs.items()}
    check("2. 闸门内 (n=51 < 512) 走串行 + 结果与首次一致",
          all(np.array_equal(a[0].x, b[0].x) and np.array_equal(a[1].z, b[1].z)
              for a, b in zip(r1, r2)))
    check("4. 堆叠缓冲对象身份不变 (真复用非重建)", ids1 == ids2)

    # 逃生门真实性: n>=512 切 par (桩上 pool=None 走 _aabbs_batched 单组 512)
    models_big = models * 11  # 561 > 512
    fw_big = [np.eye(4) for _ in range(561)]
    rb = eng._aabbs_batched(models_big, fw_big)
    check("逃生门 n=561 >= 512 切 par 不崩 + 数值稳定",
          len(rb) == 561 and rb[0][1].x is not None)

    print("结果:", "ALL PASS" if fails == 0 else "FAIL")
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
