# -*- coding: utf-8 -*-
"""smoke_eai_passthrough.py — EAI 命令透传 MCP 工具冒烟

覆盖:
  A) tools 列表包含 loom_eai_list / loom_eai_call
  B) dispatch_tool 有对应 handler
  C) loom_eai_list 调用 get_status 返回命令列表
  D) loom_eai_call 透传命令与参数
  E) loom_eai_call 缺 cmd 参数报错
"""
import ast
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ A) tools 列表 ============
src = open(os.path.join(BASE, 'loom_mcp.py'), 'r', encoding='utf-8').read()
check('A1) tools 含 loom_eai_list',
      "'name': 'loom_eai_list'" in src)
check('A2) tools 含 loom_eai_call',
      "'name': 'loom_eai_call'" in src)


# ============ B) dispatch handler ============
tree = ast.parse(src)
handlers = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Compare):
        if isinstance(node.left, ast.Name) and node.left.id == 'name':
            for c in node.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    handlers.add(c.value)
check('B1) dispatch 有 loom_eai_list', 'loom_eai_list' in handlers)
check('B2) dispatch 有 loom_eai_call', 'loom_eai_call' in handlers)


# ============ C/D/E) 行为测试（mock client）============
import importlib
import loom_mcp
importlib.reload(loom_mcp)


class _MockClient:
    def __init__(self):
        self.calls = []
    def get_status(self):
        return {'ok': True, 'service': 'loom-agent',
                'commands': ['scene_new', 'object_add', 'camera_preview',
                             'import_obj', 'prefab_save']}
    def call(self, cmd, args=None, timeout=30.0):
        self.calls.append((cmd, dict(args or {})))
        return {'ok': True, 'result': {'echo_cmd': cmd, 'echo_args': args}}


# 构造一个只有 client 的轻量 server（其他依赖全 mock）
srv = loom_mcp.LoomMCPServer.__new__(loom_mcp.LoomMCPServer)
srv.client = _MockClient()

# C) loom_eai_list
r_list = srv.dispatch_tool('loom_eai_list', {})
content_text = r_list['content'][0]['text']
check('C1) eai_list 返回命令列表',
      'camera_preview' in content_text and 'import_obj' in content_text,
      content_text[:100])
check('C2) eai_list 列出命令数', '5' in content_text, content_text[:80])


# D) loom_eai_call
r_call = srv.dispatch_tool('loom_eai_call', {
    'cmd': 'camera_preview',
    'args': {'name': 'MainCam'},
})
check('D1) eai_call 不报错', r_call.get('isError') is not True, r_call)
check('D2) eai_call 透传 cmd', srv.client.calls[-1][0] == 'camera_preview',
      srv.client.calls[-1])
check('D3) eai_call 透传 args',
      srv.client.calls[-1][1] == {'name': 'MainCam'},
      srv.client.calls[-1])


# E) 缺 cmd 报错
r_err = srv.dispatch_tool('loom_eai_call', {})
check('E1) 缺 cmd 报错',
      r_err.get('isError') is True or 'error' in str(r_err),
      r_err)


# 清理
print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
