# -*- coding: utf-8 -*-
"""eai.ui_common — UI 命令共享前置

我负责：Canvas 定位 (_ui_canvas) 与 UI 编辑撤销入口 (_push_ui_undo)。
我不负责：任何 UI 命令（见 ui_canvas_ops.py / ui_element_ops.py / ui_event_ops.py）。
"""

from .helpers import as_float

def _push_ui_undo(win, cmd, auto_do=True):
    """UI 编辑撤销入口（2026-10-18 阶段5）.

    auto_do=True : 通过 undo.push 执行 cmd.do() 并压栈（默认，用于 ui_add/ui_remove）
    auto_do=False: 通过 undo.push_no_do 只压栈（用于 ui_set，字段已改完只需记录快照差异）

    2026-10-18 修复：无 undo_mgr 环境（PlayerApp 无撤销 / 冒烟桩）时：
      - auto_do=True : 手动执行 cmd.do() 完成实际修改（否则元素根本不会加/删）
      - auto_do=False: 跳过 do()（ui_set 已 setattr 完，幂等重复也无害但不必）
    """
    ed = getattr(win, 'editor', None)
    undo_mgr = getattr(ed, 'undo', None) if ed is not None else None
    if undo_mgr is None:
        if auto_do:
            try:
                cmd.do()
            except Exception:
                pass
        return
    try:
        if auto_do:
            undo_mgr.push(cmd)
        else:
            undo_mgr.push_no_do(cmd)
    except Exception:
        pass


def _ui_canvas(win, args):
    """按 args['canvas'] 取 Canvas（缺省=第 0 个）. 找不到返回 None."""
    ui = getattr(win.editor, 'ui', None)
    if ui is None or not ui.canvases:
        return None
    idx = int(as_float(args.get('canvas', 0), 0))
    if idx < 0 or idx >= len(ui.canvases):
        return None
    return ui.canvases[idx]
