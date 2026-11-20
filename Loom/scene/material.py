# -*- coding: utf-8 -*-
"""scene/material.py — **材质资产**解析/发射（B2 自 sceneio.py 拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  _emit_material / _warn_dup_guid（横幅注释随 asset 段）/ _apply_material_texture /
  _CUR_BASE_DIR / _resolve_scene_rel / _apply_material_env / _emit_material_refs /
  _apply_materials / _is_default_material / _drop_orphan_default_materials

_CUR_BASE_DIR 是本模块全局（唯一读者 _resolve_scene_rel）——「当前正在加载的
场景目录」密闭夹具基准；写方 = scene/io.scene_from_dict 与 scene_driver VK 装配。
"""
import os

from scene.asset import (_clear_slot_ref, _cubemap_ref_dict, _keep_slot_ref,
                         _texture_ref_dict, _warn_dup_guid, generate_guid,
                         record_asset_error)




# ---------------- 材质资产 (M23) ----------------

def _emit_material(mat, ctx=None):
    """Material -> dict (v11: 项目托管贴图/立方图**只写 guid**；未托管沿用旧字段)

    ctx 为 None（无项目资产库）时行为与 beta5 完全一致 —— 这是兼容闸门。
    """
    d = {"id": mat.guid, "name": mat.name,
         "color": mat.color, "saturation": mat.saturation,
         "metallic": getattr(mat, 'metallic', 0.0),
         "roughness": getattr(mat, 'roughness', 0.5),
         "pbr": getattr(mat, 'pbr', False)}
    kept = getattr(mat, '_asset_ref_slots', None)
    kept = kept if isinstance(kept, dict) else {}

    def _slot(key, attr):
        obj = getattr(mat, attr, None)
        if obj is not None:
            return (_texture_ref_dict(obj, ctx) if attr != 'env_map'
                    else _cubemap_ref_dict(obj, ctx))
        ref = kept.get(key)
        return dict(ref) if isinstance(ref, dict) and ref else None

    for key, attr in (('albedo', 'albedo'), ('normal_map', 'normal_map'),
                      ('env_map', 'env_map')):
        ref = _slot(key, attr)
        if ref is not None:
            d[key] = ref
    return d



def _apply_material_texture(engine, mat, slot, ref, ctx):
    """材质贴图槽: guid 优先（项目资产）；旧 path 兼容读 + 告警；失败一律有声。

    Q-B1-1=A: **任何失败都保留原引用**（_keep_slot_ref），保存时原样写回，
    绝不因为"这次没解析出来"就把 guid 从场景里抹掉。
    """
    if not isinstance(ref, dict) or not ref:
        return
    guid = ref.get('guid')
    try:
        if ctx is not None and guid and ctx.owns(guid, 'texture'):
            tex, ok, why = ctx.texture(guid, ref)
            if tex is not None:
                setattr(mat, slot, tex)
                _clear_slot_ref(mat, slot)
            else:
                _keep_slot_ref(mat, slot, ref)
            if why:
                record_asset_error(engine, 'materials.%s' % slot, guid, why)
            return
        path = _resolve_scene_rel(ref.get('path'), ctx) if ref.get('path') else None
        if path:
            record_asset_error(engine, 'materials.%s' % slot, guid,
                               '旧路径引用（beta6 兼容期；建议 asset_import 迁移为 guid）: %s'
                               % (path,))
            try:
                from loom_texture import Texture
                tex = Texture.from_file(
                    path, name=ref.get('name'), guid=guid,
                    mipmaps=ref.get('mipmaps', True),
                    wrap=ref.get('wrap', 'repeat'),
                    filter_mode=ref.get('filter_mode', 'trilinear'),
                    aniso=ref.get('aniso', 1.0),
                    max_size=ref.get('max_size', 0),
                    compression=ref.get('compression', 'none'))
                setattr(mat, slot, tex)
                _clear_slot_ref(mat, slot)
            except Exception as e:
                _keep_slot_ref(mat, slot, ref)
                record_asset_error(engine, 'materials.%s' % slot, guid,
                                   '贴图加载失败 (%r): %s' % (e, path))
            return
        if guid:
            _keep_slot_ref(mat, slot, ref)
            if ctx is not None:
                record_asset_error(engine, 'materials.%s' % slot, guid,
                                   '资产 guid 未在项目索引中（可能被删/换了项目）: %s'
                                   % (guid,))
            else:
                record_asset_error(engine, 'materials.%s' % slot, guid,
                                   '只有 guid 但没有项目资产索引（缺 Assets/assets.json）')
    except Exception as e:
        # 资产层任何异常都不许穿透到"已清空场景"之后（F7 / 两端一致）
        _keep_slot_ref(mat, slot, ref)
        record_asset_error(engine, 'materials.%s' % slot, guid,
                           '资产解析异常 (%r)' % (e,))



# 当前正在加载的场景目录（场景内相对资源路径的解析基准）。
# 有资产上下文时用 ctx.root；没有项目资产库（如 tests/ab_scenes 这种密闭夹具）时用这个。
_CUR_BASE_DIR = None



def _resolve_scene_rel(p, ctx=None):
    """2026-11-11: 旧式相对路径按**场景目录**解析（ctx.root = 场景目录）。

    密闭夹具（tests/ab_scenes/assets/...）靠这条生效；绝对路径原样返回。
    """
    try:
        s = str(p)
    except Exception:
        return p
    if not s or os.path.isabs(s):
        return s
    root = getattr(ctx, 'root', None) or _CUR_BASE_DIR
    if root:
        return os.path.join(root, s.replace('/', os.sep))
    return s



def _apply_material_env(engine, mat, ref, ctx):
    """材质环境贴图: guid 优先；旧 6 面 paths / 纯色兼容读。失败保留原引用。"""
    if not isinstance(ref, dict) or not ref:
        return
    guid = ref.get('guid')
    try:
        if ctx is not None and guid and ctx.owns(guid, 'cubemap'):
            cube, ok, why = ctx.cubemap(guid, ref)
            if cube is not None:
                mat.env_map = cube
                _clear_slot_ref(mat, 'env_map')
            else:
                _keep_slot_ref(mat, 'env_map', ref)
            if why:
                record_asset_error(engine, 'materials.env_map', guid, why)
            return
        from loom_cubemap import Cubemap
        if ref.get('paths'):
            record_asset_error(engine, 'materials.env_map', guid,
                               '旧路径引用（6 面路径，beta6 兼容期；建议 asset_import）')
            try:
                mat.env_map = Cubemap.from_files(
                    [_resolve_scene_rel(p, ctx) for p in ref['paths']],
                    name=ref.get('name'), guid=guid)
                _clear_slot_ref(mat, 'env_map')
            except Exception as e:
                _keep_slot_ref(mat, 'env_map', ref)
                record_asset_error(engine, 'materials.env_map', guid,
                                   '环境贴图加载失败 (%r)' % (e,))
        elif ref.get('solid_color'):
            mat.env_map = Cubemap.from_solid(tuple(ref['solid_color']),
                                             name=ref.get('name'), guid=guid)
            _clear_slot_ref(mat, 'env_map')
        elif guid:
            _keep_slot_ref(mat, 'env_map', ref)
            record_asset_error(engine, 'materials.env_map', guid,
                               '资产 guid 未在项目索引中（可能被删/换了项目）: %s' % (guid,))
    except Exception as e:
        _keep_slot_ref(mat, 'env_map', ref)
        record_asset_error(engine, 'materials.env_map', guid,
                           '环境贴图加载失败 (%r)' % (e,))



def _emit_material_refs(mats, ctx, engine=None, sync=False):
    """Q-B1-3=A: 场景只写材质**引用**（id/name），定义在资产库。

    sync=True（真正保存时）把未登记/被编辑的材质写回资产库；ctx 为 None
    （无项目资产库）退化为旧的内联定义写入 —— 兼容闸门。
    返回 (materials_list, migrated_count)。
    """
    if ctx is None:
        return [_emit_material(m, ctx) for m in mats], 0
    out, migrated = [], 0
    for m in mats:
        gid = getattr(m, 'guid', None) or generate_guid()
        try:
            m.guid = gid
        except Exception:
            pass
        if sync:
            _g, _mig, _why = ctx.sync_material(m)
            if not (_g and ctx.owns(gid, 'material')):
                # 登记失败 -> 退化为内联定义（宁可写冗余，不可丢数据），并出声
                out.append(_emit_material(m, None))
                if _why:
                    print('[资产] 材质 %r 无法登记资产库 (%s) -> 本次写内联定义'
                          % (getattr(m, 'name', '?'), _why))
                continue
            if _mig:
                migrated += 1
        elif not ctx.owns(gid, 'material'):
            # digest/预览路径不写盘：未登记材质先按内联发射（保存后收敛为引用）
            out.append(_emit_material(m, None))
            continue
        out.append({'id': gid, 'name': getattr(m, 'name', None)})
    return out, migrated



def _apply_materials(engine, mat_dicts, ctx=None):
    """材质 -> engine.materials (清空重建).

    Q-B1-3=A（2026-11-10 人类裁决）: **资产库 Assets/assets.json 是唯一真相源**。
      · ctx 存在 + 库里有该 guid -> 一律用库定义；场景内联定义忽略，
        内容不一致 -> 告警「场景副本与资产不一致，已按资产库加载」（不静默）。
      · ctx 存在 + 库里没有 -> 迁移期回退内联定义 + 告警「尚未登记，保存时会迁移」。
      · ctx 为 None（无项目资产库）-> 旧路径模式，行为与 beta5 一致（兼容闸门）。
    """
    engine.materials.clear()
    try:
        from loom_assets import material_has_inline as _has_inline
    except Exception:
        def _has_inline(_d):
            return False
    _ignored = 0
    for d in mat_dicts:
        if not isinstance(d, dict):
            print('[场景] 材质段不是对象 (%s) -> 跳过该段' % (type(d).__name__,))
            continue
        guid = d.get('id') or d.get('guid')
        _warn_dup_guid(engine, 'material', guid, 'materials[]')
        _inline = _has_inline(d)
        if ctx is not None and guid and ctx.owns(guid, 'material'):
            mat, _ok, _why = ctx.material(guid)
            if mat is not None:
                if _inline:
                    if ctx.material_matches(guid, d):
                        _ignored += 1
                    else:
                        record_asset_error(
                            engine, 'materials[]', guid,
                            '场景副本与资产不一致，已按资产库加载')
                engine.materials.append(mat)
                if _why:
                    record_asset_error(engine, 'materials[]', guid, _why)
                continue
            record_asset_error(engine, 'materials[]', guid,
                               '资产库材质构造失败 (%s) -> 回退场景内联定义' % (_why,))
        elif ctx is not None and guid:
            if _inline:
                record_asset_error(engine, 'materials[]', guid,
                                   '该材质尚未登记资产库（保存时会自动迁移）')
            else:
                record_asset_error(engine, 'materials[]', guid,
                                   '资产库中不存在该材质（场景只有引用）')
        try:
            mat = engine.add_material(color=d.get('color'),
                                      saturation=d.get('saturation', 1.0),
                                      name=d.get('name'),
                                      guid=guid)
        except Exception as _e:
            record_asset_error(engine, 'materials[]', guid,
                               '材质创建失败 (%r)' % (_e,))
            continue
        if guid:
            mat.guid = guid
        # M36 PBR: 恢复金属度/粗糙度/PBR 开关
        try:
            mat.metallic = d.get('metallic', 0.0)
            mat.roughness = d.get('roughness', 0.5)
            mat.pbr = d.get('pbr', False)
        except Exception:
            pass
        for slot, key in (('albedo', 'albedo'), ('normal_map', 'normal_map')):
            _apply_material_texture(engine, mat, slot, d.get(key), ctx)
        _apply_material_env(engine, mat, d.get('env_map'), ctx)
    if _ignored:
        print('[资产] materials[]: %d 条内联定义已忽略（以资产库为准）' % (_ignored,))



def _is_default_material(mat):
    """材质是否是 add_model 自建的默认材质 (无颜色/贴图/PBR 参数, 名字=材质).

    用于加载期孤儿判定: 只有"默认材质"可以安全丢弃; 用户显式创建的彩色/贴图
    材质即使暂未引用也保留 (资产库语义).
    """
    if mat is None:
        return False
    if getattr(mat, 'color', None) is not None:
        return False
    if getattr(mat, 'pbr', False):
        return False
    if (getattr(mat, 'albedo', None) is not None
            or getattr(mat, 'normal_map', None) is not None
            or getattr(mat, 'env_map', None) is not None):
        return False
    # Q-B1-1=A: 只有"失效引用"的材质不是默认材质 —— 不能被孤儿规则丢掉
    # （否则保存后 ref 也没了，等于换个方式丢资产）
    if isinstance(getattr(mat, '_asset_ref_slots', None), dict) \
            and any(isinstance(v, dict) and v
                    for v in mat._asset_ref_slots.values()):
        return False
    if getattr(mat, 'name', None) not in (None, '材质'):
        return False
    try:
        if abs(float(getattr(mat, 'saturation', 1.0)) - 1.0) > 1e-9:
            return False
        if abs(float(getattr(mat, 'metallic', 0.0))) > 1e-9:
            return False
        if abs(float(getattr(mat, 'roughness', 0.5)) - 0.5) > 1e-9:
            return False
    except (TypeError, ValueError):
        return False
    return True



def _drop_orphan_default_materials(engine, keep_ids, models):
    """D2=A (2026-11-07): 加载时丢弃无物体引用的默认材质.

    每次 load 时每个物体都会先建默认材质再换成文件引用材质, 旧实现把这些
    默认材质留在 engine.materials 并随下次 save 落盘 -> 每次 load->save 材质
    数线性膨胀. 规则:
      - 本次加载新建且无引用 (不在文件材质库 keep_ids 里) -> 丢弃;
      - 文件里显式登记但无引用的"默认形态"材质 -> 丢弃并告警;
      - 文件里显式登记且非默认形态 (有颜色/贴图/PBR/自定义名) -> 保留,
        即使暂未引用 (资产库语义; 保存端不动).
    """
    refs = set()
    for m in models:
        mat = getattr(getattr(m, 'renderer', None), 'material', None)
        if mat is not None:
            refs.add(id(mat))
    dropped = 0
    for mat in list(engine.materials):
        if id(mat) in refs:
            continue
        if id(mat) not in keep_ids or _is_default_material(mat):
            engine.materials.remove(mat)
            dropped += 1
    if dropped:
        print("[sceneio] 警告: 丢弃 %d 个无引用的加载默认材质 (防孤儿膨胀)"
              % dropped)
