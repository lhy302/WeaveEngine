# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 末尾 print 的 ✅/❌/≤ 等字符会抛
# UnicodeEncodeError, 让"测试通过"被记录成 exit=1 的假失败。
# 统一把 stdout/stderr 切到 UTF-8(replace), 失败信号重新只由断言决定。
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门: 出现以 "FAIL" 开头的行 -> 退出码改 1 (防 run_all 假绿)。
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
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

import agent_commands as ac
import loom_ui
from loom_ui import UIManager

ok = True


def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


def _call(fn, *a, **kw):
    """调一次并区分 [正常返回 / ValueError / 其它异常] -> (ok, 值或错误串)."""
    try:
        return True, fn(*a, **kw)
    except ValueError as e:
        return False, str(e)
    except Exception as e:                     # noqa: BLE001 - 报错类型也要看清
        return False, '__OTHER__%r' % (e,)


class _Win:
    """命令层最小替身: 只要 .editor.ui (与 tests/test_agent_commands.py 同款思路)."""

    def __init__(self):
        ed = type('Ed', (), {})()
        ed.ui = UIManager()
        ed.ui.default_canvas()
        ed.undo = None
        self.editor = ed

    @property
    def ui(self):
        return self.editor.ui

    def _root(self):
        return self.editor.ui.canvases[0].root


class _RenderEngine:
    """只复刻 color 消费方式 (loom_hud.draw_screen_rect 里的 color[x]/255.0):
    坏元组 (长度 7 / 元素是 str) 在这里必然抛 TypeError —— 就是线上播放器
    "渲染帧 TypeError -> 退出" 的最小复现。"""

    def draw_screen_rect(self, rect, color):
        a = (color[3] / 255.0) if len(color) > 3 else 1.0
        return (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, a)


# ============ 1. parse_color: 合法输入 ============
LEGAL = [
    ('#ff0000', (255, 0, 0, 255)),
    ('#FF0000', (255, 0, 0, 255)),
    ('#00ff0080', (0, 255, 0, 128)),
    ('ff0000', (255, 0, 0, 255)),            # 无 # 前缀
    ('  #102030  ', (16, 32, 48, 255)),      # 前后空白
    ('#f00', (255, 0, 0, 255)),              # #RGB 简写
    ([1, 2, 3], (1, 2, 3, 255)),             # 3 项列表
    ((1, 2, 3), (1, 2, 3, 255)),             # 3 项元组
    ([1, 2, 3, 4], (1, 2, 3, 4)),
    ((0, 0, 0, 0), (0, 0, 0, 0)),
    ((255, 255, 255, 255), (255, 255, 255, 255)),
]
for _inp, _exp in LEGAL:
    _fine, _got = _call(ac.parse_color, _inp)
    check('parse_color(%r) -> %r' % (_inp, _exp), _fine and _got == _exp,
          _got if _fine else 'raised: %s' % (_got,))

# ============ 2. parse_color: 非法输入必须抛 ValueError ============
ILLEGAL = [
    'not-a-color', '#ff', '#ffff', '#gggggg', '#ff00zz',
    'ff00', '', (1, 2), (1, 2, 3, 4, 5), [1], (300, 0, 0), (-1, 0, 0),
    (1, 2, 'x'), 123, 1.5, None, {}, True,
]
for _bad in ILLEGAL:
    _fine, _err = _call(ac.parse_color, _bad)
    check('parse_color(%r) 抛 ValueError' % (_bad,),
          (not _fine) and not str(_err).startswith('__OTHER__'),
          _err if not _fine else '未抛异常, 返回 %r' % (_err,))

# ============ 3. _COLOR_FIELDS 覆盖所有着色字段 ============
for _f in ('bg_color', 'color', 'tint', 'text_color', 'normal_color',
           'hover_color', 'pressed_color', 'track_color', 'fill_color',
           'handle_color', 'box_color', 'check_color', 'label_color',
           'stroke_color', 'focus_bg_color', 'placeholder_color',
           'cursor_color', 'list_bg', 'list_hover', 'bar_color'):
    check('_COLOR_FIELDS 含 %s' % _f, _f in ac._COLOR_FIELDS)

# ============ 4. ui_add: 字符串颜色 -> 合法 4 元组, 渲染帧不炸 ============
CASES = [
    ('panel', 'bg_color', '#ff0000'),
    ('text', 'color', '#00ff00'),
    ('image', 'tint', '#0000ff80'),
    ('button', 'normal_color', '#123456'),
    ('slider', 'fill_color', (10, 20, 30)),
    ('toggle', 'box_color', [40, 50, 60, 70]),
    ('progress_bar', 'fill_color', '#abcdef'),
    ('scroll_view', 'bar_color', '#0f0f0f'),
    ('input_field', 'cursor_color', '#f0f0f0'),
    ('dropdown', 'list_bg', '#010203'),
    ('grid_layout', 'bg_color', '#040506'),
    ('shape', 'fill_color', '#070809'),
]
win = _Win()
eng = _RenderEngine()
for _typ, _field, _val in CASES:
    _r = ac.dispatch('ui_add', {'type': _typ, _field: _val}, win)
    _elem = win._root().children[-1] if _r.get('ok') else None
    _c = getattr(_elem, _field, None) if _elem is not None else None
    _ok = (bool(_r.get('ok')) and isinstance(_c, tuple) and len(_c) == 4
           and all(isinstance(x, int) and 0 <= x <= 255 for x in _c))
    _detail = ''
    if _ok:
        try:
            eng.draw_screen_rect((0, 0, 8, 8), _c)
        except Exception as e:                  # noqa: BLE001
            _ok, _detail = False, 'render: %r' % (e,)
    else:
        _detail = '%r / %r' % (_r.get('error') or _r, _c)
    check('ui_add %s %s=%r -> 渲染可用 4 元组' % (_typ, _field, _val), _ok, _detail)

# ============ 5. ui_add: 非法颜色必须报错且不留半成品 ============
for _bad in ('not-a-color', '#ff', (1, 2), (300, 0, 0)):
    _n0 = len(win._root().children)
    _r = ac.dispatch('ui_add', {'type': 'panel', 'bg_color': _bad}, win)
    check('ui_add 非法颜色 %r -> 拒绝 (%s)' % (_bad, (_r.get('error') or '')[:24]),
          _r.get('ok') is False and 'error' in _r)
    check('ui_add 非法颜色 %r -> 未建出元素' % (_bad,), len(win._root().children) == _n0)

# ============ 6. ui_set: 与 ui_add 复用同一解析 (改前后行为) ============
_r = ac.dispatch('ui_add', {'type': 'panel', 'bg_color': '#ffffff'}, win)
_name = _r['result']['name']
_panel = win._root().find(_name)
_r = ac.dispatch('ui_set', {'name': _name, 'bg_color': '#11223344'}, win)
check('ui_set bg_color 字符串 -> (17,34,51,68)',
      _r.get('ok') and _panel.bg_color == (17, 34, 51, 68), _panel.bg_color)
_before = _panel.bg_color
_r = ac.dispatch('ui_set', {'name': _name, 'bg_color': 'oops'}, win)
check('ui_set 非法颜色 -> 拒绝且字段不变',
      _r.get('ok') is False and _panel.bg_color == _before, _r.get('error'))

# ============ 7. bool 字符串语义 (原 bool("false") == True) ============
win2 = _Win()
FALSEY = ['false', '0', 'no', 'off', 'none', '', False, 0]
TRUTHY = ['true', '1', 'yes', 'on', True, 1]
for _v in FALSEY:
    _r = ac.dispatch('ui_add', {'type': 'button', 'visible': _v, 'enabled': _v}, win2)
    _b = win2._root().children[-1]
    check('ui_add visible/enabled=%r -> False' % (_v,), _b.visible is False and _b.enabled is False,
          (bool(_b.visible), bool(_b.enabled)))
for _v in TRUTHY:
    _r = ac.dispatch('ui_add', {'type': 'button', 'visible': _v, 'enabled': _v}, win2)
    _b = win2._root().children[-1]
    check('ui_add visible/enabled=%r -> True' % (_v,), _b.visible is True and _b.enabled is True,
          (bool(_b.visible), bool(_b.enabled)))

_r = ac.dispatch('ui_add', {'type': 'toggle', 'is_on': 'false'}, win2)
_tog = win2._root().children[-1]
check('ui_add toggle is_on="false" -> False', _tog.is_on is False, _tog.is_on)
_r = ac.dispatch('ui_add', {'type': 'scroll_view', 'show_bar': 'false'}, win2)
_sv = win2._root().children[-1]
check('ui_add scroll_view show_bar="false" -> False', _sv.show_bar is False, _sv.show_bar)
_r = ac.dispatch('ui_add', {'type': 'shape', 'close': 'false'}, win2)
_sh = win2._root().children[-1]
check('ui_add shape close="false" -> False', _sh.close is False, _sh.close)

_bname = _r['result']['name']
_r = ac.dispatch('ui_add', {'type': 'button'}, win2)
_b = win2._root().children[-1]
_r = ac.dispatch('ui_set', {'name': _b.name, 'visible': 'false', 'enabled': '0'}, win2)
check('ui_set visible/enabled 字符串 false -> False',
      _r.get('ok') and _b.visible is False and _b.enabled is False,
      _r.get('result'))
_r = ac.dispatch('ui_set', {'name': _b.name, 'visible': 'true'}, win2)
check('ui_set visible="true" -> True', _b.visible is True, _b.visible)

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
