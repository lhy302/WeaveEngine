# -*- coding: utf-8 -*-
"""smoke_ui_phase5_mcp.py — 阶段5 MCP 工具冒烟 (2026-10-18)

不启动 HTTP 服务，直接调 LoomMCPServer.handle_request 模拟 tools/list + tools/call。
用桩 LoomEngineClient，c.call 直接转发到 agent_commands._COMMANDS。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac
import loom_mcp
import loom_ui


class _Ed:
    def __init__(self):
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen', width=800, height=600))


class _Win:
    def __init__(self):
        self.editor = _Ed()


w = _Win()


class _StubClient:
    """桩 EngineClient: call() 直接转 agent_commands._COMMANDS."""
    def call(self, cmd_name, payload=None):
        fn = ac._COMMANDS.get(cmd_name)
        if fn is None:
            return {'error': '命令不存在: %s' % cmd_name}
        return fn(w, payload or {})


srv = loom_mcp.LoomMCPServer(client=_StubClient())


def rpc(method, params=None):
    return srv.handle_request({
        'jsonrpc': '2.0', 'id': 1, 'method': method,
        'params': params or {}})


# 1) tools/list 应含 5 个 loom_ui_* 工具
r = rpc('tools/list')
tool_names = [t['name'] for t in r['result']['tools']]
expected = ['loom_ui_list', 'loom_ui_add', 'loom_ui_set',
            'loom_ui_remove', 'loom_ui_canvas_add']
for n in expected:
    assert n in tool_names, '缺工具: %s' % n
print('tools/list 含 5 个 loom_ui_* 工具 OK')


# 2) tools/call loom_ui_list（空）
r = rpc('tools/call', {'name': 'loom_ui_list', 'arguments': {}})
res = r['result']
assert 'content' in res, res
import json
text = res['content'][0]['text']
data = json.loads(text)
assert data['total'] == 1
assert data['canvases'][0]['canvas_type'] == 'screen'
print('tools/call loom_ui_list OK')


# 3) tools/call loom_ui_add（button）
r = rpc('tools/call', {
    'name': 'loom_ui_add',
    'arguments': {
        'type': 'button', 'name': 'my_btn',
        'rect': [10, 20, 120, 40], 'text': 'Click me',
    }})
res = r['result']
data = json.loads(res['content'][0]['text'])
assert data.get('name') == 'my_btn', data
assert data.get('type') == 'button', data
print('tools/call loom_ui_add OK')


# 4) tools/call loom_ui_set（改 text）
r = rpc('tools/call', {
    'name': 'loom_ui_set',
    'arguments': {'name': 'my_btn', 'text': '修改后'}})
res = r['result']
data = json.loads(res['content'][0]['text'])
assert data.get('changed', {}).get('text') == '修改后', data
print('tools/call loom_ui_set OK')


# 5) tools/call loom_ui_canvas_add
r = rpc('tools/call', {
    'name': 'loom_ui_canvas_add',
    'arguments': {'type': 'screen', 'width': 1024, 'height': 768}})
res = r['result']
data = json.loads(res['content'][0]['text'])
assert data.get('total') == 2, data
print('tools/call loom_ui_canvas_add OK')


# 6) tools/call loom_ui_remove
r = rpc('tools/call', {
    'name': 'loom_ui_remove', 'arguments': {'name': 'my_btn'}})
res = r['result']
data = json.loads(res['content'][0]['text'])
assert data.get('removed') == 'my_btn', data
print('tools/call loom_ui_remove OK')


# 7) 参数错误（ui_add 无 type）
r = rpc('tools/call', {
    'name': 'loom_ui_add', 'arguments': {}})
res = r['result']
data = json.loads(res['content'][0]['text'])
assert 'error' in data, data
print('loom_ui_add 缺 type -> error OK')


print('SMOKE_PASS')
