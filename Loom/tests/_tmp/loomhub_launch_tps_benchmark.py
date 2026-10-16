# -*- coding: utf-8 -*-
"""loomhub_launch_tps_benchmark.py — LoomHub 真实启动链路自动化基准测试
流程:
  1. 启动 LoomHub.py --agent
  2. 调用 launch_engine 启动 压测500混合.json
  3. 采样 20 TPS 与 30 TPS 下的实时 FPS / TPS / Jitter
  4. 输出客观实测数据并退出
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
HUB_DIR = os.path.join(ROOT, 'Loom(py源代码-工作区)', 'LoomHub')
SCENE = os.path.join(LOOM, '保存', '压测500混合.json')

HUB_PORT_FILE = os.path.join(HUB_DIR, '.hub_agent_port.json')
ENG_PORT_FILE = os.path.join(LOOM, '.agent_port.json')

for pf in [HUB_PORT_FILE, ENG_PORT_FILE]:
    if os.path.exists(pf):
        try: os.unlink(pf)
        except Exception: pass

print("[LoomHub-Bench] 1. 启动 LoomHub 进程...")
hub_proc = subprocess.Popen(
    [sys.executable, '-u', os.path.join(HUB_DIR, 'LoomHub.py'), '--agent'],
    cwd=HUB_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)

def wait_file(path, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if d.get('port'): return d
            except Exception: pass
        time.sleep(0.4)
    return None

hub_info = wait_file(HUB_PORT_FILE, 30)
if not hub_info:
    print("[FATAL] LoomHub 启动超时")
    hub_proc.kill()
    sys.exit(1)

hub_port = hub_info['port']
hub_token = hub_info['token']
print(f"[LoomHub-Bench] 2. LoomHub 已连接: 127.0.0.1:{hub_port}")

def hub_call(cmd, args=None):
    body = json.dumps({'cmd': cmd, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:{hub_port}/cmd', data=body, method='POST',
        headers={'X-Agent-Token': hub_token, 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode('utf-8'))

print("[LoomHub-Bench] 3. 通过 LoomHub 发送 launch_engine...")
launch_res = hub_call('launch_engine', {'scene': SCENE, 'agent': True}).get('result', {})

engine_port_info = launch_res.get('agent_port')
if not engine_port_info:
    engine_port_info = wait_file(ENG_PORT_FILE, 30)

if not engine_port_info:
    print("[FATAL] 引擎 Agent 端口超时")
    hub_proc.kill()
    sys.exit(1)

eng_port = engine_port_info['port']
eng_token = engine_port_info['token']
print(f"[LoomHub-Bench] 4. 引擎已就绪: 127.0.0.1:{eng_port}")

def eng_call(cmd, args=None):
    body = json.dumps({'cmd': cmd, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:{eng_port}/cmd', data=body, method='POST',
        headers={'X-Agent-Token': eng_token, 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))

try:
    time.sleep(4.0)
    print("\n>>> 采集 20 TPS 场景 <<<")
    eng_call('settings_set', {'key': 'logic_fps', 'value': 20})
    time.sleep(1.0)
    eng_call('play', {'on': True})
    time.sleep(3.0)

    samples_20 = []
    for _ in range(4):
        time.sleep(1.0)
        m = eng_call('engine_metrics').get('result', {})
        j = m.get('get_frame_jitter') or [0, 0, 0]
        samples_20.append({'fps': m.get('fps', 0), 'tps': m.get('get_tps', 0), 'std': j[0]})

    print("\n>>> 采集 30 TPS 场景 <<<")
    eng_call('settings_set', {'key': 'logic_fps', 'value': 30})
    time.sleep(3.0)

    samples_30 = []
    for _ in range(4):
        time.sleep(1.0)
        m = eng_call('engine_metrics').get('result', {})
        j = m.get('get_frame_jitter') or [0, 0, 0]
        samples_30.append({'fps': m.get('fps', 0), 'tps': m.get('get_tps', 0), 'std': j[0]})

    fps20 = sum(s['fps'] for s in samples_20) / len(samples_20)
    tps20 = sum(s['tps'] for s in samples_20) / len(samples_20)
    fps30 = sum(s['fps'] for s in samples_30) / len(samples_30)
    tps30 = sum(s['tps'] for s in samples_30) / len(samples_30)

    print("\n[LoomHub-Bench] 实测数据汇报:")
    print(f"  20 TPS 档: TPS={tps20:.2f}, FPS={fps20:.1f}")
    print(f"  30 TPS 档: TPS={tps30:.2f}, FPS={fps30:.1f}")
    print("[LoomHub-Bench] BENCHMARK_COMPLETE")

finally:
    try:
        eng_call('play', {'on': False})
        eng_call('quit', {'save': 'discard'})
    except Exception: pass
    try:
        hub_call('engine_stop', {})
    except Exception: pass
    time.sleep(1.0)
    if hub_proc.poll() is None:
        hub_proc.kill()
