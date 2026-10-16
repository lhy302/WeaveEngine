# -*- coding: utf-8 -*-
r"""stress_probe.py — 高面数球压测: 8 核均摊验证探针 (2026-08-15).

用法: py -3.12 tests/_tmp/stress_probe.py [帧数] [场景json]
  默认 300 帧 stress_50spheres.json (历史基线场景);
  500 球: py -3.12 tests/_tmp/stress_probe.py 300 stress_500spheres.json
  - 关 vsync (GL_SWAP_CONTROL=0, 须在 set_mode 前) -> 真 FPS
  - LOOM_PROFILE=1: 逐阶段耗时 (physics / world_matrices / aabbs / shadow_prep, ms/帧)
  - 每线程 CPU% 采样 (ctypes GetThreadTimes, 测量窗口内 delta / 墙钟)
  - 线程名 -> tid 映射 (threading.enumerate) + 亲和掩码
场景生成见 stress_scene.py (默认 50; 500 球: stress_scene.py 500).
"""
import os
import sys
import time

# 关 vsync: 必须在 set_mode 前设好 GL 属性 (pygame.init 后可设)
os.environ['LOOM_PROFILE'] = '1'          # 打开阶段计时 (render 内 _profile 插桩)
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
os.chdir(BASE)

import ctypes
from ctypes import wintypes
import threading
import queue
import subprocess
import pygame
import numpy as np


# ---------------- GPU 利用率采样 (nvidia-smi 轮询, 2026-08-28 性能调优加) ----------------
def gpu_sampler(stop_ev, q):
    """后台线程: 每 0.5s 采样 nvidia-smi util.gpu, 结果放队列."""
    while not stop_ev.is_set():
        try:
            out = subprocess.run(
                ['nvidia-smi', '--query-gpu=utilization.gpu',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            q.put(float(out.stdout.strip().splitlines()[0]))
        except Exception:
            pass
        stop_ev.wait(0.15)

SCENE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     (sys.argv[2] if len(sys.argv) > 2 else 'stress_50spheres.json'))
W, H = 1024, 768

# ---------------- 每线程 CPU 采样 (ctypes) ----------------
TH32CS_SNAPTHREAD = 0x00000004
THREAD_QUERY_INFORMATION = 0x0040
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _FILETIME(ctypes.Structure):
    _fields_ = [('lo', wintypes.DWORD), ('hi', wintypes.DWORD)]


class _TE(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG),
                ('dwFlags', wintypes.DWORD)]


def _ft_ms(ft):
    return (ft.hi << 32 | ft.lo) / 10000.0        # 100ns -> ms


def sample_thread_cpu():
    """进程内每线程 (kernel+user) CPU ms 快照 -> {tid: ms}."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        return {}
    pid = os.getpid()
    te = _TE(); te.dwSize = ctypes.sizeof(_TE)
    out = {}
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            h = k32.OpenThread(THREAD_QUERY_INFORMATION, False, te.th32ThreadID)
            if h:
                ct, et, kt, ut = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
                if k32.GetThreadTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                      ctypes.byref(kt), ctypes.byref(ut)):
                    out[te.th32ThreadID] = _ft_ms(kt) + _ft_ms(ut)
                k32.CloseHandle(h)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return out


def thread_name_map():
    """{tid: thread名}. 主线程名 'MainThread'."""
    m = {}
    for t in threading.enumerate():
        try:
            m[t.ident] = t.name
        except Exception:
            pass
    return m


def main():
    n_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    # ---- 关 vsync + 建引擎 ----
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    import runtime
    eng = runtime.PlayerApp(SCENE, W, H)
    eng.set_mouse_locked(False)          # 探针不锁鼠标 (PlayerApp 默认捕获)

    # 线程名/亲和信息 (引擎线程已建好)
    names = thread_name_map()
    aff = {}
    for t in threading.enumerate():
        try:
            m = parallel_mask_of_thread(t.ident)
            aff[t.ident] = m
        except Exception:
            aff[t.ident] = 0

    # ---- 预热 (让脚本实例/阴影贴图/缓存就位) ----
    for _ in range(40):
        eng.render(1.0 / 120.0)

    # GC 冻结 (流畅度批 2026-09-01): 预热后把 GL 惰性资源 (阴影 FBO/桶 VAO/
    # 文字纹理缓存/脚本实例) 一起冻进去 —— 测量窗口=稳态, 与发布玩家生命周期一致.
    # (PlayerApp.__init__ 已冻过一次, 此处是叠加冻结预热期新增对象, 合法.)
    # LOOM_GC_LEGACY=1 时 gc_play_enter 自动 no-op -> 与无 GC 管理基线一致.
    from engine import gc_play_enter
    gc_play_enter()

    # ---- GC 对账探针 (LOOM_GC_PROBE=1 开; 默认关零开销) ----
    _gc_probe = None
    if os.environ.get('LOOM_GC_PROBE') == '1':
        import gc
        _probe_state = {'frame': 0, 't': 0.0}
        _gc_events = []

        def _gc_cb(phase, info):
            if phase == 'start':
                _probe_state['t'] = time.perf_counter()
            else:
                _gc_events.append((_probe_state['frame'], info['generation'],
                                   (time.perf_counter() - _probe_state['t']) * 1000.0,
                                   info.get('collected', -1),
                                   info.get('uncollectable', -1)))
        gc.callbacks.append(_gc_cb)
        _gc_probe = (_gc_cb, _gc_events, _probe_state)

    # ---- 测量窗口 ----
    eng._stage_times.clear()
    stop_ev = threading.Event()
    gq = queue.Queue()
    gth = threading.Thread(target=gpu_sampler, args=(stop_ev, gq), daemon=True)
    gth.start()
    t0 = time.perf_counter()
    cpu0 = sample_thread_cpu()
    frames = 0
    dts = []                             # 逐帧墙钟秒 (GC 批: 帧尖刺对账用)
    while frames < n_frames:
        _f0 = time.perf_counter()
        eng.render(1.0 / 120.0)
        dts.append(time.perf_counter() - _f0)
        frames += 1
        if _gc_probe is not None:
            _gc_probe[2]['frame'] = frames
    wall = time.perf_counter() - t0
    cpu1 = sample_thread_cpu()
    if _gc_probe is not None:
        import gc
        gc.callbacks.remove(_gc_probe[0])    # 按对象身份摘除 (防误删其他消费者)
    stop_ev.set(); gth.join(timeout=2)
    gpus = []
    try:
        while True:
            gpus.append(gq.get_nowait())
    except queue.Empty:
        pass

    fps = frames / wall
    # 每线程 CPU% (相对墙钟, 可 >100 表示多核并行利用)
    cpus = {}
    for tid, ms0 in cpu0.items():
        ms1 = cpu1.get(tid, ms0)
        cpus[tid] = (ms1 - ms0) / (wall * 1000.0) * 100.0

    # ---- 汇总 ----
    def _mask_bits(m):
        return [i for i in range(64) if m & (1 << i)]

    print("\n========== 压测 %s (%d 帧, 墙钟 %.2fs) =========="
          % (os.path.basename(SCENE), frames, wall))
    print("FPS: %.1f  (平均帧时间 %.3f ms)" % (fps, 1000.0 / fps))
    if gpus:
        print("GPU 利用率: 平均 %.1f%% 峰值 %.1f%% (nvidia-smi %d 样本)"
              % (sum(gpus) / len(gpus), max(gpus), len(gpus)))
    st = eng._stage_times
    print("逐阶段累计耗时 (LOOM_PROFILE):")
    for k in ('logic_step', 'interp', 'pipe_wait', 'physics', 'phys_bridge_ensure', 'phys_bridge_pre', 'phys_bridge_step',
              'phys_bridge_post', 'world_matrices', 'aabbs', 'shadow_prep',
              'shadow_bounds', 'shadow_cornerfill', 'shadow_matmul',
              'collide_pairs', 'shadow_jobs', 'dispatch', 'buckets'):
        print("  %-22s %7.2f ms/帧" % (k, st.get(k, 0.0) / frames))
    tot = sum(st.values()) / frames
    print("  已插桩阶段合计      %7.2f ms/帧 (帧时间 %.3f ms, 其余=GL/脚本/事件)"
          % (tot, 1000.0 / fps))

    print("\n每线程 CPU% (测量窗口; >100% = 用了多个核/并行):")
    rows = sorted(cpus.items(), key=lambda kv: -kv[1])
    for tid, p in rows:
        if p < 0.5:
            continue
        nm = names.get(tid, '?')
        am = _mask_bits(aff.get(tid, 0))
        ams = ",".join(str(b) for b in am) if am else "未绑定(全核)"
        print("  tid=%-6d CPU=%6.1f%%  %-28s 亲和[%s]" % (tid, p, nm, ams))

    # ---- GC 对账 + 帧稳定性汇总 (流畅度批 2026-09-01) ----
    if dts:
        dms = sorted(d * 1000.0 for d in dts)
        p50 = dms[int(0.50 * len(dms))]
        p99 = dms[min(int(0.99 * len(dms)), len(dms) - 1)]
        spike2 = sum(1 for m in dms if m > 2 * p50)
        spike4 = sum(1 for m in dms if m > 4 * p50)
        print("\n帧稳定性: p50=%.3f p99=%.3f max=%.3f ms | >2x中位 尖刺=%d帧 (%.1f%%) >4x=%d帧"
              % (p50, p99, dms[-1], spike2, 100.0 * spike2 / len(dms), spike4))
    if _gc_probe is not None:
        import gc
        _ev = _gc_probe[1]
        print("\n========== GC 对账 (LOOM_GC_PROBE, %d 帧) ==========" % frames)
        if not _ev:
            print("GC 事件: 0 (窗口内零 GC —— freeze+阈值生效)")
        else:
            for gen in (0, 1, 2):
                ev = [e for e in _ev if e[1] == gen]
                if not ev:
                    print("  gen%d: 事件=0" % gen)
                    continue
                ms = sorted(e[2] for e in ev)
                print("  gen%d: 事件=%d 总ms=%.2f avg=%.3f max=%.3f p99=%.3f"
                      % (gen, len(ev), sum(ms), sum(ms) / len(ms),
                         ms[-1], ms[min(int(0.99 * len(ms)), len(ms) - 1)]))
        # 延迟直方图 (全部事件)
        if _ev:
            edges = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
            names_h = ("[0,0.1)", "[0.1,0.5)", "[0.5,1)", "[1,2)", "[2,5)",
                       "[5,10)", "[10,20)", "[20,50)", "[50,100)", "[100+)")
            hist = [0] * 10
            for e in _ev:
                idx = len(edges)
                for i, b in enumerate(edges):
                    if e[2] < b:
                        idx = i
                        break
                hist[idx] += 1
            print("延迟直方图 (全部事件): " +
                  "  ".join("%s=%d" % (n, c) for n, c in zip(names_h, hist) if c))
        # 帧尖刺对账: 尖刺帧 vs 落入的 GC 事件
        if dts and _ev:
            dm = [d * 1000.0 for d in dts]
            med = sorted(dm)[int(0.50 * len(dm))]
            spikes = [(i, dm[i]) for i in range(len(dm)) if dm[i] > 2 * med]
            ev_by_frame = {}
            for e in _ev:
                ev_by_frame.setdefault(e[0], []).append(e)
            print("帧尖刺对账: 尖刺帧 %d 个 (dt > 2×中位 %.3fms):" % (len(spikes), med))
            hit = 0
            for fi, dtv in spikes[:10]:
                evs = ev_by_frame.get(fi, [])
                gms = sum(e[2] for e in evs)
                if evs:
                    hit += 1
                print("  frame %d: dt=%.2fms  GC: %s" % (
                    fi, dtv,
                    "gen%s %.2fms" % (",".join(str(e[1]) for e in evs), gms)
                    if evs else "无 GC 事件"))
            if spikes:
                print("尖刺帧落 GC 比例: %d/%d = %.0f%% (70%%+ 证明 GC 元凶 / 30%%- 排除)"
                      % (hit, len(spikes), 100.0 * hit / len(spikes)))
        elif dts:
            print("帧尖刺对账: 窗口零 GC 事件, 尖刺若存在必非 GC (冻结+阈值生效)")

    eng._stop_parallel()
    pygame.quit()
    print("\n完成。")


def parallel_mask_of_thread(tid):
    """线程亲和掩码 (只读, 供报告)."""
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.OpenThread.restype = wintypes.HANDLE   # 关键: 不设 restype 默认截断成 32 位句柄
        h = k32.OpenThread(THREAD_QUERY_INFORMATION, False, int(tid))
        if not h:
            return 0
        pm = wintypes.c_size_t(0)
        sm = wintypes.c_size_t(0)
        k32.GetThreadAffinityMask(wintypes.HANDLE(h), ctypes.byref(pm),
                                  ctypes.byref(sm))
        k32.CloseHandle(wintypes.HANDLE(h))
        return int(pm.value)
    except Exception:
        return 0


if __name__ == '__main__':
    main()
