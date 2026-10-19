# -*- coding: utf-8 -*-
"""smoke_object_find.py — 对象查找冒烟 (2026-10-18 阶段1档序8)"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import agent_commands as ac
import loom_mcp
import engine as E

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


class _StubSC:
    def __init__(self, sid):
        self.script_id = sid
        self.script_vars = {}
        self._script = None
        self._script_broken = False


def _mk(name, scripts_ids):
    m = type('M', (), {})()
    m.name = name
    m.scripts = [_StubSC(sid) for sid in scripts_ids]
    return m


# 造 engine 桩（复用真实方法）
class _Eng:
    def __init__(self, models):
        self.models = models
    find_by_name = E.GLEngine.find_by_name
    find_all_by_name = E.GLEngine.find_all_by_name
    find_by_script = E.GLEngine.find_by_script
    find_by_tag = E.GLEngine.find_by_tag


# 场景：
#   Player (rotate)
#   Enemy (enemy_ai)
#   Enemy (enemy_ai)    <- 两个同名 Enemy
#   Coin (rotate, enemy_ai)   <- 挂了两个脚本
m_player = _mk('Player', ['rotate'])
m_enemy1 = _mk('Enemy', ['enemy_ai'])
m_enemy2 = _mk('Enemy', ['enemy_ai'])
m_coin = _mk('Coin', ['rotate', 'enemy_ai'])
m_dup = _mk('Dup', ['enemy_ai', 'enemy_ai'])   # 同物体挂两个相同脚本
eng = _Eng([m_player, m_enemy1, m_enemy2, m_coin, m_dup])

# 1. find_by_name 找到唯一
check('1) find_by_name 找到唯一',
      eng.find_by_name('Player') is m_player)

# 2. find_by_name 找不到
check('2) find_by_name 找不到返回 None',
      eng.find_by_name('NoSuch') is None)

# 3. find_by_name 空/非字符串
check('3) find_by_name 空/非字符串返回 None',
      eng.find_by_name('') is None
      and eng.find_by_name(None) is None
      and eng.find_by_name(123) is None)

# 4. find_all_by_name 多匹配
r = eng.find_all_by_name('Enemy')
check('4) find_all_by_name 返回 2 个 Enemy',
      len(r) == 2 and m_enemy1 in r and m_enemy2 in r,
      'n=%d' % len(r))

# 5. find_all_by_name 空
check('5) find_all_by_name 找不到返回 []',
      eng.find_all_by_name('NoSuch') == []
      and eng.find_all_by_name('') == [])

# 6. find_by_script 找到挂载物体
r = eng.find_by_script('rotate')
check('6a) find_by_script(rotate) 找到 Player + Coin',
      set(r) == {m_player, m_coin},
      'names=%r' % [m.name for m in r])
r = eng.find_by_script('enemy_ai')
check('6b) find_by_script(enemy_ai) 找到 Enemy*2 + Coin + Dup',
      set(r) == {m_enemy1, m_enemy2, m_coin, m_dup},
      'names=%r' % [m.name for m in r])

# 7. find_by_script 找不到
check('7) find_by_script 找不到返回 []',
      eng.find_by_script('nope') == [])

# 8. 同物体多个相同脚本只返回一次
r = eng.find_by_script('enemy_ai')
check('8) 同物体多个相同脚本不重复',
      r.count(m_dup) == 1, 'count=%d' % r.count(m_dup))

# ============ EAI 命令 ============
class _Win:
    def __init__(self, ed):
        self.editor = ed
win = _Win(eng)

# 9. find_by_name 命令
fn = ac._COMMANDS.get('find_by_name')
r = fn(win, {'model': 'Player'})
check('9a) EAI find_by_name 正常',
      r.get('found') is not None and r['found']['name'] == 'Player', r)
check('9b) EAI find_by_name 找不到 → found=null',
      fn(win, {'model': 'NoSuch'})['found'] is None)
check('9c) EAI find_by_name 参数缺失 → error',
      'error' in fn(win, {}))

# 10. find_all_by_name 命令
fn = ac._COMMANDS.get('find_all_by_name')
r = fn(win, {'model': 'Enemy'})
check('10a) EAI find_all_by_name 返回 2 个',
      len(r['found']) == 2, 'n=%d' % len(r['found']))
check('10b) EAI find_all_by_name 空 → []',
      fn(win, {'model': 'NoSuch'})['found'] == [])
check('10c) EAI find_all_by_name 参数缺失 → error',
      'error' in fn(win, {}))

# 11. find_by_script 命令
fn = ac._COMMANDS.get('find_by_script')
r = fn(win, {'script_id': 'rotate'})
check('11a) EAI find_by_script(rotate) 找到 2 个',
      len(r['found']) == 2, 'n=%d' % len(r['found']))
check('11b) EAI find_by_script 空 → []',
      fn(win, {'script_id': 'nope'})['found'] == [])
check('11c) EAI find_by_script 参数缺失 → error',
      'error' in fn(win, {}))

# ============ MCP 工具 ============
class _StubClient:
    def call(self, name, payload=None):
        fn = ac._COMMANDS.get(name)
        if fn is None:
            return {'error': 'no command'}
        return fn(win, payload or {})

srv = loom_mcp.LoomMCPServer(client=_StubClient())

# 12. tools/list 含 3 个新工具
r = srv.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
names = {t['name'] for t in r['result']['tools']}
for n in ['loom_find_by_name', 'loom_find_all_by_name', 'loom_find_by_script']:
    check('12) MCP tools/list 含 %s' % n, n in names)

# 13. 转发
def _call_tool(cmd, args):
    r = srv.handle_request({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': cmd, 'arguments': args}})
    return json.loads(r['result']['content'][0]['text'])

r = _call_tool('loom_find_by_name', {'model': 'Player'})
check('13a) MCP loom_find_by_name 转发',
      r.get('found') is not None and r['found']['name'] == 'Player', r)

r = _call_tool('loom_find_all_by_name', {'model': 'Enemy'})
check('13b) MCP loom_find_all_by_name 转发',
      len(r['found']) == 2, 'n=%d' % len(r['found']))

r = _call_tool('loom_find_by_script', {'script_id': 'rotate'})
check('13c) MCP loom_find_by_script 转发',
      len(r['found']) == 2, 'n=%d' % len(r['found']))

print()
if fails:
    print('FAILED: %d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('SMOKE_PASS')
