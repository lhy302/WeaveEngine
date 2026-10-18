# -*- coding: utf-8 -*-
"""smoke_ui_phase5_mcp_reparent.py — 阶段5 MCP 拖拽工具冒烟 (2026-10-18)"""
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
        'jsonrpc': '2.0', 'id': 1, 'method': method,
        'params': params or {}})


# 1) tools/list 应含 7 个 loom_ui_* 工具
r = rpc('tools/list')
tool_names = [t['name'] for t in r['result']['tools']]
expected = ['loom_ui_list', 'loom_ui_add', 'loom_ui_set',
            'loom_ui_remove', 'loom_ui_canvas_add',
            'loom_ui_reparent', 'loom_ui_move_child']
for n in expected:
    assert n in tool_names, '缺工具: %s' % n
print('tools/list 含 7 个 loom_ui_* 工具 OK')


def call_tool(cmd_name, **kwargs):
    r = rpc('tools/call', {'name': cmd_name, 'arguments': kwargs})
    return json.loads(r['result']['content'][0]['text'])


# 2) 准备环境：加 3 个 panel
call_tool('loom_ui_add', type='panel', name='pa')
call_tool('loom_ui_add', type='panel', name='pb')
call_tool('loom_ui_add', type='button', name='b1', parent='pa', text='X')


# 3) loom_ui_reparent：b1 从 pa 挂到 pb
r = call_tool('loom_ui_reparent', name='b1', new_parent='pb')
assert 'error' not in r, r
assert r['old_parent'] == 'pa'
assert r['new_parent'] == 'pb'
root = w.editor.ui.default_canvas().root
pa = root.find('pa')
pb = root.find('pb')
b1 = root.find('b1')
assert b1.parent is pb
print('loom_ui_reparent OK')


# 4) 撤销 -> b1 应回到 pa
w.editor.undo.undo()
assert b1.parent is pa
print('loom_ui_reparent 撤销 OK')


# 5) loom_ui_move_child：同级内换序
# 现在 root 里的顺序: pa, pb
names_before = [ch.name for ch in root.children]
# 找 pb 的 index
pb_idx = names_before.index('pb')
# 把 pa 移到末尾
target = len(root.children) - 1
r = call_tool('loom_ui_move_child', name='pa', to_index=target)
assert 'error' not in r, r
assert r.get('moved') is True
names_after = [ch.name for ch in root.children]
assert names_after[-1] == 'pa', names_after
print('loom_ui_move_child OK')


# 6) 撤销 -> 恢复原序
w.editor.undo.undo()
assert [ch.name for ch in root.children] == names_before
print('loom_ui_move_child 撤销 OK')


# 7) 循环依赖拒绝
# 现在: pa -> b1 (已撤销回去), 试把 pa 挂到 b1 下
r = call_tool('loom_ui_reparent', name='pa', new_parent='b1')
assert 'error' in r, '应拒绝循环依赖, 实际: %r' % r
print('循环依赖拒绝 OK')


# 8) 越界拒绝
r = call_tool('loom_ui_move_child', name='pa', to_index=999)
assert 'error' in r
print('越界拒绝 OK')


print('SMOKE_PASS')
