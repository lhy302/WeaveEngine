# -*- coding: utf-8 -*-
"""test_new_compiled_exe.py — 编译版可执行文件 Loom.exe 真实实机测试
"""
import os
import sys
import time
import json
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
ROOT = os.path.abspath(os.path.join(LOOM, '..', '..'))
EXE_DIR = os.path.join(ROOT, 'Loom(编译版)', 'Loom')
EXE = os.path.join(EXE_DIR, 'Loom.exe')
SCENE = os.path.join(EXE_DIR, '保存', '压测500混合.json')
PORT_JSON = os.path.join(EXE_DIR, '.agent_port.json')

if not os.path.isfile(EXE):
    print(f"[FATAL] 未找到编译版文件: {EXE}")
    sys.exit(1)

if os.path.exists(PORT_JSON):
    try: os.unlink(PORT_JSON)
    except Exception: pass

print(f"[Exe-Test] 1. 启动编译版: {EXE}")
env = dict(os.environ)
env['LOOM_PROFILE'] = '1'

proc = subprocess.Popen([EXE, '--open', SCENE, '--agent'], cwd=EXE_DIR, env=env)

def wait_for_port():
    t0 = time.time()
    while time.time() - t0 < 35:
        if os.path.exists(PORT_JSON):
            try:
                with open(PORT_JSON, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if d.get('pid') == proc.pid and d.get('port'):
                    return d
            except Exception: pass
        time.sleep(0.5)
    return None

info = wait_for_port()
if not info:
    print("[FATAL] 编译版 Agent 端口超时")
    proc.kill()
    sys.exit(1)

port = info['port']
token = info['token']
print(f"[Exe-Test] 2. 连接就绪: 127.0.0.1:{port}, PID={proc.pid}")

def call(cmd, args=None):
    body = json.dumps({'cmd': cmd, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/cmd', data=body, method='POST',
        headers={'X-Agent-Token': token, 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))

try:
    time.sleep(4.0)
    print("\n>>> 采集编译版 20 TPS 场景 <<<")
    call('settings_set', {'key': 'logic_fps', 'value': 20})
    time.sleep(1.0)
    call('play', {'on': True})
    time.sleep(3.0)

    samples_20 = []
    for _ in range(4):
        time.sleep(1.0)
        m = call('engine_metrics').get('result', {})
        samples_20.append({'fps': m.get('fps', 0), 'tps': m.get('get_tps', 0)})

    print("\n>>> 采集编译版 30 TPS 场景 <<<")
    call('settings_set', {'key': 'logic_fps', 'value': 30})
    time.sleep(3.0)

    samples_30 = []
    for _ in range(4):
        time.sleep(1.0)
        m = call('engine_metrics').get('result', {})
        samples_30.append({'fps': m.get('fps', 0), 'tps': m.get('get_tps', 0)})

    fps20 = sum(s['fps'] for s in samples_20) / len(samples_20)
    tps20 = sum(s['tps'] for s in samples_20) / len(samples_20)
    fps30 = sum(s['fps'] for s in samples_30) / len(samples_30)
    tps30 = sum(s['tps'] for s in samples_30) / len(samples_30)

    print("\n[Exe-Test] 编译版实测数据汇报:")
    print(f"  20 TPS 档: TPS={tps20:.2f}, FPS={fps20:.1f}")
    print(f"  30 TPS 档: TPS={tps30:.2f}, FPS={fps30:.1f}")
    print("[Exe-Test] BENCHMARK_COMPLETE")

finally:
    try:
        call('play', {'on': False})
        call('quit', {'save': 'discard'})
    except Exception: pass
    time.sleep(1.0)
    if proc.poll() is None:
        proc.kill()
