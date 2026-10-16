# -*- coding: utf-8 -*-
r"""percore_check.py — 每核/每线程负载探针 (M2 验收②, 2026-09-08 重写)

★为什么重写 (用户指出的口径问题):
  旧探针沿用「主线程做一切」的旧架构假设 —— 用单次 GetThreadTimes 差分算
  主线程 CPU%, 在**新架构**下失真:
    · prep 链已进 C DLL (pipeline) 且经 worker 池分摊 → 主线程 CPU% 变化
      被帧率波动淹没;
    · 单次差分窗口短 (数秒) + 帧率不稳 → 同一配置两次跑能差 1-3 个点;
    · 系统级每核 busy 含其他进程噪声, 单点采样不可信。
  新口径 = **进程内线程 CPU 时间 (绝对 ms/帧)** + 系统级每核 busy (多窗均值):
    · 主指标: 每帧 CPU 时间 (ms/帧) —— 与帧率解耦, 可跨配置比较;
    · 分类: 主线程 / 物理线程 (loom-physics) / worker 池 / 其他;
    · 每核 busy: parallel.measure_core_busy 多窗采样取中位数 (抗噪声)。

用法: py -3.12 tests\_tmp\percore_check.py [帧数] [场景json] [--child on|off] [--out x.json]
"""
import ctypes
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'core_components'))
os.chdir(BASE)

W, H = 1280, 720
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAILED', name, detail))


class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', wintypes.DWORD),
                ('dwHighDateTime', wintypes.DWORD)]


def _ft(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ThreadID', wintypes.DWORD),
                ('th32OwnerProcessID', wintypes.DWORD),
                ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG),
                ('dwFlags', wintypes.DWORD)]


def snap_thread_cpu():
    """{tid: cpu_100ns} 本进程全部线程的 kernel+user 累计时间。"""
    k32 = ctypes.windll.kernel32
    THREAD_QUERY_INFORMATION = 0x0040
    TH32CS_SNAPTHREAD = 0x00000004
    h = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if h == -1:
        return {}
    pid = os.getpid()
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    out = {}
    ok = k32.Thread32First(h, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            th = k32.OpenThread(THREAD_QUERY_INFORMATION, False, te.th32ThreadID)
            if th:
                ct, et, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
                if k32.GetThreadTimes(th, ctypes.byref(ct), ctypes.byref(et),
                                      ctypes.byref(kt), ctypes.byref(ut)):
                    out[te.th32ThreadID] = _ft(kt) + _ft(ut)
                k32.CloseHandle(th)
        ok = k32.Thread32Next(h, ctypes.byref(te))
    k32.CloseHandle(h)
    return out


def run_child(frames, scene, out_path):
    """★B2 退役 (2026-10-16): 删 off (LOOM_NO_PIPELINE=1) 档, 单档 on。"""
    os.environ['LOOM_PROFILE'] = '1'
    import pygame
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)
    import threading
    import runtime
    import parallel
    eng = runtime.PlayerApp(scene, W, H)
    eng.set_mouse_locked(False)
    for _ in range(60):                      # 更长的预热 (让池/物理线程稳定)
        eng.render(1.0 / 120.0)
    try:
        from engine import gc_play_enter
        gc_play_enter()
    except Exception:
        pass
    eng._stage_times.clear()

    names = {t.ident: t.name for t in threading.enumerate()}
    core_windows = []
    c0 = snap_thread_cpu()
    t0 = time.perf_counter()
    for i in range(frames):
        eng.render(1.0 / 120.0)
        if i % 40 == 39:
            cb = parallel.measure_core_busy(window=0.12)
            if cb:
                core_windows.append(cb)
    wall = time.perf_counter() - t0
    c1 = snap_thread_cpu()

    # ---- 每线程 CPU 时间 → ms/帧 ----
    per_thread = []
    for tid, ms0 in c0.items():
        if tid not in c1:
            continue
        ms = (c1[tid] - ms0) / 1e4 / frames          # 100ns → ms, 除以帧数
        per_thread.append({'tid': tid, 'name': names.get(tid, '?'),
                           'ms_per_frame': ms,
                           'cpu_pct': ms * frames / (wall * 1000.0) * 100.0})

    def _sum(pred):
        return sum(r['ms_per_frame'] for r in per_thread if pred(r['name']))

    main_ms = _sum(lambda n: n == 'MainThread')
    phys_ms = _sum(lambda n: n.startswith('loom-physics'))
    sched_ms = _sum(lambda n: n.startswith('loom-sched'))
    script_ms = _sum(lambda n: n.startswith('loom-scripts'))
    pool_ms = _sum(lambda n: n.startswith('ThreadPoolExecutor'))
    numba_ms = _sum(lambda n: 'numba' in n.lower())
    total_ms = sum(r['ms_per_frame'] for r in per_thread)

    # ---- 每核 busy: 多窗中位数 ----
    ncore = os.cpu_count() or 1
    per_core = [0.0] * ncore
    if core_windows:
        for k in range(ncore):
            vals = [w.get(k, 0.0) for w in core_windows]
            per_core[k] = statistics.median(vals)

    meta = {
        'frames': frames, 'wall': wall, 'fps': frames / wall,
        'ncore': ncore, 'core_windows': len(core_windows),
        'per_core_busy': per_core,
        'others_mean': (sum(per_core[1:]) / max(1, len(per_core) - 1)),
        'others_max': max(per_core[1:]) if len(per_core) > 1 else 0.0,
        'main_ms': main_ms, 'phys_ms': phys_ms, 'sched_ms': sched_ms,
        'script_ms': script_ms, 'pool_ms': pool_ms, 'numba_ms': numba_ms,
        'total_ms': total_ms,
        'stage_shadow_bounds': eng._stage_times.get('shadow_bounds', 0.0) / max(1, frames),
        'stage_aabbs': eng._stage_times.get('aabbs', 0.0) / max(1, frames),
        'stage_collide': eng._stage_times.get('collide_pairs', 0.0) / max(1, frames),
        'threads': sorted(per_thread, key=lambda r: -r['ms_per_frame'])[:12],
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    print('CHILD_OK', flush=True)
    return 0


def _line(d):
    print('\n--- 单档  FPS=%.1f  帧数=%d  每核窗=%d ---'
          % (d['fps'], d['frames'], d['core_windows']))
    print('  进程内 CPU (ms/帧): 主线程=%.3f  物理=%.3f  sched=%.3f  '
          'scripts=%.3f  池=%.3f  合计=%.3f'
          % (d['main_ms'], d['phys_ms'], d['sched_ms'], d['script_ms'],
             d['pool_ms'], d['total_ms']))
    print('  逐阶段: shadow_bounds=%.3f  aabbs=%.3f  collide=%.3f ms/帧'
          % (d['stage_shadow_bounds'], d['stage_aabbs'], d['stage_collide']))
    print('  每核 busy%% (中位数): %s'
          % ' '.join('%.0f' % x for x in d['per_core_busy']))
    print('  其他核均值=%.1f%%  峰值=%.1f%%' % (d['others_mean'], d['others_max']))
    print('  线程前 6: %s'
          % ' | '.join('%s %.3fms' % (t['name'], t['ms_per_frame'])
                       for t in d['threads'][:6]))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    frames = int(args[0]) if args else 300
    scene = args[1] if len(args) > 1 else 'stress_500mixed.json'
    scene_path = scene if os.path.isabs(scene) else os.path.join(BASE, 'tests', '_tmp', scene)
    if '--child' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]
        return run_child(frames, scene_path, out)

    print('=== percore_check (M2 验收②, 新口径: ms/帧 + 每核中位数) %d 帧 ===' % frames)
    tmp = tempfile.mkdtemp(prefix='loom_percore_')
    out = os.path.join(tmp, 'on.json')
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run([sys.executable, os.path.abspath(__file__), str(frames),
                        scene, '--child', '--out', out],
                       capture_output=True, timeout=1200, env=env)
    ok = r.returncode == 0 and os.path.isfile(out)
    check('子进程跑通', ok, 'rc=%d' % r.returncode)
    if not ok:
        print((r.stderr or b'').decode('utf-8', 'replace')[-1500:])
        return 1
    a = json.load(open(out, encoding='utf-8'))
    _line(a)

    check('采集完成 (主线程/物理/池 ms/帧 + 每核中位数)',
          a['main_ms'] > 0 and a['core_windows'] > 0,
          '主线程=%.3fms 进程=%.3fms' % (a['main_ms'], a['total_ms']))
    check('DLL 路径生效 (shadow_bounds > 0)',
          a['stage_shadow_bounds'] > 0,
          'shadow=%.3f' % a['stage_shadow_bounds'])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    bad = results.count(False)
    print('--- %d 项: PASS %d / FAILED %d ---'
          % (len(results), results.count(True), bad))
    print('ALL PASS' if bad == 0 else 'FAILED %d 项' % bad)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
    sys.exit(main())
