# -*- coding: utf-8 -*-
"""test_wheel_backend_semantics.py — R3 收尾: 滚轮消费语义 + 发布链实际后端日志.

覆盖两处 scan_05 遗留 (F5 报告 §遗留):
  1. vk_ui.last_wheel_consumed 必须是"本帧滚轮是否被 UI 消费", 而不是
     "本帧鼠标事件整体是否被消费"; 同帧"点按钮 + 滚轮"时滚轮没被
     ScrollView 吃掉 -> last_wheel_consumed 必须为 False。
  2. game_player._start_pack 的 "渲染API=" 必须打印回退后**实际生效**
     的后端 (vulkan 初始化失败 -> opengl; auto 内部回退同理)。

纯 CPU / 无窗口; 发布链用 fake game_pack/scripts + run_player 后端桩。
"""
import atexit as _atexit
import contextlib
import io
import os as _os
import sys as _sys
import types

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


import vk_ui
from loom_ui import UIManager, Canvas, Button, ScrollView

W, H = 480, 320


def check(label, cond, detail=''):
    if cond:
        print('PASS ' + label)
    else:
        print('FAIL ' + label + (('  ' + str(detail)) if detail else ''))


# ==================== 1) 滚轮消费语义 ====================

def build_ui(scrollable=True):
    """按钮在滚动区外; ScrollView 在 (200,100,200,150), 内含一个按钮."""
    mgr = UIManager()
    c = Canvas(canvas_type='screen', width=W, height=H)
    mgr.add_canvas(c)
    btn = Button(name='btn', rect=(20, 20, 120, 32), text='OK')
    sv = ScrollView(name='sv', rect=(200, 100, 200, 150),
                    content_size=(200, 800 if scrollable else 100))
    sv.add_child(Button(name='inner', rect=(10, 10, 100, 32), text='IN'))
    c.root.add_child(btn)
    c.root.add_child(sv)
    return mgr, sv


def frame(mgr, pos, pressed=(), wheel=0):
    b = vk_ui.UIInputBridge(mgr)
    b.on_cursor(*pos)
    for p in pressed:
        b.on_mouse_button(p, True)
    if wheel:
        b.on_scroll(wheel)
    consumed = b.begin_frame()
    return b, bool(consumed)


def t_wheel_semantics():
    print('=== 1) vk_ui.last_wheel_consumed 语义 ===')

    # A. 同帧点按钮 + 滚轮, 指针不在滚动区 -> 点击消费, 滚轮不消费.
    mgr, sv = build_ui()
    b, consumed = frame(mgr, (50, 36), (1,), 3)
    check('A 同帧点按钮+滚轮(不在滚动区): 点击被消费', consumed, consumed)
    check('A 同帧点按钮+滚轮: last_wheel_consumed=False',
          b.last_wheel_consumed is False, b.last_wheel_consumed)
    check('A last_wheel 记录本帧增量 3', b.last_wheel == 3, b.last_wheel)

    # D. 同帧点按钮 + 滚轮, 指针在"不可滚"ScrollView 的内层按钮上:
    #    点击消费, 滚轮仍不消费 (ScrollView 无溢出).
    mgr, sv = build_ui(scrollable=False)
    b, consumed = frame(mgr, (250, 130), (1,), 3)
    check('D 不可滚 ScrollView 内按钮: 点击被消费', consumed, consumed)
    check('D 不可滚 ScrollView 内按钮: last_wheel_consumed=False',
          b.last_wheel_consumed is False, b.last_wheel_consumed)
    check('D 不可滚 ScrollView 内按钮: scroll_pos 未变',
          sv.scroll_pos == (0.0, 0.0), sv.scroll_pos)

    # C. 仅滚轮, 指针在可滚 ScrollView -> 真被 UI 消费.
    mgr, sv = build_ui(scrollable=True)
    b, consumed = frame(mgr, (250, 150), (), -3)
    check('C 可滚 ScrollView 仅滚轮: consumed=True', consumed, consumed)
    check('C 可滚 ScrollView 仅滚轮: last_wheel_consumed=True',
          b.last_wheel_consumed is True, b.last_wheel_consumed)
    check('C 可滚 ScrollView 仅滚轮: 真滚动 (scroll_pos.y<0)',
          sv.scroll_pos[1] < 0, sv.scroll_pos)

    # E. 仅滚轮, 指针在不可滚 ScrollView -> 不消费.
    mgr, sv = build_ui(scrollable=False)
    b, consumed = frame(mgr, (250, 130), (), 3)
    check('E 不可滚 ScrollView 仅滚轮: consumed=False', not consumed, consumed)
    check('E 不可滚 ScrollView 仅滚轮: last_wheel_consumed=False',
          b.last_wheel_consumed is False, b.last_wheel_consumed)

    # F. 仅滚轮, 指针在普通按钮上 -> 不消费.
    mgr, sv = build_ui()
    b, consumed = frame(mgr, (50, 36), (), 3)
    check('F 仅滚轮(按钮上): consumed=False', not consumed, consumed)
    check('F 仅滚轮(按钮上): last_wheel_consumed=False',
          b.last_wheel_consumed is False, b.last_wheel_consumed)

    # G. 无滚轮 -> 不消费.
    mgr, sv = build_ui()
    b, consumed = frame(mgr, (50, 36), (1,), 0)
    check('G 无滚轮: last_wheel=0 / last_wheel_consumed=False',
          b.last_wheel == 0 and b.last_wheel_consumed is False,
          (b.last_wheel, b.last_wheel_consumed))

    # H. 无 UI -> 不消费.
    b = vk_ui.UIInputBridge(None)
    b.on_scroll(3)
    b.begin_frame()
    check('H 无 UI: last_wheel_consumed=False', b.last_wheel_consumed is False)

    # I. 未知 UI (无 _hit_scroll_view) 但 dispatch 返回消费 -> 保守按已消费.
    class _FakeUI:
        def dispatch_mouse(self, pos, pressed, released, wheel=0):
            return True

        def update_hover_only(self, pos):
            pass

    b = vk_ui.UIInputBridge(_FakeUI())
    b.on_scroll(2)
    b.begin_frame()
    check('I 未知 UI 消费滚轮: 保守按已消费', b.last_wheel_consumed is True,
          b.last_wheel_consumed)

    # J. 判据助手本身: None / 可滚 / 不可滚.
    check('J helper(None)=False', vk_ui._wheel_taken_by_scrollview(None, (0, 0)) is False)
    mgr, sv = build_ui(scrollable=True)
    check('J helper(可滚)=True',
          vk_ui._wheel_taken_by_scrollview(mgr, (250, 150)) is True)
    mgr, sv = build_ui(scrollable=False)
    check('J helper(不可滚)=False',
          vk_ui._wheel_taken_by_scrollview(mgr, (250, 130)) is False)


# ==================== 2) 发布链实际后端日志 ====================

def _fake_modules():
    gm = {'scene': {}, 'scripts': [], 'config': {'name': 'ProbeGame'}}
    gp = types.ModuleType('game_pack')
    gp.load = lambda d: gm
    gp.install_game_plugins = lambda exe_dir, g: 0
    sc = types.ModuleType('scripts')
    sc.register_sources = lambda s: 0
    return gp, sc


class _FakeEng:
    """GL 播放器替身（_open_opengl 只构建不阻塞）。"""
    models = []

    def run(self):
        return None


class _BackendHarness:
    """fake 游戏包 + run_player 后端桩; 记录实际调用的后端顺序."""

    def __init__(self):
        import run_player
        self.rp = run_player
        self.orig_vk = run_player._run_vulkan
        self.orig_gl = run_player._run_opengl
        self.orig_open = run_player._open_opengl
        self.old_gp = _sys.modules.get('game_pack')
        self.old_sc = _sys.modules.get('scripts')
        gp, sc = _fake_modules()
        _sys.modules['game_pack'] = gp
        _sys.modules['scripts'] = sc
        self.calls = []
        self.vk_stub = None
        self.gl_stub = None

    def install(self, vk_exc=None, gl_exc=None):
        def _vk(scene, **kw):
            self.calls.append('vulkan')
            if vk_exc is not None:
                raise vk_exc
            return 'vk'

        def _gl(scene=None, **kw):
            self.calls.append('opengl')
            if gl_exc is not None:
                raise gl_exc
            return _FakeEng()

        self.vk_stub, self.gl_stub = _vk, _gl
        self.rp._run_vulkan = _vk
        # 2026-11-09: GL 的真实入口是 _open_opengl（只构建不阻塞）；
        # _run_opengl 保留为兼容调用面。
        self.rp._open_opengl = _gl
        self.rp._run_opengl = lambda scene=None, **kw: 'gl'

    def restore(self):
        self.rp._run_vulkan = self.orig_vk
        self.rp._open_opengl = self.orig_open
        self.rp._run_opengl = self.orig_gl
        if self.old_gp is None:
            _sys.modules.pop('game_pack', None)
        else:
            _sys.modules['game_pack'] = self.old_gp
        if self.old_sc is None:
            _sys.modules.pop('scripts', None)
        else:
            _sys.modules['scripts'] = self.old_sc


def _start_pack(h, backend):
    import game_player
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ret = game_player._start_pack(backend)
    return ret, buf.getvalue()


def _logged_api(out):
    for line in out.splitlines():
        if '渲染API=' in line:
            return line.rsplit('渲染API=', 1)[1].rstrip(')')
    return None


def t_backend_log():
    print()
    print('=== 2) game_player 渲染API 日志 ===')

    # A. vulkan 初始化失败 -> 回退 opengl, 日志必须写 opengl.
    h = _BackendHarness()
    h.install(vk_exc=RuntimeError('模拟 Vulkan 初始化失败'))
    try:
        ret, out = _start_pack(h, 'vulkan')
    finally:
        h.restore()
    check('A vulkan 回退后 _start_pack 仍返回 True', ret is True, ret)
    check('A vulkan 回退后日志=渲染API=opengl',
          _logged_api(out) == 'opengl', _logged_api(out))
    check('A vulkan 回退调用序列 vulkan->opengl',
          h.calls == ['vulkan', 'opengl'], h.calls)

    # B. auto 内部回退 -> 日志必须写 opengl (不是 auto).
    h = _BackendHarness()
    h.install(vk_exc=RuntimeError('模拟 Vulkan 初始化失败'))
    try:
        ret, out = _start_pack(h, 'auto')
    finally:
        h.restore()
    check('B auto 回退后日志=渲染API=opengl',
          _logged_api(out) == 'opengl', _logged_api(out))
    check('B auto 回退调用序列 vulkan->opengl',
          h.calls == ['vulkan', 'opengl'], h.calls)

    # C. auto 成功 -> 日志 vulkan.
    h = _BackendHarness()
    h.install()
    try:
        ret, out = _start_pack(h, 'auto')
    finally:
        h.restore()
    check('C auto 成功日志=渲染API=vulkan',
          _logged_api(out) == 'vulkan', _logged_api(out))
    check('C auto 成功只调用 vulkan', h.calls == ['vulkan'], h.calls)

    # D. 直接 opengl -> 日志 opengl.
    h = _BackendHarness()
    h.install()
    try:
        ret, out = _start_pack(h, 'opengl')
    finally:
        h.restore()
    check('D opengl 日志=渲染API=opengl',
          _logged_api(out) == 'opengl', _logged_api(out))
    check('D opengl 只调用 opengl', h.calls == ['opengl'], h.calls)

    # E. _run_backend_safe 直接回传实际后端.
    import game_player
    h = _BackendHarness()
    h.install(vk_exc=RuntimeError('boom'))
    try:
        actual = game_player._run_backend_safe('vulkan', None)
    finally:
        h.restore()
    check('E _run_backend_safe 回退后返回 opengl', actual == 'opengl', actual)

    h = _BackendHarness()
    h.install()
    try:
        actual = game_player._run_backend_safe('opengl', None)
    finally:
        h.restore()
    check('E _run_backend_safe 直接 opengl 返回 opengl', actual == 'opengl', actual)

    # F. 异常路径也必须恢复 run_player 的两个入口 (不污染后续调用).
    h = _BackendHarness()
    h.install(vk_exc=SystemExit(1))
    try:
        try:
            game_player._run_backend_safe('vulkan', None)
        except SystemExit:
            pass
        check('F SystemExit 后恢复 run_player 入口',
              h.rp._run_vulkan is h.vk_stub and h.rp._open_opengl is h.gl_stub)
    finally:
        h.restore()


def main():
    t_wheel_semantics()
    t_backend_log()
    print()
    if not _FAILED:
        print('ALL PASS')
        return 0
    print('有 FAIL: %d 项' % len(_FAILED))
    return 1


if __name__ == '__main__':
    _sys.exit(main())
