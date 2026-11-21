# -*- coding: utf-8 -*-
"""scene/object.py — 场景**对象 <-> dict**（B2 自 sceneio.py 按域拆出，函数体逐字一致）。

内容（= 旧 sceneio.py 同名段）:
  SceneCycleError / _validate_object_graph / _validate_model_graph（父链成环拒绝）
  _f3 / _f1（容错取值）+ 对象发射/装配: _emit_object / _emit_subtree /
  _make_mesh / _apply_object / _link_by_map / _link_parents
  Canvas UI 段序列化: _emit_ui_element / _emit_ui / _apply_ui_element /
  _apply_ui / _link_ui_targets

依赖注意: 本文件 import loom_components（numpy 链），所以**不是**契约级模块；
场景契约（scene.contract）能单独 import 的门不经过本文件。
"""
import os

from core.primitives import Point3D
from components.components import animator_from_dict, animator_to_dict
from mathlib.mesh import create_cube, spec_to_mesh

from scene.asset import record_asset_error




class SceneCycleError(ValueError):
    """场景/Prefab 父链成环或对象图不可达.

    加载/保存遇到时直接拒绝 (不静默丢对象). 继承 ValueError, 调用方可按
    普通数据错误处理.
    """



def _validate_object_graph(objects):
    """检测场景/Prefab dict 列表的 parent_id 成环 (不修改数据).

    返回 {对象 id: dict}. 成环抛 SceneCycleError. 非 dict/缺 id 的条目跳过
    (由后续加载容错路径处理), 避免坏文件在检测阶段崩溃.
    """
    id_map = {}
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        oid = obj.get('id') or obj.get('guid')
        if isinstance(oid, str) and oid:
            id_map[oid] = obj
    state = {}          # 1=当前路径, 2=已完成
    for start in id_map:
        if state.get(start) == 2:
            continue
        chain = []
        cur = start
        while cur is not None and cur in id_map:
            st = state.get(cur)
            if st == 1:
                try:
                    i = chain.index(cur)
                except ValueError:
                    i = 0
                cyc = chain[i:] + [cur]
                raise SceneCycleError(
                    "场景父链成环 (parent_id): %s" % " -> ".join(cyc))
            if st == 2:
                break
            state[cur] = 1
            chain.append(cur)
            pid = id_map[cur].get('parent_id')
            cur = pid if isinstance(pid, str) and pid in id_map else None
        for oid in chain:
            state[oid] = 2
    return id_map



def _validate_model_graph(models):
    """检测运行时模型父链成环/不可达 (保存前防御).

    场景保存只从根 DFS; 若父链成环或父指针悬空, 部分对象会被静默丢弃.
    本函数在序列化前显式拒绝, 抛 SceneCycleError.
    """
    model_ids = {id(m) for m in models}
    for m in models:
        path = set()
        cur = m
        while cur is not None:
            k = id(cur)
            if k in path:
                raise SceneCycleError(
                    "场景父链成环 (模型): %r" % (getattr(cur, 'name', cur),))
            path.add(k)
            cur = getattr(cur, 'parent', None)
    reachable = set()
    stack = [m for m in models if getattr(m, 'parent', None) is None]
    while stack:
        m = stack.pop()
        k = id(m)
        if k in reachable or k not in model_ids:
            continue
        reachable.add(k)
        stack.extend(getattr(m, 'children', ()) or ())
    if len(reachable) != len(model_ids):
        raise SceneCycleError(
            "场景对象图存在不可达对象 (%d 个): 父链可能成环"
            % (len(model_ids) - len(reachable)))



# ---------------- 对象 <-> dict ----------------

def _f3(v, default):
    """容错 3 分量取值 (安全扫描 2026-08-20 加固): 接受 [x,y,z]/tuple 且每分量
    可转 float; 其他 (None/字符串/长度不符/坏数) -> 返回 default. 坏场景文件不崩."""
    if isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return tuple(float(x) for x in v)
        except (TypeError, ValueError):
            pass
    return default



def _f1(v, default):
    """容错单数值: 可转 float 才用, 否则 default (坏场景文件不崩)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default



def _emit_object(m, ctx=None):
    """GameObject -> dict (单对象). M25: 脚本组件数组 (可多个). M23: 材质引用."""
    mat = m.renderer.material
    return {
        "id": m.guid,
        "parent_id": m.parent.guid if m.parent is not None else None,
        "prefab_ref": m.prefab_ref,
        "name": m.name,
        # Layer/Tag (2026-10-18): 项目级身份元信息; 旧文件无此二键 -> 加载取默认
        "layer": m.layer,
        "tag": m.tag,
        "type": m.primitive or 'cube',
        "params": dict(m.params) if m.params else {'size': 1.0},
        "position": [m.position.x, m.position.y, m.position.z],
        "rotation": [m.rotation.x, m.rotation.y, m.rotation.z],
        "scale": list(m.scale),
        "color": m.color,
        "material_id": mat.guid if mat is not None else None,   # M23: 引用材质库
        "normal_mode": m.normal_mode,
        "saturation": m.saturation,
        "visible": m.visible,
        "scripts": [{"id": sc.script_id, "vars": dict(sc.script_vars)}
                    for sc in m.scripts if sc.script_id],
        # M28 + B1 (2026-08-30): 碰撞体 (含接触材质: 摩擦系数/弹性, 静态体用);
        # B1-P1 加 rolling_friction (旧文件无此键 -> 缺省=默认 0.1, 兼容不变)
        "collider": {"shape": m.collider.shape, "enabled": m.collider.enabled,
                     "friction": m.collider.friction,
                     "restitution": m.collider.restitution,
                     "rolling_friction": m.collider.rolling_friction,
                     # 2026-10-18 Trigger: is_trigger (旧文件无此键 -> 缺省 False)
                     "is_trigger": bool(getattr(m.collider, 'is_trigger', False))},
        # M31 + B1: 刚体 (包含接触材质: 动态体用; 缺省=默认, 兼容旧文件)
        "rigidbody": None if m.rigidbody is None else {
            "mass": m.rigidbody.mass,
            "use_gravity": m.rigidbody.use_gravity,
            "is_kinematic": m.rigidbody.is_kinematic,
            "friction": m.rigidbody.friction,
            "restitution": m.rigidbody.restitution,
            "rolling_friction": m.rigidbody.rolling_friction,
        },
        "audio_source": None if m.audio_source is None else {  # M34: 音频源
            "clip": m.audio_source.clip,
            "loop": m.audio_source.loop,
            "volume": m.audio_source.volume,
            # 2026-10-18 3D 音频 (契约 §6.1)
            "category": m.audio_source.category,
            "min_distance": m.audio_source.min_distance,
            "max_distance": m.audio_source.max_distance,
            "rolloff": m.audio_source.rolloff,
        },
        # M35 动画 / beta6 C1: 序列化走唯一实现 (speed + 每片段 loop_mode 是
        # v11 的增量字段; time/playing **不落盘** —— 只作编辑器预览态, 存盘=回
        # 起点, 见 animator_to_dict 的契约说明与 test_animation_base.py).
        "animator": animator_to_dict(m.animator),
    }



def _emit_subtree(m, out, seen=None, ctx=None):
    """DFS 前序输出子树. seen 共享集合用于检测重复/成环 (防无限递归)."""
    if seen is None:
        seen = set()
    key = id(m)
    if key in seen:
        raise SceneCycleError(
            "序列化父链成环/对象重复: %r" % (getattr(m, 'name', m),))
    seen.add(key)
    out.append(_emit_object(m, ctx))
    for c in m.children:
        _emit_subtree(c, out, seen)



def _make_mesh(obj):
    """容错建网格: obj 类型重读外部文件; 未知/坏参数/文件失效 -> 立方体兜底"""
    t = obj.get('type', 'cube')
    params = obj.get('params', {})
    if t == 'obj' and isinstance(params.get('obj'), str) and params['obj']:
        try:
            from mathlib.mesh import load_obj
            return load_obj(params['obj'])     # M36: 重读 .obj 文件
        except (ValueError, OSError):
            return create_cube(1.0)            # 文件失效 -> 立方体兜底
    try:
        return spec_to_mesh(t, params)
    except (ValueError, TypeError):
        return create_cube(1.0)



def _apply_object(engine, obj, ctx=None):
    """按 dict 创建物体 (不做父链). 返回 (model, oid).
    M23: 有 material_id 则引用材质库中的共享材质 (找不到则按颜色/饱和度自建),
    无 material_id (v4 旧文件) 保持 add_model 自建的默认材质."""
    mesh = _make_mesh(obj)
    m = engine.add_model(mesh,
                         Point3D(*_f3(obj.get('position'), (0, 0, 0))),
                         Point3D(*_f3(obj.get('rotation'), (0, 0, 0))),
                         normal_mode=obj.get('normal_mode', 'flat'),
                         name=obj.get('name', '物体'),
                         scale=_f3(obj.get('scale'), (1, 1, 1)),
                         visible=obj.get('visible', True),
                         color=obj.get('color'),
                         saturation=obj.get('saturation', 1.0))
    mat_id = obj.get('material_id')
    if mat_id:
        mat = engine._find_material(mat_id)
        if mat is None and ctx is not None and ctx.owns(mat_id, 'material'):
            # beta6 B1: 材质资产（assets.json）里的 guid 终于能回查到（修探针 I 段缺陷）
            mat, _mok, _mwhy = ctx.material(mat_id)
            if _mwhy:
                record_asset_error(engine, 'objects.material_id', mat_id, _mwhy)
        if mat is None:                    # 材质不在库 (旧文件/手工编辑) -> 自建并登记
            mat = engine.add_material(color=obj.get('color'),
                                      saturation=obj.get('saturation', 1.0),
                                      guid=mat_id)
        m.renderer.material = mat          # 引用共享材质 (资产语义)
    oid = obj.get('id') or obj.get('guid') or m.guid
    if oid:
        m.guid = oid
    m.prefab_ref = obj.get('prefab_ref')
    # Layer/Tag (2026-10-18, 契约 §3.3 容错):
    #   layer 越界 -> 钳制 0 + 警告;  tag 未注册 -> 自动注册 + 警告;
    #   tag 非法字符 -> 回退 'Untagged' + 警告. 任何情况都不阻断场景加载.
    try:
        lv = int(obj.get('layer', 0))
    except (TypeError, ValueError):
        lv = 0
    if lv < 0 or lv > 31:
        print("[sceneio] 警告: 物体 %r 的 layer=%r 越界, 已钳制为 0"
              % (m.name, obj.get('layer')))
        lv = 0
    m.layer = lv
    tg = obj.get('tag', 'Untagged')
    if not isinstance(tg, str) or not tg.strip():
        tg = 'Untagged'
    tg = tg.strip()
    import kernels.layer_tag as layer_tag
    if not layer_tag.tag_exists(tg):
        try:
            layer_tag.register_tag(tg)
            print("[sceneio] 警告: 标签 %r 未注册, 已自动注册" % tg)
        except ValueError as e:
            print("[sceneio] 警告: 标签 %r 非法 (%s), 回退 'Untagged'"
                  % (tg, e))
            tg = 'Untagged'
    m.tag = tg
    # 脚本 (M25): 恢复全部脚本组件 (可多个). 兼容 v3 的单 "script" 字段.
    scs = obj.get('scripts')
    if scs is None:
        sc = obj.get('script')
        scs = [sc] if isinstance(sc, dict) and sc.get('id') else []
    for s in scs:
        if isinstance(s, dict) and s.get('id'):
            m.add_script(s['id'], s.get('vars') if isinstance(s.get('vars'), dict) else {})
    # 刚体 (M31): 文件有 rigidbody 字段则加刚体 (旧文件无字段=无刚体, 保持原行为)
    # B1: friction/restitution/rolling_friction 缺省=默认 (0.5/0.0/0.1), 兼容旧文件
    rb = obj.get('rigidbody')
    if isinstance(rb, dict):
        m.add_rigidbody(mass=rb.get('mass', 1.0),
                        use_gravity=rb.get('use_gravity', True),
                        is_kinematic=rb.get('is_kinematic', False),
                        friction=rb.get('friction', 0.5),
                        restitution=rb.get('restitution', 0.0),
                        rolling_friction=rb.get('rolling_friction', 0.1))
    # 音频源 (M34): 文件有 audio_source 字段则加 (旧文件无=无音频)
    au = obj.get('audio_source')
    if isinstance(au, dict):
        # 2026-10-18 3D 音频 (契约 §6.2): 逐项校验 + 显式警告 (组件 setter 是静默回退,
        # 场景加载需要让用户知道文件里写坏了什么).
        cat = au.get('category', 'sfx')
        if not isinstance(cat, str) or cat.strip().lower() not in ('music', 'sfx', 'voice'):
            print("[sceneio] 警告: 物体 %r 的音频 category=%r 非法, 回退 'sfx'"
                  % (m.name, cat))
            cat = 'sfx'
        else:
            cat = cat.strip().lower()
        try:
            mn = float(au.get('min_distance', 1.0))
        except (TypeError, ValueError):
            mn = 1.0
        if mn <= 0:
            print("[sceneio] 警告: 物体 %r 的音频 min_distance=%r 非法, 回退 1.0"
                  % (m.name, au.get('min_distance')))
            mn = 1.0
        try:
            mx = float(au.get('max_distance', 500.0))
        except (TypeError, ValueError):
            mx = 500.0
        if mx <= mn:
            print("[sceneio] 警告: 物体 %r 的音频 max_distance=%r 不大于 min_distance=%r, "
                  "回退默认 (1.0/500.0)" % (m.name, au.get('max_distance'), mn))
            mn, mx = 1.0, 500.0
        try:
            ro = float(au.get('rolloff', 1.0))
        except (TypeError, ValueError):
            ro = 1.0
        if ro <= 0:
            print("[sceneio] 警告: 物体 %r 的音频 rolloff=%r 非法, 回退 1.0"
                  % (m.name, au.get('rolloff')))
            ro = 1.0
        m.add_audio_source(clip=au.get('clip'),
                           loop=au.get('loop', False),
                           volume=au.get('volume', 1.0),
                           category=cat, min_distance=mn,
                           max_distance=mx, rolloff=ro)
    # 动画 (M35): 文件有 animator 字段则加 (重建 AnimationClip).
    # beta6 C1: 解析收敛到 loom_components.animator_from_dict —— 与
    # scene_driver.load_from_data 共用同一份 (旧文件无 speed/clip_meta 兼容).
    an = obj.get('animator')
    if isinstance(an, dict) and isinstance(an.get('clips'), dict):
        clips, cur, loop, speed = animator_from_dict(an)
        m.add_animator(clips=clips, current=cur, loop=loop)
        m.animator.speed = speed
    # 碰撞体 (M28): 文件有 collider 字段则覆盖默认 (旧文件无字段保持自动派生)
    # B1: friction/restitution/rolling_friction 缺省=默认 (0.5/0.0/0.1), 兼容旧文件
    col = obj.get('collider')
    if isinstance(col, dict):
        if col.get('shape') in ('box', 'sphere', 'none'):
            m.collider.shape = col['shape']
        m.collider.enabled = bool(col.get('enabled', True))
        m.collider.friction = float(col.get('friction', 0.5))
        m.collider.restitution = float(col.get('restitution', 0.0))
        m.collider.rolling_friction = float(col.get('rolling_friction', 0.1))
        # 2026-10-18 Trigger: 旧文件无此键 -> 缺省 False（兼容不变）
        m.collider.is_trigger = bool(col.get('is_trigger', False))
    return m, oid



def _link_by_map(objects, models, id_map):
    """按 id_map (对象 id -> model) 建父链. objects/models 等长 DFS 前序."""
    for obj, m in zip(objects, models):
        pid = obj.get('parent_id')
        if pid and pid in id_map and id_map[pid] is not m:
            par = id_map[pid]
            m.parent = par
            par.children.append(m)



def _link_parents(objects, models):
    """默认: 以 model.guid 为 id_map (加载场景时 guid == 对象 id)"""
    _link_by_map(objects, models, {m.guid: m for m in models})



def _emit_ui_element(elem):
    """UIElement -> dict (递归). 阶段1 支持 panel/text/image."""
    base = {
        'type': elem.ctype,
        'name': elem.name,
        'rect': list(elem.rect),
        'anchor': list(elem.anchor),
        'pivot': list(elem.pivot),
        'visible': bool(elem.visible),
        'enabled': bool(elem.enabled),
        'z_order': int(elem.z_order),
    }
    if elem.ctype == 'panel':
        base['bg_color'] = list(elem.bg_color)
    elif elem.ctype == 'text':
        base['text'] = elem.text
        base['font_size'] = int(elem.font_size)
        base['color'] = list(elem.color)
        base['align'] = elem.align
        base['wrap_width'] = int(elem.wrap_width)
    elif elem.ctype == 'image':
        base['texture_path'] = elem.texture_path
        base['tint'] = list(elem.tint)
        base['fit'] = elem.fit
    elif elem.ctype == 'button':
        base['text'] = elem.text
        base['font_size'] = int(elem.font_size)
        base['text_color'] = list(elem.text_color)
        base['normal_color'] = list(elem.normal_color)
        base['hover_color'] = list(elem.hover_color)
        base['pressed_color'] = list(elem.pressed_color)
        # on_click 不序列化 (运行时由脚本挂载, 契约 §8)
    elif elem.ctype == 'slider':
        base['min_value'] = float(elem.min_value)
        base['max_value'] = float(elem.max_value)
        base['value'] = float(elem.value)
        base['direction'] = elem.direction
        base['track_color'] = list(elem.track_color)
        base['fill_color'] = list(elem.fill_color)
        base['handle_color'] = list(elem.handle_color)
        # on_change 不序列化
    elif elem.ctype == 'toggle':
        base['is_on'] = bool(elem.is_on)
        base['label'] = elem.label
        base['label_size'] = int(elem.label_size)
        base['box_color'] = list(elem.box_color)
        base['check_color'] = list(elem.check_color)
        base['label_color'] = list(elem.label_color)
        # on_change 不序列化
    elif elem.ctype == 'progress_bar':
        base['value'] = float(elem.value)
        base['bg_color'] = list(elem.bg_color)
        base['fill_color'] = list(elem.fill_color)
    elif elem.ctype == 'scroll_view':
        base['content_size'] = list(elem.content_size)
        base['scroll_pos'] = list(elem.scroll_pos)
        base['bg_color'] = list(elem.bg_color)
        base['bar_color'] = list(elem.bar_color)
        base['bar_width'] = int(elem.bar_width)
        base['show_bar'] = bool(elem.show_bar)
        base['scroll_step'] = int(elem.scroll_step)
    elif elem.ctype == 'dropdown':
        base['options'] = list(elem.options)
        base['selected_index'] = int(elem.selected_index)
        base['bg_color'] = list(elem.bg_color)
        base['hover_color'] = list(elem.hover_color)
        base['list_bg'] = list(elem.list_bg)
        base['list_hover'] = list(elem.list_hover)
        base['text_color'] = list(elem.text_color)
        base['font_size'] = int(elem.font_size)
        base['item_height'] = int(elem.item_height)
        # on_change 不序列化
    elif elem.ctype == 'grid_layout':
        base['cell_size'] = [elem.cell_w, elem.cell_h]
        base['spacing'] = [elem.spacing_x, elem.spacing_y]
        base['columns'] = int(elem.columns)
        base['bg_color'] = list(elem.bg_color)
    elif elem.ctype == 'input_field':
        base['text'] = elem.text
        base['placeholder'] = elem.placeholder
        base['max_length'] = int(elem.max_length)
        base['bg_color'] = list(elem.bg_color)
        base['focus_bg_color'] = list(elem.focus_bg_color)
        base['text_color'] = list(elem.text_color)
        base['placeholder_color'] = list(elem.placeholder_color)
        base['cursor_color'] = list(elem.cursor_color)
        base['font_size'] = int(elem.font_size)
        # on_submit / on_change 不序列化 (运行时由脚本挂载, 契约 §8)
    elif elem.ctype == 'shape':
        # 2026-10-20 沙盘 2D 绘制（line/polyline/polygon/circle）
        base['shape_type'] = getattr(elem, 'shape_type', 'line')
        base['points'] = [list(p) for p in (getattr(elem, 'points', []) or [])]
        base['radius'] = float(getattr(elem, 'radius', 0.0))
        sc = getattr(elem, 'stroke_color', None)
        base['stroke_color'] = list(sc) if sc else None
        base['stroke_width'] = int(getattr(elem, 'stroke_width', 2))
        fc = getattr(elem, 'fill_color', None)
        base['fill_color'] = list(fc) if fc else None
        base['segments'] = int(getattr(elem, 'segments', 32))
        base['close'] = bool(getattr(elem, 'close', False))
    # 2026-10-19 P0-5: 声明式事件绑定可序列化（{event: {script, method, owner_guid}}）
    eb = getattr(elem, 'event_bindings', None)
    if eb:
        base['event_bindings'] = dict(eb)
    base['children'] = [_emit_ui_element(c) for c in elem.children]
    return base



def _emit_ui(ui_manager):
    """UIManager -> dict (契约 §8). 空/None -> 空 canvases."""
    if ui_manager is None:
        return {'canvases': []}
    canvases = []
    for c in ui_manager.canvases:
        d = {
            'canvas_type': c.canvas_type,
            'z_order': int(c.z_order),
            'width': int(c.width),
            'height': int(c.height),
            'elements': [_emit_ui_element(c.root)],
        }
        # 2026-10-19 第1档序3阶段4 World Space UI: world 模式三字段
        if c.canvas_type == 'world':
            tgt = getattr(c, 'target', None)
            d['target_id'] = getattr(tgt, 'guid', None) if tgt is not None else None
            d['world_scale'] = float(getattr(c, 'world_scale', 0.01))
            d['billboard'] = bool(getattr(c, 'billboard', True))
        canvases.append(d)
    return {'canvases': canvases}



def _apply_ui_element(d, base_dir=None):
    """dict -> UIElement (按 type 分发). 未知类型返回 None + 警告."""
    if not isinstance(d, dict):
        return None
    import loom_ui
    typ = d.get('type', '')
    kw = {
        'name': d.get('name', 'element'),
        'rect': tuple(d.get('rect') or (0, 0, 100, 30)),
        'anchor': tuple(d.get('anchor') or (0, 0)),
        'pivot': tuple(d.get('pivot') or (0, 0)),
        'visible': bool(d.get('visible', True)),
        'enabled': bool(d.get('enabled', True)),
        'z_order': int(d.get('z_order', 0)),
    }
    if typ == 'element':
        # Canvas.root 等纯容器 (无专属字段)
        elem = loom_ui.UIElement(**kw)
    elif typ == 'panel':
        elem = loom_ui.Panel(bg_color=tuple(d.get('bg_color') or (0, 0, 0, 128)), **kw)
    elif typ == 'text':
        elem = loom_ui.Text(text=str(d.get('text', '')),
                            font_size=int(d.get('font_size', 16)),
                            color=tuple(d.get('color') or (255, 255, 255)),
                            align=d.get('align', 'left'),
                            wrap_width=int(d.get('wrap_width', 0)), **kw)
    elif typ == 'image':
        _tp = str(d.get('texture_path', ''))
        if _tp and not os.path.isabs(_tp) and base_dir:
            _tp = os.path.join(base_dir, _tp.replace('/', os.sep))
        elem = loom_ui.Image(texture_path=_tp,
                             tint=tuple(d.get('tint') or (255, 255, 255, 255)),
                             fit=d.get('fit', 'stretch'), **kw)
    elif typ == 'button':
        elem = loom_ui.Button(text=str(d.get('text', '')),
                              font_size=int(d.get('font_size', 16)),
                              text_color=tuple(d.get('text_color') or (255, 255, 255)),
                              normal_color=tuple(d.get('normal_color') or (70, 80, 100, 255)),
                              hover_color=tuple(d.get('hover_color') or (90, 100, 125, 255)),
                              pressed_color=tuple(d.get('pressed_color') or (50, 60, 80, 255)),
                              **kw)
    elif typ == 'slider':
        elem = loom_ui.Slider(min_value=float(d.get('min_value', 0.0)),
                              max_value=float(d.get('max_value', 1.0)),
                              value=float(d.get('value', 0.0)),
                              direction=d.get('direction', 'h'),
                              track_color=tuple(d.get('track_color') or (50, 55, 70, 255)),
                              fill_color=tuple(d.get('fill_color') or (80, 140, 220, 255)),
                              handle_color=tuple(d.get('handle_color') or (220, 225, 235, 255)),
                              **kw)
    elif typ == 'toggle':
        elem = loom_ui.Toggle(is_on=bool(d.get('is_on', False)),
                              label=str(d.get('label', '')),
                              label_size=int(d.get('label_size', 16)),
                              box_color=tuple(d.get('box_color') or (70, 80, 100, 255)),
                              check_color=tuple(d.get('check_color') or (80, 200, 120, 255)),
                              label_color=tuple(d.get('label_color') or (230, 230, 230)),
                              **kw)
    elif typ == 'progress_bar':
        elem = loom_ui.ProgressBar(value=float(d.get('value', 0.0)),
                                   bg_color=tuple(d.get('bg_color') or (40, 44, 54, 255)),
                                   fill_color=tuple(d.get('fill_color') or (80, 220, 120, 255)),
                                   **kw)
    elif typ == 'scroll_view':
        elem = loom_ui.ScrollView(content_size=tuple(d.get('content_size') or (300, 800)),
                                  bg_color=tuple(d.get('bg_color') or (30, 34, 44, 255)),
                                  bar_color=tuple(d.get('bar_color') or (120, 130, 150, 255)),
                                  bar_width=int(d.get('bar_width', 8)),
                                  show_bar=bool(d.get('show_bar', True)),
                                  scroll_step=int(d.get('scroll_step', 30)),
                                  **kw)
        if d.get('scroll_pos'):
            elem.scroll_pos = tuple(d['scroll_pos'])
    elif typ == 'dropdown':
        elem = loom_ui.Dropdown(options=list(d.get('options') or []),
                                selected_index=int(d.get('selected_index', 0)),
                                bg_color=tuple(d.get('bg_color') or (70, 80, 100, 255)),
                                hover_color=tuple(d.get('hover_color') or (90, 100, 125, 255)),
                                list_bg=tuple(d.get('list_bg') or (50, 55, 70, 255)),
                                list_hover=tuple(d.get('list_hover') or (80, 140, 220, 255)),
                                text_color=tuple(d.get('text_color') or (255, 255, 255)),
                                font_size=int(d.get('font_size', 14)),
                                item_height=int(d.get('item_height', 28)),
                                **kw)
    elif typ == 'grid_layout':
        cs = tuple(d.get('cell_size') or (64, 64))
        sp = tuple(d.get('spacing') or (8, 8))
        elem = loom_ui.GridLayout(cell_size=cs, spacing=sp,
                                  columns=int(d.get('columns', 4)),
                                  bg_color=tuple(d.get('bg_color') or (0, 0, 0, 0)),
                                  **kw)
        # GridLayout 子元素添加后会自动 reflow (在 add_child 里)
    elif typ == 'input_field':
        elem = loom_ui.InputField(
            text=str(d.get('text', '')),
            placeholder=str(d.get('placeholder', '')),
            max_length=int(d.get('max_length', 200)),
            bg_color=tuple(d.get('bg_color') or (50, 55, 70, 255)),
            focus_bg_color=tuple(d.get('focus_bg_color') or (60, 70, 90, 255)),
            text_color=tuple(d.get('text_color') or (255, 255, 255)),
            placeholder_color=tuple(d.get('placeholder_color') or (140, 140, 150)),
            cursor_color=tuple(d.get('cursor_color') or (220, 220, 230)),
            font_size=int(d.get('font_size', 16)),
            **kw)
    elif typ == 'shape':
        # 2026-10-20 沙盘 2D 绘制（line/polyline/polygon/circle）
        sc = d.get('stroke_color')
        fc = d.get('fill_color')
        elem = loom_ui.Shape(
            shape_type=str(d.get('shape_type') or 'line'),
            points=list(d.get('points') or []),
            radius=float(d.get('radius', 0.0)),
            stroke_color=tuple(sc) if sc else None,
            stroke_width=int(d.get('stroke_width', 2)),
            fill_color=tuple(fc) if fc else None,
            segments=int(d.get('segments', 32)),
            close=bool(d.get('close', False)),
            **kw)
    else:
        print("[sceneio] 警告: 未知 UI 元素类型 %r, 跳过" % typ)
        return None
    # 2026-10-19 P0-5: 恢复声明式事件绑定
    eb = d.get('event_bindings')
    if eb and isinstance(eb, dict):
        try:
            elem.event_bindings = {k: dict(v) if isinstance(v, dict) else v
                                   for k, v in eb.items()}
        except Exception:
            pass
    for cd in (d.get('children') or []):
        ch = _apply_ui_element(cd, base_dir)
        if ch is not None:
            elem.add_child(ch)
    # GridLayout: 加载完成后强制 reflow (序列化恢复的 child.rect 被自动排列覆盖)
    if typ == 'grid_layout' and hasattr(elem, '_reflow'):
        try:
            elem._reflow()
        except Exception:
            pass
    return elem



def _apply_ui(engine, ui_data, base_dir=None):
    """dict -> engine.ui (清空重建). 缺/空 -> 保留一个空默认 Canvas."""
    if not hasattr(engine, 'ui') or engine.ui is None:
        return
    import loom_ui
    engine.ui.clear()
    canvases = (ui_data or {}).get('canvases') or []
    if not canvases:
        # 无 ui 段: 留一个默认 screen Canvas (与引擎 __init__ 一致)
        engine.ui.add_canvas(loom_ui.Canvas(
            canvas_type='screen',
            width=getattr(engine, 'width', 1280),
            height=getattr(engine, 'height', 800)))
        return
    for cd in canvases:
        typ = cd.get('canvas_type', 'screen')
        canvas = loom_ui.Canvas(
            canvas_type=typ,
            width=int(cd.get('width', 1280)),
            height=int(cd.get('height', 800)),
            z_order=int(cd.get('z_order', 0)),
            world_scale=float(cd.get('world_scale', 0.01)),
            billboard=bool(cd.get('billboard', True)))
        # 2026-10-19 第1档序3阶段4: world target 二次绑定
        # 此处 models 尚未建好（_apply_ui 在 _apply_object 之前），暂存 guid，
        # 由 scene_from_dict 末尾 _link_ui_targets 补绑。
        if typ == 'world':
            canvas._pending_target_id = cd.get('target_id')
        for ed in (cd.get('elements') or []):
            root_el = _apply_ui_element(ed, base_dir)
            if root_el is not None:
                # 第一层元素替换 root (而非作为 root 的子元素)
                canvas.root = root_el
        engine.ui.add_canvas(canvas)



def _link_ui_targets(engine, id_map=None):
    """2026-10-19 第1档序3阶段4: world Canvas target 二次绑定.

    _apply_ui 早于 _apply_object 调用，此时 models 尚未建好。本函数在
    objects + 父链建好后调用，按 guid 把 pending target_id 绑回 GameObject。
    target 不存在（用户删了物体）-> target 保持 None（渲染时跳过）。
    """
    ui = getattr(engine, 'ui', None)
    if ui is None:
        return
    id_map = id_map or {m.guid: m for m in engine.models if m.guid}
    for c in ui.canvases:
        tid = getattr(c, '_pending_target_id', None)
        if tid is None:
            continue
        c.target = id_map.get(tid)
        try:
            delattr(c, '_pending_target_id')
        except Exception:
            pass
