# -*- coding: utf-8 -*-
r"""diag2_dual_matrix.py — 批1-3 后双侧同口径矩阵探针 (2026-09-07 只读测量)

任务: 量化"批1-3 优化对源代码的作用 vs 对编译版的作用"。
基准对齐: diag_perf_matrix.py (09-06 批1-3 前定基, TPS30 三侧) — 本探针补
批1-3 后同口径 + TPS20 用户实测口径。

  --side exe        : 编译版 Loom.exe (设置 base=exe 目录, 探针坑铁律)
  --side src_native : 源码 py -3.12 (numba 在装, C 内核 DLL 同样生效)
  --side src_frozen : 源码 + LOOM_NO_NUMBA=1 (模拟编译版软件形态)
  --tps 20|30       : logic_fps 档 (20=用户实测口径, 30=定基口径)

流程 (每侧每档一次启动, 先编辑态后播放态):
  1. 备份 设置.json -> .diag2bak (测后还原, 铁律)
  2. 写口径: fps_limit=unlimited / frame_buffer 双关 / logic_fps=<tps>
  3. 启动 (--open 场景 --agent), 端口文件 pid 匹配 40s
  4. 编辑态: 8s 预热 -> 6 样本 @2s
  5. 播放态: play on -> 8s 预热 -> 14 样本 @2s (28s ≈ compiled_verify 30s 口径)
  6. stage_times 相邻样本差分 -> ms/墙钟秒 + ms/渲染帧 + ms/逻辑帧
  7. quit(save=discard) -> 还原 设置.json
输出: tests/_tmp/diag2_perf_<side>_tps<tps>.json
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
EXE = r"D:\my-project\Loom(编译版)\Loom\Loom.exe"
EXE_DIR = os.path.dirname(EXE)
SCENE = os.path.join(LOOM, '保存', '压测500混合.json')

side = 'src_native'
tps = 20
for i, a in enumerate(sys.argv):
    if a == '--side' and i + 1 < len(sys.argv):
        side = sys.argv[i + 1]
    if a == '--tps' and i + 1 < len(sys.argv):
        tps = int(sys.argv[i + 1])
assert tps in (20, 30)

if side == 'exe':
    base = EXE_DIR
    scene = os.path.join(EXE_DIR, '保存', '压测500混合.json')
    cmd = [EXE, '--open', scene, '--agent']
else:
    base = LOOM
    scene = SCENE
    cmd = [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']

env = dict(os.environ)
env['LOOM_PROFILE'] = '1'
if side == 'src_frozen':
    env['LOOM_NO_NUMBA'] = '1'

settings_path = os.path.join(base, '设置.json')
bak_path = settings_path + '.diag2bak'
out_json = os.path.join(HERE, 'diag2_perf_%s_tps%d.json' % (side, tps))

# ---- 1. 备份 + 写测量口径设置 ----
orig_text = None
if os.path.isfile(settings_path):
    with open(settings_path, 'r', encoding='utf-8') as f:
        orig_text = f.read()
    shutil.copyfile(settings_path, bak_path)
s = json.loads(orig_text) if orig_text else {}
s['fps_limit'] = 'unlimited'
s['frame_buffer_tps'] = False
s['frame_buffer_fps'] = False
s['logic_fps'] = tps
with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print('[settings] logic_fps=%d -> %s' % (tps, settings_path), flush=True)

results = {'side': side, 'tps': tps, 'base': base, 'scene': scene,
           'env_LOOM_PROFILE': env.get('LOOM_PROFILE'),
           'env_LOOM_NO_NUMBA': env.get('LOOM_NO_NUMBA'),
           'cmd': cmd, 'started': time.strftime('%H:%M:%S')}
proc = None
port = token = None
try:
    print('[launch]', cmd, flush=True)
    proc = subprocess.Popen(cmd, cwd=base, env=env)

    info = None
    t0 = time.time()
    while time.time() - t0 < 40:
        try:
            with open(os.path.join(base, '.agent_port.json'),
                      encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                info = cand
                break
        except Exception:
            pass
        time.sleep(0.5)
    if info is None:
        raise SystemExit('[FATAL] 端口文件 40s 未就绪')
    port, token = info['port'], info['token']
    print('[agent] port=%d pid=%d' % (port, proc.pid), flush=True)

    def call(c, a=None):
        body = json.dumps({'cmd': c, 'args': a or {}}).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
            headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode('utf-8')).get('result', {})

    def sample():
        m = call('engine_metrics', {})
        j = m.get('get_frame_jitter') or [0, 0, 0]
        return {'t': time.time(), 'fps': m.get('fps'),
                'tps': m.get('get_tps'),
                'jit_std': j[0], 'jit_max': j[1],
                'clock': m.get('clock'),
                'frame_buffer': m.get('frame_buffer'),
                'render_buffer': m.get('render_buffer'),
                'stage_times': dict(m.get('stage_times') or {})}

    # ---- 2. 编辑态 (8s 预热 -> 6 样本 @2s) ----
    time.sleep(8.0)
    st = call('status')
    results['edit_models'] = len(st.get('models', []))
    results['edit_settings_readback'] = call('settings_get', {})
    edit = []
    for _ in range(6):
        edit.append(sample())
        time.sleep(2.0)
    results['edit_samples'] = edit
    ef = [x['fps'] for x in edit if x['fps']]
    ef_sorted = sorted(ef) if ef else []
    results['edit_fps_mean'] = round(sum(ef) / len(ef), 1) if ef else None
    results['edit_fps_median'] = (ef_sorted[len(ef_sorted) // 2]
                                  if ef_sorted else None)
    print('[edit] models=%d fps_mean=%s median=%s'
          % (results['edit_models'], results['edit_fps_mean'],
             results['edit_fps_median']), flush=True)

    # ---- 3. 播放态 (8s 预热 -> 14 样本 @2s = 28s) ----
    r = call('play', {'on': True})
    results['play_cmd'] = r
    time.sleep(8.0)
    play = []
    for _ in range(14):
        play.append(sample())
        time.sleep(2.0)
    results['play_samples'] = play
    pf = [x['fps'] for x in play if x['fps']]
    pt = [x['tps'] for x in play if x['tps']]
    pf_sorted = sorted(pf)
    results['play_fps_mean'] = round(sum(pf) / len(pf), 1) if pf else None
    results['play_fps_median'] = (pf_sorted[len(pf_sorted) // 2]
                                  if pf_sorted else None)
    results['play_fps_last8_mean'] = (round(sum(pf[-8:]) / len(pf[-8:]), 1)
                                      if len(pf) >= 8 else None)
    results['play_tps_mean'] = round(sum(pt) / len(pt), 2) if pt else None
    print('[play] fps_mean=%s median=%s last8=%s tps_mean=%s'
          % (results['play_fps_mean'], results['play_fps_median'],
             results['play_fps_last8_mean'], results['play_tps_mean']),
          flush=True)

    # ---- 4. stage_times 差分账 (播放态) ----
    account = {}
    for a, b in zip(play, play[1:]):
        dt = b['t'] - a['t']
        if dt <= 0.5:
            continue
        frames = ((a['fps'] or 0) + (b['fps'] or 0)) / 2.0 * dt
        logics = ((a['tps'] or 0) + (b['tps'] or 0)) / 2.0 * dt
        keys = set(a['stage_times']) | set(b['stage_times'])
        for k in keys:
            d = (b['stage_times'].get(k, 0.0) - a['stage_times'].get(k, 0.0))
            if d <= 0.001:
                d = 0.0
            e = account.setdefault(k, {'ms_s': [], 'ms_frame': [],
                                       'ms_logic': []})
            e['ms_s'].append(d / dt)
            if frames > 0:
                e['ms_frame'].append(d / frames)
            if logics > 0:
                e['ms_logic'].append(d / logics)
    summary = {}
    for k, e in account.items():
        row = {'ms_per_wall_s': round(sum(e['ms_s']) / len(e['ms_s']), 2)}
        if e['ms_frame']:
            row['ms_per_frame'] = round(sum(e['ms_frame']) / len(e['ms_frame']), 3)
        if e['ms_logic']:
            row['ms_per_logic'] = round(sum(e['ms_logic']) / len(e['ms_logic']), 3)
        summary[k] = row
    results['play_stage_account'] = dict(
        sorted(summary.items(), key=lambda kv: -kv[1]['ms_per_wall_s']))

    # 编辑态账 (同法)
    eacct = {}
    for a, b in zip(edit, edit[1:]):
        dt = b['t'] - a['t']
        if dt <= 0.5:
            continue
        frames = ((a['fps'] or 0) + (b['fps'] or 0)) / 2.0 * dt
        keys = set(a['stage_times']) | set(b['stage_times'])
        for k in keys:
            d = (b['stage_times'].get(k, 0.0) - a['stage_times'].get(k, 0.0))
            if d <= 0.001:
                d = 0.0
            e = eacct.setdefault(k, {'ms_s': [], 'ms_frame': []})
            e['ms_s'].append(d / dt)
            if frames > 0:
                e['ms_frame'].append(d / frames)
    esum = {}
    for k, e in eacct.items():
        row = {'ms_per_wall_s': round(sum(e['ms_s']) / len(e['ms_s']), 2)}
        if e['ms_frame']:
            row['ms_per_frame'] = round(sum(e['ms_frame']) / len(e['ms_frame']), 3)
        esum[k] = row
    results['edit_stage_account'] = dict(
        sorted(esum.items(), key=lambda kv: -kv[1]['ms_per_wall_s']))

    call('screenshot', {'file': os.path.join(
        HERE, 'diag2_shot_%s_tps%d.png' % (side, tps)), 'full': True})
finally:
    if port is not None:
        try:
            body = json.dumps({'cmd': 'quit',
                               'args': {'save': 'discard', 'after': 0.2}}
                              ).encode('utf-8')
            req = urllib.request.Request(
                'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
                headers={'X-Agent-Token': token, 'Content-Type':
                         'application/json'})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
    if proc is not None:
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
                print('[cleanup] 进程 kill', flush=True)
            except Exception:
                pass
    if orig_text is not None:
        with open(settings_path, 'w', encoding='utf-8') as f:
            f.write(orig_text)
        print('[settings] 已还原原 设置.json', flush=True)
    try:
        os.remove(bak_path)
    except OSError:
        pass

with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print('[done]', out_json, flush=True)
