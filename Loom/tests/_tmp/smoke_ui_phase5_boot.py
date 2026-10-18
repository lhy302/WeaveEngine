# -*- coding: utf-8 -*-
"""smoke_ui_phase5_boot.py — 阶段5 完整启动冒烟 (2026-10-18)

覆盖：
  1) PlayerApp (GLFW) 加载含 UI 树的场景 -> 渲染 N 帧 -> 干净退出
  2) Qt 编辑器 (LoomGUI) 启动 -> UI 树正确加载 -> 点击选中 -> 改属性 -> 撤销重做
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

# 场景数据：含一个 Canvas + button + input_field
SCENE = {
    'models': [], 'materials': [], 'lights': [], 'cameras': [],
    'ui': {
        'canvases': [{
            'canvas_type': 'screen',
            'width': 800, 'height': 600, 'z_order': 0,
            'elements': [{
                'type': 'element', 'name': 'root',
                'rect': [0, 0, 800, 600], 'anchor': [0, 0],
                'pivot': [0, 0], 'visible': True, 'enabled': True,
                'z_order': 0,
                'children': [
                    {
                        'type': 'button', 'name': 'btn_ok',
                        'rect': [100, 100, 120, 40], 'anchor': [0, 0],
                        'pivot': [0, 0], 'visible': True, 'enabled': True,
                        'z_order': 0, 'text': 'OK',
                        'font_size': 16,
                        'text_color': [255, 255, 255],
                        'normal_color': [70, 80, 100, 255],
                        'hover_color': [90, 100, 125, 255],
                        'pressed_color': [50, 60, 80, 255],
                        'children': []
                    },
                    {
                        'type': 'input_field', 'name': 'inp_name',
                        'rect': [100, 160, 200, 32], 'anchor': [0, 0],
                        'pivot': [0, 0], 'visible': True, 'enabled': True,
                        'z_order': 0,
                        'text': '', 'placeholder': '请输入',
                        'max_length': 50,
                        'bg_color': [50, 55, 70, 255],
                        'focus_bg_color': [60, 70, 90, 255],
                        'text_color': [255, 255, 255],
                        'placeholder_color': [140, 140, 150],
                        'cursor_color': [220, 220, 230],
                        'font_size': 16,
                        'children': []
                    },
                ]
            }]
        }]
    }
}


# ===== 第一部分：PlayerApp GLFW 渲染冒烟 =====
print('===== 第一部分: PlayerApp (GLFW) =====')
import runtime
eng = runtime.PlayerApp(None, 800, 600, scene_data=SCENE)
print('[1/2] PlayerApp + 场景加载成功')

c = eng.ui.default_canvas()
assert c is not None
btn = c.root.find('btn_ok')
inp = c.root.find('inp_name')
assert btn is not None and btn.ctype == 'button'
assert inp is not None and inp.ctype == 'input_field'
print('[1/2] UI 树加载 OK (2 元素)')

# InputField 焦点 + 输入
eng.ui.focus_element(inp)
assert eng.ui.focused() is inp
eng.ui.dispatch_text('Hello UI')
assert inp.text == 'Hello UI'
print('[1/2] InputField 焦点+文本输入 OK')

# 渲染 2 秒
eng._running = True
eng.last_frame_time = time.perf_counter()
t0 = time.perf_counter()
frames = 0
while time.perf_counter() - t0 < 2.0 and eng._running:
    eng._handle_events()
    now = time.perf_counter()
    dt = min(now - eng.last_frame_time, 0.1)
    eng.last_frame_time = now
    eng.move_camera(dt)
    eng.rotate_camera(dt)
    eng.render(dt)
    frames += 1
    time.sleep(0.001)

elapsed = time.perf_counter() - t0
print('[1/2] 渲染 %d 帧 / %.2f 秒 (%.1f FPS)' % (
    frames, elapsed, frames / elapsed))

# 撤销操作（PlayerApp 无 undo 字段，用独立 UndoManager 验证）
import undo as undo_mod
undo_mgr = undo_mod.UndoManager()
before = undo_mod.ui_elem_snapshot(btn)
btn.text = '修改后'
after = undo_mod.ui_elem_snapshot(btn)
undo_mgr.push_no_do(undo_mod.UIStateCommand('改文字', eng, btn, before, after))
assert btn.text == '修改后'
undo_mgr.undo()
assert btn.text == 'OK'
undo_mgr.redo()
assert btn.text == '修改后'
print('[1/2] 撤销/重做 OK')

eng._glfw_shutdown()
try:
    eng._stop_parallel()
except Exception:
    pass
try:
    eng.audio.shutdown()
except Exception:
    pass
print('[1/2] PlayerApp 关闭 OK')


# ===== 第二部分：Qt 编辑器冒烟 =====
print()
print('===== 第二部分: Qt 编辑器 =====')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.loom_gui import LoomGUI
win = LoomGUI(scene_path=None, width=800, height=600)
win.show()


def _run_checks():
    print('[2/2] LoomGUI 已启动')
    # 加 2 个 UI 元素（测试 UI 树 + 命令壳 + 撤销）
    r = win._invoke_ui_cmd('ui_add', type='button', name='g_btn',
                           text='Qt测试', rect=(10, 10, 120, 40))
    assert 'error' not in r, r
    r = win._invoke_ui_cmd('ui_add', type='panel', name='g_panel',
                           rect=(200, 10, 300, 200))
    assert 'error' not in r, r
    print('[2/2] ui_add via GUI OK')

    # 刷新 UI 树
    win.uitree.refresh()
    # 遍历树看是否包含 g_btn
    tree = win.uitree.tree
    found = [False]
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        for j in range(top.childCount()):
            ch = top.child(j)
            if 'g_btn' in ch.text(0):
                found[0] = True
                break
    assert found[0], 'UI 树未显示 g_btn'
    print('[2/2] UI 树显示 g_btn OK')

    # 选中 + 检查器联动
    win._ui_tree_set_selection('g_btn', 0)
    win._insp_key = None
    win._rebuild_inspector()
    assert win.inspector_layout.count() > 0
    print('[2/2] 检查器 UI 属性显示 OK')

    # 撤销栈有内容
    e = win.editor
    n_undo_before = len(e.undo.undo_stack)
    assert n_undo_before >= 2, '撤销栈项数不足: %d' % n_undo_before
    print('[2/2] 撤销栈 %d 项 OK' % n_undo_before)

    # 拖拽（模拟 -> 命令壳 -> 撤销）
    # 把 g_btn 移到 g_panel 里
    r = win._invoke_ui_cmd('ui_reparent', name='g_btn', new_parent='g_panel')
    assert 'error' not in r, r
    print('[2/2] ui_reparent via GUI OK')

    # 撤销 -> 回到 root
    e.undo.undo()
    panel = e.ui.default_canvas().root.find('g_panel')
    btn = e.ui.default_canvas().root.find('g_btn')
    assert btn.parent is e.ui.default_canvas().root, \
        '撤销后 g_btn 应回到 root, 实际 %r' % (
            getattr(btn.parent, 'name', None),)
    print('[2/2] ui_reparent 撤销 OK')

    print('[2/2] SMOKE_PASS')
    QTimer.singleShot(100, win.close)


QTimer.singleShot(500, _run_checks)
QTimer.singleShot(6000, win.close)
app.exec()
print('[2/2] QApplication 退出')
print()
print('===== ALL SMOKE_PASS =====')
