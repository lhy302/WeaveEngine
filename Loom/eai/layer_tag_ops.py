# -*- coding: utf-8 -*-
"""eai.layer_tag_ops — 层级/标签命令

我负责：set_layer / set_tag / get_layer_tag / list_tags / register_tag / list_layers。
我不负责：layer_tag 数据文件实现（layer_tag.py）。
"""

from .commit import _Ambiguous, _commit, _resolve
from .helpers import as_float
from .registry import command

@command('set_layer', '设置物体 Layer: {name?, layer} (0~31)')
def cmd_set_layer(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    if args.get('layer') is None:
        return {'error': '需要 layer (0~31)'}
    lv = int(as_float(args['layer'], -1))
    if lv < 0 or lv > 31:
        return {'error': 'layer must be 0..31, got %r' % (args['layer'],)}
    _commit(ed, kind, obj, '设置 Layer', lambda: setattr(obj, 'layer', lv))
    return {'layer': obj.layer, 'layer_name': ed.layer_name(obj.layer)}


@command('set_tag', '设置物体 Tag: {name?, tag} (未注册自动注册; 非法字符拒绝)')
def cmd_set_tag(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    tg = args.get('tag')
    if not tg:
        return {'error': '需要 tag'}
    if isinstance(tg, str):
        tg = tg.strip()
    import kernels.layer_tag as layer_tag
    ok, reason = layer_tag.validate_tag(tg)
    if not ok:
        return {'error': reason}
    # EAI 宽松语义 (契约 §5.2): 未注册先注册再应用
    if not ed.tag_exists(tg):
        try:
            ed.register_tag(tg)
        except ValueError as e:
            return {'error': str(e)}
    _commit(ed, kind, obj, '设置 Tag', lambda: setattr(obj, 'tag', tg))
    return {'tag': obj.tag}


@command('get_layer_tag', '查询物体 Layer/Tag: {name?}')
def cmd_get_layer_tag(win, args):
    ed = win.editor
    try:
        kind, obj = _resolve(ed, args, kinds=('model',))
    except _Ambiguous as e:
        return {'error': str(e)}
    if obj is None:
        return {'error': '找不到物体: %s (先 object_list 看全部)'
                % (args.get('name') or '(未选中)')}
    return {'layer': obj.layer, 'layer_name': ed.layer_name(obj.layer),
            'tag': obj.tag}


@command('list_tags', '列出所有已注册 Tag')
def cmd_list_tags(win, args):
    import kernels.layer_tag as layer_tag
    return {'tags': layer_tag.get_tags()}


@command('register_tag', '注册新 Tag (幂等): {tag} (非法抛错; 已存在返回 registered=False)'
                   ' (Q-B7-56-2: GUI Tag 下拉与命令行同一注册入口)')
def cmd_register_tag(win, args):
    # Q-B7-56-2 JVM 七步: 分类=GUI 点击命令化; 公共实现已在 SceneQueryMixin
    # .register_tag (scene/query.py, GL/VK 同一函数对象) + kernels/layer_tag 模块;
    # 本命令是薄壳。
    ed = win.editor
    tg = args.get('tag')
    if not tg:
        return {'error': '需要 tag'}
    if isinstance(tg, str):
        tg = tg.strip()
    try:
        created = ed.register_tag(tg)
    except ValueError as e:
        return {'error': str(e)}
    return {'tag': tg, 'registered': bool(created)}


@command('list_layers', '列出所有层编号与层名')
def cmd_list_layers(win, args):
    ed = win.editor
    return {'layers': {str(i): ed.layer_name(i) for i in range(32)}}
