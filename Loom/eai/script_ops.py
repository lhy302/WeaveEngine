# -*- coding: utf-8 -*-
"""eai.script_ops — 脚本命令

我负责：script_add / script_remove / script_reload / scripts / script_var /
send_message（脚本挂载与脚本间通信）。
我不负责：脚本解释器与热重载实现（script/ 包）。
"""

import sys
from .commit import _no_target, _resolve
from .helpers import as_float
from .registry import command
from .target import _find

@command('script_add', '给目标挂脚本: {sid, target} (缺省当前选中)')
def cmd_script_add(win, args):
    ed = win.editor
    sid = args.get('sid')
    if not sid:
        return {'error': '必须传 sid='}
    target = args.get('target')
    if target:
        kind, obj, i = _find(ed, target)
        if obj is None:
            return {'error': '找不到: %s' % target}
    else:
        obj = ed._selected() or ed._selected_light() or ed._selected_camera()
    if obj is None:
        return {'error': '没有选中物体'}
    # 2026-10-19 P0-2 修复: add_script 现在会抛 ValueError（脚本不存在），
    # 捕获后返回 error dict，不崩、不留坏组件。
    # 同时透传 vars（P1-1: MCP script_vars 一路带到引擎）。
    try:
        ed.add_script(obj, sid, extra_vars=args.get('vars'))
    except ValueError as e:
        return {'error': str(e)}
    return {'sid': sid, 'target': getattr(obj, 'name', None)}


@command('script_remove', '移除脚本: {name?, index} (检查器脚本行 × 按钮)')
def cmd_script_remove(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model', 'light', 'camera'))
    if m is None:
        return _no_target(('model',))
    i = int(as_float(args.get('index'), -1))
    if not 0 <= i < len(getattr(m, 'scripts', [])):
        return {'error': 'index 越界: %s (脚本数 %d)'
                % (args.get('index'), len(getattr(m, 'scripts', [])))}
    sid = m.scripts[i].script_id
    ed.remove_script(m, i)
    return {'name': m.name, 'removed': sid}


@command('script_reload', '热重载游戏脚本目录 (改完脚本不必重启编辑器) '
                           '{dir? 缺省=引擎旁 scripts/}')
def cmd_script_reload(win, args):
    """2026-10-19 P0-2: 重新扫描脚本目录，让新写的 .py/.lua 即时可挂载。

    之前 load_script_dir 只在引擎启动时调一次，Agent 每改一次脚本都要重启编辑器，
    整个"写脚本->挂载->播放->看结果->改"闭环无法连续迭代。
    """
    import script.scripts as _scripts
    import os as _os
    target_dir = args.get('dir')
    if not target_dir:
        # 默认: 引擎目录旁的 scripts/（与 engine.py:366 一致）
        target_dir = _os.path.join(
            _os.path.dirname(_os.path.abspath(sys.argv[0])), 'scripts')
    if not _os.path.isdir(target_dir):
        return {'error': '脚本目录不存在: %s' % target_dir}
    before = set(_scripts.SCRIPTS.keys())
    try:
        count = _scripts.load_script_dir(target_dir)
    except Exception as e:
        return {'error': '热重载失败: %r' % e}
    after = set(_scripts.SCRIPTS.keys())
    return {
        'dir': target_dir,
        'loaded': count,
        'added': sorted(after - before),
        'total': len(_scripts.SCRIPTS),
    }


@command('scripts', '列出所有已注册的游戏脚本 (id + 名称 + 参数)')
def cmd_scripts(win, args):
    """2026-10-19 P0-2: 供 Agent 在 script_add 前查询有效 id，
    避免再猜一个不存在的 id 导致挂载失败。"""
    import script.scripts as _scripts
    out = []
    for sid, cls in _scripts.SCRIPTS.items():
        params = []
        for p in getattr(cls, 'params', []):
            # params 元组: (key, label, default, *extra)
            if isinstance(p, (tuple, list)) and len(p) >= 3:
                params.append({'key': p[0], 'label': p[1], 'default': p[2]})
        out.append({
            'id': sid,
            'name': getattr(cls, 'name', sid),
            'params': params,
        })
    return {'total': len(out), 'scripts': out}


@command('script_var', '改脚本参数 (一步撤销): {name?, index, key, value}')
def cmd_script_var(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model', 'light', 'camera'))
    if m is None:
        return _no_target(('model',))
    i = int(as_float(args.get('index'), -1))
    if not 0 <= i < len(getattr(m, 'scripts', [])):
        return {'error': 'index 越界: %s' % args.get('index')}
    key = args.get('key')
    if not key:
        return {'error': '需要 key (参数名; inspect 可看已有参数)'}
    v = as_float(args.get('value'), 0.0)
    # active=False = 一次到位 (对齐 GUI 松手提交)。
    # Q-B7-56-2 修正: set_script_var(active=False) 只有在 GUI 会话协议预先登记
    # 快照 (kkey 已在 _insp_undo_start) 时才压栈 —— 命令行独立调用的 kkey 永远
    # 不在会话表里, 撤销从未发生 (与本命令"一步撤销"的帮助不符, 实测抓到)。
    # 包一层 commit_model (快照->写->差异数据才压栈) 保证命令一次写 = 一步撤销;
    # 写入仍走 set_script_var 单源。
    ed.commit_model(m, '脚本参数', lambda: ed.set_script_var(
        m, i, key, v, False, 'cmd.svar.%d.%s' % (i, key)))
    return {'name': m.name, 'index': i, key: m.scripts[i].script_vars.get(key)}


@command('send_message', '脚本间通信: {model, method, args?} 在指定物体所有脚本上调用方法名 '
                         '返回 {called: N}（成功调用脚本数）')
def cmd_send_message(win, args):
    ed = win.editor
    model_name = args.get('model')
    method = args.get('method')
    if not model_name or not method:
        return {'error': '需要 model（物体名）和 method（方法名）'}
    call_args = args.get('args', [])
    if not isinstance(call_args, (list, tuple)):
        return {'error': 'args 必须是数组'}
    try:
        n = ed.send_message_to_name(str(model_name), str(method), *call_args)
    except Exception as e:
        return {'error': '调用失败: %r' % e}
    return {'called': int(n)}
