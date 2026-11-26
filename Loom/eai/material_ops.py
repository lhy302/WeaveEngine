# -*- coding: utf-8 -*-
"""eai.material_ops — 材质命令

我负责：materials / set_material / material_new / set_texture / set_pbr /
set_lod / set_env。
我不负责：材质数据结构与 GPU 上传（components/material 与渲染后端）。
"""

import os
from .commit import _no_target, _resolve
from .helpers import as_bool, as_float
from .registry import command

@command('materials', '材质列表 (索引/名字; set_material 用)')
def cmd_materials(win, args):
    ed = win.editor
    return {'materials': [{'index': i, 'name': mt.name}
                          for i, mt in enumerate(ed.materials)]}


@command('set_material', '换材质: {name?, index 或 material=材质名} (共享引用语义)')
def cmd_set_material(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mats = ed.materials
    if not mats:
        return {'error': '场景没有材质 (先 material_new)'}
    key = args.get('material')
    if key is not None:
        idx = next((i for i, mt in enumerate(mats) if mt.name == key), None)
        if idx is None:
            return {'error': '找不到材质: %s (可用: %s)'
                    % (key, [mt.name for mt in mats])}
    else:
        idx = int(as_float(args.get('index'), -1))
        if not 0 <= idx < len(mats):
            return {'error': 'index 越界: %s (材质数 %d)' % (args.get('index'), len(mats))}
    ed.commit_model(m, "换材质",
                    lambda: setattr(m.renderer, 'material', mats[idx]))
    return {'name': m.name, 'material': mats[idx].name, 'index': idx}


@command('material_new', '新建材质并挂给目标: {name?} (同检查器[＋新建材质])')
def cmd_material_new(win, args):
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    ed.new_material(m)
    return {'name': m.name,
            'material': getattr(m.renderer.material, 'name', None),
            'count': len(ed.materials)}


@command('set_texture', '设物体材质的颜色贴图: {name?, path=图片路径} 或 path="" 清除')
def cmd_set_texture(win, args):
    """M36 贴图: 从图片文件加载 albedo 贴图并绑到目标物体的材质上。
    path 为空 -> 清除贴图。加载失败返回 error (不改变原状态)。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    path = args.get('path')
    mat = m.renderer.material
    if mat is None:
        return {'error': '物体无材质'}
    if path is None or path == '':
        def _clear_alb():
            setattr(mat, 'albedo', None)
            # Q-B1-1=A: 用户显式清空 = 真正移除（连"保留的失效引用"一起清）
            try:
                import sceneio as _sio
                _sio.clear_asset_slot(mat, 'albedo')
            except Exception:
                pass
        ed.commit_model(m, "清除贴图", _clear_alb)
        return {'name': m.name, 'material': mat.name, 'albedo': None}
    # 相对路径基于引擎目录 (Q-B7-38-1 包化: eai/ 的上一级)
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = path if os.path.isabs(path) else os.path.join(_root, path)
    if not os.path.isfile(ap):
        return {'error': '贴图文件不存在: %s' % (ap,)}
    # beta6 B1: 有项目资产库 -> 导入 Assets/ 并登记 guid（场景只存 guid）
    _ctx = None
    try:
        _ctx = ed._asset_context()
    except Exception:
        _ctx = None
    if _ctx is not None:
        _guid, _created, _why = _ctx.import_texture(
            ap, name=os.path.basename(ap),
            import_settings={'wrap': args.get('wrap', 'repeat'),
                             'filter_mode': args.get('filter_mode', 'trilinear'),
                             'aniso': as_float(args.get('aniso'), 1.0),
                             'max_size': int(as_float(args.get('max_size'), 0)),
                             'compression': args.get('compression', 'none')})
        if _guid is None:
            return {'error': '贴图导入失败: %s' % (_why,)}
        tex, _ok, _why2 = _ctx.texture(_guid)
        if tex is None:
            return {'error': '贴图解码失败: %s' % (_why2,)}
    else:
        try:
            from assets.texture import Texture
            tex = Texture.from_file(
                ap, name=os.path.basename(ap),
                wrap=args.get('wrap', 'repeat'),
                filter_mode=args.get('filter_mode', 'trilinear'),
                aniso=as_float(args.get('aniso'), 1.0),
                max_size=int(as_float(args.get('max_size'), 0)),
                compression=args.get('compression', 'none'))
        except Exception as e:
            return {'error': '贴图加载失败: %r' % (e,)}
    ed.commit_model(m, "设贴图", lambda: setattr(mat, 'albedo', tex))
    return {'name': m.name, 'material': mat.name,
            'albedo': tex.name, 'size': [tex.width, tex.height],
            'guid': tex.guid, 'managed': _ctx is not None}


@command('set_pbr', '设材质 PBR: {name?, metallic?, roughness?|smoothness?, on?} (对标 Unity Standard Shader)')
def cmd_set_pbr(win, args):
    """M36 PBR: 设金属度/粗糙度。smoothness 为 Unity 风格 (smoothness=1-roughness)。
    给了 metallic/roughness/smoothness 任一 -> 自动启用 PBR; on 可显式开关。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mat = m.renderer.material
    if mat is None:
        return {'error': '物体无材质'}

    def apply():
        if args.get('metallic') is not None:
            mat.metallic = as_float(args.get('metallic'), 0.0)
        if args.get('roughness') is not None:
            mat.roughness = as_float(args.get('roughness'), 0.5)
        elif args.get('smoothness') is not None:
            mat.roughness = 1.0 - as_float(args.get('smoothness'), 0.5)
        if args.get('on') is not None:
            mat.pbr = as_bool(args.get('on'))
        elif any(args.get(k) is not None
                 for k in ('metallic', 'roughness', 'smoothness')):
            mat.pbr = True
    ed.commit_model(m, "设 PBR", apply)
    return {'name': m.name, 'material': mat.name, 'metallic': mat.metallic,
            'roughness': mat.roughness, 'pbr': mat.pbr}


@command('set_lod', '设 LOD: {name?, bias?, screen?, on?} (对标 Unity LODGroup; 为基元自动生成低精度)')
def cmd_set_lod(win, args):
    """M36 LOD (对标 Unity LODGroup): 按屏幕占比切换网格精度。
    sphere 自动生成半精度低模; on=False 关闭 LOD; bias 为 LOD 偏移 (大=更高质量)。

    2026-11-08 批4 (审计 P-04-07 / 裁决 Q5=A):
      ① **先校验后改**: 非 sphere 又不关 LOD 时直接拒绝, 一个字段都不改
         (旧实现先写 lod_bias 再报 error -> 调用方按失败处理, 状态已经变了);
      ② **bias 与 levels 一起进 commit_model**: 旧实现直写 r.lod_bias 绕过撤销栈,
         导致 LOD 偏移不可撤销 (Q5=A 要求的"LOD 可撤销"实际只有一半)。
    """
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    r = m.renderer
    bias = None
    if args.get('bias') is not None:
        bias = max(0.1, as_float(args.get('bias'), 1.0))
    want_off = args.get('on') is not None and not as_bool(args.get('on'))
    prim = getattr(m, 'primitive', None)
    params = dict(getattr(m, 'params', None) or {})
    if not want_off and prim != 'sphere':
        # 校验先行: 拒绝时保持"命令没生效"的常规定义 (P-04-07 ①)
        return {'name': m.name,
                'error': '仅 sphere 基元支持自动 LOD (其它网格无细分可降)',
                'primitive': prim}
    lo = None
    thr = max(0.0, min(1.0, as_float(args.get('screen'), 0.1)))
    if not want_off:
        import mathlib.mesh as _mesh
        lo = _mesh.create_sphere(
            params.get('radius', 0.5),
            max(3, int(params.get('stacks', 14)) // 2),
            max(6, int(params.get('slices', 28)) // 2))

    def _apply():
        if bias is not None:
            r.lod_bias = bias
        if want_off:
            r.lod_screen_levels = None
            r.lod_levels = None
            r._lod_cur = None
        else:
            r.lod_screen_levels = [(thr, m.mesh), (0.0, lo)]

    ed.commit_model(m, "关闭 LOD" if want_off else "设 LOD", _apply)   # P-04-07 ②
    if want_off:
        return {'name': m.name, 'lod': None, 'bias': r.lod_bias}
    return {'name': m.name, 'mode': 'screen', 'threshold': thr,
            'levels': 2, 'hi_verts': len(m.mesh.vertices),
            'lo_verts': len(lo.vertices), 'bias': r.lod_bias}


@command('set_env', '设材质环境反射贴图: {name?, paths=[6图] | color=#RRGGBB} (对标 Unity Reflection Probe)')
def cmd_set_env(win, args):
    """M36 环境反射: 从 6 面图片 (px,nx,py,ny,pz,nz) 或纯色创建 cubemap 并绑到材质。
    paths 空且无 color -> 清除环境贴图。"""
    ed = win.editor
    kind, m = _resolve(ed, args, ('model',))
    if m is None:
        return _no_target(('model',))
    mat = m.renderer.material
    if mat is None:
        return {'error': '物体无材质'}
    paths = args.get('paths')
    color = args.get('color')
    if not paths and not color:
        def _clear_env():
            setattr(mat, 'env_map', None)
            try:
                import sceneio as _sio
                _sio.clear_asset_slot(mat, 'env_map')
            except Exception:
                pass
        ed.commit_model(m, "清除环境贴图", _clear_env)
        return {'name': m.name, 'material': mat.name, 'env_map': None}
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _ctx = None
    try:
        _ctx = ed._asset_context()
    except Exception:
        _ctx = None
    try:
        from assets.cubemap import Cubemap
        if paths:
            if isinstance(paths, str):
                paths = [p for p in paths.split(',') if p.strip()]
            ap = [p if os.path.isabs(p) else os.path.join(_root, p) for p in paths]
            # beta6 B1: 项目内 -> 六面图登记为 cubemap 资产（场景只存 guid）
            if _ctx is not None:
                _g, _created, _why = _ctx.import_cubemap(ap, name='环境贴图')
                if _g is None:
                    return {'error': '环境贴图导入失败: %s' % (_why,)}
                cube, _ok, _why2 = _ctx.cubemap(_g)
                if cube is None:
                    return {'error': '环境贴图加载失败: %s' % (_why2,)}
            else:
                cube = Cubemap.from_files(ap, name='环境贴图')
        else:
            cube = Cubemap.from_solid(color, size=16, name='环境贴图')
    except Exception as e:
        return {'error': '环境贴图创建失败: %r' % (e,)}
    ed.commit_model(m, "设环境贴图", lambda: setattr(mat, 'env_map', cube))
    return {'name': m.name, 'material': mat.name, 'env_map': cube.name,
            'size': cube.size, 'guid': cube.guid, 'managed': _ctx is not None}
