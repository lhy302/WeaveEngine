# -*- coding: utf-8 -*-
"""Canvas UI 基础测试 (2026-10-18, 替换 M33 RuntimeUI 测试).

覆盖: UIElement 布局/anchor/pivot, Panel/Text/Image 绘制调用,
      UIManager 多 Canvas + draw_all, 命中测试.
不画 GPU (桩 engine 只记录调用).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom_ui import (UIElement, Canvas, UIManager, Panel, Text)


ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


# ---- 布局: anchor/pivot ----
PARENT = (100.0, 50.0, 400.0, 300.0)
e = UIElement('a', rect=(10, 20, 100, 40), anchor=(0, 0), pivot=(0, 0))
check("左上对齐", e.screen_rect(PARENT) == (110.0, 70.0, 100.0, 40.0))

e = UIElement('b', rect=(0, 0, 100, 40), anchor=(1, 1), pivot=(1, 1))
check("右下对齐", e.screen_rect(PARENT) == (400.0, 310.0, 100.0, 40.0))

e = UIElement('c', rect=(0, 0, 100, 40), anchor=(0.5, 0.5), pivot=(0.5, 0.5))
sr = e.screen_rect(PARENT)
check("居中", abs(sr[0] - 250.0) < 1e-6 and abs(sr[1] - 180.0) < 1e-6)


# ---- 树 + 查找 ----
root = UIElement('root', rect=(0, 0, 400, 300))
p1 = UIElement('p1', rect=(0, 0, 200, 100))
t1 = Text('t1', rect=(10, 10, 100, 20), text='hello')
root.add_child(p1)
p1.add_child(t1)
check("find 命中", root.find('t1') is t1)
check("find 未命中", root.find('nope') is None)
check("walk 顺序", [n.name for n in root.walk()] == ['root', 'p1', 't1'])


# ---- 桩 engine ----
class _StubEngine:
    def __init__(self):
        self.rect_calls = []
        self.text_calls = []

    def draw_screen_rect(self, rect, color):
        self.rect_calls.append((rect, color))

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        self.text_calls.append((text, x, y, size))

    def _measure_text(self, text, size=None):
        return (len(text) * 10, 18)


eng = _StubEngine()

# ---- Panel 绘制 ----
panel = Panel('p', rect=(10, 10, 100, 50), bg_color=(255, 0, 0, 128))
panel.draw(eng, (10, 10, 100, 50))
check("Panel 绘制", len(eng.rect_calls) == 1 and
      eng.rect_calls[0][1] == (255, 0, 0, 128))

# ---- Text 对齐 ----
eng.text_calls.clear()
t = Text('t', rect=(0, 0, 200, 30), text='Hello', font_size=16)
t.draw(eng, (5, 5, 200, 30))
check("Text left 对齐", eng.text_calls[0][1] == 5)

eng.text_calls.clear()
t.align = 'center'
t.draw(eng, (0, 0, 200, 30))
check("Text center 对齐", eng.text_calls[0][1] == 75)

# ---- Text 自动换行 ----
eng.text_calls.clear()
tw = Text('tw', rect=(0, 0, 100, 100), text='abcdefghij', wrap_width=30)
lines = tw._wrap_lines(eng)
check("Text 自动换行 (每行 3 字符)", lines == ['abc', 'def', 'ghi', 'j'], str(lines))

# ---- UIManager 多 Canvas + draw_all ----
m = UIManager()
c1 = Canvas(width=200, height=200, z_order=0)
c2 = Canvas(width=200, height=200, z_order=10)
c1.root.add_child(Text('a', rect=(0, 0, 100, 20), text='A'))
c2.root.add_child(Text('b', rect=(0, 0, 100, 20), text='B'))
m.add_canvas(c1)
m.add_canvas(c2)
eng.text_calls.clear()
m.draw_all(eng)
check("draw_all 按 z_order 画两个 Canvas",
      [c[0] for c in eng.text_calls] == ['A', 'B'],
      str([c[0] for c in eng.text_calls]))

# ---- 命中测试 ----
hit_canvas, hit_elem = m.hit_test((50, 10))
check("hit_test 命中顶层 Canvas", hit_canvas is c2 and hit_elem.name == 'b')

# ---- default_canvas ----
m2 = UIManager()
dc = m2.default_canvas()
check("default_canvas 自动创建", dc is not None and dc.canvas_type == 'screen')

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
