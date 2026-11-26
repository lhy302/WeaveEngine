# -*- coding: utf-8 -*-
"""eai.object_ops — 对象命令

我负责：object_add / object_list / object_select / object_rename /
object_delete / object_duplicate 与自动聚焦前置 (_auto_focus*)。
我不负责：目标寻址（target.py）、层级挂父（hierarchy_ops.py）、脚本挂载（script_ops.py）。
"""

from .commit import _Ambiguous
from .helpers import as_bool, as_float
from .registry import _CMD_SCOPE, command, log
from .target import _find, _find_all

# ====================================================================
# 物体
# ====================================================================
@command('object_add', '添加基元: cube|sphere|plane')
def cmd_object_add(win, args):
    typ = args.get('type', 'cube')
    ed = win.editor
    # 2026-10-19 P0-3: _add_primitive 现在返回 model，命令层直接拿到 guid/name，
    # 不再"创建完让 Agent 猜最后一个"（重名/撤销后必错）。
    m = ed._add_primitive(typ)
    # 2026-11-07 C: 新物体创建后自动聚焦 (Agent 每一步都要人类看得见)
    # Q-B7-56-1 裁定① (2026-11-22): 自动聚焦是 Agent 可见性设施 —— GUI 点击
    # (scope='user') 翻译执行时跳过, 保持人类点工具栏加物体相机不被拖走的旧 UX;
    # 可观察等价面 (对象状态/撤销栈/命令日志) 两路一致 (相机视角不属场景状态)。
    if m is not None and _CMD_SCOPE.current != 'user':
        try:
            _auto_focus(win, ed, ed.models.index(m))
        except ValueError:
            pass
    return {
        'type': typ,
        'guid': getattr(m, 'guid', None),
        'name': getattr(m, 'name', None),
    }


# ---- 自动聚焦 (2026-11-07 C: Agent 操作必须"看得见") ----
def _auto_focus_enabled(win):
    """settings.agent_auto_focus 未显式关闭 -> True (缺省 True).

    设置来自与设置面板同一份 设置.json (guiloader.load_settings); 读不到/坏值
    一律按开 (Agent 操作默认要可见, 与用户裁决一致).
    """
    try:
        import guiloader
        s = guiloader.load_settings('loom')
        return as_bool(s.get('agent_auto_focus', True), True)
    except Exception:
        return True


def _auto_focus(win, ed, index):
    """object_add / object_select 成功后把相机聚焦到目标 (失败不影响命令结果).
    返回 True/False/None (None = 未尝试: 开关关闭或编辑器不支持)."""
    fn = getattr(ed, 'focus_on_object', None)
    if fn is None:
        return None
    if not _auto_focus_enabled(win):
        return None
    try:
        return bool(fn(index, smooth=True))
    except Exception as e:
        log('[命令] 自动聚焦失败: %r' % e)
        return False


@command('object_list', '场内全部物体/光源/相机 (带序号, 重名时用 index= 指定)')
def cmd_object_list(win, args):
    ed = win.editor
    sel = getattr(ed._selected(), 'name', None) if ed._selected() else None
    return {
        # 2026-10-19 P0-3: 每项带 guid（稳定 ID），Agent 可用它精确寻址
        'models': [{'index': i, 'name': m.name,
                    'guid': getattr(m, 'guid', None),
                    'parent': getattr(getattr(m, 'parent', None), 'name', None)}
                   for i, m in enumerate(ed.models)],
        'lights': [{'index': i, 'name': l.name,
                    'guid': getattr(l, 'guid', None),
                    'kind_of': getattr(l, 'kind', None)}
                   for i, l in enumerate(ed.lights)],
        'cameras': [{'index': i, 'name': c.name,
                     'guid': getattr(c, 'guid', None)}
                    for i, c in enumerate(ed.cameras)],
        'selected': sel,
    }


@command('object_select', '选中 {name?/index?} (物体名/光源名/相机名; 重名加 index=)')
def cmd_object_select(win, args):
    ed = win.editor
    name = args.get('name')
    if name is None:
        idx = int(as_float(args.get('index', 0), 0))
        if not 0 <= idx < len(ed.models):
            return {'error': 'index 越界: %d (物体数 %d)' % (idx, len(ed.models))}
        ed._select_model(idx)
        # 2026-11-07 C: 按 index 选中物体也自动聚焦
        _auto_focus(win, ed, idx)
        return {'selected': getattr(ed._selected(), 'name', None)}
    hits = _find_all(ed, name)
    if not hits:
        return {'error': '找不到: %s (先 object_list 看全部)' % name}
    # 2026-11-07 P1: 重名/越界 index 一律拒绝, 不再静默取第一个。
    # 原写法 `hits = [...] or hits` 有三处坑: (1) 没有 index 时直接选 hits[0];
    # (2) index 越界时 or 兜底回全量 hits, 仍然选 hits[0]; (3) 只按序号过滤,
    # 序号跨类型共用时可能同时命中 model#1 与 light#1。MCP 的
    # unity_gameobject_delete / _duplicate 就是先 object_select 再动手 ——
    # 选错对象等于删错/复制错, 代价不可逆。歧义消息复用 _Ambiguous
    # (列出全部候选的种类#序号, 与 prefab_unlink 等同一条契约)。
    if len(hits) > 1:
        idx = args.get('index')
        if idx is None:
            raise _Ambiguous(name, hits)
        want = int(as_float(idx, -1))
        picked = [h for h in hits if h[2] == want]
        if len(picked) != 1:
            raise _Ambiguous(name, hits)
        hits = picked
    kind, obj, i = hits[0]
    if kind == 'model':
        ed._select_model(i)
        # 2026-11-07 C: 选中物体后自动聚焦 (与 GUI 双击层级行同款"看得见")
        _auto_focus(win, ed, i)
    elif kind == 'light':
        ed.selected_light_index = i
        ed.selected_index = ed.selected_camera_index = -1
    else:
        ed.selected_camera_index = i
        ed.selected_index = ed.selected_light_index = -1
    return {'selected': obj.name, 'kind': kind, 'index': i,
            'ambiguous': len(_find_all(ed, name)) > 1}


@command('object_rename', '改名: {name, new}')
def cmd_object_rename(win, args):
    ed = win.editor
    # 2026-10-19 P0-3: 支持 guid 寻址（_find -> _find_all 已支持 guid）
    kind, obj, i = _find(ed, args.get('name'))
    if obj is None:
        return {'error': '找不到: %s' % args.get('name')}
    new = args.get('new')
    if not new or not str(new).strip():
        return {'error': '新名字不能为空'}
    new = str(new).strip()
    old = obj.name
    if kind == 'model':
        ed.rename(obj, new, old)
    elif kind == 'light':
        ed.rename_light(obj, new, old)
    else:
        ed.rename_camera(obj, new, old)
    # 2026-10-19 P0-3 关键修复: ed.rename 重名时只弹 GUI 提示不抛异常，
    # 旧代码无论成功失败都返回 renamed=[old,new] -> Agent 误以为成功。
    # 修复：事后检查 obj.name 才是真实结果。
    actual = getattr(obj, 'name', None)
    if actual != new:
        return {
            'error': '改名失败（重名或非法名）',
            'requested': new,
            'actual': actual,
            'guid': getattr(obj, 'guid', None),
        }
    return {
        'renamed': [old, new],
        'actual': actual,
        'guid': getattr(obj, 'guid', None),
    }


@command('object_delete', '删除当前选中')
def cmd_object_delete(win, args):
    win.editor.delete_object()
    return {'ok': True}


@command('object_duplicate', '复制当前选中')
def cmd_object_duplicate(win, args):
    win.editor.duplicate_object()
    return {'ok': True}
