# -*- coding: utf-8 -*-
"""eai.app_ops — 应用级命令

我负责：quit / status / screenshot 三条应用级命令。
我不负责：场景/对象等编辑命令。
"""

import os
import sys
from .helpers import as_float
from .registry import command
from .whitelist import _safe_write_path

# ====================================================================
# 系统/视图
# ====================================================================
@command('quit', '退出编辑器: {save?=save|discard|cancel, after?} '
                  '({save} 只给 Agent 自动退出用; 你手敲 quit 就行)')
def cmd_quit(win, args):
    """延时关闭 (先把 HTTP 响应发回 Agent 再关窗口).
    2026-08-28 修复 (用户报告): 没保存直接关引擎会弹"是否保存"对话框 ——
    GUI 里那是保护, 但**远程 Agent** 下弹的是模态框: 窗口卡死在 ask() 上,
    命令永远等不到结果. 故 Agent 链路把三态决策显式化 (同一《A01 三态》契约):
      save=save     -> 先保存 (有路径直接存; 无路径报错退出中止)
      save=discard  -> 丢弃改动直接关 (跳过询问)
      save=cancel   -> 中止退出 (返回 ok, 不关窗口)
    不传 save 且场景脏 (= 人在编辑器里手敲 quit, 或浏览器试): 按 GUI 语义
    正常关窗口, 让 closeEvent 弹三态框给你选 —— 只有人有空去选才该弹框;
    Agent 不想弹框就明确给 save= (先 status 看 dirty 决策)."""
    ed = getattr(win, 'editor', None)
    dirty = False
    if ed is not None and hasattr(ed, 'scene_is_dirty'):
        try:
            dirty = bool(ed.scene_is_dirty())
        except Exception:
            dirty = False
    resolve = 'none'        # dirty 决断: 'save' | 'discard' | 'cancel'
    if dirty:
        choice = (args.get('save') or '').strip().lower()
        if choice == 'cancel':
            return {'quitting': False, 'dirty': True, 'cancelled': True}
        if choice == 'discard':
            resolve = 'discard'
        elif choice == 'save':
            path = args.get('path')
            if path:
                ok, full = _safe_write_path(path, 'quit save', win)
                if not ok:
                    return {'error': full}
                path = full
                if not ed._save_scene(path):
                    return {'error': '保存失败: %s (退出已中止)' % path}
            elif getattr(ed, '_scene_path', None):
                ed.save_scene()
            else:
                return {'error': '未保存改动且无场景文件: 传 save=discard 丢弃, '
                                 '或 path= 指定保存位置 (退出已中止)'}
            resolve = 'save'
        else:
            # 缺省= GUI 弹框默认项语义: 有对应文件先保存, 没文件只能丢弃
            # (命令行绝不弹模态框 —— 模态框会卡死命令链, 用户实测指出的问题)
            if getattr(ed, '_scene_path', None):
                ed.save_scene()
                resolve = 'save'
            else:
                resolve = 'discard'
    delay = as_float(args.get('after', 0.15), 0.15)
    # dirty 已由命令层决断 (save/discard): 关窗前先给窗口挂"跳过弹框"标记,
    # closeEvent 照此跳过 _confirm_unsaved —— 否则 win.close() 会在 closeEvent
    # 里弹"是否保存"模态框**再次**卡死整个链 (用户 2026-08-28 实测直接指出).
    try:
        if dirty:
            win._suppress_confirm = True      # qt_view.closeEvent 认这个标记
    except Exception:
        pass
    delay = as_float(args.get('after', 0.15), 0.15)
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            QTimer.singleShot(int(delay * 1000), win.close)
            return {'quitting': True, 'after': delay, 'dirty': dirty,
                    'resolved': resolve}
    except Exception:
        pass
    win.close()
    return {'quitting': True, 'after': 0, 'immediate': True, 'dirty': dirty,
            'resolved': resolve}


@command('status', '引擎状态摘要 (物体/光源/相机/选中/相机参数/帧率)')
def cmd_status(win, args):
    import math
    ed = win.editor
    sel = ed._selected() or ed._selected_light() or ed._selected_camera()
    fps = getattr(getattr(win, 'viewport', None), '_fps', None) or \
          getattr(win, '_fps', None)
    return {
        'scene': getattr(ed, 'scene_name', getattr(ed, 'name', None)),
        'models': [m.name for m in ed.models],
        'lights': [l.name for l in ed.lights],
        'cameras': [c.name for c in ed.cameras],
        'selected': getattr(sel, 'name', None),
        'playing': bool(getattr(ed, 'is_playing',
                                getattr(ed, 'playing', False))),
        # 未保存改动 (quit 前置检查; 2026-08-28): Agent 先 status 看到 dirty,
        # 退出时才不会撞上"是否保存"模态框
        'dirty': bool(ed.scene_is_dirty()) if hasattr(ed, 'scene_is_dirty') else False,
        'fps': fps,
        'camera': {'target': list(ed.camera_target),
                   'distance': ed.camera_distance,
                   'yaw_deg': round(math.degrees(ed.camera_yaw), 1),
                   'pitch_deg': round(math.degrees(ed.camera_pitch), 1)},
    }


@command('screenshot', '视口截图存 PNG, save 返回文件路径 (白名单外拒绝; '
                       'full=true 抓整窗含工具栏/状态栏 FPS|TPS)')
def cmd_screenshot(win, args):
    from scene.identity import new_guid   # Q-B7-49-1 P2: 随机身份唯一真源
    out = args.get('file')
    if not out:
        out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                           '保存', 'shot_%s.png' % new_guid()[:8])
    else:
        ok, full = _safe_write_path(out, 'screenshot', win)
        if not ok:
            return {'error': full}
        out = full
    if args.get('full'):
        img = win.grab().toImage()       # 整窗 (含状态栏 FPS|TPS 读数)
    else:
        img = win.viewport.grab().toImage()
    if not img.save(out):
        return {'error': '截图保存失败: %s' % out}
    return {'file': out, 'size': [img.width(), img.height()]}
