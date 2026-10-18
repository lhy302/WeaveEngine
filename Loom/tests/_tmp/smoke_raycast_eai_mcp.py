# -*- coding: utf-8 -*-
"""smoke_raycast_eai_mcp.py — Raycast EAI/MCP 冒烟 (2026-10-18)"""
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
    def __init__(self, name, pos, size=2.0, visible=True):
        self.name = name
        self.position = _Vec3(*pos)
        self.scale = (size, size, size)
        self.visible = visible
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


class _Win:
    def __init__(self, eng):
        self.editor = eng


# 场景
m1 = _Model('A', (0, 0, 0), size=2.0)
m2 = _Model('B', (0, 0, 5), size=2.0)
eng = _Eng([m1, m2])
w = _Win(eng)


def call(cmd, **kw):
    fn = ac._COMMANDS.get(cmd)
    if fn is None:
        raise KeyError('命令不存在: %s' % cmd)
    return fn(w, kw)


# 1) EAI raycast 命中
r = call('raycast', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1, max_dist=100)
assert 'hit' in r
assert r['hit']['name'] == 'A', r
assert abs(r['hit']['distance'] - 9.0) < 0.01
print('1) EAI raycast 命中 OK')

# 2) EAI raycast 无命中
r = call('raycast', ox=100, oy=100, oz=-10, dx=0, dy=0, dz=1)
assert r['hit'] is None
print('2) EAI raycast 未命中 OK')

# 3) EAI raycast 参数缺失
r = call('raycast', ox=0)
assert 'error' in r
print('3) EAI raycast 参数缺失 -> error OK')

# 4) EAI raycast_all
r = call('raycast_all', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1, max_dist=100)
assert 'hits' in r
assert len(r['hits']) == 2
assert r['hits'][0]['name'] == 'A'
assert r['hits'][1]['name'] == 'B'
print('4) EAI raycast_all OK')

# 5) EAI raycast_screen 无 _vp -> hit=None（降级路径）
r = call('raycast_screen', px=400, py=300)
assert r['hit'] is None
print('5) EAI raycast_screen 无 vp -> hit=None OK')

# 6) EAI raycast_screen 有 _vp 命中
from matlib import mat4_perspective, mat4_view_yaw_pitch
view = np.array(mat4_view_yaw_pitch(np, (0.0, 0.0, -20.0), 0.0, 0.0), dtype='f4')
proj = np.array(mat4_perspective(np, 60.0, 800.0 / 600.0, 0.1, 1000.0), dtype='f4')
eng._vp = (view @ proj).astype('f4')
r = call('raycast_screen', px=400, py=300)
assert r['hit'] is not None
assert r['hit']['name'] == 'A', r
print('6) EAI raycast_screen 正常 OK')


# ===== MCP =====
class _StubClient:
    def call(self, cmd_name, payload=None):
        fn = ac._COMMANDS.get(cmd_name)
        if fn is None:
            return {'error': '命令不存在: %s' % cmd_name}
        return fn(w, payload or {})


srv = loom_mcp.LoomMCPServer(client=_StubClient())


def rpc(method, params=None):
    return srv.handle_request({'jsonrpc': '2.0', 'id': 1,
                               'method': method, 'params': params or {}})


def call_tool(cmd_name, **kw):
    r = rpc('tools/call', {'name': cmd_name, 'arguments': kw})
    return json.loads(r['result']['content'][0]['text'])


# 7) tools/list 含 3 个 Raycast 工具
r = rpc('tools/list')
names = {t['name'] for t in r['result']['tools']}
for n in ['loom_raycast', 'loom_raycast_all', 'loom_raycast_screen']:
    assert n in names, '缺工具: %s' % n
print('7) MCP tools/list 含 3 个 Raycast 工具 OK')

# 8) loom_raycast 转发
r = call_tool('loom_raycast', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1)
assert 'hit' in r and r['hit']['name'] == 'A', r
print('8) MCP loom_raycast 转发 OK')

# 9) loom_raycast_all 转发
r = call_tool('loom_raycast_all', ox=0, oy=0, oz=-10, dx=0, dy=0, dz=1)
assert len(r['hits']) == 2
print('9) MCP loom_raycast_all 转发 OK')

# 10) loom_raycast_screen 转发
r = call_tool('loom_raycast_screen', px=400, py=300)
assert r['hit'] is not None and r['hit']['name'] == 'A', r
print('10) MCP loom_raycast_screen 转发 OK')

print('SMOKE_PASS')
