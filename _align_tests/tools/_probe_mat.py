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
call('object_add', {'type': 'cube'})
nm = call('object_list')['result']['models'][-1]['name']
call('object_rename', {'name': nm, 'new': 'A'})
for c in ('#FF0000', '#00FF00', '#0000FF', '#FF5555'):
    call('set_color', {'name': 'A', 'color': c})
    r = call('inspect', {'name': 'A'})['result']
    print('set %s -> material_color=%s material=%s' % (c, r.get('material_color'), r.get('material')))
# 饱和度
call('set_saturation', {'name': 'A', 'value': 0.5})
print('saturation:', call('inspect', {'name': 'A'})['result'].get('saturation'))
