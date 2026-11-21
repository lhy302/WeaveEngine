# -*- coding: utf-8 -*-
"""test_vk_ui_input.py — Vk 播放器 UI 输入分发对齐 GL (2026-11-06 R3)

覆盖:
  1. UIInputBridge (render/vk/ui.py) 的鼠标/键盘/文本事件 -> UIManager 与 GL 路径
     (editor._dispatch_ui_mouse / loom_glfw_window._on_key_cb 的直调等价物)
     **逐步状态一致**: Button 点击回调、Slider 拖动值、InputField 输入/提交、
     焦点元素、hover 元素、每帧 consumed 标记.
  2. 相机门控: UI 消费点击/拖动时 wants_camera()=False, 纯 hover/空白时=True.
  3. 静态断言 (Q-B7-34-3): 生产代码里没有 UIInputBridge.on_key / on_text 的调用方
     —— 键/文本只能走内核; 宿主直调 = 绕过内核的第二个 UI 写者, 行为门抓不到.

本测试无 GPU / 无窗口, 只碰 loom_ui 的数据层 (与后端无关).
"""
import atexit as _atexit
import os as _os
import sys as _sys

try:
    _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _os.path.dirname(HERE))
_os.environ.setdefault('LOOM_NO_PARALLEL', '1')

_FAILED = []


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
            _FAILED.append(text.strip())
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_gate = _FailGateStream(_sys.stdout)
_sys.stdout = _gate


@_atexit.register
def _enforce():
    if _gate.failed:
        try:
            _sys.stdout.flush()
            _sys.stderr.flush()
        except Exception:
            pass
        _os._exit(1)


import loom_ui
import render.vk.ui as vk_ui
from loom_ui import UIManager, Canvas, Button, Slider, InputField

try:
    import pygame
    K_BACKSPACE = pygame.K_BACKSPACE
    K_RETURN = pygame.K_RETURN
    K_ESCAPE = pygame.K_ESCAPE
    K_LEFT = pygame.K_LEFT
except Exception:                       # pygame 缺失时用 SDL 键码常量
    K_BACKSPACE, K_RETURN, K_ESCAPE, K_LEFT = 8, 13, 27, 1073741904

W, H = 480, 320


def build_ui():
    """同一棵树分别喂给 GL 直调路径 / VK 桥路径."""
    clicks, changes, submits = [], [], []
    mgr = UIManager()
    c = Canvas(canvas_type='screen', width=W, height=H)
    mgr.add_canvas(c)
    btn = Button(name='btn', rect=(20, 20, 120, 32), text='OK',
                 on_click=lambda: clicks.append(1))
    sld = Slider(name='sld', rect=(20, 70, 200, 20), min_value=0.0,
                 max_value=100.0, value=0.0,
                 on_change=lambda v: changes.append(v))
    inp = InputField(name='inp', rect=(20, 110, 220, 30),
                     on_submit=lambda t: submits.append(t))
    for e in (btn, sld, inp):
        c.root.add_child(e)
    return mgr, {'clicks': clicks, 'changes': changes, 'submits': submits}


def state(mgr):
    ui = mgr
    focused = getattr(ui, '_focused', None)
    hovered = getattr(ui, '_hovered', None)
    sld = ui.find('sld')
    inp = ui.find('inp')
    return {
        'focused': getattr(focused, 'name', None),
        'hovered': getattr(hovered, 'name', None),
        'slider': round(float(sld.value), 6),
        'input': inp.text,
        'cursor': getattr(inp, '_cursor', None),
    }


def gl_frame(mgr, pos, pressed=(), released=(), wheel=0):
    """GL editor._dispatch_ui_mouse 的等价直调序列.

    真实 GL 调用点 (editor._dispatch_ui_mouse) 用 try/except 包住
    dispatch_mouse; 这里同样包住, 以复现"GL 路径吞异常"的既有语义.
    """
    try:
        consumed = mgr.dispatch_mouse(pos, set(pressed), set(released), wheel)
    except Exception as e:
        print('  (GL dispatch_mouse 异常按 editor 同款吞掉: %r)' % (e,))
        consumed = False
    if not consumed:
        mgr.update_hover_only(pos)
    return bool(consumed)


def check(label, cond, detail=''):
    if cond:
        print('PASS ' + label)
    else:
        print('FAIL ' + label + (('  ' + str(detail)) if detail else ''))

# ============================================================================
# Q-B7-34-3: 静态断言「UIInputBridge.on_key / on_text 在生产代码里无调用方」
#
# 背景（裁决 Q-B7-33-1=B 的字面要求 vs 实际）: 裁决要求 vk_ui.UIInputBridge 只留
# 鼠标/滚轮, 实际 on_key / on_text / dispatch_key / dispatch_text 四个方法全部保留
# —— 真实原因: 本测试第 1) 段用 dispatch_key / dispatch_text 做 UI 层对拍, 删掉
# 就没有对照物了（方案 b）。
# 保留的代价: 将来任何宿主直接调 on_key / on_text = **绕过内核的第二个 UI 写者**
# （输入框打一个字出两个字）, 而现有行为门抓不到这种「接回」—— 宿主自己喂一次 UI,
# 内核第③步又喂一次, 两个写者打的是同一个 UIManager。
# 所以补这条静态断言: 生产代码（Loom/**.py, 排除 tests/ 与 render/vk/ui.py 自身定义）里
# 不允许出现对这两个方法的调用点, 也不允许 getattr(x, 'on_key'/'on_text') 间接取用。
# 为什么只扫 on_key / on_text, 不扫 dispatch_key / dispatch_text: 后两个是**转调内层**
# （on_key -> self.dispatch_key -> self.ui.dispatch_key）, 而内核第③步在
# engine_core.py:193/235 里对 UIManager 的正当调用也是 `ui.dispatch_key(...)` ——
# 纯按名字扫会把那条**正确**的生产调用误判成违规（假红）。on_key / on_text 是
# 桥独有的名字, 只可能来自「宿主直喂桥」这一种接回方式, 所以可以安全地全量扫。
# ============================================================================
def bridge_direct_call_sites(paths):
    """在给定 .py 文件里找 UIInputBridge.on_key / on_text 的调用点.

    返回 [(路径, 行号, 属性名), ...]; 除直接调用外, 也覆盖 getattr(x, 'on_key')
    这种间接取用（第二条接回方式）。定义处（def on_key）不是 Call, 不会被算作调用。
    """
    import ast
    hits = []
    for path in paths:
        try:
            with open(path, 'rb') as f:
                src = f.read().decode('utf-8', 'replace')
            tree = ast.parse(src, filename=path)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in ('on_key', 'on_text'):
                hits.append((path, node.lineno, fn.attr))
            elif (isinstance(fn, ast.Name) and fn.id == 'getattr'
                  and len(node.args) >= 2
                  and isinstance(node.args[1], ast.Constant)
                  and node.args[1].value in ('on_key', 'on_text')):
                hits.append((path, node.lineno, 'getattr(%r)' % (node.args[1].value,)))
    return hits


def production_py_files(root):
    """生产代码清单: root 下所有 .py, 排除 tests/（门自己）与 __pycache__/_tmp。"""
    out = []
    for dirpath, dirnames, filenames in _os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in ('tests', '__pycache__', '_tmp'))
        for fn in sorted(filenames):
            if not fn.endswith('.py'):
                continue
            p = _os.path.join(dirpath, fn)
            rel = _os.path.relpath(p, root).replace('\\', '/')
            if rel == 'render/vk/ui.py':      # 定义处自身（on_key 内部转调 dispatch_key）不算调用方
                continue
            out.append(p)
    return out


def main():
    # ---------------- 1) 两条路径跑同一事件序列 ----------------
    mgr_gl, cb_gl = build_ui()
    mgr_vk, cb_vk = build_ui()
    bridge = vk_ui.UIInputBridge(mgr_vk)

    steps = [
        # (说明, pos, pressed, released, key_or_text)
        ('hover button', (50, 36), (), (), None),
        ('press button', (50, 36), (1,), (), None),
        ('release button', (50, 36), (), (1,), None),
        ('press slider', (60, 80), (1,), (), None),
        ('drag slider', (180, 80), (), (), None),
        ('release slider', (180, 80), (), (1,), None),
        ('focus input', (60, 125), (1,), (), None),
        ('type abc', (60, 125), (), (), ('text', 'abc')),
        ('backspace', (60, 125), (), (), ('key', K_BACKSPACE)),
        ('type Z', (60, 125), (), (), ('text', 'Z')),
        ('left arrow', (60, 125), (), (), ('key', K_LEFT)),
        ('submit', (60, 125), (), (), ('key', K_RETURN)),
        ('release input', (60, 125), (), (1,), None),
        ('blank hover', (400, 300), (), (), None),
    ]
    ok = True
    for desc, pos, pressed, released, ev in steps:
        # GL 直调
        c_gl = gl_frame(mgr_gl, pos, pressed, released)
        if ev is not None:
            kind, val = ev
            if kind == 'text':
                mgr_gl.dispatch_text(val)
            else:
                mgr_gl.dispatch_key(val)
        # VK 桥
        bridge.on_cursor(*pos)
        for b in pressed:
            bridge.on_mouse_button(b, True)
        for b in released:
            bridge.on_mouse_button(b, False)
        c_vk = bridge.begin_frame()
        if ev is not None:
            kind, val = ev
            if kind == 'text':
                bridge.dispatch_text(val)
            else:
                bridge.dispatch_key(val)
        s_gl, s_vk = state(mgr_gl), state(mgr_vk)
        same = (c_gl == c_vk) and (s_gl == s_vk)
        ok = ok and same
        check('一致: ' + desc, same,
              'consumed GL=%r VK=%r' % (c_gl, c_vk) if c_gl != c_vk
              else 'state GL=%r VK=%r' % (s_gl, s_vk))

    # ---------------- 2) 行为断言 (两条路径都验) ----------------
    check('Button 点击回调触发 1 次 (GL)', len(cb_gl['clicks']) == 1, cb_gl['clicks'])
    check('Button 点击回调触发 1 次 (VK)', len(cb_vk['clicks']) == 1, cb_vk['clicks'])
    check('Slider 拖动值 = 80 (GL)', abs(mgr_gl.find('sld').value - 80.0) < 1e-6,
          mgr_gl.find('sld').value)
    check('Slider 拖动值 = 80 (VK)', abs(mgr_vk.find('sld').value - 80.0) < 1e-6,
          mgr_vk.find('sld').value)
    check('InputField 文本 = abZ (GL)', mgr_gl.find('inp').text == 'abZ',
          repr(mgr_gl.find('inp').text))
    check('InputField 文本 = abZ (VK)', mgr_vk.find('inp').text == 'abZ',
          repr(mgr_vk.find('inp').text))
    check('InputField 提交 = abZ (GL)', cb_gl['submits'] == ['abZ'], cb_gl['submits'])
    check('InputField 提交 = abZ (VK)', cb_vk['submits'] == ['abZ'], cb_vk['submits'])

    # ---------------- 3) 相机门控 ----------------
    mgr3, _ = build_ui()
    b3 = vk_ui.UIInputBridge(mgr3)
    b3.on_cursor(50, 36)
    c0 = b3.begin_frame()
    check('纯 hover 不抢相机 (consumed=False, wants_camera=True)',
          (not c0) and b3.wants_camera())
    b3.on_mouse_button(1, True)
    c1 = b3.begin_frame()
    check('按钮按下抢相机 (consumed=True, wants_camera=False)',
          c1 and not b3.wants_camera())
    b3.on_mouse_button(1, False)
    c2 = b3.begin_frame()
    # 2026-11-07: 松开当帧在 GL 语义里仍算"消费" (on_mouse_up 返回 True ->
    # consumed=True)。此前这条断言期望"当帧即释放", 实际是被 loom_ui 的
    # `self._dragging_elem._dragging = False if ... else None` 崩溃掩盖了
    # (异常让 up 帧没走完)。该缺陷已修, 断言改为与 GL 同序 + 下一帧释放。
    check('松开当帧仍算消费 (与 GL 同序)', b3.ui_active and not b3.wants_camera())
    c3 = b3.begin_frame()
    check('松开后下一帧释放相机', (not b3.ui_active) and b3.wants_camera())
    # 滑条拖动跨帧: 按下后即使本帧无新事件也应保持 ui_active
    b4 = vk_ui.UIInputBridge(mgr3)
    b4.on_cursor(60, 80)
    b4.on_mouse_button(1, True)
    b4.begin_frame()
    b4.on_cursor(120, 80)
    b4.begin_frame()
    check('滑条拖动跨帧仍抢相机', (not b4.wants_camera())
          and mgr3.find('sld')._dragging)
    b4.on_mouse_button(1, False)
    b4.begin_frame()
    check('拖动松开的当帧仍算消费 (drag_to 在 up 之前跑, 与 GL 同序)',
          b4.last_consumed)
    b4.begin_frame()          # 下一帧无事件 -> 应恢复相机
    check('拖动结束后的下一帧释放相机', b4.wants_camera())

    # ---------------- 4) 空 UI / 无焦点边界 ----------------
    empty = vk_ui.UIInputBridge(None)
    check('无 UI 时帧分发不崩且不抢相机',
          empty.begin_frame() is False and empty.wants_camera())
    check('无 UI 时按键/文本返回 False',
          empty.dispatch_key(K_BACKSPACE) is False
          and empty.dispatch_text('x') is False)
    mgr5, _ = build_ui()
    b5 = vk_ui.UIInputBridge(mgr5)
    check('无焦点时按键不消费 (GL 语义)',
          b5.dispatch_key(K_BACKSPACE) is False
          and mgr5.dispatch_key(K_BACKSPACE) is False)

    # ---------------- 5) 静态断言: 桥的 on_key/on_text 无生产调用方 (Q-B7-34-3) ----------------
    # 为什么这条断言是必要的: 见文件上方 Q-B7-34-3 说明 —— 保留这两个方法等于留了一个
    # 「宿主绕过内核直喂 UI」的接口, 行为门看不见, 只有静态扫描能守住。
    _root = _os.path.dirname(HERE)
    _prod = production_py_files(_root)
    _hits = [(_os.path.relpath(p, _root).replace('\\', '/'), ln, attr)
             for (p, ln, attr) in bridge_direct_call_sites(_prod)]
    check('静态断言: 生产代码无 UIInputBridge.on_key / on_text 调用方（键/文本只能走内核）',
          not _hits, '扫了 %d 个生产 .py，命中 %d 处: %r' % (len(_prod), len(_hits), _hits[:5]))
    ok = ok and not _hits
    # 扫描器自检: 把同一段「直调」写成临时样本, 必须被抓到 —— 否则这条断言可能空转
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        _probe = _os.path.join(_td, 'planted_direct_call.py')
        with open(_probe, 'w', encoding='utf-8') as _f:
            _f.write('def f(bridge, ev):\n'
                     '    bridge.on_key(ev)\n'
                     '    return getattr(bridge, "on_text")(ev)\n')
        _planted = bridge_direct_call_sites([_probe])
    check('静态断言扫描器自检: 故意直调 .on_key 与 getattr(...,"on_text") 的样本必须被抓到',
          len(_planted) == 2, _planted)
    ok = ok and len(_planted) == 2

    print()
    if ok and not _FAILED:
        print('ALL PASS')
        return 0
    print('有 FAIL: %d 项' % len(_FAILED))
    return 1


if __name__ == '__main__':
    _sys.exit(main())
