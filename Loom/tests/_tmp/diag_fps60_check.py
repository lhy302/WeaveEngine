# -*- coding: utf-8 -*-
"""diag_fps60_check.py — 悬案决定性实验 (2026-09-06 诊断代理)

假设: 台账 19:37 "源码冻结播放 58.3FPS" 是 fps_limit=60 限帧器伪读数
(58.3≈60 太整齐), 真实能力 ≈25.6 (unlimited 实测 + 深夜 playcam fps26)。
本探针: 源码冻结 + fps_limit=60 档跑播放态, 预测 FPS 顶到 ~58。
输出 tests/_tmp/diag_fps60_check.json
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
SCENE = os.path.join(LOOM, '保存', '压测500混合.json')
LIMIT = sys.argv[1] if len(sys.argv) > 1 else '60'
LLOGIC = int(sys.argv[2]) if len(sys.argv) > 2 else 30

cmd = [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
       '--open', SCENE, '--agent']
env = dict(os.environ)
env['LOOM_PROFILE'] = '1'
env['LOOM_NO_NUMBA'] = '1'

settings_path = os.path.join(LOOM, '设置.json')
bak = settings_path + '.diagbak'
with open(settings_path, 'r', encoding='utf-8') as f:
    orig_text = f.read()
shutil.copyfile(settings_path, bak)
s = json.loads(orig_text)
s['fps_limit'] = LIMIT
s['frame_buffer_tps'] = False
s['frame_buffer_fps'] = False
s['logic_fps'] = LLOGIC
with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print('[settings] fps_limit=%s logic_fps=%s' % (LIMIT, LLOGIC), flush=True)

results = {'fps_limit': LIMIT, 'side': 'src_frozen'}
proc = None
port = token = None
try:
    proc = subprocess.Popen(cmd, cwd=LOOM, env=env)
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
        raise SystemExit('[FATAL] 端口文件 40s 未就绪')
    port, token = info['port'], info['token']
    print('[agent] port=%d' % port, flush=True)

    def call(c, a=None):
        body = json.dumps({'cmd': c, 'args': a or {}}).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
            headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode('utf-8')).get('result', {})

    time.sleep(8.0)
    call('play', {'on': True})
    time.sleep(6.0)
    samples = []
    for _ in range(8):
        m = call('engine_metrics', {})
        samples.append({'fps': m.get('fps'), 'tps': m.get('get_tps')})
        time.sleep(2.0)
    results['samples'] = samples
    fps = [x['fps'] for x in samples if x['fps']]
    results['fps_mean'] = round(sum(fps) / len(fps), 1) if fps else None
    print('[play@%s] fps_mean=%s' % (LIMIT, results['fps_mean']), flush=True)
finally:
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
            except Exception:
                pass
    with open(settings_path, 'w', encoding='utf-8') as f:
        f.write(orig_text)
    print('[settings] 已还原', flush=True)
    try:
        os.remove(bak)
    except OSError:
        pass

with open(os.path.join(HERE, 'diag_fps60_check.json'), 'w',
          encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print('[done]', flush=True)
