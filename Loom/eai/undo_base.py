# -*- coding: utf-8 -*-
"""eai.undo_base — 撤销管理器取用（共享前置）

我负责：从 win 取 UndoManager 并校验批次能力 (_undo_manager)。
我不负责：撤销/批次命令本身（见 undo_ops.py）。
"""

# ---- 批次撤销 (2026-11-07 D: Agent 一整批操作一键撤销) ----
def _undo_manager(win):
    """取编辑器实例上的 UndoManager; 不可用时返回 (None, 错误串).
    (不直接写 win.editor.undo —— 命令层 API 静态扫描会把这种写法当成方法调用)"""
    ed = getattr(win, 'editor', None)
    um = getattr(ed, 'undo', None)
    if um is None:
        return None, '编辑器没有 undo 管理器 (undo 缺失)'
    for name in ('begin_batch', 'end_batch', 'cancel_batch'):
        if not hasattr(um, name):
            return None, 'UndoManager 不支持批次 (缺 %s)' % name
    return um, None
