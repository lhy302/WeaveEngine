# -*- coding: utf-8 -*-
"""eai.query_ops — 查询/射线命令

我负责：raycast / raycast_all / raycast_screen 与对象查找 find_by_name /
find_all_by_name / find_by_script（含 _model_brief 响应整形）。
我不负责：射线求解与场景查询实现（scene/query.py）。
"""

from .helpers import as_float
from .registry import command
from .target import _find_model_by_name

# ================= 2026-10-18 射线检测命令 =================

# ---- 2026-10-18 阶段1档序8 对象查找（用户拍板 1=C 双 API / 2=A 物体列表）----


@command('raycast', '射线检测: {ox,oy,oz, dx,dy,dz, max_dist?, backend?} '
                     '返回最近命中 {hit: {name, distance, point} | null}')
def cmd_raycast(win, args):
    ed = win.editor
    try:
        ox = float(args['ox']); oy = float(args['oy']); oz = float(args['oz'])
        dx = float(args['dx']); dy = float(args['dy']); dz = float(args['dz'])
    except (KeyError, ValueError, TypeError):
        return {'error': '需要 ox/oy/oz/dx/dy/dz 六个数值参数'}
    max_dist = float(as_float(args.get('max_dist', 1000.0), 1000.0))
    backend = str(args.get('backend', 'auto'))
    layer_mask = args.get('layer_mask')
    if layer_mask is not None:
        try:
            layer_mask = int(layer_mask)
        except (TypeError, ValueError):
            return {'error': 'layer_mask 必须是整数位掩码'}
    ignore = None
    if args.get('ignore'):
        ignore = _find_model_by_name(ed, args['ignore'])
    r = ed.raycast((ox, oy, oz), (dx, dy, dz),
                   max_dist=max_dist, ignore_model=ignore, backend=backend,
                   layer_mask=layer_mask)
    if r is None:
        return {'hit': None}
    model, dist, pt = r
    return {'hit': {'name': model.name,
                    'distance': round(float(dist), 4),
                    'point': [round(p, 4) for p in pt]}}


@command('raycast_all', '射线检测（全部命中）: 参数同上，返回 hits 列表按距离升序')
def cmd_raycast_all(win, args):
    ed = win.editor
    try:
        ox = float(args['ox']); oy = float(args['oy']); oz = float(args['oz'])
        dx = float(args['dx']); dy = float(args['dy']); dz = float(args['dz'])
    except (KeyError, ValueError, TypeError):
        return {'error': '需要 ox/oy/oz/dx/dy/dz 六个数值参数'}
    max_dist = float(as_float(args.get('max_dist', 1000.0), 1000.0))
    backend = str(args.get('backend', 'auto'))
    layer_mask = args.get('layer_mask')
    if layer_mask is not None:
        try:
            layer_mask = int(layer_mask)
        except (TypeError, ValueError):
            return {'error': 'layer_mask 必须是整数位掩码'}
    rs = ed.raycast_all((ox, oy, oz), (dx, dy, dz),
                        max_dist=max_dist, backend=backend,
                        layer_mask=layer_mask)
    return {'hits': [{'name': m.name,
                      'distance': round(float(d), 4),
                      'point': [round(p, 4) for p in pt]}
                     for m, d, pt in rs]}


@command('raycast_screen', '屏幕坐标反投影射线: {px, py, max_dist?, backend?} '
                            '返回最近命中（与鼠标点选等价）')
def cmd_raycast_screen(win, args):
    ed = win.editor
    if 'px' not in args or 'py' not in args:
        return {'error': '需要 px/py（屏幕像素坐标）'}
    px = float(as_float(args['px'])); py = float(as_float(args['py']))
    max_dist = float(as_float(args.get('max_dist', 1000.0), 1000.0))
    backend = str(args.get('backend', 'auto'))
    layer_mask = args.get('layer_mask')
    if layer_mask is not None:
        try:
            layer_mask = int(layer_mask)
        except (TypeError, ValueError):
            return {'error': 'layer_mask 必须是整数位掩码'}
    r = ed.raycast_screen(px, py, max_dist=max_dist, backend=backend,
                          layer_mask=layer_mask)
    if r is None:
        return {'hit': None}
    model, dist, pt = r
    return {'hit': {'name': model.name,
                    'distance': round(float(dist), 4),
                    'point': [round(p, 4) for p in pt]}}


def _model_brief(ed, m):
    """返回物体的 EAI 响应格式（name + models 下标，避开 guid 可能为 None 的情况）。"""
    try:
        idx = ed.models.index(m)
    except ValueError:
        idx = -1
    return {'name': getattr(m, 'name', ''), 'index': int(idx)}


@command('find_by_name', '按物体名查找首个匹配: {model} 返回 {found: {...} | null}')
def cmd_find_by_name(win, args):
    ed = win.editor
    name = args.get('model')
    if not name:
        return {'error': '需要 model（物体名）'}
    m = ed.find_by_name(str(name))
    return {'found': None if m is None else _model_brief(ed, m)}


@command('find_all_by_name', '按物体名查找所有匹配: {model} 返回 {found: [...]}')
def cmd_find_all_by_name(win, args):
    ed = win.editor
    name = args.get('model')
    if not name:
        return {'error': '需要 model（物体名）'}
    ms = ed.find_all_by_name(str(name))
    return {'found': [_model_brief(ed, m) for m in ms]}


@command('find_by_script', '查找挂有指定脚本的物体: {script_id} 返回 {found: [...]}')
def cmd_find_by_script(win, args):
    ed = win.editor
    sid = args.get('script_id')
    if not sid:
        return {'error': '需要 script_id（脚本 id）'}
    ms = ed.find_by_script(str(sid))
    return {'found': [_model_brief(ed, m) for m in ms]}
