# -*- coding: utf-8 -*-
"""eai.render_backend_ops — 渲染后端配置命令

我负责：render_api（查询/写入渲染后端配置，重启生效）。
我不负责：编辑器设置（settings_ops.py）与键位（keybind_ops.py）。
"""

from .registry import command

@command('render_api', '渲染后端: 查询 {api?缺省=查} 或 写入配置 {api=vulkan|opengl|auto}'
                          ' (写入后需重启游戏生效)')
def cmd_render_api(win, args):
    ed = win.editor
    api = args.get('api')
    if api:
        return ed.set_render_api(api)
    cur = ed.get_render_api() if hasattr(ed, 'get_render_api') else None
    saved = ed.get_saved_render_api() if hasattr(ed, 'get_saved_render_api') else None
    return {'current': cur, 'saved': saved, 'restart_required': bool(saved and saved != cur)}
