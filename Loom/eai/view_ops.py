# -*- coding: utf-8 -*-
"""eai.view_ops — 视图与播放命令

我负责：view_focus / gizmo / play / logic_pause / logic_step。
我不负责：开发者相机位姿注入（camera_ops.py）。
"""

from .commit import _Ambiguous
from .helpers import as_bool, as_float
from .registry import command
from .target import _find_all

@command('view_focus', '相机聚焦到物体: {name?|index?, smooth?=true} '
                       '(世界 AABB 中心 + 包围球适配距离; 缺省=当前选中)')
def cmd_view_focus(win, args):
    ed = win.editor
    smooth = as_bool(args.get('smooth', True), True)
    name = args.get('name') or args.get('name_or_id')
    idx = args.get('index')
    if name is not None:
        hits = [h for h in _find_all(ed, name) if h[0] == 'model']
        if not hits:
            return {'error': '找不到物体: %s (先 object_list 看全部)' % name}
        if len(hits) > 1:
            want = args.get('index')
            if want is None:
                raise _Ambiguous(name, _find_all(ed, name))
            picked = [h for h in hits if h[2] == int(as_float(want, -1))]
            if len(picked) != 1:
                raise _Ambiguous(name, _find_all(ed, name))
            hits = picked
        idx = hits[0][2]
    elif idx is None:
        sel = ed._selected()
        if sel is None:
            return {'error': '没有选中物体: 传 name= 或 index=, 或先 object_select'}
        try:
            idx = ed.models.index(sel)
        except ValueError:
            return {'error': '选中物体不在场景中'}
    idx = int(as_float(idx, -1))
    if not 0 <= idx < len(ed.models):
        return {'error': 'index 越界: %d (物体数 %d)' % (idx, len(ed.models))}
    fn = getattr(ed, 'focus_on_object', None)
    if fn is None:
        return {'error': '当前编辑器不支持 focus_on_object'}
    if not fn(idx, smooth=smooth):
        # 2026-11-08 批4 (P-04-10): 按真实原因给 error, 不再把"取不到包围盒"
        # 也说成"播放态"（那会把排查方向带偏）。
        why = getattr(ed, '_focus_fail', None)
        msg = {'playing': '聚焦失败 (播放态不能移动编辑器相机)',
               'bad_index': '聚焦失败 (index=%s 无效)' % (idx,),
               'no_aabb': '聚焦失败 (取不到该物体的世界包围盒; 网格/变换异常?)'
               }.get(why, '聚焦失败 (原因未知: %r)' % (why,))
        return {'error': msg, 'reason': why}
    return {'focused': getattr(ed.models[idx], 'name', None), 'index': idx,
            'target': list(ed.camera_target),
            'distance': ed.camera_distance, 'smooth': smooth}


@command('gizmo', 'gizmo 模式: translate|rotate')
def cmd_gizmo(win, args):
    win.editor.set_gizmo_mode(args.get('mode', 'translate'))
    return {'mode': args.get('mode', 'translate')}


@command('play', '开/关播放: 缺省 toggle, on=true|false 指定态; '
                 'paused=true 进入播放即冻结逻辑帧 (物理对拍用)')
def cmd_play(win, args):
    state = args.get('on')
    ed = win.editor
    cur = bool(getattr(ed, 'is_playing', getattr(ed, 'playing', False)))
    if state is not None:
        state = as_bool(state)      # 'false' 是字符串, 不能裸 bool()
    if state is not None and state == cur:
        if cur and as_bool(args.get('paused'), False):
            ed._logic_paused = True
        return {'playing': cur, 'nochange': True}
    ed.toggle_play()
    now = bool(getattr(ed, 'is_playing', getattr(ed, 'playing', False)))
    if now and as_bool(args.get('paused'), False):
        # 进入播放即冻结: 渲染帧照跑但零逻辑, 直到 physics_simulate 显式步进.
        # 与 toggle_play 同一主线程操作, 中间无渲染帧插入 → 从零时刻起确定.
        ed._logic_paused = True
    return {'playing': now,
            'paused': bool(getattr(ed, '_logic_paused', False))}


@command('logic_pause', '暂停/恢复逻辑时钟 (F9 同款): {} (toggle; 未播放时无效)'
                   ' (Q-B7-56-2: GUI TPS 按钮与命令行同一命令体)')
def cmd_logic_pause(win, args):
    # Q-B7-56-2 JVM 七步: 分类=GUI 点击命令化; 公共实现已在 EngineCore
    # (toggle_logic_paused: GL/VK 同一函数对象, 见 test_gui_command_unification G1);
    # 本命令是薄壳 (无新增引擎逻辑, 无后端差异)。
    ed = win.editor
    paused = ed.toggle_logic_paused()
    return {'paused': bool(paused),
            'playing': bool(getattr(ed, 'is_playing', False))}


@command('logic_step', '步进 1 逻辑帧 (F10 同款, 仅暂停态生效): {}')
def cmd_logic_step(win, args):
    # Q-B7-56-2 JVM 七步: 薄壳, 公共实现 EngineCore.step_logic_once (两端同源)。
    ed = win.editor
    if not ed.step_logic_once():
        return {'error': '未在暂停态 (先 logic_pause 或 F9), 步进未生效',
                'stepped': False}
    return {'stepped': True}
