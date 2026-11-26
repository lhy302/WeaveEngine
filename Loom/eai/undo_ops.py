# -*- coding: utf-8 -*-
"""eai.undo_ops — 撤销与 Agent 批次命令

我负责：undo / redo / agent_batch_begin / agent_batch_end / agent_batch_cancel
与结果整形 (_history_result)、批次状态钩子 (_batch_status_hook)。
我不负责：UndoManager 的取用（undo_base.py）与撤销栈实现（editor/undo/）。
"""

from .helpers import as_float
from .registry import command, log
from .undo_base import _undo_manager

# ====================================================================
# 编辑 / 播放 / 视图
# ====================================================================
@command('undo', '撤销一步 (Agent 批次租约内会被拒绝并给出剩余秒数)')
def cmd_undo(win, args):
    """撤销一步. 2026-11-08 批4 (D10=B): 批次租约内的拒绝必须变成 ok=False + 原因,
    不能像旧实现那样返回 ok=True 而什么都没做（Agent 会误判"已撤销"）。"""
    res = win.editor._undo_action()
    return _history_result(res)


@command('redo', '重做一步 (Agent 批次租约内会被拒绝并给出剩余秒数)')
def cmd_redo(win, args):
    res = win.editor._redo_action()
    return _history_result(res)


def _history_result(res):
    """_undo_action/_redo_action 的返回值 -> 命令结果 (blocked/error 一律报错)."""
    if isinstance(res, dict):
        if res.get('blocked'):
            return {'ok': False, 'error': res['blocked'], 'blocked': True}
        if res.get('error'):
            return {'ok': False, 'error': res['error']}
        return {'ok': True, 'label': res.get('label') or ''}
    return {'ok': True}


def _batch_status_hook(win, um):
    """把批次租约剩余秒数推给 GUI (状态栏"Agent 批次进行中（剩余 Xs）")."""
    fn = getattr(win, '_agent_batch_status', None)
    if fn is None:
        return
    try:
        rem = um.batch_remaining() if hasattr(um, 'batch_remaining') else None
        if rem is None:
            fn(None)
        else:
            secs = int(rem) + (1 if rem > int(rem) else 0)
            fn(secs)
    except Exception as e:
        log('[agent] 批次状态钩子失败: %r' % (e,))


@command('agent_batch_begin', '开始 Agent 批次: 之后每批写命令合并为一步撤销 '
                             '{label?, lease_s?:默认30} (未 end 又 begin 会自动 cancel 旧批并告警)')
def cmd_agent_batch_begin(win, args):
    um, err = _undo_manager(win)
    if um is None:
        return {'error': err}
    # 2026-11-08 批4 (D10=A): 先让"已过租约"的悬挂批自动收口 (end_batch, 历史保留),
    # 再做"仍活着"的悬挂判定 —— 旧实现在这里直接 cancel, 把整批历史丢掉。
    closed = um.tick_batch() if hasattr(um, 'tick_batch') else None
    if closed is not None:
        log('[命令] agent_batch_begin: 上一批次租约到期, 已收口为一步 (%d 条)'
            % len(getattr(closed, 'cmds', ()) or ()))
    stale = bool(getattr(um, 'batch_active', False))
    if stale:
        # 租约还没到、上一批也没 end: 仍按原契约丢弃 (deny 半批), 并写日志告警
        um.cancel_batch()
        log('[命令] agent_batch_begin: 上一批次未 end, 已自动 cancel (防悬挂)')
    label = args.get('label') or 'Agent 批次'
    lease = None
    if args.get('lease_s') is not None:
        lease = as_float(args.get('lease_s'), 0.0)
    try:
        # absorb=False: 只吸"Agent 命令作用域"内的写命令, 用户编辑不进批 (D10-A)
        um.begin_batch(label, lease_s=lease, absorb=False)
    except TypeError:            # 兼容没有租约参数的旧 UndoManager
        um.begin_batch(label)
    _batch_status_hook(win, um)
    return {'batch': True, 'label': label,
            # 契约键 (docs/audit/fix_agent_visual_pacing_batch_focus.md §4): had_stale
            'had_stale': stale,
            # 兼容别名 (2026-11-07 实现里用的键; 保留以免破坏既有调用方)
            'cancelled_stale': stale,
            'closed_stale': (getattr(closed, 'label', None)
                             if closed is not None else None),
            'lease_s': getattr(um, 'batch_lease_s', None)}


@command('agent_batch_end', '结束 Agent 批次: 批内全部命令合成一步撤销 (不重复执行)')
def cmd_agent_batch_end(win, args):
    um, err = _undo_manager(win)
    if um is None:
        return {'error': err}
    if not getattr(um, 'batch_active', False):
        return {'error': '没有进行中的批次 (先 agent_batch_begin)'}
    n = int(getattr(um, 'batch_size', 0))
    batch = um.end_batch()
    _batch_status_hook(win, um)
    return {'batch': False, 'commands': n,
            'label': getattr(batch, 'label', None) if batch is not None else None,
            'undoable': batch is not None}


@command('agent_batch_cancel', '取消 Agent 批次: 丢弃批记录 (已执行的修改不回滚)')
def cmd_agent_batch_cancel(win, args):
    um, err = _undo_manager(win)
    if um is None:
        return {'error': err}
    n = um.cancel_batch() if getattr(um, 'batch_active', False) else 0
    _batch_status_hook(win, um)
    return {'batch': False, 'cancelled': n}
