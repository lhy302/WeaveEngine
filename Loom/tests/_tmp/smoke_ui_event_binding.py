# -*- coding: utf-8 -*-
"""smoke_ui_event_binding.py — P0-5 UI 声明式事件绑定冒烟

覆盖:
  A) UIElement.event_bindings 字段存在
  B) _fire_binding 从 _ACTIVE_ENGINE 查脚本实例并派发
  C) Button 点击触发 'click' 绑定
  D) InputField change / submit 触发对应绑定
  E) 序列化往返（_emit_ui_element -> _apply_ui_element）保留 event_bindings
  F) ui_bind_event / ui_unbind_event 命令（AST + 行为）
  G) MCP 有 loom_ui_bind_event / loom_ui_unbind_event 工具
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

import loom_ui
import sceneio

fails = []


def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ A) UIElement.event_bindings ============
el = loom_ui.UIElement(name='test')
check('A1) UIElement 有 event_bindings', hasattr(el, 'event_bindings'))
check('A2) 默认是空字典', el.event_bindings == {})


# ============ B) _fire_binding 从 _ACTIVE_ENGINE 派发 ============
class _MockScript:
    def __init__(self, script_id):
        self.script_id = script_id
        self.fired = []
    def on_click(self, *args):
        self.fired.append(('click', args))
    def on_submit(self, *args):
        self.fired.append(('submit', args))
    def on_change(self, *args):
        self.fired.append(('change', args))


class _MockModel:
    def __init__(self, guid, script):
        self.guid = guid
        self.name = 'model_' + guid
        self.scripts = [script]


class _MockEngine:
    def __init__(self):
        self.models = []


# 注册脚本 + engine
sc = _MockScript('test_sid')
model = _MockModel('g1', sc)
engine = _MockEngine()
engine.models = [model]
loom_ui._ACTIVE_ENGINE = engine

# 直接调用 _fire_binding
el.event_bindings = {'click': {'script': 'test_sid', 'method': 'on_click'}}
fired_ok = loom_ui._fire_binding(el, 'click')
check('B1) _fire_binding 找到脚本并调用', fired_ok, sc.fired)
check('B2) 脚本记录到一次 click', len(sc.fired) == 1, sc.fired)

# owner_guid 限定
sc.fired.clear()
el.event_bindings = {'click': {'script': 'test_sid', 'method': 'on_click',
                              'owner_guid': 'gWRONG'}}
loom_ui._fire_binding(el, 'click')
check('B3) owner_guid 不匹配时不触发', sc.fired == [], sc.fired)

# owner_guid 匹配
el.event_bindings = {'click': {'script': 'test_sid', 'method': 'on_click',
                              'owner_guid': 'g1'}}
loom_ui._fire_binding(el, 'click')
check('B4) owner_guid 匹配时触发', len(sc.fired) == 1, sc.fired)


# ============ C) Button 点击触发 ============
sc.fired.clear()
btn = loom_ui.Button(name='b1', rect=(0, 0, 100, 40), text='OK')
btn.event_bindings = {'click': {'script': 'test_sid', 'method': 'on_click'}}
btn.on_mouse_down((50, 20))
btn.on_mouse_up((50, 20))
check('C1) Button 按下+松开触发 click', len(sc.fired) == 1, sc.fired)
check('C2) 事件类型是 click', sc.fired[0][0] == 'click', sc.fired)


# ============ D) InputField change / submit ============
sc.fired.clear()
inp = loom_ui.InputField(name='inp1', rect=(0, 0, 200, 30))
inp.event_bindings = {
    'change': {'script': 'test_sid', 'method': 'on_change'},
    'submit': {'script': 'test_sid', 'method': 'on_submit'},
}
inp._set_text('hello')
check('D1) _set_text 触发 change', len(sc.fired) == 1, sc.fired)
inp._submit()
check('D2) _submit 触发 submit', len(sc.fired) == 2, sc.fired)
check('D3) submit 事件参数是当前文本',
      sc.fired[1][1] == ('hello',), sc.fired[1])


# ============ E) 序列化往返 ============
el2 = loom_ui.Button(name='b2', rect=(10, 20, 100, 40), text='Submit')
el2.event_bindings = {
    'click': {'script': 'cmd_ui', 'method': 'on_send', 'owner_guid': 'g1'}
}
d = sceneio._emit_ui_element(el2)
check('E1) 序列化包含 event_bindings',
      'event_bindings' in d, d.get('event_bindings'))
check('E2) 序列化内容正确',
      d.get('event_bindings') == el2.event_bindings, d.get('event_bindings'))

restored = sceneio._apply_ui_element(d)
check('E3) 反序列化元素非 None', restored is not None)
check('E4) 反序列化保留 event_bindings',
      getattr(restored, 'event_bindings', None) == el2.event_bindings,
      getattr(restored, 'event_bindings', None))


# ============ F) ui_bind_event 命令 ============
ac_src = open(os.path.join(BASE, 'agent_commands.py'), 'r', encoding='utf-8').read()
check('F1) 有 cmd_ui_bind_event', 'def cmd_ui_bind_event(' in ac_src)
check('F2) 有 cmd_ui_unbind_event', 'def cmd_ui_unbind_event(' in ac_src)
check('F3) 有 @command ui_bind_event', "@command('ui_bind_event'" in ac_src)
check('F4) 有 @command ui_unbind_event', "@command('ui_unbind_event'" in ac_src)


# ============ G) MCP 工具 ============
mcp_src = open(os.path.join(BASE, 'loom_mcp.py'), 'r', encoding='utf-8').read()
check('G1) MCP 有 loom_ui_bind_event 工具',
      "'name': 'loom_ui_bind_event'" in mcp_src)
check('G2) MCP 有 loom_ui_unbind_event 工具',
      "'name': 'loom_ui_unbind_event'" in mcp_src)
check('G3) MCP dispatch 有 ui_bind_event',
      "if name == 'loom_ui_bind_event':" in mcp_src)
check('G4) MCP dispatch 有 ui_unbind_event',
      "if name == 'loom_ui_unbind_event':" in mcp_src)


# ============ 清理 ============
loom_ui._ACTIVE_ENGINE = None


print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
