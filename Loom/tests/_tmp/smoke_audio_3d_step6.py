# -*- coding: utf-8 -*-
"""smoke_audio_3d_step6.py — MCP 音频 3D 工具冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import loom_mcp

names = [t['name'] for t in loom_mcp.TOOLS_DEF]
assert 'loom_audio_3d_set' in names, names
assert 'loom_audio_3d_get' in names, names
print('total tools:', len(names))
assert len(names) == len(set(names)), '工具名重复'
print('no duplicate names OK')

# dispatch_tool 至少有对应分支（用桩 client 验证不抛 KeyError/NameError）
class _StubClient:
    def call(self, cmd, args=None, timeout=30.0):
        return {'ok': True, 'result': {'cmd': cmd, 'args': args}}


h = loom_mcp.LoomMCPHandler.__new__(loom_mcp.LoomMCPHandler) if hasattr(loom_mcp, 'LoomMCPHandler') else None
if h is not None:
    h.client = _StubClient()
    r = h.dispatch_tool('loom_audio_3d_get', {'name': 'A'})
    assert r.get('isError') is False, r
    print('dispatch get OK')
    r = h.dispatch_tool('loom_audio_3d_set', {'name': 'A', 'category': 'sfx', 'min_distance': 2.0})
    assert r.get('isError') is False, r
    print('dispatch set OK')
else:
    print('handler class not found, skip dispatch check')
print('SMOKE_PASS')
