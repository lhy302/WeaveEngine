# -*- coding: utf-8 -*-
"""real_framebuf_test.py — 帧缓冲实验实机 A/B 实测 (2026-09-06)

用户指令: 按 LoomHub 启动流程实开引擎, 由 CC 设置 TPS/FPS 并开启功能实测。

链路 (与 real_launch_verify 同款): py -3.12 Loom.py --open 压测500混合 --agent

流程:
  A 轮 (基线): 缓冲全关 (frame_buffer_tps/fps=False) + fps_limit=unlimited
    → 播放态 30s: engine_metrics 每 2s 采样 (fps/tps/帧长std/max/缓冲计数)
  B 轮 (开启): frame_buffer_tps=True + frame_buffer_fps=True + fps_limit=120
    → 重启引擎 → 播放态 30s 同款采样 (命中数应 >0)
对比: 帧长 std / max / p99 (1% low 代理) + TPS 稳定性 (std of tps 样本)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
PY = sys.executable or 'py -3.12'

scene = os.path.join(LOOM, '保存', '压测500混合.json')
out_json = os.path.join(HERE, 'framebuf_ab_result.json')
shots = os.path.join(HERE, 'framebuf_shots')
os.makedirs(shots, exist_ok=True)

# ---- A/B 两轮的设置 (直接写 设置.json, 引擎启动读) ----
sys.path.insert(0, LOOM)
import guiloader  # noqa: E402

SETTINGS_A = {'frame_buffer_tps': False, 'frame_buffer_fps': False,
              'fps_limit': 'unlimited', 'logic_fps': 30}
SETTINGS_B = {'frame_buffer_tps': True, 'frame_buffer_fps': True,
              'fps_limit': '120', 'logic_fps': 30}


def write_settings(d):
    # ★base 显式指 Loom 目录: program_dir 默认取 sys.argv[0] 所在目录,
    # 探针直接跑会写进 tests/_tmp/设置.json (引擎读不到 — 本轮实测踩坑)
    s = guiloader.load_settings('loom', base=LOOM)
    s.update(d)
    guiloader.save_settings('loom', s, base=LOOM)


def launch():
    cmd = [PY, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']
    proc = subprocess.Popen(cmd, cwd=LOOM,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # 等端口文件新鲜
    info = None
    t0 = time.time()
    while time.time() - t0 < 40:
        try:
            with open(os.path.join(LOOM, '.agent_port.json'),
                      encoding='utf-8') as f:
                cand = json.load(f)
            if cand.get('pid') == proc.pid and cand.get('port'):
                info = cand
                break
        except Exception:
            pass
        time.sleep(0.5)
    if info is None:
        proc.kill()
        raise RuntimeError('端口文件 40s 未就绪')
    return proc, info['port'], info['token']


def call(port, token, cmd_name, args=None, timeout=35):
    """EAI 返回 {"ok":..,"result":..} 包装 — 解包 result."""
    body = json.dumps({'cmd': cmd_name, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
        headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8')).get('result', {})


def sample_round(label, seconds=30):
    """播放态每 2s 采 engine_metrics → (samples, p99 代理帧长序列)."""
    proc, port, token = launch()
    samples = []
    try:
        time.sleep(6.0)                       # 加载 501 对象
        st = call(port, token, 'status')
        n_models = len(st.get('models', []))
        r = call(port, token, 'play', {'on': True})
        print('[%s] play -> %s' % (label, r), flush=True)
        time.sleep(6.0)                       # TPS 滑窗 + 帧长窗 120 帧就位
        t0 = time.time()
        while time.time() - t0 < seconds:
            m = call(port, token, 'engine_metrics', {})
            j = m.get('get_frame_jitter') or [0, 0, 0]
            fb = m.get('frame_buffer') or {}
            rb = m.get('render_buffer') or {}
            samples.append({
                't': round(time.time() - t0, 1),
                'fps': m.get('fps'), 'tps': m.get('get_tps'),
                'jit_std_ms': j[0], 'jit_max_ms': j[1], 'jit_n': j[2],
                'tps_hits': (fb.get('hits') or 0),
                'tps_prefetches': (fb.get('prefetches') or 0),
                'tps_outstanding': (fb.get('outstanding') or 0),
                'rb_preframes': (rb.get('preframes') or 0),
                'rb_blits': (rb.get('blit_hits') or 0),
                'rb_state': rb.get('state'),
            })
            time.sleep(2.0)
        r = call(port, token, 'screenshot',
                 {'file': os.path.join(shots, '%s.png' % label), 'full': True})
        print('[%s] models=%d fps=%s tps=%s' % (
            label, n_models, samples[-1]['fps'], samples[-1]['tps']),
            flush=True)
    finally:
        try:
            call(port, token, 'quit', {'save': 'discard', 'after': 0.2})
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
    return samples


def summarize(samples):
    fps = [s['fps'] for s in samples if s['fps']]
    tps = [s['tps'] for s in samples if s['tps']]
    std = [s['jit_std_ms'] for s in samples if s['jit_std_ms']]
    mx = [s['jit_max_ms'] for s in samples if s['jit_max_ms']]
    return {
        'n': len(samples),
        'fps_mean': round(statistics.mean(fps), 1) if fps else None,
        'fps_min': min(fps) if fps else None,
        'fps_std': round(statistics.stdev(fps), 2) if len(fps) > 1 else 0,
        'tps_mean': round(statistics.mean(tps), 2) if tps else None,
        'tps_std': round(statistics.stdev(tps), 3) if len(tps) > 1 else 0,
        'jit_std_mean': round(statistics.mean(std), 2) if std else None,
        'jit_std_max': round(max(std), 2) if std else None,
        'jit_max_worst': round(max(mx), 1) if mx else None,
    }


results = {'scene': scene, 'settings_a': SETTINGS_A, 'settings_b': SETTINGS_B}
try:
    # ---- A 轮: 缓冲全关 ----
    write_settings(SETTINGS_A)
    sa = sample_round('A_off', 30)
    results['A_off_samples'] = sa
    results['A_summary'] = summarize(sa)
    print('[A summary]', json.dumps(results['A_summary']), flush=True)
    time.sleep(3.0)   # 进程收尾

    # ---- B 轮: 缓冲全开 ----
    write_settings(SETTINGS_B)
    sb = sample_round('B_on', 30)
    results['B_on_samples'] = sb
    results['B_summary'] = summarize(sb)
    print('[B summary]', json.dumps(results['B_summary']), flush=True)

    tps_hits = max((s['tps_hits'] for s in sb), default=0)
    tps_pref = max((s['tps_prefetches'] for s in sb), default=0)
    rb_blits = max((s['rb_blits'] for s in sb), default=0)
    results['B_engagement'] = {'tps_hits': tps_hits, 'tps_prefetches': tps_pref,
                               'render_blits': rb_blits}
    print('[B engagement]', results['B_engagement'], flush=True)
finally:
    write_settings(SETTINGS_A)   # 还原默认 (缓冲关)

with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print('[done]', out_json, flush=True)
