# -*- coding: utf-8 -*-
r"""m2b_play_forensics.py — M2b 播放模式「多核分摊 + GPU 吃满」取证 (单档)

口径 (与 tests\_tmp\editor_core_check.py / TPS_FPS分核取证报告 完全一致, 只加 GPU + 截图):
  Loom.py --open 保存\压测500混合.json --agent
    → 等 .agent_port.json (pid 匹配, <=60s)
    → 启动后 8s 预热
    → agent POST /cmd  play {on:true}
    → 稳态 10s
    → 采样窗 12s:
        · 每核 busy%  : parallel.measure_core_busy(window=0.5) 连续采样 → 18 核均值
        · 每线程 CPU  : GetThreadTimes 增量 (窗口前后各一次快照), 按 tid 排序
        · GPU 引擎    : Get-Counter '\GPU Engine(*)\Utilization Percentage'
                        -SampleInterval 1 -MaxSamples 12 → 按 engtype 分组
        · FPS/TPS     : agent engine_metrics
    → 定向截图: powershell -File tests\_tmp\tm_shot.ps1 -View both -Tag <tag>
    → agent quit {save:'discard'} → 必要时 taskkill /T

用法:
  py -3.12 tests/_tmp/m2b_play_forensics.py --tag play_src [--secs 12]

★B2 退役 (2026-10-16): 删 --mode off (LOOM_NO_PIPELINE=1) 档, 单档 on。

落盘 (UTF-8):
  tests/_tmp/m2b_play_forensics_on<suffix>.json    原始产物
  tests/_tmp/m2b_play_forensics_on<suffix>.log     Loom.py 控制台输出
"""
import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, LOOM)

SCENE = os.path.join(LOOM, '保存', '压测500混合.json')
if not os.path.isfile(SCENE):
    SCENE = os.path.join(HERE, 'stress_500mixed.json')

import parallel  # noqa: E402

SHOT_PS1 = os.path.join(HERE, 'tm_shot.ps1')

k32 = ctypes.windll.kernel32
THREAD_QUERY_INFORMATION = 0x0040
TH32CS_SNAPTHREAD = 0x4

ENG_RE = re.compile(r'engtype_([a-z0-9_]+)', re.I)
PID_RE = re.compile(r'pid_(\d+)_', re.I)


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ThreadID', wintypes.DWORD),
                ('th32OwnerProcessID', wintypes.DWORD),
                ('tpBasePri', ctypes.c_long), ('tpDeltaPri', ctypes.c_long),
                ('dwFlags', wintypes.DWORD)]


def snap_threads(pid):
    """{tid: kernel+user 秒} 快照 (GetThreadTimes 增量口径)."""
    out = {}
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == -1:
        return out
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            th = k32.OpenThread(THREAD_QUERY_INFORMATION, False, te.th32ThreadID)
            if th:
                ct, et, kt, ut = (ctypes.c_ulonglong(0) for _ in range(4))
                if k32.GetThreadTimes(th, ctypes.byref(ct), ctypes.byref(et),
                                      ctypes.byref(kt), ctypes.byref(ut)):
                    out[te.th32ThreadID] = (kt.value + ut.value) / 1e7
                k32.CloseHandle(th)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return out


def kill_tree(pid):
    try:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return
    except Exception:
        pass
    try:
        os.kill(pid, 9)
    except Exception:
        pass


# ===================== GPU 引擎利用率采样 (独立线程) =====================
GPU_PS = (r"$ErrorActionPreference='SilentlyContinue';"
          r"Get-Counter -Counter '\GPU Engine(*)\Utilization Percentage' "
          r"-SampleInterval 1 -MaxSamples %d | ForEach-Object {"
          r"$t=$_.Timestamp.ToString('o');"
          r"foreach($cs in $_.CounterSamples){"
          r"'{0}|{1}|{2}' -f $t,$cs.InstanceName,$cs.CookedValue } }")


def gpu_sampler(secs, pid, holder):
    """后台线程: 采 secs 个 1s 间隔样本 → holder['rows'] = [(t, inst, val), ...]."""
    cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
           '-Command', GPU_PS % int(secs)]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=secs + 60)
        raw = (p.stdout or b'').decode('utf-8', 'replace')
        rows = []
        for line in raw.splitlines():
            parts = line.strip().split('|')
            if len(parts) != 3:
                continue
            try:
                rows.append((parts[0], parts[1], float(parts[2])))
            except ValueError:
                continue
        holder['rows'] = rows
        holder['stderr'] = (p.stderr or b'').decode('utf-8', 'replace')[:2000]
        holder['rc'] = p.returncode
    except Exception as e:
        holder['error'] = '%s: %s' % (type(e).__name__, e)


def summarize_gpu(rows, loom_pid):
    """按 engtype 分组: 每样本内对同类实例求和 → 均值/最大值; 另给 Loom 进程单独口径."""
    if not rows:
        return None
    times = sorted(set(r[0] for r in rows))
    by_eng = {}
    by_eng_pid = {}
    per_inst_max = {}
    for t, inst, v in rows:
        m = ENG_RE.search(inst)
        eng = (m.group(1).lower() if m else 'other')
        pm = PID_RE.search(inst)
        ipid = int(pm.group(1)) if pm else -1
        by_eng.setdefault(eng, {}).setdefault(t, 0.0)
        by_eng[eng][t] += v
        if ipid == loom_pid:
            by_eng_pid.setdefault(eng, {}).setdefault(t, 0.0)
            by_eng_pid[eng][t] += v
        per_inst_max[inst] = max(per_inst_max.get(inst, 0.0), v)

    def agg(d):
        out = {}
        for eng, series in d.items():
            vals = [series.get(t, 0.0) for t in times]
            out[eng] = {'n_samples': len(vals),
                        'mean': sum(vals) / len(vals),
                        'max': max(vals),
                        'series': [round(x, 3) for x in vals]}
        return dict(sorted(out.items(), key=lambda kv: -kv[1]['mean']))

    top_inst = sorted(per_inst_max.items(), key=lambda kv: -kv[1])[:12]
    return {'n_samples': len(times), 'n_rows': len(rows),
            'by_engtype_all': agg(by_eng),
            'by_engtype_loompid': agg(by_eng_pid),
            'top_instances_max': [{'instance': k, 'max': v} for k, v in top_inst]}


# ===================== agent =====================
def wait_port(proc, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with open(os.path.join(LOOM, '.agent_port.json'), encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                return cand
        except Exception:
            pass
        time.sleep(0.5)
    return None


def make_call(port, token):
    def call(name, args=None):
        body = json.dumps({'cmd': name, 'args': args or {}}).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
            headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode('utf-8'))
    return call


# ===================== 主流程 =====================
def run(tag, secs, do_shot, warmup, steady, suffix=''):
    """★B2 退役 (2026-10-16): 删 mode (off) 档, 单档 on。"""
    out = {'tag': tag, 'secs': secs,
           'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'scene': SCENE, 'warmup_s': warmup, 'steady_s': steady,
           'errors': []}

    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'

    log_path = os.path.join(HERE, 'm2b_play_forensics_on%s.log' % suffix)
    logf = open(log_path, 'wb')
    proc = subprocess.Popen(
        [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
         '--open', SCENE, '--agent'],
        cwd=LOOM, stdout=logf, stderr=subprocess.STDOUT, env=env)
    out['pid'] = proc.pid
    out['log'] = log_path
    call = None
    try:
        info = wait_port(proc, 60.0)
        if info is None:
            raise RuntimeError('端口文件 60s 未就绪 (pid=%d), 见 %s' % (proc.pid, log_path))
        out['port'] = info['port']
        call = make_call(info['port'], info['token'])

        time.sleep(warmup)
        r = call('play', {'on': True})
        out['play_result'] = r
        time.sleep(steady)

        # ---- 采样窗 12s ----
        gpu_holder = {}
        gt = threading.Thread(target=gpu_sampler, args=(int(secs), proc.pid, gpu_holder),
                              daemon=True)
        gt.start()

        th0 = snap_threads(proc.pid)
        t0 = time.perf_counter()
        cores = []
        while time.perf_counter() - t0 < secs:
            s = parallel.measure_core_busy(window=0.5)
            if s:
                cores.append(s)
            time.sleep(0.1)
        wall = time.perf_counter() - t0
        th1 = snap_threads(proc.pid)
        out['wall'] = wall
        out['n_core_samples'] = len(cores)

        if not cores:
            raise RuntimeError('parallel.measure_core_busy 未返回任何样本, 采样无效')
        nc = len(cores[0])
        cm = [0.0] * nc
        for s in cores:
            for k, v in s.items():
                if 0 <= k < nc:
                    cm[k] += v
        cm = [v / len(cores) for v in cm]
        out['per_core'] = cm
        out['total_core'] = sum(cm)
        out['core_equiv'] = sum(cm) / 100.0
        ti, tp = -1, 0.0
        for i, v in enumerate(cm):
            if ti < 0 or v > tp:
                ti, tp = i, v
        out['top_core_index'] = ti
        out['top_core_pct'] = tp
        out['n_cores_over_10'] = sum(1 for v in cm if v > 10.0)
        out['n_cores_over_20'] = sum(1 for v in cm if v > 20.0)
        out['sum_others'] = sum(cm) - tp

        threads = []
        for tid, c0 in th0.items():
            if tid in th1:
                sec = th1[tid] - c0
                if sec > 0.005:
                    threads.append({'tid': tid, 'cpu_s': sec,
                                    'pct_of_core': 100.0 * sec / wall})
        threads.sort(key=lambda x: -x['cpu_s'])
        out['threads'] = threads[:16]
        out['n_threads_sampled'] = len(threads)
        if threads:
            out['main_tid'] = threads[0]['tid']
            out['main_is_primary'] = (threads[0]['tid'] == proc.pid)
            out['main_pct'] = threads[0]['pct_of_core']
        else:
            out['errors'].append('未取到任何线程 CPU 增量 (GetThreadTimes)')

        try:
            m = call('engine_metrics')
            m = m.get('result', m) if isinstance(m, dict) else m
            out['metrics'] = m
            if isinstance(m, dict):
                out['fps'] = m.get('fps')
                out['tps'] = m.get('get_tps')
                out['jitter'] = m.get('get_frame_jitter')
                out['is_playing'] = m.get('is_playing')
        except Exception as e:
            out['errors'].append('engine_metrics: %s: %s' % (type(e).__name__, e))

        if out.get('fps'):
            out['main_ms_per_frame'] = (out.get('main_pct', 0.0) / 100.0 * 1000.0
                                        / float(out['fps']))
            out['main_ms_per_frame_formula'] = 'cpu_s*1000/(fps*wall)'
            if threads:
                out['main_ms_per_frame'] = (threads[0]['cpu_s'] * 1000.0
                                            / max(1.0, float(out['fps']) * wall))

        gt.join(timeout=int(secs) + 60)
        out['gpu_rc'] = gpu_holder.get('rc')
        if gpu_holder.get('error'):
            out['errors'].append('gpu sampler: ' + gpu_holder['error'])
        out['gpu'] = summarize_gpu(gpu_holder.get('rows') or [], proc.pid)
        if out['gpu'] is None:
            out['errors'].append('GPU 计数器未返回任何样本 (stderr=%s)'
                                 % (gpu_holder.get('stderr') or '')[:300])

        # ---- 定向截图 (测量完成后, 播放仍在运行) ----
        if do_shot:
            cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-File', SHOT_PS1, '-View', 'both', '-Tag', tag]
            try:
                p = subprocess.run(cmd, capture_output=True, timeout=180,
                                   cwd=LOOM, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
                so = (p.stdout or b'').decode('utf-8', 'replace')
                se = (p.stderr or b'').decode('utf-8', 'replace')
                out['shot_stdout'] = so
                out['shot_stderr'] = se[:3000]
                out['shot_rc'] = p.returncode
                out['shots'] = re.findall(r'\[SHOT\]\s+(.+\.png)', so)
                out['shot_views'] = re.findall(r'^VIEW=.*$', so, re.M)
            except Exception as e:
                out['errors'].append('shot: %s: %s' % (type(e).__name__, e))
    finally:
        if call is not None:
            try:
                call('quit', {'save': 'discard'})
            except Exception as e:
                out['errors'].append('quit: %s: %s' % (type(e).__name__, e))
        time.sleep(1.0)
        if proc.poll() is None:
            kill_tree(proc.pid)
            out['killed'] = True
        try:
            logf.close()
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    # ★B2 退役 (2026-10-16): 删 --mode; 单档 on。
    ap.add_argument('--tag', default='')
    ap.add_argument('--secs', type=float, default=12.0)
    ap.add_argument('--warmup', type=float, default=8.0)
    ap.add_argument('--steady', type=float, default=10.0)
    ap.add_argument('--no-shot', action='store_true')
    ap.add_argument('--suffix', default='', help='产物文件名后缀 (保留多轮物证)')
    a = ap.parse_args()
    tag = a.tag or 'play_src'
    print('=== m2b_play_forensics  tag=%s secs=%.1f ===' % (tag, a.secs))
    print('scene =', SCENE)
    out = run(tag, a.secs, not a.no_shot, a.warmup, a.steady, a.suffix)
    dst = os.path.join(HERE, 'm2b_play_forensics_on%s.json' % a.suffix)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('saved', dst)
    if out.get('per_core'):
        print('per_core :', ' '.join('%.1f' % x for x in out['per_core']))
        print('top=#%d %.2f%%  total=%.2f%% (%.2f core)  >10%%: %d cores  others=%.2f%%'
              % (out['top_core_index'], out['top_core_pct'], out['total_core'],
                 out['core_equiv'], out['n_cores_over_10'], out['sum_others']))
        print('fps=%s tps=%s main_ms/frame=%s'
              % (out.get('fps'), out.get('tps'), out.get('main_ms_per_frame')))
    if out.get('gpu'):
        for k, v in out['gpu']['by_engtype_all'].items():
            print('gpu[all] %-12s mean=%.2f%% max=%.2f%%' % (k, v['mean'], v['max']))
        for k, v in (out['gpu']['by_engtype_loompid'] or {}).items():
            print('gpu[loom] %-12s mean=%.2f%% max=%.2f%%' % (k, v['mean'], v['max']))
    if out.get('errors'):
        print('ERRORS:')
        for e in out['errors']:
            print('  -', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
