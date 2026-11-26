# -*- coding: utf-8 -*-
"""eai.asset_ops — 资产库命令

我负责：assets / asset_apply / asset_place / asset_save / asset_import /
asset_get / asset_user_override / asset_list / scene_assets_check 与输入路径解析前置。
我不负责：资产库实现（assets/ 包）与 Prefab 命令（prefab_ops.py）。
"""

import os
from .commit import _no_target, _resolve
from .helpers import as_bool, as_float
from .registry import command
from .whitelist import _safe_write_path

# ---------------- beta6 B1: 项目资产库 (Assets/assets.json + guid) ----------------


@command('assets', '资源面板清单 (asset_apply/asset_place 的 type+key 取这里)')
def cmd_assets(win, args):
    # 资源面板每次现扫盘 (_scan_assets), 没有常驻 self.assets 列表 —— 命令
    # 走同一入口, 与面板看到的内容一致.
    return {'assets': [{'type': it['type'], 'key': it['key'],
                        'name': it.get('name')}
                       for it in win.editor._scan_assets()]}


def _asset_of(ed, args):
    """{type,key} -> 资产项 (与资源面板双击/按钮同一 _find_asset 入口)."""
    typ, key = args.get('type'), args.get('key')
    if not typ or not key:
        return None, {'error': '需要 type 与 key (先跑 assets 看清单)'}
    it = ed._find_asset((typ, key))
    if it is None:
        return None, {'error': '找不到资产: (%s, %s)' % (typ, key)}
    return it, None


@command('asset_apply', '材质资产应用到选中: {type, key, name?}')
def cmd_asset_apply(win, args):
    ed = win.editor
    it, err = _asset_of(ed, args)
    if err:
        return err
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    ed._apply_material_asset(it, m)
    return {'applied': args.get('key'), 'to': m.name}


@command('asset_place', '资产放入场景 (视口中心): {type, key}')
def cmd_asset_place(win, args):
    ed = win.editor
    it, err = _asset_of(ed, args)
    if err:
        return err
    ed._asset_drop_to_scene(it, (ed.width / 2, ed.height / 2))
    return {'placed': args.get('key'), 'count': len(ed.models)}


@command('asset_save', '存资产: {what=mesh|material, path?} (检查器两个"存…为资产"; 白名单外拒绝)')
def cmd_asset_save(win, args):
    ed = win.editor
    what = (args.get('what') or 'material').lower()
    p = args.get('path')
    if p:
        ok, full = _safe_write_path(p, 'asset_save', win)
        if not ok:
            return {'error': full}
        p = full
    if what == 'mesh':
        ed._save_mesh_asset(p)
    elif what == 'material':
        ed._save_material_asset(p)
    else:
        return {'error': 'what 只能 mesh|material'}
    return {'saved': what, 'path': p}


def _resolve_asset_input(win, p):
    """资产导入的输入路径: 绝对 / 引擎目录相对 / 场景目录相对 三种写法统一。"""
    if not p:
        return None
    p = str(p)
    if os.path.isabs(p):
        return p
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cand = os.path.join(_root, p)
    if os.path.exists(cand):
        return cand
    try:
        ed = getattr(win, 'editor', None)
        if ed is not None:
            cand2 = os.path.join(ed._scene_dir(), p)
            if os.path.exists(cand2):
                return cand2
    except Exception:
        pass
    return cand


@command('asset_import',
         '导入资产到项目 Assets/ (贴图/六面图/材质): '
         '{type=texture|cubemap|material, path?, paths=[6图]?, name?}')
def cmd_asset_import(win, args):
    """beta6 B1: 资产导入（复制进项目 + 登记 guid）。

    失败一律 {'ok': False, 'error': reason}；成功返回 guid（场景引用只写 guid）。
    """
    ed = win.editor
    if getattr(ed, 'is_playing', False):
        return {'error': '播放中不允许导入资产（请先停止播放）'}
    kind = str(args.get('type') or args.get('kind') or 'texture').strip().lower()
    name = args.get('name')
    if kind == 'cubemap':
        paths = args.get('paths')
        if isinstance(paths, str):
            paths = [x for x in paths.split(',') if x.strip()]
        if not isinstance(paths, (list, tuple)) or len(paths) != 6:
            return {'error': 'type=cubemap 需要 paths=6 个路径 (px,nx,py,ny,pz,nz)'}
        paths = [_resolve_asset_input(win, x) for x in paths]
        guid, created, why = ed.asset_import(kind='cubemap', paths=paths, name=name)
    elif kind == 'material':
        guid, created, why = ed.asset_import(kind='material', name=name)
    elif kind == 'texture':
        p = _resolve_asset_input(win, args.get('path'))
        if not p:
            return {'error': 'type=texture 需要 path'}
        if not os.path.isfile(p):
            return {'error': '文件不存在: %s' % (p,)}
        imp = {}
        for k in ('wrap', 'filter_mode', 'compression'):
            if args.get(k) is not None:
                imp[k] = args[k]
        if args.get('max_size') is not None:
            imp['max_size'] = int(as_float(args.get('max_size'), 0))
        if args.get('aniso') is not None:
            imp['aniso'] = as_float(args.get('aniso'), 1.0)
        if args.get('mipmaps') is not None:
            imp['mipmaps'] = as_bool(args.get('mipmaps'), True)
        guid, created, why = ed.asset_import(path=p, kind='texture', name=name,
                                             import_settings=imp)
    else:
        return {'error': 'type 只能 texture|cubemap|material (收到 %r)' % (kind,)}
    if guid is None:
        return {'error': why or '资产导入失败'}
    ctx = ed._asset_context()
    return {'guid': guid, 'created': bool(created), 'type': kind,
            'name': name, 'project': getattr(ctx, 'root', None),
            'warning': why,
            'warnings': list(getattr(ctx, 'warnings', None) or [])}


@command('asset_get', '读资产条目 + 解析结果 (valid/reason): {guid}')
def cmd_asset_get(win, args):
    ed = win.editor
    ctx = ed._asset_context()
    guid = args.get('guid')
    if not guid:
        return {'error': '需要 guid'}
    if ctx is None:
        return {'guid': guid, 'valid': False,
                'reason': '当前项目没有资产库（缺 Assets/assets.json）'}
    entry = ctx.entry(guid)
    if entry is None:
        return {'guid': guid, 'valid': False, 'reason': '资产不存在'}
    path, _e, ok, why = ctx.resolve(guid)
    delta = (ctx.user_delta or {}).get(guid)
    try:
        eff = ctx._import_settings(entry, None, guid)
    except Exception:
        eff = entry.get('import')
    return {'guid': guid, 'valid': bool(ok), 'reason': why,
            'type': entry.get('type'), 'name': entry.get('name'),
            'src': entry.get('src'),
            'path': os.path.relpath(path, ctx.root) if path else None,
            'import': entry.get('import'),
            'user_delta': (delta if isinstance(delta, dict) else None),
            'effective_import': eff, 'project': ctx.root}


@command('asset_user_override',
         '用户层资产覆盖（本机 delta，不随项目共享）: '
         '{guid, src?, wrap?/filter_mode?/aniso?/max_size?/mipmaps?/compression?, clear?}')
def cmd_asset_user_override(win, args):
    """F-02: 用户层 delta 的唯一写入口（旧实现只有读、没有 writer -> 死代码）。"""
    import assets.assets as loom_assets
    ed = win.editor
    root = ed._project_root()
    if root is None:
        return {'error': '当前项目没有资产库（缺 Assets/assets.json）'}
    guid = args.get('guid')
    if not guid:
        return {'error': '需要 guid'}
    if args.get('clear'):
        ok, why = loom_assets.clear_user_delta(root, guid)
        if not ok:
            return {'error': why}
        return {'guid': guid, 'cleared': True,
                'user_index': loom_assets.user_index_path(root)}
    imp = {}
    for k in ('wrap', 'filter_mode', 'compression'):
        if args.get(k) is not None:
            imp[k] = args[k]
    if args.get('mipmaps') is not None:
        imp['mipmaps'] = as_bool(args.get('mipmaps'), True)
    if args.get('max_size') is not None:
        imp['max_size'] = int(as_float(args.get('max_size'), 0))
    if args.get('aniso') is not None:
        imp['aniso'] = as_float(args.get('aniso'), 1.0)
    ok, why = loom_assets.write_user_delta(root, guid, src=args.get('src'),
                                           import_settings=(imp or None))
    if not ok:
        return {'error': why}
    ctx = ed._asset_context()
    delta = (getattr(ctx, 'user_delta', None) or {}).get(guid)
    eff = None
    try:
        entry = ctx.entry(guid) if ctx else None
        if entry is not None:
            eff = ctx._import_settings(entry, None, guid)
    except Exception:
        eff = None
    return {'guid': guid, 'user_index': loom_assets.user_index_path(root),
            'delta': (delta if isinstance(delta, dict) else None),
            'effective_import': eff}


@command('asset_list', '项目资产清单 (含逐条 valid/reason): {type?}')
def cmd_asset_list(win, args):
    """P1-2: 必须区分「缺文件 / 文件在但部分坏 / 完全不可用」三种状态。"""
    import assets.assets as loom_assets
    ed = win.editor
    root = ed._project_root()
    if root is None:
        return {'assets': [], 'project': None, 'valid': False, 'state': 'missing',
                'reason': '当前项目没有资产库（缺 Assets/assets.json）'}
    st = loom_assets.inspect_index(root)
    if st['state'] in ('corrupt', 'invalid'):
        return {'assets': [], 'project': root, 'valid': False,
                'state': st['state'], 'reason': st['reason'],
                'warnings': st.get('warnings') or []}
    ctx = ed._asset_context()
    if ctx is None:
        return {'assets': [], 'project': root, 'valid': False,
                'state': st['state'], 'reason': st['reason']}
    want = args.get('type')
    out = []
    for gid, e in sorted(ctx.entries().items()):
        if want and e.get('type') != want:
            continue
        path, _e, ok, why = ctx.resolve(gid)
        out.append({'guid': gid, 'type': e.get('type'), 'name': e.get('name'),
                    'src': e.get('src'), 'valid': bool(ok), 'reason': why})
    return {'project': ctx.root, 'count': len(out), 'assets': out,
            'valid': True, 'state': st['state'], 'reason': st.get('reason'),
            'warnings': st.get('warnings') or []}


@command('scene_assets_check',
         '场景资产体检: 本次加载记录的引用问题 (valid/reason)，对齐 skybox_get 口径')
def cmd_scene_assets_check(win, args):
    import sceneio
    import assets.assets as loom_assets
    ed = win.editor
    errs = sceneio.asset_errors(ed)          # 含天空盒/相机天空盒（P-05 修）
    root = ed._project_root()
    if root is None:
        st = {'state': 'missing', 'reason': '当前项目没有资产库（缺 Assets/assets.json）'}
    else:
        st = loom_assets.inspect_index(root)
    bad_index = st.get('state') in ('corrupt', 'invalid')
    return {'ok': (not errs) and not bad_index,
            'count': len(errs),
            'errors': [{'where': w, 'guid': g, 'reason': r} for (w, g, r) in errs],
            'project': root,
            'index': st.get('state'), 'index_reason': st.get('reason'),
            'kept': sceneio.asset_refs_kept(ed),
            'notice': sceneio.asset_issue_notice(ed, '体检')}
