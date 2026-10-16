# -*- coding: utf-8 -*-
r"""editor_core_check.py — 编辑器口径每核/每线程负载 + 验收② 判定闸 (B2 后单档)

口径对齐 tests/_tmp/TPS_FPS分核取证报告_20260907.txt:
  Loom.py --open 混合500 --agent → play on → 稳态 → 采样窗 12s
  · 每核 busy% (parallel.measure_core_busy, NtQuerySystemInformation SPPI)
  · 每线程 CPU 时间 (GetThreadTimes 增量) → 按 tid 排序
  · FPS/TPS (agent engine_metrics)

★B2 退役 (2026-10-16): 原为 A/B (on vs off), B2 后 pipeline 无 Python 回退路径,
探针改单档 on。回归闸从「on ≤ off 主线程 ms/帧」改为绝对阈值 REGRESSION_MAX_MS。

用法:
  # 主流程 (验收② + 回归闸; build_all.bat 调用)
  py -3.12 tests/_tmp/editor_core_check.py --both [--secs 12] [--strict-accept2]
  # 单档测量 (--both 的子进程就是用它, 也可单独跑)
  py -3.12 tests/_tmp/editor_core_check.py [--secs 12]

落盘 (UTF-8, ensure_ascii=False, indent=2; 永不删除):
  tests/_tmp/editor_core_on.json       ON 档原始产物 (子进程落盘)
  tests/_tmp/editor_core_verdict.json  汇总 + 两项闸门判定 (--both 专有)
  tests/_tmp/editor_core_on_loom.log   Loom.py 控制台输出 (诊断用)

闸门 (--both 时在控制台打印固定前缀的可机读判定行):
  [GATE-ACCEPT2] core0_busy=xx.xx%  target<=45.0%  -> PASS|FAIL
  [GATE-REGRESSION] main_ms_per_frame on=.. max=8.0 -> PASS|FAIL

退出码 (--both):
  0 = 采样有效 且 回归闸 PASS (ON 主线程 ms/帧 ≤ 绝对阈值)
  1 = 采样无效 / 子进程失败 / 超时 / json 读取失败 / 回归闸 FAIL
      加 --strict-accept2 时, 验收② 未达标也退 1
"""
import ctypes
import json
import os
import subprocess
import sys
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

# ---- 判据常量 (只在此处定义, 便于审计) ----
ACCEPT2_TARGET = 45.0     # 验收②: ON 档最高核 busy% 上限
# ★B2 退役 (2026-10-16): 原回归闸 = ON ≤ OFF 主线程 ms/帧; B2 后无 off 对照,
# 改为绝对阈值 (监控严重回归)。历史 on 实测 ~4.9-5.0 ms/帧, 留 ~60% 余量。
REGRESSION_MAX_MS = 8.0
DEFAULT_SECS = 12.0       # 稳态采样窗 (秒, 语义不变)
CHILD_TIMEOUT = 600.0     # 单档子进程上限 (秒)
STALE_TOL = 5.0           # 产物 mtime 早于本次运行起点超过该秒数 → 判为陈旧文件

USAGE = ('用法:\n'
         '  py -3.12 tests/_tmp/editor_core_check.py --both [--secs 12] [--strict-accept2]\n'
         '  py -3.12 tests/_tmp/editor_core_check.py [--secs 12]\n'
         '可选: --target 45.0 (验收② 上限, 默认 45.0) / --timeout 600 (子进程上限秒)\n')

k32 = ctypes.windll.kernel32
THREAD_QUERY_INFORMATION = 0x0040
TH32CS_SNAPTHREAD = 0x4


class ProbeError(Exception):
    """探针自身可判定的错误 → 明确报错 + 退出码 1。"""


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ThreadID', wintypes.DWORD),
                ('th32OwnerProcessID', wintypes.DWORD),
                ('tpBasePri', ctypes.c_long), ('tpDeltaPri', ctypes.c_long),
                ('dwFlags', wintypes.DWORD)]


def snap_threads(pid):
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
    """杀进程及其子孙 (超时后不留 Loom GUI 孤儿)。"""
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=20)
            return
        except Exception:
            pass
    try:
        os.kill(pid, 9)
    except Exception:
        pass


def _num(v, default=None):
    """安全取数值; 非数值/NaN/inf → default。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float('inf'), float('-inf')):
        return default
    return f


def top_core(per_core):
    """从 per_core 数组如实算出最高核 → (index, busy%); 空/非法 → (-1, 0.0)。

    ★ 不硬编码核0: 最高核是谁就记谁。
    """
    idx, pct = -1, 0.0
    for i, v in enumerate(per_core or []):
        f = _num(v)
        if f is None:
            continue
        if idx < 0 or f > pct:
            idx, pct = i, f
    return idx, pct


def parse_args(argv):
    opts = {'both': False, 'strict_accept2': False,
            'secs': DEFAULT_SECS, 'target': ACCEPT2_TARGET,
            'timeout': CHILD_TIMEOUT}
    i = 0
    while i < len(argv):
        raw = argv[i]
        key, eq, val = raw.partition('=')
        if key in ('--secs', '--target', '--timeout'):
            if not eq:
                if i + 1 >= len(argv):
                    raise ProbeError('%s 缺少取值' % key)
                i += 1
                val = argv[i]
            num = _num(val)
            if num is None:
                raise ProbeError('%s 取值非法: %r' % (key, val))
            opts[key[2:]] = num
        elif key == '--both' and not eq:
            opts['both'] = True
        elif key == '--strict-accept2' and not eq:
            opts['strict_accept2'] = True
        elif key in ('-h', '--help'):
            print(USAGE)
            sys.exit(0)
        else:
            print('[WARN] 未知参数, 已忽略: %s' % raw)
        i += 1
    if opts['secs'] <= 0:
        raise ProbeError('--secs 必须 > 0, 得到 %s' % opts['secs'])
    if opts['timeout'] <= 0:
        raise ProbeError('--timeout 必须 > 0, 得到 %s' % opts['timeout'])
    return opts


def dump_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def accept2_note(per_core, idx, pct, target, passed):
    """验收② 备注: 如实说明最高核是谁; 非核0 时必须点名。"""
    if idx < 0 or not per_core:
        return '无 per_core 数据, 判据不成立'
    c0 = _num(per_core[0], 0.0)
    parts = ['判据=ON 档实测最高核 busy%% (measured=%.2f%%) %s target=%.1f%%'
             % (pct, '<=' if passed else '>', target)]
    if idx == 0:
        parts.append('实测最高核即核0')
    else:
        parts.append('注意: 实测最高核为核%d (非核0), 以最高核作保守判据; 核0 实测 %.2f%%'
                     % (idx, c0))
    return '; '.join(parts)


# ======================================================================
# 单档测量 (口径与历史版本逐行一致; finally 必 quit + 必要时 kill)
# ======================================================================
def measure_once(out, secs):
    """★B2 退役 (2026-10-16): 删 off (LOOM_NO_PIPELINE=1) 档, 单档 on。"""
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'

    # Loom.py 输出落日志文件 (不再用 PIPE: 不读的管道写满会阻塞 Loom 主线程 → 污染测量)
    log_path = os.path.join(HERE, 'editor_core_on_loom.log')
    try:
        logf = open(log_path, 'wb')
    except Exception as e:
        print('[WARN] 无法打开日志 %s (%s), 输出丢弃' % (log_path, e))
        logf = None
    sink = logf if logf is not None else subprocess.DEVNULL

    proc = subprocess.Popen(
        [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
         '--open', SCENE, '--agent'],
        cwd=LOOM, stdout=sink, stderr=subprocess.STDOUT, env=env)

    try:
        info = None
        t0 = time.time()
        while time.time() - t0 < 60:
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
            raise ProbeError('端口文件 60s 未就绪 (.agent_port.json, pid=%d), 见 %s'
                             % (proc.pid, log_path))
        port, token = info['port'], info['token']

        def call(name, args=None):
            body = json.dumps({'cmd': name, 'args': args or {}}).encode('utf-8')
            req = urllib.request.Request(
                'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
                headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=35) as r:
                return json.loads(r.read().decode('utf-8'))

        time.sleep(8.0)
        call('play', {'on': True})
        time.sleep(8.0)
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

        if not cores:
            raise ProbeError('parallel.measure_core_busy 未返回任何样本, 采样无效')
        nc = len(cores[0])
        cm = [0.0] * nc
        for s in cores:
            for k, v in s.items():
                if 0 <= k < nc:
                    cm[k] += v
        cm = [v / len(cores) for v in cm]

        threads = []
        for tid, c0 in th0.items():
            if tid in th1:
                sec = th1[tid] - c0
                if sec > 0.005:
                    threads.append({'tid': tid, 'cpu_s': sec,
                                    'pct_of_core': 100.0 * sec / wall})
        threads.sort(key=lambda x: -x['cpu_s'])
        if not threads:
            raise ProbeError('未取到任何线程 CPU 增量 (GetThreadTimes), 采样无效')

        m = call('engine_metrics')
        m = m.get('result', m) if isinstance(m, dict) else m
        out.update({'per_core': cm, 'threads': threads[:12],
                    'fps': m.get('fps') if isinstance(m, dict) else None,
                    'total_core': sum(cm), 'wall': wall})
        top, tpc = top_core(cm)
        out['top_core_index'] = top
        out['top_core_pct'] = tpc
        print('单档(on)  采样 %.1fs' % wall)
        print('  每核 busy%%: %s' % ' '.join('%.0f' % x for x in cm))
        print('  最高核 = 核%d @ %.1f%%   总 = %.1f%% (= %.2f 核当量)'
              % (top, tpc, sum(cm), sum(cm) / 100.0))
        print('  FPS = %s' % out['fps'])
        print('  线程 CPU 前 6:')
        for t in threads[:6]:
            print('    tid=%-6d %6.2fs  (%5.1f%% 单核)' % (t['tid'], t['cpu_s'],
                                                          t['pct_of_core']))
        # 主线程 CPU% = 最大线程 (编辑器主线程恒为最大)
        out['main_pct'] = threads[0]['pct_of_core']
        out['main_ms_per_frame'] = (threads[0]['cpu_s'] * 1000.0
                                    / max(1.0, (out['fps'] or 1) * wall))
        print('  主线程(最大线程) = %.1f%% 单核 = %.3f ms/帧'
              % (out['main_pct'], out['main_ms_per_frame']))
    finally:
        try:
            call('quit', {'save': 'discard'})
        except Exception:
            pass
        time.sleep(1.0)
        if proc.poll() is None:
            kill_tree(proc.pid)
        try:
            if logf is not None:
                logf.close()
        except Exception:
            pass


def run_single(opts):
    """单档测量 → 落盘 editor_core_on.json (即使失败也落盘, 带 error 字段)。
    ★B2 退役 (2026-10-16): 删 off 档。"""
    mode = 'on'
    out = {'mode': mode, 'secs': opts['secs'],
           'ts': time.strftime('%Y-%m-%dT%H:%M:%S')}
    err = None
    try:
        measure_once(out, opts['secs'])
    except Exception as e:
        err = '%s: %s' % (type(e).__name__, e)
        out['error'] = err
        print('[FATAL] 单档测量失败: %s' % err)
    dst = os.path.join(HERE, 'editor_core_on.json')
    try:
        dump_json(dst, out)
        print('saved', dst)
    except Exception as e:
        print('[FATAL] 写 %s 失败: %s' % (dst, e))
        return 1
    return 0 if err is None else 1


# ======================================================================
# A/B 验收模式
# ======================================================================
def run_child(argv, timeout):
    """跑一个单档子进程 → (returncode|None=超时, 合并输出文本)。"""
    print('  $ %s' % ' '.join(argv), flush=True)
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=dict(os.environ, PYTHONIOENCODING='utf-8'),
                         creationflags=flags)
    try:
        raw, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(p.pid)
        try:
            raw, _ = p.communicate(timeout=15)
        except Exception:
            raw = b''
        return None, (raw or b'').decode('utf-8', 'replace')
    return p.returncode, (raw or b'').decode('utf-8', 'replace')


def load_artifact(path, mode, t_start):
    """读取并校验单档产物; 缺文件/坏 json/字段缺失/陈旧文件 → ProbeError。"""
    if not os.path.isfile(path):
        raise ProbeError('%s 档产物缺失: %s' % (mode, path))
    if os.path.getmtime(path) < t_start - STALE_TOL:
        raise ProbeError('%s 档产物为陈旧文件 (mtime 早于本次运行): %s' % (mode, path))
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
    except Exception as e:
        raise ProbeError('%s 档产物 json 读取失败 (%s): %s' % (mode, path, e))
    if not isinstance(obj, dict):
        raise ProbeError('%s 档产物不是 json 对象: %s' % (mode, path))
    if obj.get('error'):
        raise ProbeError('%s 档产物含 error 字段: %s' % (mode, obj['error']))
    if obj.get('mode') != mode:
        raise ProbeError('%s 档产物 mode 字段不符 (得到 %r): %s'
                         % (mode, obj.get('mode'), path))
    per_core = obj.get('per_core')
    if not isinstance(per_core, list) or not per_core:
        raise ProbeError('%s 档 per_core 为空: %s' % (mode, path))
    for key in ('main_ms_per_frame', 'total_core', 'main_pct'):
        if _num(obj.get(key)) is None:
            raise ProbeError('%s 档 %s 缺失/非数值: %s' % (mode, key, path))
    if _num(obj.get('main_ms_per_frame')) <= 0:
        raise ProbeError('%s 档 main_ms_per_frame <= 0, 采样无效: %s' % (mode, path))
    return obj


def summarize(mode, obj, idx, pct):
    return {'mode': mode,
            'fps': obj.get('fps'),
            'per_core': obj.get('per_core'),
            'total_core': obj.get('total_core'),
            'main_pct': obj.get('main_pct'),
            'main_ms_per_frame': obj.get('main_ms_per_frame'),
            'top_core_index': idx,
            'top_core_pct': pct}


def run_ab(opts):
    """★B2 退役 (2026-10-16): 原 A/B (on vs off), B2 后无 off 档, 改单档 +
    绝对阈值回归闸。保留 [GATE-ACCEPT2] / [GATE-REGRESSION] 前缀 (build_all 消费)。"""
    secs = opts['secs']
    target = opts['target']
    strict = opts['strict_accept2']
    print('=== editor_core_check (编辑器基线口径, B2 后单档 + 绝对阈值闸门) ===')
    print('  口径: Loom.py --open 混合500 --agent → play on → 稳态采样 %.1fs' % secs)
    print('  验收② 判据: ON 档最高核 busy%% ≤ %.1f%%' % target)
    print('  回归判据:   ON 主线程 ms/帧 ≤ %.3f (B2 后绝对阈值)' % REGRESSION_MAX_MS)

    t_start = time.time()
    argv = [sys.executable, '-u', os.path.abspath(__file__), '--secs', str(secs)]
    rc, text = run_child(argv, opts['timeout'])
    if text.strip():
        print(text.rstrip())
    if rc is None:
        print('[FATAL] 子进程超时 (>%.0fs), 已 taskkill /T' % opts['timeout'])
        return 1
    if rc != 0:
        print('[FATAL] 子进程退出码 %d' % rc)
        return 1
    path = os.path.join(HERE, 'editor_core_on.json')
    try:
        a = load_artifact(path, 'on', t_start)
    except ProbeError as e:
        print('[FATAL] %s' % e)
        return 1

    on_idx, on_pct = top_core(a['per_core'])
    on_ms = float(a['main_ms_per_frame'])
    on_total = float(a['total_core'])

    sampling_valid = (on_ms > 0 and on_total >= 0 and bool(a['per_core']))
    accept2_pass = bool(sampling_valid and on_pct <= target)
    reg_pass = bool(sampling_valid and on_ms <= REGRESSION_MAX_MS)

    verdict = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'secs': secs,
        'on': summarize('on', a, on_idx, on_pct),
        'accept2': {'metric': 'core0_busy_pct',
                    'target_max': target,
                    'measured': on_pct,
                    'pass': accept2_pass,
                    'note': accept2_note(a['per_core'], on_idx, on_pct, target,
                                         accept2_pass)},
        'regression': {'metric': 'main_ms_per_frame',
                       'on': on_ms, 'max_allowed': REGRESSION_MAX_MS,
                       'pass': reg_pass},
        'parallelism': {'on_total_core': on_total,
                        'on_core_equiv': on_total / 100.0},
        'sampling_valid': sampling_valid,
        'artifacts': {'on': os.path.join(HERE, 'editor_core_on.json'),
                      'verdict': os.path.join(HERE, 'editor_core_verdict.json')},
        'exit_policy': {'default': 'regression',
                        'strict_accept2': bool(strict)},
    }
    vpath = os.path.join(HERE, 'editor_core_verdict.json')
    try:
        dump_json(vpath, verdict)
    except Exception as e:
        print('[FATAL] 写 %s 失败: %s' % (vpath, e))
        return 1
    print('saved', vpath)

    # ---- 可机读判定行 (前缀固定, 不得改动) ----
    print('[GATE-ACCEPT2] core0_busy=%.2f%%  target<=%.1f%%  -> %s'
          % (on_pct, target, 'PASS' if accept2_pass else 'FAIL'))
    print('[GATE-REGRESSION] main_ms_per_frame on=%.3f max=%.3f -> %s'
          % (on_ms, REGRESSION_MAX_MS, 'PASS' if reg_pass else 'FAIL'))
    # ---- 汇总行 ----
    print('[SUMMARY] top_core=#%d %.2f%%  total_core on=%.2f%%  '
          'core_equiv on=%.2f  fps on=%s'
          % (on_idx, on_pct, on_total, on_total / 100.0, a.get('fps')))

    exit_code = 0 if reg_pass else 1
    if strict and not accept2_pass:
        exit_code = 1
    print('[EXIT] policy=%s  strict_accept2=%s  exit_code=%d'
          % ('regression' if not strict else 'regression+accept2',
             'on' if strict else 'off', exit_code))
    print('ALL PASS' if exit_code == 0 else 'FAILED')
    return exit_code

def main():
    try:
        opts = parse_args(sys.argv[1:])
    except ProbeError as e:
        print('[FATAL] 参数错误: %s' % e)
        print(USAGE)
        return 1
    if opts['both']:
        return run_ab(opts)
    if opts['strict_accept2']:
        print('[WARN] --strict-accept2 只在 --both 模式生效, 单档模式已忽略')
    return run_single(opts)


if __name__ == '__main__':
    sys.exit(main())
