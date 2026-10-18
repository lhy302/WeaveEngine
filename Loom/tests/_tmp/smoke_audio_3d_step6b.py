# -*- coding: utf-8 -*-
"""smoke_audio_3d_step6b.py — MCP dispatch 分支冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import loom_mcp


class _StubClient:
    def call(self, cmd, args=None, timeout=30.0):
        return {'ok': True, 'result': {'cmd': cmd, 'args': args}}


srv = loom_mcp.LoomMCPServer.__new__(loom_mcp.LoomMCPServer)
srv.client = _StubClient()

r = srv.dispatch_tool('loom_audio_3d_get', {'name': 'A'})
assert r.get('isError') is False, r
assert 'get_audio_3d' in r['content'][0]['text'], r
print('dispatch get OK')

r = srv.dispatch_tool('loom_audio_3d_set', {'name': 'A', 'category': 'sfx',
                                            'min_distance': 2.0})
assert r.get('isError') is False, r
assert 'set_audio_3d' in r['content'][0]['text'], r
print('dispatch set OK')

# 无 name 时不应带 name 参数
r = srv.dispatch_tool('loom_audio_3d_get', {})
assert r.get('isError') is False, r
print('dispatch no-name OK')
print('SMOKE_PASS')
