# -*- coding: utf-8 -*-
"""scene/asset.py — 场景**资产身份层**（B2 自 sceneio.py 按域拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  generate_guid / asset_context / reset_asset_errors / record_asset_error /
  asset_errors / asset_error_count / _keep_slot_ref / _clear_slot_ref /
  clear_asset_slot / asset_refs_kept / asset_issue_notice /
  _texture_ref_dict / _cubemap_ref_dict / _warn_dup_guid

与旧版唯一差异（人类裁决 Q-B7-49-1 P2 收敛）: generate_guid 改为调
scene.identity.new_guid（uuid4 唯一实现只在 scene/identity.py），语义不变。
"""
from scene.identity import new_guid




def generate_guid():
    """（Q-B7-49-1 P2 收敛）新对象 guid —— 唯一实现 = scene.identity.new_guid。

    旧实现是本文件内联的 uuid.uuid4().hex；B2 起全仓生产代码只许
    scene/identity.py 一处 uuid4（门: test_scene_contract G3）。本名保留作旧引用面锚点
    （loom_assets 文档引用 / 外部 generate_guid 调用点），语义与旧版完全一致。
    """
    return new_guid()



# ---------------- 资产身份层 (beta6 B1: 项目 Assets/ + guid) ----------------
_TEXTURE_IMPORT_KEYS = ('mipmaps', 'wrap', 'filter_mode', 'aniso', 'max_size',
                        'compression')



def asset_context(base_dir=None, create=False):
    """场景目录 -> 资产上下文；无项目 <root>/Assets/assets.json 时返回 None。

    None = **旧路径模式**（无项目资产库）：一切行为与 beta5 完全一致（兼容闸门）。
    """
    try:
        from loom_assets import context_for_scene
        return context_for_scene(base_dir, create=create)
    except Exception:
        return None



# F-02: 资产问题上限（超出只计数，不再 append/print）——旧实现 item in errs
# 是 O(N) 扫描 -> 5000 条 313ms；现在 set 去重 O(1) + 打印上限 200。
ASSET_ERROR_LIMIT = 200



def reset_asset_errors(engine):
    """清空资产问题（换场景/新建场景统一入口；连同去重键与溢出计数）。"""
    try:
        engine._asset_errors = []
        engine._asset_error_keys = set()
        engine._asset_error_overflow = 0
    except Exception:
        pass



def record_asset_error(engine, where, guid, reason):
    """把资产解析失败/过期挂到引擎（形状对齐 _skybox_valid/_skybox_error）。

    O(1) 追加：去重键放在 set 里（不再线性扫描列表）；超过 ASSET_ERROR_LIMIT
    只累加 overflow 计数，不 append、不打印（避免脏场景刷屏 + 二次方耗时）。
    """
    if not reason:
        return
    try:
        errs = getattr(engine, '_asset_errors', None)
        if errs is None:
            errs = []
            engine._asset_errors = errs
            engine._asset_error_keys = set()
            engine._asset_error_overflow = 0
        keys = getattr(engine, '_asset_error_keys', None)
        if not isinstance(keys, set):
            keys = set(errs)
            engine._asset_error_keys = keys
    except Exception:
        return
    gid = guid if isinstance(guid, str) else None
    item = (str(where), gid, str(reason))
    if item in keys:
        return
    keys.add(item)
    if len(errs) >= ASSET_ERROR_LIMIT:
        try:
            engine._asset_error_overflow = int(
                getattr(engine, '_asset_error_overflow', 0) or 0) + 1
        except Exception:
            pass
        return
    errs.append(item)
    print('[资产] %s: %s%s' % (where, reason, ('  (guid=%s)' % gid) if gid else ''))



def asset_errors(engine):
    """引擎上累积的资产问题 [(where, guid, reason)]（只读副本，已截断到上限）。"""
    return list(getattr(engine, '_asset_errors', None) or [])



def asset_error_count(engine):
    """资产问题总数（含超出上限被折叠的计数）。"""
    errs = getattr(engine, '_asset_errors', None) or []
    try:
        over = int(getattr(engine, '_asset_error_overflow', 0) or 0)
    except Exception:
        over = 0
    return len(errs) + over



def _keep_slot_ref(mat, slot, ref):
    """Q-B1-1=A: 解析失败时把**原始引用**留在材质对象上，保存时原样写回。

    没有这一步，一次 Ctrl+S 就会把 guid 引用永久销毁（轮5 审计 P-01：
    贴图文件被删/索引缺失/索引坏 -> 打开告警 -> 保存后 albedo 整键消失、
    天空盒被替换成"默认蓝天 + 新随机 guid"）。
    """
    if not isinstance(ref, dict) or not ref:
        return
    try:
        slots = getattr(mat, '_asset_ref_slots', None)
        if not isinstance(slots, dict):
            slots = {}
            mat._asset_ref_slots = slots
        slots[slot] = dict(ref)
    except Exception:
        pass



def _clear_slot_ref(mat, slot):
    """槽位解析成功 -> 丢掉保留的旧引用（不让旧 ref 覆盖新资产）。"""
    try:
        slots = getattr(mat, '_asset_ref_slots', None)
        if isinstance(slots, dict):
            slots.pop(slot, None)
            if not slots:
                mat._asset_ref_slots = None
    except Exception:
        pass



def clear_asset_slot(mat, slot):
    """用户**显式清空**某个槽位时调用：连"保留的失效引用"一起清掉。

    Q-B1-1=A 的边界：解析失败保留引用；用户主动清空才算移除（否则一次 Ctrl+S
    之后旧引用又从 _asset_ref_slots 复活）。
    """
    _clear_slot_ref(mat, slot)



def asset_refs_kept(engine):
    """本次保存会"原样写回"的失效引用条数（材质槽 + 场景/相机天空盒）。"""
    n = 0
    seen = set()
    try:
        mats = list(getattr(engine, 'materials', None) or [])
        for mdl in list(getattr(engine, 'models', None) or []):
            mat = getattr(getattr(mdl, 'renderer', None), 'material', None)
            if mat is not None:
                mats.append(mat)
        for mat in mats:
            if id(mat) in seen:
                continue
            seen.add(id(mat))
            slots = getattr(mat, '_asset_ref_slots', None)
            if isinstance(slots, dict):
                # 与 _emit_material 完全同口径：只有"槽位为空 + 有保留引用"才会写回
                for slot, ref in slots.items():
                    if not isinstance(ref, dict) or not ref:
                        continue
                    if getattr(mat, slot, None) is None:
                        n += 1
    except Exception:
        pass
    try:
        if isinstance(getattr(engine, '_skybox_ref', None), dict) \
                and getattr(engine, '_skybox_valid', True) is False:
            n += 1
        for cam in list(getattr(engine, 'cameras', None) or []):
            if isinstance(getattr(cam, '_skybox_ref', None), dict) \
                    and getattr(cam, 'skybox', None) is None:
                n += 1
    except Exception:
        pass
    return n



def asset_issue_notice(engine, where='打开'):
    """给编辑器/播放器的一句可见提示（没有资产问题返回 None）。"""
    n_err = asset_error_count(engine)
    kept = asset_refs_kept(engine)
    if not n_err and not kept:
        return None
    parts = []
    if n_err:
        parts.append('%d 条资产问题' % (n_err,))
    if kept:
        parts.append('%d 条失效引用已保留（保存不会改写）' % (kept,))
    return '资产：%s —— scene_assets_check 可查看明细' % ('，'.join(parts))



def _texture_ref_dict(tex, ctx=None):
    """Texture -> 场景引用 dict。项目托管资产**只写 guid**（路径永不落盘）。"""
    guid = getattr(tex, 'guid', None)
    if ctx is not None and ctx.owns(guid, 'texture'):
        return {'guid': guid, 'name': getattr(tex, 'name', None)}
    ref = {'guid': guid, 'path': getattr(tex, 'path', None),
           'name': getattr(tex, 'name', None)}
    for k in _TEXTURE_IMPORT_KEYS:
        v = getattr(tex, k, None)
        if v is not None:
            ref[k] = v
    return ref



def _cubemap_ref_dict(cube, ctx=None):
    """Cubemap -> 引用 dict。托管资产只写 guid；否则沿用 beta5 的 paths/纯色。"""
    if cube is None:
        return None
    guid = getattr(cube, 'guid', None)
    out = {'name': getattr(cube, 'name', None), 'guid': guid}
    if ctx is not None and ctx.owns(guid, 'cubemap'):
        return out
    paths = getattr(cube, 'paths', None)
    if paths:
        out['paths'] = list(paths)
        return out
    solid = getattr(cube, '_solid_color', None)
    if solid:
        out['solid_color'] = [int(c) for c in solid]
        return out
    return None



def _warn_dup_guid(engine, kind, guid, where):
    """重复 guid 告警（beta6 B1: 现状是静默首条胜出 -> 必须出声）。"""
    if not guid:
        return
    _find = getattr(engine, '_find_material', None)
    if kind == 'material' and callable(_find) and _find(guid) is not None:
        print('[资产] 材质 guid 重复 (%s, 位置 %s) -> 同 guid 只保留首个，其余不生效'
              % (guid, where))
