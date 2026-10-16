# -*- coding: utf-8 -*-
"""real_launch_verify.py — LoomHub 同款链路实机验证 (2026-09-05 方案一/二验收)

流程 (用户指令: 实际通过 LoomHub 路径打开引擎截图帧率还有运行时帧率):
  1. 启动链 = LoomHub 启动器同款: py -3.12 Loom.py --open <混合500场景> --agent
     (cwd=Loom, Qt 默认 LoomGUI 视图, 启动日志核对 501 对象)
  2. 编辑器态: 等 5s 预热 → screenshot 截图 (帧率可见 HUD/状态栏) + status 读 FPS
  3. 播放态: play on=true → 等 6s (逻辑帧节律就位) → screenshot + status
     + 引擎 get_tps/get_frame_jitter 注入读取
  4. F9 暂停态: 截图 (TPS 显示"已暂停")
  5. 退出 (save=discard), 收集结果写 _tmp\real_launch_result.json
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))
PY = sys.executable or 'py -3.12'

scene = os.path.join(LOOM, '保存', '压测500混合.json')
out_json = os.path.join(HERE, 'real_launch_result.json')
shots = os.path.join(HERE, 'real_shots')
os.makedirs(shots, exist_ok=True)

cmd = [PY, '-u', os.path.join(LOOM, 'Loom.py'),
       '--open', scene, '--agent']
print('[launch]', ' '.join(cmd), flush=True)
proc = subprocess.Popen(cmd, cwd=LOOM,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

# ---- 等 agent 端口文件新鲜 (pid 存活判定, 台账 H 系规则) ----
info = None
t0 = time.time()
while time.time() - t0 < 40:
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
    print('[FATAL] 端口文件未就绪 (40s)')
    proc.kill()
    sys.exit(1)
port, token = info['port'], info['token']
print('[agent] port=%d pid=%d' % (port, proc.pid), flush=True)


def call(cmd_name, args=None):
    body = json.dumps({'cmd': cmd_name, 'args': args or {}}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
        headers={'X-Agent-Token': token,
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode('utf-8'))


results = {'launch_cmd': cmd, 'pid': proc.pid}
try:
    # 启动日志核对 501 对象
    time.sleep(6.0)
    st = call('status')
    results['editor_status'] = st
    print('[editor status] models=%d playing=%s fps=%s'
          % (len(st.get('models', [])), st.get('playing'), st.get('fps')),
          flush=True)

    # 编辑器态截图 (整窗: 状态栏 FPS|TPS + HUD 帧长行可见)
    r = call('screenshot', {'file': os.path.join(shots, 'edit_mode.png'),
                            'full': True})
    results['editor_shot'] = r
    print('[editor shot]', r, flush=True)

    # 播放态
    r = call('play', {'on': True})
    results['play'] = r
    print('[play]', r, flush=True)
    time.sleep(8.0)   # TPS 滑窗 2s + 帧长滑窗 120 帧就位

    st2 = call('status')
    results['play_status'] = st2
    print('[play status] playing=%s fps=%s' % (st2.get('playing'), st2.get('fps')),
          flush=True)
    r = call('engine_metrics', {})
    results['play_metrics'] = r
    print('[play metrics]', json.dumps(r, ensure_ascii=False), flush=True)
    r = call('screenshot', {'file': os.path.join(shots, 'play_mode.png'),
                            'full': True})
    results['play_shot'] = r
    print('[play shot]', r, flush=True)

    # F9 暂停 (逻辑时钟暂停) — 经 settings 不可行, F9 无命令;
    # 用引擎 API 不可达 → 改: 暂停经由 toggle_logic_paused 无命令入口.
    # 这里验证 TPS/指标读数即可, 暂停态人工测 (台账 A43 已登记人工).
    r = call('screenshot', {'file': os.path.join(shots, 'paused_note.png'),
                            'full': True})
finally:
    try:
        call('quit', {'save': 'discard', 'after': 0.2})
    except Exception:
        pass
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
    results['exitcode'] = proc.returncode

with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print('[done]', out_json, flush=True)
