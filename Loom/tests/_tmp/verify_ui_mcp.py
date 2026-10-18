# -*- coding: utf-8 -*-
"""verify_ui_mcp.py — 阶段5 MCP 工具注册与转发验收 (契约 §12)

覆盖 7 个 UI 工具：loom_ui_list / add / set / remove / canvas_add / reparent / move_child
验证：
  1) tools/list 返回 7 个 loom_ui_* 工具定义
  2) tools/call 转发到对应 EAI 命令
  3) 端到端调用能正常操作 UI 树
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac
import loom_mcp
import loom_ui
import undo as undo_mod


class _Ed:
    def __init__(self):
        self.ui = loom_ui.UIManager()
        self.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen', width=800, height=600))
        self.undo = undo_mod.UndoManager()


class _Win:
    def __init__(self):
        self.editor = _Ed()


w = _Win()


class _StubClient:
    def call(self, cmd_name, payload=None):
        fn = ac._COMMANDS.get(cmd_name)
        if fn is None:
            return {'error': '命令不存在: %s' % cmd_name}
        return fn(w, payload or {})


srv = loom_mcp.LoomMCPServer(client=_StubClient())


def rpc(method, params=None):
    return srv.handle_request({
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})


def call_tool(cmd_name, **kwargs):
    r = rpc('tools/call', {'name': cmd_name, 'arguments': kwargs})
    return json.loads(r['result']['content'][0]['text'])


# 1) tools/list：7 个 UI 工具定义完整
r = rpc('tools/list')
tool_names = {t['name'] for t in r['result']['tools']}
expected = {'loom_ui_list', 'loom_ui_add', 'loom_ui_set',
            'loom_ui_remove', 'loom_ui_canvas_add',
            'loom_ui_reparent', 'loom_ui_move_child'}
for n in expected:
    assert n in tool_names, '缺工具: %s' % n
print('tools/list 含 7 个 UI 工具 OK')

# 2) 每个工具的 inputSchema 字段完整
for t in r['result']['tools']:
    if t['name'] not in expected:
        continue
    assert 'description' in t, t['name']
    assert 'inputSchema' in t, t['name']
    assert t['inputSchema'].get('type') == 'object', t['name']
print('7 个工具 inputSchema 结构 OK')

# 3) 端到端：ui_canvas_add -> ui_add -> ui_set -> ui_list
r = call_tool('loom_ui_canvas_add', type='screen', width=1024, height=768)
assert 'error' not in r
assert r['total'] == 2
print('loom_ui_canvas_add 转发 OK')

r = call_tool('loom_ui_add', type='button', name='btn_a',
              text='A', canvas=1, rect=(10, 10, 100, 30))
assert 'error' not in r
assert r['name'] == 'btn_a'
print('loom_ui_add 转发 OK')

r = call_tool('loom_ui_set', name='btn_a', canvas=1, text='B')
assert 'error' not in r
assert r['changed']['text'] == 'B'
print('loom_ui_set 转发 OK')

r = call_tool('loom_ui_list', canvas=1)
assert r['canvases'][0]['width'] == 1024
print('loom_ui_list 转发 OK')

# 4) ui_reparent + ui_move_child
r = call_tool('loom_ui_add', type='panel', name='p1', canvas=1,
              rect=(0, 0, 400, 400))
assert 'error' not in r
r = call_tool('loom_ui_reparent', name='btn_a', new_parent='p1', canvas=1)
assert 'error' not in r
assert r['new_parent'] == 'p1'
print('loom_ui_reparent 转发 OK')

r = call_tool('loom_ui_add', type='panel', name='p2', canvas=1)
# p1 已在 index 0, 移到 index 1 (末尾) 才有效
r = call_tool('loom_ui_move_child', name='p1', to_index=1, canvas=1)
assert 'error' not in r and r['moved'] is True, r
print('loom_ui_move_child 转发 OK')

# 5) ui_remove
r = call_tool('loom_ui_remove', name='btn_a', canvas=1)
assert 'removed' in r
print('loom_ui_remove 转发 OK')

# 6) 错误参数处理（ui_add 缺 type）
r = call_tool('loom_ui_add')
assert 'error' in r
print('loom_ui_add 缺 type -> error 转发 OK')

print('PASS verify_ui_mcp')
