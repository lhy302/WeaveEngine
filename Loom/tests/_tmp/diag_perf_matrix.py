# -*- coding: utf-8 -*-
"""diag_perf_matrix.py — 编译版性能定基主探针 (2026-09-06 诊断代理, 只读测量)

对 同一场景 (压测500混合.json) 采集 2×2 矩阵中一侧 (编辑态+播放态):
  --side src_frozen : 源码 + LOOM_NO_NUMBA=1 (模拟冻结) + LOOM_PROFILE=1
  --side src_native : 源码原生 (numba 可用) + LOOM_PROFILE=1
  --side exe        : 编译版 exe + LOOM_PROFILE=1 (设置 base=exe 目录)

流程 (每侧一次启动, 先编辑态后播放态):
  1. 备份 设置.json -> 设置.json.diagbak (测后还原, 铁律)
  2. 写播放态口径设置: fps_limit=unlimited / frame_buffer_tps=false /
     frame_buffer_fps=false / logic_fps=30 (其余保留)
  3. 启动 (--open 场景 --agent), 等端口文件 pid 匹配 (40s 超时)
  4. 编辑态: 8s 预热 -> 8 个 engine_metrics 样本 @2s
  5. 播放态: play on -> 6s 预热 -> 12 个样本 @2s
     (stage_times 累计值 -> 相邻样本差分 -> ms/墙钟秒 -> ms/渲染帧 + ms/逻辑帧)
  6. quit(save=discard) -> 进程清理 -> 还原 设置.json
输出: tests/_tmp/diag_perf_<side>.json
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

side = 'src_frozen'
scene_override = None
for i, a in enumerate(sys.argv):
    if a == '--side' and i + 1 < len(sys.argv):
        side = sys.argv[i + 1]
    if a == '--scene' and i + 1 < len(sys.argv):
        scene_override = sys.argv[i + 1]

if side == 'exe':
    base = EXE_DIR
    scene = scene_override or os.path.join(EXE_DIR, '保存', '压测500混合.json')
    cmd = [EXE, '--open', scene, '--agent']
elif side == 'src_native':
    base = LOOM
    scene = scene_override or SCENE
    cmd = [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']
else:  # src_frozen
    base = LOOM
    scene = scene_override or SCENE
    cmd = [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']

env = dict(os.environ)
env['LOOM_PROFILE'] = '1'
if side == 'src_frozen':
    env['LOOM_NO_NUMBA'] = '1'

settings_path = os.path.join(base, '设置.json')
bak_path = settings_path + '.diagbak'
suffix = '_' + side + ('_sph' if scene_override and
                       'spheres' in scene_override else '')
out_json = os.path.join(HERE, 'diag_perf%s.json' % suffix)

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
s['logic_fps'] = 30
with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print('[settings] 已写测量口径 ->', settings_path, flush=True)

results = {'side': side, 'base': base, 'scene': scene,
           'env_LOOM_PROFILE': env.get('LOOM_PROFILE'),
           'env_LOOM_NO_NUMBA': env.get('LOOM_NO_NUMBA'),
           'cmd': cmd, 'started': time.strftime('%H:%M:%S')}
proc = None
port = token = None
try:
    print('[launch]', cmd, flush=True)
    proc = subprocess.Popen(cmd, cwd=base, env=env)

    # ---- 等端口文件 (pid 匹配) ----
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
        """一次 engine_metrics 快照 (全量 stage_times + fps/tps/jitter/clock)."""
        m = call('engine_metrics', {})
        j = m.get('get_frame_jitter') or [0, 0, 0]
        return {'t': time.time(), 'fps': m.get('fps'),
                'tps': m.get('get_tps'),
                'jit_std': j[0], 'jit_max': j[1],
                'clock': m.get('clock'),
                'frame_buffer': m.get('frame_buffer'),
                'render_buffer': m.get('render_buffer'),
                'stage_times': dict(m.get('stage_times') or {})}

    # ---- 2. 编辑态 (8s 预热 -> 8 样本 @2s = 16s) ----
    time.sleep(8.0)
    st = call('status')
    results['edit_models'] = len(st.get('models', []))
    results['edit_settings_readback'] = call('settings_get', {})
    edit = []
    for _ in range(8):
        edit.append(sample())
        time.sleep(2.0)
    results['edit_samples'] = edit
    ef = [x['fps'] for x in edit if x['fps']]
    results['edit_fps_mean'] = round(sum(ef) / len(ef), 1) if ef else None
    print('[edit] models=%d fps_mean=%s' % (results['edit_models'],
                                            results['edit_fps_mean']), flush=True)

    # ---- 3. 播放态 (6s 预热 -> 12 样本 @2s = 24s) ----
    r = call('play', {'on': True})
    results['play_cmd'] = r
    time.sleep(6.0)
    play = []
    for _ in range(12):
        play.append(sample())
        time.sleep(2.0)
    results['play_samples'] = play
    pf = [x['fps'] for x in play if x['fps']]
    pt = [x['tps'] for x in play if x['tps']]
    results['play_fps_mean'] = round(sum(pf) / len(pf), 1) if pf else None
    results['play_tps_mean'] = round(sum(pt) / len(pt), 2) if pt else None
    print('[play] fps_mean=%s tps_mean=%s'
          % (results['play_fps_mean'], results['play_tps_mean']), flush=True)

    # ---- 4. stage_times 差分账 (播放态: 相邻样本差 / 墙钟窗口) ----
    # stage_times 是累计 ms; 差分 = 该 2s 窗内各阶段 ms。归一:
    #   ms_per_wall_s = diff / 2.0            (每墙钟秒的阶段毫秒, 可>1000=并行)
    #   ms_per_frame  = diff / (mean(fps)×2)  (每渲染帧摊派)
    #   ms_per_logic  = diff / (mean(tps)×2)  (每逻辑帧摊派)
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
            e = account.setdefault(k, {'ms_s': [], 'ms_frame': [], 'ms_logic': []})
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

    # 编辑态账 (同法, 只 ms/s + ms/帧)
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

    call('screenshot', {'file': os.path.join(HERE, 'diag_shot_%s.png' % side),
                        'full': True})
finally:
    # ---- 5. 进程清理 + 设置还原 ----
    if port is not None:
        try:
            body = json.dumps({'cmd': 'quit',
                               'args': {'save': 'discard', 'after': 0.2}}).encode('utf-8')
            req = urllib.request.Request(
                'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
                headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
    if proc is not None:
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
                print('[cleanup] 进程 kill (quit 未正常退出)', flush=True)
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
