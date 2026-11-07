# -*- coding: utf-8 -*-

"""多 Canvas 命中语义 (裁决 Q7=C: 只吞空白, 2026-11-07 P1-6).

背景: UIManager.hit_test 原本是 [从最上层 Canvas 往下测, 第一个命中就返回]。
screen Canvas 的 root 铺满整屏, 所以最上层 Canvas 永远命中 root —— 低一层
Canvas 上的按钮/列表/输入框永远点不到 (被顶层空白吞掉)。

Q7=C 语义 (本文件锁定的契约):
  1) 命中子元素 -> 上层优先, 立刻返回 (老行为不变);
  2) 只命中 Canvas root (空白) -> 继续下探低层 Canvas;
  3) 全部 Canvas 都没命中子元素 -> 返回最上层 Canvas 的 root (吞空白,
     空白点击仍算 UI 消费, 不漏到 3D 拾取/相机)。

这些用例在修复前会全部 FAIL (返回的都是顶层 root)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from loom_ui import (Canvas, UIManager, Panel, Button, Text, ScrollView)

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _mgr(*canvases):
    m = UIManager()
    for c in canvases:
        m.add_canvas(c)
    return m


W = H = 200

# ============ 1. 空白: 全部没命中子元素 -> 顶层 root (吞空白) ============
c_low = Canvas(width=W, height=H, z_order=0)
c_top = Canvas(width=W, height=H, z_order=10)
m = _mgr(c_low, c_top)
cv, el = m.hit_test((100, 100))
check('多层空白 -> 返回最上层 Canvas 的 root',
      cv is c_top and el is c_top.root,
      (getattr(cv, 'z_order', None), getattr(el, 'name', None)))

# ============ 2. 子元素优先: 两层都有子元素 -> 取上层 ============
b_low = Button('low_btn', rect=(0, 0, 100, 40), text='L')
b_top = Button('top_btn', rect=(0, 0, 100, 40), text='T')
c_low.root.add_child(b_low)
c_top.root.add_child(b_top)
cv, el = m.hit_test((50, 20))
check('重叠区域 -> 上层 Canvas 的子元素优先',
      cv is c_top and el is b_top,
      (getattr(cv, 'z_order', None), getattr(el, 'name', None)))

# ============ 3. 顶层空白 -> 低层子元素仍可命中 (Q7=C 核心) ============
cv, el = m.hit_test((150, 150))
check('两层都空白 -> 顶层 root (吞空白)',
      cv is c_top and el is c_top.root, getattr(el, 'name', None))
c_top.root.children.clear()
cv, el = m.hit_test((50, 20))
check('顶层空白 + 低层子元素 -> 命中的是低层按钮',
      cv is c_low and el is b_low,
      (getattr(cv, 'z_order', None), getattr(el, 'name', None)))

# ============ 4. 顶层有别的子元素时不挡低层 ============
c_top.root.children.clear()
c_top.root.add_child(Panel('top_side', rect=(0, 0, 60, 20)))
c_low.root.children.clear()
c_low.root.add_child(Button('low_btn2', rect=(100, 100, 60, 20), text='B2'))
cv, el = m.hit_test((120, 110))
check('顶层只有别处的子元素 -> 低层按钮仍命中',
      cv is c_low and getattr(el, 'name', None) == 'low_btn2',
      (getattr(cv, 'z_order', None), getattr(el, 'name', None)))
cv, el = m.hit_test((10, 10))
check('顶层子元素在其自身区域仍优先',
      cv is c_top and getattr(el, 'name', None) == 'top_side',
      (getattr(cv, 'z_order', None), getattr(el, 'name', None)))

# ============ 5. world Canvas 不参与 screen 命中 ============
m5 = UIManager()
c_screen = Canvas(width=W, height=H, z_order=0)
c_world = Canvas(canvas_type='world', width=W, height=H, z_order=99)
c_world.root.add_child(Button('world_btn', rect=(0, 0, 50, 50)))
m5.add_canvas(c_screen)
m5.add_canvas(c_world)
cv, el = m5.hit_test((10, 10))
check('world Canvas 不参与鼠标命中 (返回 screen root)',
      cv is c_screen and el is c_screen.root, getattr(el, 'name', None))

# ============ 6. 空 UIManager ============
cv, el = UIManager().hit_test((1, 1))
check('无 Canvas -> (None, None)', cv is None and el is None)

# ============ 7. dispatch_mouse: 低层按钮真能点 (修复前点不动) ============
clicks = []
m7 = UIManager()
lo = Canvas(width=W, height=H, z_order=0)
hi = Canvas(width=W, height=H, z_order=10)
hi.root.add_child(Panel('hud_bg', rect=(0, 0, 40, 40)))
btn = Button('btn_low', rect=(100, 100, 60, 30), text='OK',
             on_click=lambda: clicks.append('low'))
lo.root.add_child(btn)
m7.add_canvas(lo)
m7.add_canvas(hi)
m7.dispatch_mouse((120, 110), set(), set())
check('hover 低层按钮 (顶层空白不吞)', m7._hovered is btn,
      getattr(m7._hovered, 'name', None))
consumed = m7.dispatch_mouse((120, 110), {1}, set())
check('按下被低层按钮消费', consumed is True and btn._pressed is True)
consumed = m7.dispatch_mouse((120, 110), set(), {1})
check('低层按钮 on_click 真触发 (修复前永远不触发)',
      clicks == ['low'] and consumed is True, clicks)

# ============ 8. dispatch_mouse: 顶层子元素仍然最先响应 ============
top_clicks = []
m8 = UIManager()
lo8 = Canvas(width=W, height=H, z_order=0)
hi8 = Canvas(width=W, height=H, z_order=10)
lo8.root.add_child(Button('lo8_btn', rect=(100, 100, 60, 30),
                          on_click=lambda: clicks.append('lo8')))
hi8.root.add_child(Button('hi8_btn', rect=(100, 100, 60, 30),
                          on_click=lambda: top_clicks.append('hi8')))
m8.add_canvas(lo8)
m8.add_canvas(hi8)
m8.dispatch_mouse((120, 110), set(), set())
check('重叠时 hover 落在顶层按钮',
      getattr(m8._hovered, 'name', None) == 'hi8_btn',
      getattr(m8._hovered, 'name', None))
m8.dispatch_mouse((120, 110), {1}, set())
m8.dispatch_mouse((120, 110), set(), {1})
check('重叠时只有顶层按钮触发', top_clicks == ['hi8'] and clicks == ['low'],
      (top_clicks, clicks))

# ============ 9. update_hover_only 同规则 ============
m9 = UIManager()
lo9 = Canvas(width=W, height=H, z_order=0)
hi9 = Canvas(width=W, height=H, z_order=5)
low_txt = Text('low_txt', rect=(0, 0, 80, 20), text='t')
lo9.root.add_child(low_txt)
m9.add_canvas(lo9)
m9.add_canvas(hi9)
m9.update_hover_only((10, 10))
check('update_hover_only 能 hover 到低层元素 (顶层空白不吞)',
      m9._hovered is low_txt, getattr(m9._hovered, 'name', None))
m9.update_hover_only((190, 190))
check('空白处 hover 到顶层 root (吞空白)', m9._hovered is hi9.root,
      getattr(m9._hovered, 'name', None))

# ============ 10. 滚轮: 低层 ScrollView 也能被命中转发 ============
m10 = UIManager()
lo10 = Canvas(width=W, height=H, z_order=0)
hi10 = Canvas(width=W, height=H, z_order=10)
sv = ScrollView('sv_low', rect=(0, 0, 120, 100), content_size=(120, 600))
lo10.root.add_child(sv)
m10.add_canvas(lo10)
m10.add_canvas(hi10)
check('_hit_scroll_view 找得到低层 ScrollView',
      m10._hit_scroll_view((10, 10)) is sv,
      getattr(m10._hit_scroll_view((10, 10)), 'name', None))
_before = sv.scroll_pos[1]
consumed = m10.dispatch_mouse((10, 10), set(), set(), wheel=-1)
check('低层 ScrollView 滚轮真滚动',
      sv.scroll_pos[1] != _before and consumed is True,
      (_before, sv.scroll_pos[1], consumed))

# ============ 11. 老行为回归: 单 Canvas 子元素命中 ============
m11 = UIManager()
c11 = Canvas(width=W, height=H, z_order=0)
e11 = Text('t11', rect=(0, 0, 100, 20), text='x')
c11.root.add_child(e11)
m11.add_canvas(c11)
cv, el = m11.hit_test((10, 10))
check('单 Canvas 子元素命中 (老行为不变)', cv is c11 and el is e11,
      getattr(el, 'name', None))
cv, el = m11.hit_test((150, 150))
check('单 Canvas 空白 -> root', cv is c11 and el is c11.root,
      getattr(el, 'name', None))

print()
print('总结果:', 'ALL PASS' if ok else '有 FAIL')
sys.exit(0 if ok else 1)
