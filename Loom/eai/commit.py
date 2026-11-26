# -*- coding: utf-8 -*-
"""eai.commit — 通用目标解析与一步撤销提交（共享前置）

我负责：_resolve 目标解析、重名歧义异常 _Ambiguous、_no_target 拒绝文案、
_commit 按类型走 commit_model/light/camera、_apply_fields 字段批量写入。
我不负责：撤销管理器取用（见 undo_base.py）；也不负责具体命令。
"""

from .helpers import as_float
from .target import _find_all

# ====================================================================
# 结果注入命令 (P2②, 2026-08-27) — 覆盖检查器 / 层级 / 资源 / Prefab 的
# GUI 操作面。约定 (用户拍板的"连贯操作双链原则"):
#   · 命令层只做"一次到位的结果注入" (set_*), 不模拟拖拽/长按等连贯操作;
#   · 每条命令调用**与 GUI 完全相同的 EditorApp 方法** (commit_model /
#     toggle_collider / reparent ...), 于是撤销栈、脏标记、组件语义天然一致;
#   · 一条命令 = 一步撤销 (commit_* 包整批字段), 对齐"改完松手压一次栈".
# ====================================================================
def _resolve(ed, args, kinds=('model', 'light', 'camera')):
    """目标解析: {name} 缺省 = 当前选中. 返回 (kind, obj); 找不到 (None, None).
    重名时: 若 args 有 index=(该类型列表序号) 用之, 否则**拒绝并返回歧义清单**
    —— 命令层对上错对象比报错更糟 (曾把 Prefab 实例的 unlink 应用到同名源物体,
    源头被静默断开, 用户实锤"按钮没反应"的同类病根; 2026-08-27 修)."""
    name = args.get('name') or args.get('target')
    if name:
        hits = _find_all(ed, name)
        hits = [h for h in hits if h[0] in kinds]
        if not hits:
            return None, None
        if len(hits) > 1:
            idx = args.get('index')
            if idx is None:
                raise _Ambiguous(name, hits)
            idx = int(as_float(idx, -1))
            hits = [h for h in hits if h[2] == idx]
            if not hits:
                raise _Ambiguous(name, _find_all(ed, name))
        return hits[0][0], hits[0][1]
    for kind, getter in (('model', ed._selected), ('light', ed._selected_light),
                         ('camera', ed._selected_camera)):
        if kind in kinds:
            o = getter()
            if o is not None:
                return kind, o
    return None, None


class _Ambiguous(Exception):
    """重名歧义: 命令层拒绝执行, 提示用 index= (object_list 可看每个序号)."""

    def __init__(self, name, hits):
        super().__init__('重名 %r (匹配 %d 个, 需要 index= 指定序号, 先 run '
                         'object_list 查看): %s'
                         % (name, len(hits), [('%s#%d' % (k, i)) for k, _o, i in hits]))


def _no_target(kinds):
    return {'error': '没有目标: 传 name= 指定, 或先 object_select 选中 (可选类型: %s)'
            % '/'.join(kinds)}


def _commit(ed, kind, obj, label, apply_fn):
    """按目标类型走对应的 commit_* (与 GUI 同一条撤销路径)."""
    if kind == 'model':
        ed.commit_model(obj, label, apply_fn)
    elif kind == 'light':
        ed.commit_light(obj, label, apply_fn)
    else:
        ed.commit_camera(obj, label, apply_fn)


def _apply_fields(args, obj, spec):
    """把 args 里出现的字段写进 obj. spec = {参数名: (属性名, 转换函数)}.
    返回实际写入的 {属性: 值} (没传的参数一律不碰 —— 命令是"改我给的那些")."""
    done = {}
    for key, (attr, conv) in spec.items():
        if key not in args:
            continue
        val = conv(args[key])
        setattr(obj, attr, val)
        done[attr] = val
    return done
