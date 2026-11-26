# -*- coding: utf-8 -*-
"""eai.plugin_ops — 插件命令

我负责：plugins / plugin_button（播放器层插件的命令化入口）。
我不负责：插件加载与生命周期（plugin/ 包）。
"""

from .registry import command

# ====================================================================
# 播放器层插件命令化 (2026-08-27 用户补充): 插件 register_editor_button
# 注册的按钮 = GUI「插件」菜单 + EAI 命令 两条通路, 同一回调闭包执行.
# editor 层插件 (纯开发工具) 不做命令化 (对游戏执行无影响).
# ====================================================================
@command('plugins', '插件与已注册按钮清单 (播放器层插件命令化入口)')
def cmd_plugins(win, args):
    import plugin.loader as plugin_loader
    loaded = plugin_loader.get_loaded()
    btns = []
    for text, cb, pid in plugin_loader.editor_buttons():
        btns.append({'plugin': pid, 'text': text})
    return {'plugins': [{'id': i, 'layer': e['layer'],
                         'kind': e['kind']} for i, e in loaded.items()],
            'buttons': btns}


@command('plugin_button', '运行插件按钮: {plugin, text} (与 GUI 菜单点击等价)')
def cmd_plugin_button(win, args):
    import plugin.loader as plugin_loader
    pid = args.get('plugin')
    text = args.get('text')
    for t, cb, p in plugin_loader.editor_buttons():
        if t == text and (pid is None or p == pid or pid == 'all'):
            try:
                import time as _t
                _t0 = _t.perf_counter()
                cb()
                return {'plugin': p, 'text': t,
                        'ms': round((_t.perf_counter() - _t0) * 1000, 1)}
            except Exception as e:
                return {'error': '插件按钮失败: %r' % e}
    return {'error': '找不到插件按钮: plugin=%s text=%s (可用: %s)'
            % (pid, text, [b['text'] for b in cmd_plugins(win, {})['buttons']])}
