# -*- coding: utf-8 -*-
"""flicker_probe.py — 编译版低TPS闪黑复现探针 (2026-09-06)

用户报告: 编译版 TPS=20 快闪 / TPS=1 显示1s黑1s; 源码无。
特征: 黑屏周期与 TPS 节奏同步 → 逻辑帧跑与不跑的渲染帧行为交替。
用法: py -3.12 flicker_probe.py [exe路径|py源码] [logic_fps] [拍摄数]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))

mode = sys.argv[1] if len(sys.argv) > 1 else 'source'   # source | compiled
logic_fps = sys.argv[2] if len(sys.argv) > 2 else '20'
n_shots = int(sys.argv[3]) if len(sys.argv) > 3 else 12

sys.path.insert(0, LOOM)
import guiloader

if mode == 'compiled':
    exe = r'D:\my-project\Loom(编译版)\Loom\Loom.exe'
    base = os.path.dirname(exe)
    # ★编译版读自己的设置.json (program_dir=exe 目录) — 必须写它的那份
    s = guiloader.load_settings('loom', base=base)
    s['logic_fps'] = int(logic_fps)
    s['fps_limit'] = 'unlimited'
    guiloader.save_settings('loom', s, base=base)
    scene = os.path.join(base, '保存', '压测500混合.json')
    cmd = [exe, '--open', scene, '--agent']
else:
    base = LOOM
    s = guiloader.load_settings('loom', base=LOOM)
    s['logic_fps'] = int(logic_fps)
    s['fps_limit'] = 'unlimited'
    guiloader.save_settings('loom', s, base=LOOM)
    scene = os.path.join(LOOM, '保存', '压测500混合.json')
    cmd = [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
           '--open', scene, '--agent']

proc = subprocess.Popen(cmd, cwd=base)
info = None
t0 = time.time()
while time.time() - t0 < 60:
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
    proc.kill()
    raise SystemExit('port timeout')
port, token = info['port'], info['token']


def call(c, a=None):
    body = json.dumps({'cmd': c, 'args': a or {}}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
        headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8')).get('result', {})


try:
    time.sleep(12)
    call('play', {'on': True})
    time.sleep(6)
    saved = 0
    for i in range(n_shots):
        out = os.path.join(base, '保存', 'flicker_%s_%s_%02d.png'
                           % (mode, logic_fps, i))
        try:
            r = call('screenshot', {'file': out})
            if r.get('file'):
                saved += 1
        except Exception as e:
            print('shot %d fail: %r' % (i, e))
            break
        time.sleep(0.1)
    print('[%s tps=%s] shots saved: %d' % (mode, logic_fps, saved))
    # 顺手采 metrics
    m = call('engine_metrics', {})
    print('[metrics] fps=%s tps=%s jitter=%s'
          % (m.get('fps'), m.get('get_tps'), m.get('get_frame_jitter')))
finally:
    try:
        call('quit', {'save': 'discard', 'after': 0.2})
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
