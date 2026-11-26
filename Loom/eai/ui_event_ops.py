# -*- coding: utf-8 -*-
"""eai.ui_event_ops — UI 声明式事件命令

我负责：ui_bind_event / ui_unbind_event。
我不负责：事件运行期派发（ui/ 包）与元素字段编辑（ui_element_ops.py）。
"""

from .registry import command
from .ui_common import _ui_canvas

@command('ui_bind_event', '给 UI 元素绑定声明式事件: '
                           '{name, event(click|change|submit), script, '
                           'method?, owner_guid?, canvas?}')
def cmd_ui_bind_event(win, args):
    """2026-10-19 P0-5: 声明式事件绑定（可序列化，Agent 可独立完成的 UI 交互）。

    参数:
      name       : UI 元素名
      event      : 'click' | 'change' | 'submit'（扩展: pointer_enter/exit/down/up/drag）
      script     : 脚本 script_id（必填，指向已注册脚本）
      method     : 脚本里要调的方法名（缺省=on_<event>）
      owner_guid : 可选，限定只在某物体上的脚本实例触发；缺省=任意挂该脚本的物体
      canvas     : 可选，Canvas 序号
    """
    name = args.get('name')
    event = args.get('event')
    script = args.get('script')
    if not name:
        return {'error': '必须传 name='}
    if event not in ('click', 'change', 'submit', 'pointer_enter',
                     'pointer_exit', 'pointer_down', 'pointer_up',
                     'pointer_drag'):
        return {'error': 'event 必须是 click/change/submit/pointer_*'}
    if not script:
        return {'error': '必须传 script= (脚本 script_id)'}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    if not hasattr(elem, 'event_bindings'):
        elem.event_bindings = {}
    binding = {'script': script,
               'method': args.get('method') or ('on_' + event)}
    og = args.get('owner_guid')
    if og:
        binding['owner_guid'] = og
    elem.event_bindings[event] = binding
    return {'name': name, 'event': event, 'binding': binding}


@command('ui_unbind_event', '移除 UI 元素的声明式事件绑定: {name, event?, canvas?}')
def cmd_ui_unbind_event(win, args):
    name = args.get('name')
    if not name:
        return {'error': '必须传 name='}
    c = _ui_canvas(win, args)
    if c is None:
        return {'error': '找不到 Canvas'}
    elem = c.root.find(name)
    if elem is None:
        return {'error': '找不到 UI 元素: %r' % name}
    eb = getattr(elem, 'event_bindings', None) or {}
    event = args.get('event')
    if event:
        if event in eb:
            del eb[event]
            return {'name': name, 'removed': event}
        return {'name': name, 'error': '该事件未绑定: %r' % event}
    cnt = len(eb)
    eb.clear()
    return {'name': name, 'removed_all': cnt}
