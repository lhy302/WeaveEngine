# -*- coding: utf-8 -*-
"""smoke_sandbox_shape.py — 沙盘 2D 绘制冒烟 (2026-10-20)

覆盖:
  A) Shape 类存在，字段正确
  B) engine 有 draw_screen_lines / draw_screen_polygon
  C) ui_add 支持 4 种 shape_type（line/polyline/polygon/circle）
  D) ui_set 可改 shape 字段
  E) 序列化往返（_emit_ui_element -> _apply_ui_element）
  F) MCP 有 3 个沙盘快捷工具（loom_ui_add_line/polygon/circle）
  G) 无头 GL 渲染验证（画一条线，读回像素确认真的画出来了）
"""
import io, os, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BASE)
os.chdir(BASE)

fails = []
def check(label, cond, detail=''):
    msg = ('PASS ' if cond else 'FAIL ') + label
    if detail:
        msg += '  ' + str(detail)
    print(msg)
    if not cond:
        fails.append(label)


# ============ A) Shape 类 ============
import loom_ui
check('A1) Shape 类存在', hasattr(loom_ui, 'Shape'))
if hasattr(loom_ui, 'Shape'):
    s = loom_ui.Shape(name='t', rect=(0, 0, 100, 100),
                      shape_type='line', points=[[0, 0], [100, 100]])
    check('A2) ctype=shape', s.ctype == 'shape')
    check('A3) shape_type 默认 line', s.shape_type == 'line')
    check('A4) stroke_width 默认 2', s.stroke_width == 2)
    # 非法 shape_type 回退
    s2 = loom_ui.Shape(shape_type='invalid_type')
    check('A5) 非法 shape_type 回退 line', s2.shape_type == 'line')


# ============ B) engine 有屏幕空间助手 ============
from engine import GLEngine
check('B1) engine 有 draw_screen_lines', hasattr(GLEngine, 'draw_screen_lines'))
check('B2) engine 有 draw_screen_polygon', hasattr(GLEngine, 'draw_screen_polygon'))
check('B3) engine 有 _px_to_ndc', hasattr(GLEngine, '_px_to_ndc'))


# ============ C/D) ui_add / ui_set（用 mock 编辑器） ============
class _MockCanvas:
    def __init__(self):
        self.root = loom_ui.UIElement(name='root', rect=(0, 0, 1280, 720))
        self.canvas_type = 'screen'
        self.width = 1280
        self.height = 720

class _MockUI:
    def __init__(self):
        self.canvases = [_MockCanvas()]

class _MockEditor:
    def __init__(self):
        self.ui = _MockUI()
        self.undo = None

class _MockWin:
    def __init__(self):
        self.editor = _MockEditor()

import agent_commands as ac

win = _MockWin()

# ui_add type=shape（4 种）
r1 = ac.cmd_ui_add(win, {'type': 'shape', 'name': 'test_line',
                         'shape_type': 'line',
                         'points': [[0, 0], [100, 50]],
                         'rect': [10, 10, 100, 50],
                         'stroke_color': '#FF0000'})
check('C1) ui_add shape line', r1.get('name') == 'test_line', r1)

r2 = ac.cmd_ui_add(win, {'type': 'shape', 'name': 'test_circle',
                         'shape_type': 'circle', 'radius': 30,
                         'rect': [200, 200, 60, 60],
                         'stroke_color': [255, 255, 0, 255]})
check('C2) ui_add shape circle', r2.get('name') == 'test_circle', r2)

r3 = ac.cmd_ui_add(win, {'type': 'shape', 'name': 'test_polygon',
                         'shape_type': 'polygon',
                         'points': [[0, 0], [50, 0], [25, 50]],
                         'rect': [300, 300, 50, 50],
                         'fill_color': '#00FF00'})
check('C3) ui_add shape polygon', r3.get('name') == 'test_polygon', r3)

r4 = ac.cmd_ui_add(win, {'type': 'shape', 'name': 'test_polyline',
                         'shape_type': 'polyline',
                         'points': [[0, 0], [10, 10], [20, 0], [30, 10]],
                         'rect': [400, 400, 30, 10]})
check('C4) ui_add shape polyline', r4.get('name') == 'test_polyline', r4)

# ui_set shape 字段
rs = ac.cmd_ui_set(win, {'name': 'test_line', 'stroke_width': 5,
                         'stroke_color': '#0000FF'})
check('D1) ui_set shape stroke_width', rs.get('changed', {}).get('stroke_width') == 5, rs)

rs2 = ac.cmd_ui_set(win, {'name': 'test_circle', 'radius': 50})
check('D2) ui_set shape radius', rs2.get('changed', {}).get('radius') == 50.0, rs2)


# ============ E) 序列化往返 ============
import sceneio
elem = win.editor.ui.canvases[0].root.find('test_polygon')
d = sceneio._emit_ui_element(elem)
check('E1) 序列化含 shape_type', d.get('shape_type') == 'polygon', d.get('shape_type'))
check('E2) 序列化含 fill_color', d.get('fill_color') is not None,
      d.get('fill_color'))

restored = sceneio._apply_ui_element(d)
check('E3) 反序列化非 None', restored is not None)
check('E4) 反序列化 shape_type 一致',
      restored.shape_type == 'polygon',
      restored.shape_type if restored else None)
check('E5) 反序列化 points 一致',
      restored.points == elem.points if restored else False,
      (restored.points if restored else None))


# ============ F) MCP 沙盘工具 ============
mcp_src = open(os.path.join(BASE, 'loom_mcp.py'), 'r', encoding='utf-8').read()
for t in ['loom_ui_add_line', 'loom_ui_add_polygon', 'loom_ui_add_circle']:
    check('F) MCP 有 %s' % t, ("'name': '%s'" % t) in mcp_src)


# ============ G) 无头 GL 渲染验证 ============
try:
    import moderngl
    import numpy as np
    ctx = moderngl.create_standalone_context(require=330)
    w, h = 100, 100
    fbo = ctx.framebuffer(
        color_attachments=[ctx.texture((w, h), 4)],
        depth_attachment=ctx.depth_texture((w, h)))
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)

    # 用 engine.draw_screen_lines 的内部逻辑（不依赖完整 GLEngine 实例）
    # 直接构造 line program + 顶点
    from loom_shaders import _LINE_VERT, _LINE_FRAG
    prog = ctx.program(vertex_shader=_LINE_VERT, fragment_shader=_LINE_FRAG)
    # 从 (10, 50) 画到 (90, 50) 一条红色横线
    def px_to_ndc(px, py, w, h):
        return (px / w * 2.0 - 1.0, 1.0 - py / h * 2.0)
    p0 = px_to_ndc(10, 50, w, h)
    p1 = px_to_ndc(90, 50, w, h)
    verts = np.array([
        [p0[0], p0[1], 0.0, 1.0, 0.0, 0.0, 1.0],  # 红
        [p1[0], p1[1], 0.0, 1.0, 0.0, 0.0, 1.0],
    ], dtype='f4')
    vbo = ctx.buffer(verts.tobytes())
    vao = ctx.vertex_array(prog, [(vbo, '3f 4f', 'in_pos', 'in_color')])
    prog['u_view_proj'].write(np.eye(4, dtype='f4').tobytes())
    ctx.line_width = 2.0
    vao.render(moderngl.LINES, vertices=2)

    # 读回：检查 (50, 50) 附近有红色像素
    data = fbo.read(components=3, alignment=1)
    px = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
    # 翻转 Y（GL 输出 y 从下往上）
    red_found = False
    for y in range(40, 60):
        r_, g_, b_ = px[y, 50]
        if r_ > 200 and g_ < 100 and b_ < 100:
            red_found = True
            break
    check('G1) 无头 GL 画线 + 读回像素成功', red_found,
          '没找到红色像素')
except Exception as e:
    check('G1) 无头 GL 画线 + 读回像素成功', False, repr(e))


print()
if fails:
    print('===== 失败 %d 项 =====' % len(fails))
    for f in fails:
        print('  -', f)
    sys.exit(1)
print('===== 全部通过 =====')
