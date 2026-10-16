# -*- coding: utf-8 -*-
"""tps_fps_core_probe.py — TPS/FPS 分核取证 (2026-09-07, 主线程收编自干)

实证问题 (用户): 播放态 TPS 和 FPS 是不是没分核, 单核跑死?
流程: LoomHub 同款链路启动混合500 → 播放态稳态 →
  1) 每核 busy% (parallel.measure_core_busy, NtQuerySystemInformation 同源)
  2) 线程级 GetThreadTimes 增量 (拓扑: 主线程 vs 池 worker vs numba)
  3) engine_metrics (FPS/TPS/stage_times)
输出 tests\_tmp\tps_fps_core_result.json + 控制台摘要
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

SCENE = os.path.join(LOOM, '保存', '压测500混合.json')
OUT = os.path.join(HERE, 'tps_fps_core_result.json')
SAMPLE_S = 12.0

import parallel  # noqa: E402  (LOOM 根)

# ---------- 线程 CPU 时间 ----------
k32 = ctypes.windll.kernel32
THREAD_QUERY_INFORMATION = 0x0040
TH32CS_SNAPTHREAD = 0x4


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD)]


def snap_threads(pid):
    out = {}
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32(); te.dwSize = ctypes.sizeof(THREADENTRY32)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            h = k32.OpenThread(THREAD_QUERY_INFORMATION, False, te.th32ThreadID)
            if h:
                ft = (wintypes.FILETIME * 4)()
                if k32.GetThreadTimes(wintypes.HANDLE(h),
                                      ctypes.byref(ft[0]), ctypes.byref(ft[1]),
                                      ctypes.byref(ft[2]), ctypes.byref(ft[3])):
                    to_s = lambda a, b: ((b << 32) | a) / 1e7
                    out[te.th32ThreadID] = (to_s(ft[2].dwLowDateTime, ft[2].dwHighDateTime),
                                            to_s(ft[3].dwLowDateTime, ft[3].dwHighDateTime))
                k32.CloseHandle(h)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return out


def main():
    proc = subprocess.Popen(
        [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
         '--open', SCENE, '--agent'],
        cwd=LOOM, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    info = None
    t0 = time.time()
    while time.time() - t0 < 40:
        try:
            with open(os.path.join(LOOM, '.agent_port.json'), encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                info = cand
                break
        except Exception:
            pass
        time.sleep(0.5)
    if info is None:
        print('[FATAL] 端口文件未就绪')
        proc.kill()
        return 1
    port, token = info['port'], info['token']
    print('[agent] port=%d pid=%d' % (port, proc.pid), flush=True)

    def call(name, args=None):
        import urllib.request
        body = json.dumps({'cmd': name, 'args': args or {}}).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
            headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode('utf-8'))

    result = {}
    try:
        time.sleep(6.0)
        call('play', {'on': True})
        time.sleep(6.0)  # 播放态稳态

        # ---- 采样窗: 每核 busy (1s 窗 ×6) + 线程增量 ----
        th0 = snap_threads(proc.pid)
        t0 = time.perf_counter()
        core_samples = []
        while time.perf_counter() - t0 < SAMPLE_S:
            core_samples.append(parallel.measure_core_busy(window=0.5))
            time.sleep(0.1)
        wall = time.perf_counter() - t0
        th1 = snap_threads(proc.pid)

        ncores = len(core_samples[0])
        core_mean = [0.0] * ncores
        for s in core_samples:
            for k, v in s.items():          # 键=逻辑核号, 值=busy%
                if isinstance(k, int) and 0 <= k < ncores:
                    core_mean[k] += v
        core_mean = [v / len(core_samples) for v in core_mean]

        threads = []
        for tid, (k0, u0) in th0.items():
            if tid in th1:
                k1, u1 = th1[tid]
                tot = ((k1 - k0) + (u1 - u0))
                if tot > 0.005:
                    threads.append({'tid': tid, 'cpu_s': round(tot, 3),
                                    'pct_of_core': round(100 * tot / wall, 1)})
        threads.sort(key=lambda x: -x['cpu_s'])

        m_raw = call('engine_metrics')
        m = m_raw.get('result', m_raw) if isinstance(m_raw, dict) else m_raw

        result = {
            'pid': proc.pid, 'wall_s': round(wall, 2),
            'ncores': ncores,
            'core_busy_mean_pct': [round(v, 1) for v in core_mean],
            'core_busy_sorted_top8': sorted((round(v, 1) for v in core_mean), reverse=True)[:8],
            'total_cpu_pct': round(sum(core_mean), 1),
            'threads_top': threads[:16],
            'thread_count': len(th1),
            'engine_metrics': m,
        }
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=1, default=str)

        print('\n===== 摘要 =====')
        print('采样 %.1fs / %d 逻辑核' % (wall, ncores))
        print('每核 busy%%: %s' % result['core_busy_mean_pct'])
        print('总量 %.1f%% (= %.1f 核当量 / %d 核)' % (
            result['total_cpu_pct'], result['total_cpu_pct'] / 100.0, ncores))
        print('最高8核: %s' % result['core_busy_sorted_top8'])
        print('线程数 %d, CPU 前几名:' % result['thread_count'])
        for t in threads[:10]:
            print('  tid=%-6s %6.2fs  (%.1f%% 单核算力)' % (t['tid'], t['cpu_s'], t['pct_of_core']))
        print('metrics: fps=%s tps=%s' % (
            m.get('fps') if isinstance(m, dict) else '?',
            m.get('tps') if isinstance(m, dict) else '?'))
        print('SAVED', OUT)
    finally:
        try:
            call('quit', {'save': 'discard'})
        except Exception:
            pass
        time.sleep(1.5)
        if proc.poll() is None:
            proc.kill()
    return 0


if __name__ == '__main__':
    sys.exit(main())
