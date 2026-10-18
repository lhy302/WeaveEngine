# -*- coding: utf-8 -*-
"""smoke_layermask.py — LayerMask 查询过滤冒烟 (2026-10-18)"""
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import numpy as np

import agent_commands as ac
import loom_mcp
import loom_raycast


class _Vec3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Model:
    def __init__(self, name, pos, layer=0, size=2.0, visible=True):
        self.name = name
        self.position = _Vec3(*pos)
        self.scale = (size, size, size)
        self.visible = visible
        self.layer = layer
        self.mesh = None
        self.collider = None
        self.rigidbody = None


class _Eng(loom_raycast.RaycastMixin):
    def __init__(self, models):
        self.models = models
        self.width = 800
        self.height = 600
        self._phys_bridge = None
        self._frame_world = [np.eye(4, dtype='f4') for _ in models]

    def compute_world_matrices(self, models):
        return [np.eye(4, dtype='f4') for _ in models]

    def _model_aabbs_par(self, models, fw):
        out = []
        for m in models:
            p = m.position
            sx, sy, sz = m.scale
            mn = _Vec3(p.x - sx / 2, p.y - sy / 2, p.z - sz / 2)
            mx = _Vec3(p.x + sx / 2, p.y + sy / 2, p.z + sz / 2)
            out.append((mn, mx))
        return out


# 场景：layer 0 在 z=0，layer 3 在 z=5，layer 5 在 z=10
m0 = _Model('L0', (0, 0, 0), layer=0)
m3 = _Model('L3', (0, 0, 5), layer=3)
m5 = _Model('L5', (0, 0, 10), layer=5)
eng = _Eng([m0, m3, m5])


def call(cmd, **kw):
    fn = ac._COMMANDS.get(cmd)
    return fn(_Win(eng), kw)


class _Win:
    def __init__(self, eng):
        self.editor = eng


# 1) raycast 默认 layer_mask=None（不过滤）命中 L0
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100, backend='geometry')
assert r is not None and r[0].name == 'L0'
print('1) raycast 无 mask 命中最近 OK')

# 2) raycast layer_mask 只含 layer 3 → 命中 L3
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100,
                backend='geometry', layer_mask=(1 << 3))
assert r is not None and r[0].name == 'L3', r[0].name if r else None
print('2) raycast layer_mask=1<<3 命中 L3 OK')

# 3) raycast layer_mask 只含 layer 5 → 命中 L5
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100,
                backend='geometry', layer_mask=(1 << 5))
assert r is not None and r[0].name == 'L5', r[0].name if r else None
print('3) raycast layer_mask=1<<5 命中 L5 OK')

# 4) raycast layer_mask=0 → 全无命中
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100,
                backend='geometry', layer_mask=0)
assert r is None, r
print('4) layer_mask=0 无命中 OK')

# 5) layer_mask=0xFFFFFFFF（全包含）→ 命中 L0（最近）
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100,
                backend='geometry', layer_mask=0xFFFFFFFF)
assert r is not None and r[0].name == 'L0'
print('5) layer_mask=0xFFFFFFFF 命中最近 OK')

# 6) layer_mask=负数（不限）→ 命中 L0
r = eng.raycast((0, 0, -10), (0, 0, 1), max_dist=100,
                backend='geometry', layer_mask=-1)
assert r is not None and r[0].name == 'L0'
print('6) layer_mask=-1 视作不限 OK')

# 7) raycast_all 多掩码：layer 0 + layer 5
r = eng.raycast_all((0, 0, -10), (0, 0, 1), max_dist=100,
                    backend='geometry', layer_mask=(1 << 0) | (1 << 5))
names = [x[0].name for x in r]
assert names == ['L0', 'L5'], names
print('7) raycast_all 多掩码 OK:', names)

# 8) raycast_all layer_mask=0 → 空
r = eng.raycast_all((0, 0, -10), (0, 0, 1), max_dist=100,
                    backend='geometry', layer_mask=0)
assert r == []
print('8) raycast_all layer_mask=0 空 OK')

# 9) EAI raycast 命令透传 layer_mask
r = call('raycast', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1,
         max_dist=100, layer_mask=(1 << 3))
assert r['hit'] is not None and r['hit']['name'] == 'L3', r
print('9) EAI raycast layer_mask 透传 OK')

# 10) EAI raycast_all 命令透传 layer_mask
r = call('raycast_all', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1,
         max_dist=100, layer_mask=(1 << 3) | (1 << 5))
names = [h['name'] for h in r['hits']]
assert names == ['L3', 'L5'], names
print('10) EAI raycast_all layer_mask 透传 OK')

# 11) EAI 非法 layer_mask（字符串无法转 int）
r = call('raycast', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1,
         max_dist=100, layer_mask='abc')
assert 'error' in r
print('11) EAI 非法 layer_mask -> error OK')

# 12) MCP 工具 schema 含 layer_mask
class _StubClient:
    def call(self, cmd_name, payload=None):
        fn = ac._COMMANDS.get(cmd_name)
        if fn is None:
            return {'error': 'no command'}
        return fn(_Win(eng), payload or {})

srv = loom_mcp.LoomMCPServer(client=_StubClient())
r = srv.handle_request({'jsonrpc': '2.0', 'id': 1,
                        'method': 'tools/list', 'params': {}})
tools = {t['name']: t for t in r['result']['tools']}
for n in ['loom_raycast', 'loom_raycast_all', 'loom_raycast_screen']:
    assert 'layer_mask' in tools[n]['inputSchema']['properties'], n
print('12) MCP 三工具 schema 含 layer_mask OK')

# 13) MCP loom_raycast 透传 layer_mask
r = srv.handle_request({'jsonrpc': '2.0', 'id': 2,
                        'method': 'tools/call',
                        'params': {'name': 'loom_raycast',
                                   'arguments': {
                                       'ox': 0, 'oy': 0, 'oz': -10,
                                       'dx': 0, 'dy': 0, 'dz': 1,
                                       'max_dist': 100,
                                       'layer_mask': (1 << 5)}}})
res = json.loads(r['result']['content'][0]['text'])
assert res['hit'] is not None and res['hit']['name'] == 'L5', res
print('13) MCP loom_raycast layer_mask 透传 OK')

print('SMOKE_PASS')
