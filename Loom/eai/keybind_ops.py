# -*- coding: utf-8 -*-
"""eai.keybind_ops — 键位命令

我负责：key_binding（键位查询/改键，写游戏输入配置）。
我不负责：编辑器设置与渲染后端配置。
"""

from .registry import command

@command('key_binding', '键位: 查询 {action?} / 改键 {action, keys="f"|"f,F10"}'
                          ' (写入游戏配置, 立即生效)')
def cmd_key_binding(win, args):
    """键位查询/改键.

    2026-11-08 批4 (审计 P-04-08):
      ① **动作名白名单** —— 拼错的动作名旧实现会被 rebind_action 静默收下并落盘
         ("幽灵动作"进两份配置), 现在直接拒绝并列出可用动作;
      ② **透传真实结果** —— engine.set_action_binding 已如实返回 ok/saved/error/path
         (第 1 批改), 这里不再包装成"总是成功"; 失败时给 {'error': ...},
         dispatch 会把它变成 ok=False, MCP 层据此判失败。
    """
    ed = win.editor
    bindings = ed.get_action_bindings() if hasattr(ed, 'get_action_bindings') else {}
    action = args.get('action')
    if not action:
        return {'bindings': bindings}
    keys = args.get('keys')
    if keys is None:
        return {'action': action, 'keys': (bindings or {}).get(action)}
    name = str(action).strip()
    if name not in (bindings or {}):
        return {'error': '未知动作: %r (可用: %s)'
                         % (action, ', '.join(sorted(bindings or {})) or '(空)'),
                'action': action, 'available': sorted(bindings or {})}
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split(',') if k.strip()]
    res = ed.set_action_binding(name, keys)
    if isinstance(res, dict) and not res.get('ok', True):
        return {'error': res.get('error') or '改键失败', 'action': name, 'result': res}
    return res
