# -*- coding: utf-8 -*-
"""eai.settings_ops — 编辑器设置命令

我负责：settings_get / settings_set（与设置面板同一份 设置.json，含即时生效）。
我不负责：渲染后端配置（render_backend_ops.py）与键位配置（keybind_ops.py）。
"""

from .registry import command, log

@command('settings_get', '读编辑器设置: {key?} (fps_limit/cam_speed/多核 等)')
def cmd_settings_get(win, args):
    import guiloader
    s = guiloader.load_settings('loom')
    return s if not args.get('key') else {args['key']: s.get(args['key'])}


@command('settings_set', '写编辑器设置: {key, value} (与设置面板同一份 设置.json)')
def cmd_settings_set(win, args):
    import guiloader
    key = args.get('key')
    if not key:
        return {'error': '需要 key'}
    val = args.get('value')
    if isinstance(val, str):        # 控制台只能给字符串: 归一成 bool/数字
        low = val.strip().lower()
        if low in ('true', 'yes', 'on'):
            val = True
        elif low in ('false', 'no', 'off'):
            val = False
        else:
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
    s = guiloader.load_settings('loom')
    s[key] = val
    guiloader.save_settings('loom', s)
    # 帧率档位改了要即时生效 (GUI 设置面板同款调用)
    if key == 'fps_limit' and hasattr(win, '_apply_fps_limit'):
        try:
            win._apply_fps_limit(val)
        except Exception as e:
            log('[命令] fps_limit 即时生效失败: %r' % e)
    elif key == 'logic_fps':
        try:
            v = int(val)
            ed = getattr(win, 'editor', None)
            eng = getattr(ed, 'engine', ed) if ed else None
            clk = getattr(eng, '_clock', None)
            if clk is not None and v > 0:
                clk.set_fps(logic_fps=v)
        except Exception as e:
            log('[命令] logic_fps 即时生效失败: %r' % e)
    return {'set': {key: val}, 'type': type(val).__name__}
