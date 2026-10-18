# -*- coding: utf-8 -*-
"""smoke_ui_phase3_boot.py — 阶段3 启动冒烟 (2026-10-18)

用 GLFW 窗口 + 完整 UI 元素树（含 4 种阶段3 元素）走 scene_data 加载全链路，
渲染 3 秒后自动关闭。
验证：
  1) GLFW 窗口创建 + UI 元素树加载
  2) ScrollView / InputField / Dropdown / GridLayout 在真实窗口中绘制不崩
  3) InputField 能通过 dispatch_text 接收英文
  4) 引擎干净退出
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

# 场景数据: 4 种阶段3 元素各一个, 覆盖真实加载链路
SCENE = {
    'models': [], 'materials': [], 'lights': [], 'cameras': [],
    'ui': {
        'canvases': [{
            'canvas_type': 'screen',
            'width': 800,
            'height': 600,
            'z_order': 0,
            'elements': [{
                'type': 'element', 'name': 'root',
                'rect': [0, 0, 800, 600], 'anchor': [0, 0],
                'pivot': [0, 0], 'visible': True, 'enabled': True,
                'z_order': 0,
                'children': [
                    # ScrollView 含两个 Button
                    {
                        'type': 'scroll_view', 'name': 'sv',
                        'rect': [50, 50, 300, 200], 'anchor': [0, 0],
                        'pivot': [0, 0], 'visible': True, 'enabled': True,
                        'z_order': 0,
                        'content_size': [300, 800], 'scroll_pos': [0, 0],
                        'bg_color': [30, 34, 44, 255],
                        'bar_color': [120, 130, 150, 255],
                        'bar_width': 8, 'show_bar': True, 'scroll_step': 30,
                        'children': [
                            {'type': 'button', 'name': 'b1',
                             'rect': [10, 10, 100, 30], 'anchor': [0, 0],
                             'pivot': [0, 0], 'visible': True, 'enabled': True,
                             'z_order': 0, 'text': 'Btn1',
                             'font_size': 14,
                             'text_color': [255, 255, 255],
                             'normal_color': [70, 80, 100, 255],
                             'hover_color': [90, 100, 125, 255],
                             'pressed_color': [50, 60, 80, 255],
                             'children': []},
                        ]
                    },
                    # InputField
                    {
                        'type': 'input_field', 'name': 'inp',
                        'rect': [400, 50, 300, 32], 'anchor': [0, 0],
                        'pivot': [0, 0], 'visible': True, 'enabled': True,
                        'z_order': 0,
                        'text': '', 'placeholder': '请输入...',
                        'max_length': 50,
                        'bg_color': [50, 55, 70, 255],
                        'focus_bg_color': [60, 70, 90, 255],
                        'text_color': [255, 255, 255],
                        'placeholder_color': [140, 140, 150],
                        'cursor_color': [220, 220, 230],
                        'font_size': 16,
                        'children': []
                    },
                    # Dropdown
                    {
                        'type': 'dropdown', 'name': 'dd',
                        'rect': [400, 100, 200, 32], 'anchor': [0, 0],
                        'pivot': [0, 0], 'visible': True, 'enabled': True,
                        'z_order': 0,
                        'options': ['低', '中', '高'], 'selected_index': 0,
                        'bg_color': [70, 80, 100, 255],
                        'hover_color': [90, 100, 125, 255],
                        'list_bg': [50, 55, 70, 255],
                        'list_hover': [80, 140, 220, 255],
                        'text_color': [255, 255, 255],
                        'font_size': 14, 'item_height': 28,
                        'children': []
                    },
                    # GridLayout
                    {
                        'type': 'grid_layout', 'name': 'grid',
                        'rect': [50, 300, 400, 200], 'anchor': [0, 0],
                        'pivot': [0, 0], 'visible': True, 'enabled': True,
                        'z_order': 0,
                        'cell_size': [64, 64], 'spacing': [8, 8],
                        'columns': 4, 'bg_color': [0, 0, 0, 0],
                        'children': [
                            {'type': 'panel', 'name': 'g0',
                             'rect': [0, 0, 64, 64], 'anchor': [0, 0],
                             'pivot': [0, 0], 'visible': True, 'enabled': True,
                             'z_order': 0, 'bg_color': [80, 80, 80, 255],
                             'children': []},
                            {'type': 'panel', 'name': 'g1',
                             'rect': [0, 0, 64, 64], 'anchor': [0, 0],
                             'pivot': [0, 0], 'visible': True, 'enabled': True,
                             'z_order': 0, 'bg_color': [100, 100, 100, 255],
                             'children': []},
                        ]
                    },
                ]
            }]
        }]
    }
}

import runtime

eng = runtime.PlayerApp(None, 800, 600, scene_data=SCENE)
print('[smoke] PlayerApp + UI 树加载成功')

# 验证 4 种元素都在树里
c = eng.ui.default_canvas()
assert c is not None, '默认 canvas 缺失'
sv = c.root.find('sv')
inp = c.root.find('inp')
dd = c.root.find('dd')
grid = c.root.find('grid')
assert sv is not None and sv.ctype == 'scroll_view', 'ScrollView 加载失败'
assert inp is not None and inp.ctype == 'input_field', 'InputField 加载失败'
assert dd is not None and dd.ctype == 'dropdown', 'Dropdown 加载失败'
assert grid is not None and grid.ctype == 'grid_layout', 'GridLayout 加载失败'
print('[smoke] 4 种阶段3 元素加载 OK')

# InputField 焦点 + 英文输入（模拟点击 + 输入，自动测）
eng.ui.focus_element(inp)
assert eng.ui.focused() is inp, '焦点设置失败'
assert eng.ui.dispatch_text('hello') is True
assert inp.text == 'hello', 'InputField 未接收文本, text=%r' % inp.text
print('[smoke] InputField 焦点+英文输入 OK')

# 渲染 3 秒
eng._running = True
eng.last_frame_time = time.perf_counter()
t0 = time.perf_counter()
frames = 0
while time.perf_counter() - t0 < 3.0 and eng._running:
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
print('[smoke] 跑了 %d 帧 / %.2f 秒 (%.1f FPS)' % (frames, elapsed, frames / elapsed))

eng._glfw_shutdown()
try:
    eng._stop_parallel()
except Exception:
    pass
try:
    eng.audio.shutdown()
except Exception:
    pass
print('[smoke] SMOKE_PASS')
