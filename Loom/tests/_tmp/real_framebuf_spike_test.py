# -*- coding: utf-8 -*-
"""real_framebuf_spike_test.py — 帧缓冲尖峰吸收实机验证 (2026-09-06)

场景: 混合500 @ TPS 30Hz + fps_limit 120 (FPS 缓冲可开).
注入: 播放态用后台线程对引擎主线程**不注入** (无法从外部暂停 Qt 定时器),
改用引擎内真实尖峰源 = 每 10s 触发一次大量新物体创建/删除 (结构 gen bump
+ GC 压力) — 与真实使用中"偶发卡顿帧"同源.

对比 A (缓冲关) vs B (TPS 缓冲开, FPS 缓冲关 — 饱和场景 FPS 缓冲无空窗):
采样窗口内 TPS 掉到 <28Hz 的渲染帧占比 + TPS 曲线谷底.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
PY = sys.executable

scene = os.path.join(LOOM, '保存', '压测500混合.json')
out_json = os.path.join(HERE, 'framebuf_spike_result.json')
shots = os.path.join(HERE, 'framebuf_shots')
os.makedirs(shots, exist_ok=True)

sys.path.insert(0, LOOM)
import guiloader  # noqa: E402


def write_settings(d):
    s = guiloader.load_settings('loom', base=LOOM)
    s.update(d)
    guiloader.save_settings('loom', s, base=LOOM)


def launch():
    cmd = [PY, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']
    proc = subprocess.Popen(cmd, cwd=LOOM,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
    body = json.dumps({'cmd': cmd_name, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
        headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8')).get('result', {})


def spike_round(label, tps_buf, seconds=36):
    """播放态 36s: 每 6s 创建 20 球再删 (结构尖峰 ×5), 高频采 TPS."""
    proc, port, token = launch()
    tps_series = []          # (t, tps) 高频 (0.5s 间隔)
    hits = prefs = 0
    try:
        time.sleep(6.0)
        call(port, token, 'play', {'on': True})
        time.sleep(6.0)
        t0 = time.time()
        next_spike = 0
        i = 0
        while time.time() - t0 < seconds:
            now = time.time() - t0
            if now > next_spike and i < 60:  # 结构尖峰: 连续建 60 球 (每 0.5s 1 个)
                call(port, token, 'object_add', {'type': 'sphere'})
                i += 1
                next_spike = now + 0.5
            m = call(port, token, 'engine_metrics', {})
            fb = m.get('frame_buffer') or {}
            tps_series.append((round(now, 1), m.get('get_tps')))
            hits = max(hits, fb.get('hits') or 0)
            prefs = max(prefs, fb.get('prefetches') or 0)
            time.sleep(0.5)
        call(port, token, 'screenshot',
             {'file': os.path.join(shots, 'spike_%s.png' % label), 'full': True})
    finally:
        try:
            call(port, token, 'quit', {'save': 'discard', 'after': 0.2})
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
    # 分析: TPS 谷底 (2s 滑动窗最小均值) + <28Hz 占比
    vals = [t for _, t in tps_series if t]
    dips = sum(1 for v in vals if v < 28.0)
    worst2s = min((min(vals[j:j+4]) for j in range(0, max(1, len(vals)-3))), default=0)
    return {'n': len(vals), 'dips_below28': dips,
            'dip_ratio': round(dips / max(1, len(vals)), 3),
            'worst_2s_tps': round(worst2s, 2),
            'tps_hits': hits, 'tps_prefetches': prefs,
            'series': tps_series}


results = {}
try:
    write_settings({'frame_buffer_tps': False, 'frame_buffer_fps': False,
                    'fps_limit': '120', 'logic_fps': 30})
    time.sleep(2.0)
    results['A_off'] = spike_round('A_off', False)
    print('[A_off]', json.dumps({k: v for k, v in results['A_off'].items()
                                 if k != 'series'}), flush=True)
    time.sleep(3.0)
    write_settings({'frame_buffer_tps': True, 'frame_buffer_fps': False,
                    'fps_limit': '120', 'logic_fps': 30})
    results['B_on'] = spike_round('B_on', True)
    print('[B_on]', json.dumps({k: v for k, v in results['B_on'].items()
                                if k != 'series'}), flush=True)
finally:
    write_settings({'frame_buffer_tps': False, 'frame_buffer_fps': False,
                    'logic_fps': 30})   # 还原 (缓冲关)

with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print('[done]', out_json, flush=True)
