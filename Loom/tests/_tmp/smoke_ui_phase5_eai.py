# -*- coding: utf-8 -*-
"""smoke_ui_phase5_eai.py — 阶段5 EAI 命令冒烟 (2026-10-18)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import agent_commands as ac
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


def call(cmd_name, **kwargs):
    """直接调命令函数（绕过 HTTP 层）"""
    fn = ac._COMMANDS.get(cmd_name)
    if fn is None:
        raise KeyError('命令不存在: %s' % cmd_name)
    return fn(w, kwargs)


# 1) ui_list 空
r = call('ui_list')
assert r['total'] == 1
assert len(r['canvases']) == 1
assert r['canvases'][0]['canvas_type'] == 'screen'
assert len(r['canvases'][0]['root']['children']) == 0
print('ui_list empty OK')

# 2) ui_add 11 种元素
for typ in ac._UI_TYPE_NAMES:
    extra = {}
    if typ == 'text':
        extra['text'] = 'Hello'
    elif typ == 'image':
        extra['texture_path'] = 'assets/test.png'
    elif typ == 'button':
        extra['text'] = 'OK'
    elif typ == 'slider':
        extra['min_value'] = 0; extra['max_value'] = 100; extra['value'] = 50
    elif typ == 'toggle':
        extra['label'] = 'Toggle'
    elif typ == 'progress_bar':
        extra['value'] = 0.5
    elif typ == 'scroll_view':
        extra['content_size'] = (300, 800)
    elif typ == 'input_field':
        extra['placeholder'] = '请输入'
    elif typ == 'dropdown':
        extra['options'] = ['a', 'b', 'c']
    r = call('ui_add', type=typ, **extra)
    assert 'error' not in r, '%s 失败: %r' % (typ, r)
    assert r['type'] == typ
    print('ui_add %s OK (name=%s)' % (typ, r['name']))

# 3) ui_list 确认 11 个元素
r = call('ui_list')
kids = r['canvases'][0]['root']['children']
assert len(kids) == len(ac._UI_TYPE_NAMES), len(kids)
print('ui_list after add: %d 个元素 OK' % len(kids))

# 4) ui_set 修改字段
first_name = kids[0]['name']   # panel_N
r = call('ui_set', name=first_name, rect=(10, 20, 300, 40),
         visible=False, z_order=5)
assert 'error' not in r, r
assert r['changed']['rect'] == [10, 20, 300, 40]
assert r['changed']['visible'] is False
assert r['changed']['z_order'] == 5
print('ui_set 通用字段 OK')

# 5) ui_set type-specific（Button.text）
btn = [k for k in kids if k['type'] == 'button'][0]
r = call('ui_set', name=btn['name'], text='修改后', font_size=18)
assert 'error' not in r
assert r['changed']['text'] == '修改后'
assert r['changed']['font_size'] == 18
print('ui_set type-specific OK')

# 6) ui_set 不存在的元素
r = call('ui_set', name='no_such_elem', visible=True)
assert 'error' in r
print('ui_set not-found -> error OK')

# 7) ui_remove
n0 = len(call('ui_list')['canvases'][0]['root']['children'])
r = call('ui_remove', name=first_name)
assert 'removed' in r, r
n1 = len(call('ui_list')['canvases'][0]['root']['children'])
assert n1 == n0 - 1
print('ui_remove OK')

# 8) ui_remove 不存在
r = call('ui_remove', name='no_such')
assert 'error' in r
print('ui_remove not-found -> error OK')

# 9) ui_add 带 parent（层级）
r = call('ui_add', type='panel', name='outer')
outer_name = r['name']
r = call('ui_add', type='button', name='inner_btn', parent='outer', text='X')
assert 'error' not in r
# 检查层级关系
root_kids = call('ui_list')['canvases'][0]['root']['children']
outer = [k for k in root_kids if k['name'] == 'outer'][0]
assert any(ch['name'] == 'inner_btn' for ch in outer['children']), outer
print('ui_add with parent OK')

# 10) ui_canvas_add
r = call('ui_canvas_add', type='screen', width=1024, height=768, z_order=10)
assert 'error' not in r
assert r['total'] == 2
print('ui_canvas_add OK')

# 11) ui_list 只列第 2 个 Canvas
r = call('ui_list', canvas=1)
assert r['total'] == 2
assert len(r['canvases']) == 1
assert r['canvases'][0]['width'] == 1024
print('ui_list single-canvas OK')

# 12) ui_add 未知 type
r = call('ui_add', type='nonexistent')
assert 'error' in r
print('ui_add unknown-type -> error OK')

# 13) GridLayout 改 columns 触发 reflow
r = call('ui_add', type='grid_layout', name='g', columns=2,
         cell_size=(64, 64), spacing=(8, 8))
r = call('ui_add', type='panel', name='gc0', parent='g')
r = call('ui_add', type='panel', name='gc1', parent='g')
r = call('ui_add', type='panel', name='gc2', parent='g')
# 改成 1 列 -> 3 行
r = call('ui_set', name='g', columns=1)
assert 'error' not in r
# 检查 reflow 结果
g = w.editor.ui.default_canvas().root.find('g')
assert g is not None
assert g.children[0].rect[0] == 0
assert g.children[1].rect[0] == 0
assert g.children[1].rect[1] > g.children[0].rect[1]
print('GridLayout reflow after ui_set OK')

print('SMOKE_PASS')
