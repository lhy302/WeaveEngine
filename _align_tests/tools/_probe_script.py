# -*- coding: utf-8 -*-
import json, urllib.request, os, math
LOOM = r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
def call(cmd, args=None):
    info = json.load(open(os.path.join(LOOM, '.agent_port.json'), encoding='utf-8'))
    body = json.dumps({'cmd': cmd, 'args': args or {}}).encode()
    req = urllib.request.Request('http://127.0.0.1:%d/cmd' % info['port'], data=body,
        method='POST', headers={'X-Agent-Token': info['token'],
        'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))
def last():
    m = call('object_list')['result']['models']
    return m[-1]['name'] if m else None
call('play', {'on': False}); call('scene_new')
call('object_add', {'type': 'cube'}); nm = last()
call('object_rename', {'name': nm, 'new': 'A'})
# 挂 rotate 脚本，Y 速度 90°/s
r = call('script_add', {'target': 'A', 'sid': 'rotate'})
print('script_add:', json.dumps(r, ensure_ascii=False)[:200])
call('play', {'on': True, 'paused': True})
for frames in (30, 60, 120):
    call('play', {'on': False}); call('play', {'on': True, 'paused': True})
    # 重新设置旋转为 0
    call('set_transform', {'name': 'A', 'rx': 0, 'ry': 0, 'rz': 0})
    call('physics_simulate', {'frames': frames})
    rot = call('inspect', {'name': 'A'})['result']['rotation']
    deg = [round(math.degrees(v), 2) for v in rot]
    exp = frames / 30.0 * 90.0
    print('frames=%d  rot_y=%.2f° 期望=%.2f° (90°/s, %d逻辑帧)' % (
        frames, deg[1], exp, frames))
