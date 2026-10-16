# -*- coding: utf-8 -*-
"""playcam_probe.py — 播放态相机移动实机验证 (2026-09-06, EAI 命令注入)

背景: 播放态 WASD 相机 BUG (根因=editor._update_camera 重构误删 speed 定义行,
按键即 NameError -> _on_tick 中断 -> viewport.update() 不执行 -> 不重画+逻辑
帧停摆=TPS 冻结; 已修, 键盘注入链由 playcam_headless_check.py 无头覆盖)。

本探针验证 (验证标准 #2):
  ①播放态 camera_move/camera_look 驱动 target/yaw/distance (与 WASD/方向键
    同一状态量 camera_target/camera_yaw/camera_pitch) 在渲染帧生效 -> 截图对比
  ②TPS 稳定采样 x6 (间隔 1s): 播放态逻辑帧不冻结 (波动 < ±3)
  ③engine_metrics FPS/TPS/时钟读数
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOOM = os.path.abspath(os.path.join(HERE, '..', '..'))

sys.path.insert(0, LOOM)
import guiloader

s = guiloader.load_settings('loom', base=LOOM)
s['logic_fps'] = 30
s['fps_limit'] = 'unlimited'
s['frame_buffer_tps'] = False
s['frame_buffer_fps'] = False
guiloader.save_settings('loom', s, base=LOOM)

scene = os.path.join(LOOM, '保存', '压测500混合.json')
cmd = [sys.executable, '-u', os.path.join(LOOM, 'Loom.py'),
       '--open', scene, '--agent']
proc = subprocess.Popen(cmd, cwd=LOOM)
info = None
t0 = time.time()
while time.time() - t0 < 60:
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
    raise SystemExit('port timeout')
port, token = info['port'], info['token']


def call(c, a=None):
    body = json.dumps({'cmd': c, 'args': a or {}}).encode('utf-8')
    req = urllib.request.Request(
        'http://127.0.0.1:%d/cmd' % port, data=body, method='POST',
        headers={'X-Agent-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8')).get('result', {})


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


try:
    time.sleep(10)
    call('play', {'on': True})          # 播放态 (相机统一: 与编辑态同一轨道链)
    time.sleep(4)

    # ---- 基线截图 ----
    call('screenshot', {'file': os.path.join(HERE, 'playcam_0_base.png')})

    # ---- ① camera_move: target z+15 (与 WASD 同一状态量 camera_target) ----
    r = call('camera_move', {'name': None, 'x': 0.0, 'y': 0.0, 'z': 15.0})
    print('move target->(0,0,15):', r)
    check("camera_move 写入 camera_target", abs(r.get('target', [0, 0, 0])[2] - 15.0) < 1e-6,
          str(r.get('target')))
    time.sleep(1.0)
    call('screenshot', {'file': os.path.join(HERE, 'playcam_1_moved.png')})

    # ---- ② camera_look: yaw=90 (与方向键同一状态量 camera_yaw) ----
    r = call('camera_look', {'name': None, 'yaw': 90.0, 'pitch': 10.0})
    print('look yaw=90:', r)
    check("camera_look 写入 camera_yaw", abs(r.get('yaw_deg', 0) - 90.0) < 0.5,
          str(r.get('yaw_deg')))
    time.sleep(1.0)
    call('screenshot', {'file': os.path.join(HERE, 'playcam_2_turned.png')})

    # ---- ③ distance (滚轮同一状态量) ----
    r = call('camera_move', {'name': None, 'distance': 30.0})
    print('distance=30:', r)
    check("camera_move distance 生效", abs(r.get('distance', 0) - 30.0) < 1e-6,
          str(r.get('distance')))
    time.sleep(1.0)
    call('screenshot', {'file': os.path.join(HERE, 'playcam_3_zoom.png')})

    # ---- ④ TPS 稳定采样 x6 (1s 间隔): 播放态逻辑帧不冻结 ----
    # (get_tps = 2s 滑动窗口; 先沉降 2s 隔离上段截图/camera_move 突发污染)
    time.sleep(2.0)
    tps = []
    for i in range(6):
        m = call('engine_metrics', {})
        tps.append(float(m.get('get_tps') or 0))
        time.sleep(1.0)
    print('[tps x6]', ['%.1f' % v for v in tps])
    spread = max(tps) - min(tps)
    check("TPS 稳定 (波动 < ±3, 播放态不冻结)", spread < 3.0 and min(tps) > 20.0,
          "spread=%.2f min=%.1f" % (spread, min(tps)))

    # ---- ⑤ metrics 终读 ----
    m = call('engine_metrics', {})
    print('[metrics] fps=%s tps=%s jitter=%s playing=%s paused=%s' % (
        m.get('fps'), m.get('get_tps'), m.get('get_frame_jitter'),
        m.get('is_playing'), m.get('logic_paused')))
    check("播放态保持 (全程未中断)", m.get('is_playing') is True)
finally:
    try:
        call('quit', {'save': 'discard', 'after': 0.2})
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print()
print("总结果:", "ALL PASS ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
