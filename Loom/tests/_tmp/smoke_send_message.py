# -*- coding: utf-8 -*-
"""smoke_send_message.py — SendMessage 冒烟 (2026-10-18 阶段1档序6)"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import agent_commands as ac
import loom_mcp
import scripts
from loom_game_object import GameObject


class _StubScript:
    """桩脚本实例（直接赋给 sc._script）."""
    def __init__(self, handler=None):
        self.handler = handler
        self.calls = []
    def on_hit(self, *args, **kw):
        self.calls.append(('on_hit', args, kw))
        if self.handler:
            self.handler()


class _StubSC:
    """桩 ScriptComponent."""
    def __init__(self, sid, inst=None, broken=False):
        self.script_id = sid
        self.script_vars = {}
        self._script = inst
        self._script_broken = broken


def make_obj(name, scs):
    """绕过 GameObject.__init__（避免 GPU 依赖），直接构造最小字段。
    send_message 挂真实实现（绑到桩对象上等价 GameObject 实例）。"""
    m = type('M', (), {})()
    m.name = name
    m.scripts = scs
    m.send_message = lambda *a, **kw: GameObject.send_message(m, *a, **kw)
    return m


# ---- 1. 正常调用（两个脚本，一个实现 on_hit，另一个不实现）----
s1 = _StubScript()
s2 = _StubScript()  # 也有 on_hit 方法（桩都有）
# 为了让 s2 不响应 on_hit，给它个没方法的替代
class _NoHit:
    pass
s2 = _NoHit()
sc1 = _StubSC('a', inst=s1)
sc2 = _StubSC('b', inst=s2)
m = make_obj('ObjA', [sc1, sc2])
n = m.send_message('on_hit')
assert n == 1, '期望调用 1 次（s2 没 on_hit），实际 %d' % n
assert len(s1.calls) == 1
print('1) GameObject.send_message 正常调用 OK')

# ---- 2. 方法不存在 ----
s3 = _StubScript()
m2 = make_obj('ObjB', [_StubSC('c', inst=s3)])
n = m2.send_message('nonexistent_method')
assert n == 0
print('2) 方法不存在 → 跳过 OK')

# ---- 3. 异常隔离 ----
def _crash(): raise RuntimeError('故意崩溃')
s4 = _StubScript(handler=_crash)
sc4 = _StubSC('d', inst=s4)
m3 = make_obj('ObjC', [sc4])
n = m3.send_message('on_hit')
assert n == 0  # 崩了不算成功
assert sc4._script_broken is True, '_script_broken 应被标记'
print('3) 异常隔离 + 坏脚本标记 OK')

# ---- 4. 坏脚本跳过（_script_broken=True）----
s5 = _StubScript()
sc5 = _StubSC('e', inst=s5, broken=True)
m4 = make_obj('ObjD', [sc5])
n = m4.send_message('on_hit')
assert n == 0
assert len(s5.calls) == 0  # 没被调用
print('4) 坏脚本跳过 OK')

# ---- 5. 空方法名 / 非字符串 ----
m5 = make_obj('ObjE', [_StubSC('f', inst=_StubScript())])
assert m5.send_message('') == 0
assert m5.send_message(None) == 0
assert m5.send_message(123) == 0
print('5) 空/非字符串方法名返回 0 OK')

# ---- 6. 带参数调用 ----
s6 = _StubScript()
m6 = make_obj('ObjF', [_StubSC('g', inst=s6)])
n = m6.send_message('on_hit', 'damage', 10, source='bullet')
assert n == 1
assert s6.calls[0] == ('on_hit', ('damage', 10), {'source': 'bullet'})
print('6) 带参数调用 OK')

# ---- 7. engine.send_message_to_name ----
# 造最小 engine 桩
class _Eng:
    def __init__(self, models):
        self.models = models
    # 复用真实方法
    send_message_to_name = __import__('engine').GLEngine.send_message_to_name

s7 = _StubScript()
obj7 = make_obj('Player', [_StubSC('h', inst=s7)])
eng = _Eng([obj7])

n = eng.send_message_to_name('Player', 'on_hit', 42)
assert n == 1
assert s7.calls[0][1] == (42,)
# 找不到物体
assert eng.send_message_to_name('NoSuch', 'on_hit') == 0
print('7) engine.send_message_to_name OK')

# ---- 8. EAI 命令正常 ----
class _Win:
    def __init__(self, ed):
        self.editor = ed
win = _Win(eng)

fn = ac._COMMANDS.get('send_message')
r = fn(win, {'model': 'Player', 'method': 'on_hit', 'args': ['hi']})
assert 'called' in r and r['called'] == 1, r
print('8) EAI send_message 命令 OK')

# ---- 9. EAI 参数缺失 ----
r = fn(win, {'model': 'Player'})   # 缺 method
assert 'error' in r
r = fn(win, {'method': 'on_hit'})   # 缺 model
assert 'error' in r
r = fn(win, {'model': 'Player', 'method': 'on_hit', 'args': 'not_array'})
assert 'error' in r
print('9) EAI 参数缺失 / 非法 → error OK')

# ---- 10. MCP 工具转发 ----
class _StubClient:
    def call(self, name, payload=None):
        return fn(win, payload or {})

srv = loom_mcp.LoomMCPServer(client=_StubClient())

# 10a. tools/list 含 loom_send_message
r = srv.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
names = {t['name'] for t in r['result']['tools']}
assert 'loom_send_message' in names, names
print('10a) MCP tools/list 含 loom_send_message OK')

# 10b. 转发
s8 = _StubScript()
obj8 = make_obj('Enemy', [_StubSC('i', inst=s8)])
win.editor.models = [obj7, obj8]
r = srv.handle_request({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                        'params': {'name': 'loom_send_message',
                                   'arguments': {'model': 'Enemy', 'method': 'on_hit'}}})
res = json.loads(r['result']['content'][0]['text'])
assert res['called'] == 1, res
assert len(s8.calls) == 1
print('10b) MCP loom_send_message 转发 OK')

print()
print('SMOKE_PASS')
