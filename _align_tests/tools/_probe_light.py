# -*- coding: utf-8 -*-
import json, urllib.request, os
LOOM = r"D:\my-project - 副本\Loom(py源代码-工作区)\Loom"
def call(cmd, args=None):
    info = json.load(open(os.path.join(LOOM, '.agent_port.json'), encoding='utf-8'))
    body = json.dumps({'cmd': cmd, 'args': args or {}}).encode()
    req = urllib.request.Request('http://127.0.0.1:%d/cmd' % info['port'], data=body,
        method='POST', headers={'X-Agent-Token': info['token'],
        'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))
call('scene_new')
call('light_add', {'kind': 'dir'})
r1 = call('inspect', {}).get('result', {})
print('dir  -> name=%s kind_of=%s' % (r1.get('name'), r1.get('kind_of')))
call('light_add', {'kind': 'point'})
r2 = call('inspect', {}).get('result', {})
print('point-> name=%s kind_of=%s range=%s' % (r2.get('name'), r2.get('kind_of'), r2.get('range')))
# 设 range 验证可调
call('light_set', {'name': '点光源', 'range': 25})
r3 = call('inspect', {'name': '点光源'}).get('result', {})
print('after set range=25 -> range=%s' % r3.get('range'))
