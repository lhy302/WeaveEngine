# -*- coding: utf-8 -*-
# test_scene_version_player.py — 播放器遇到更高版本场景：可见失败 + 优雅退出（Q-VER-1=A，2026-11-10）
#
# 覆盖：
#   A. 真实闸门：SceneDriver（VK 路径）原先**没有**版本门，现在与 GL 一致抛 SceneVersionError；
#   B. 三条播放器入口（vulkan / opengl / auto）都被 run_backend 统一拦截：
#      弹窗 + 打印「要求版本 / 当前版本」+ SystemExit(1)，不出现 Python traceback；
#   C. game_player 发布链同样优雅退出（不重试 GL、不打 traceback）；
#   D. LOOM_NO_DIALOG=1 时只打印、不阻塞。
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import sceneio
import run_player

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _newer_scene():
    return {'version': 11, 'min_engine_version': '99.0.0', 'objects': [], 'lights': [],
            'materials': [], 'cameras': [], 'active_camera': None}


def _scene_file(tmp):
    p = os.path.join(tmp, 'newer.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(_newer_scene(), f)
    return p


def _ver_error():
    return sceneio.SceneVersionError(
        '场景要求引擎 >= 99.0.0, 当前引擎 %s: 拒绝加载' % sceneio.ENGINE_VERSION)


class _Harness:
    def __init__(self, tmp, vk_exc=None, gl_exc=None):
        self.tmp = tmp
        self.calls = []
        self.dialogs = []
        self._orig = (run_player._run_vulkan, run_player._open_opengl,
                      run_player._run_opengl, run_player.show_blocking_dialog,
                      run_player._SETTINGS_BASE)
        self.vk_exc, self.gl_exc = vk_exc, gl_exc

    def install(self):
        run_player._SETTINGS_BASE = self.tmp
        run_player._BOOTSTRAP_KEY[0] = None

        def _vk(scene=None, **kw):
            self.calls.append('vk')
            if self.vk_exc is not None:
                raise self.vk_exc
            return 'vk'

        def _open(scene=None, **kw):
            self.calls.append('gl')
            if self.gl_exc is not None:
                raise self.gl_exc
            raise AssertionError('不应走到 GL 构造')

        run_player._run_vulkan = _vk
        run_player._open_opengl = _open
        run_player._run_opengl = lambda scene=None, **kw: 'gl'

        def _dlg(title, text):
            self.dialogs.append((title, text))
            return True

        run_player.show_blocking_dialog = _dlg

    def restore(self):
        (run_player._run_vulkan, run_player._open_opengl, run_player._run_opengl,
         run_player.show_blocking_dialog, run_player._SETTINGS_BASE) = self._orig
        run_player._BOOTSTRAP_KEY[0] = None


def _capture(fn):
    buf = io.StringIO()
    exc = None
    with contextlib.redirect_stdout(buf):
        try:
            fn()
        except BaseException as e:
            exc = e
    return buf.getvalue(), exc


def _assert_visible(out, exc, dialogs):
    text = dialogs[0][1] if dialogs else ''
    ok = (isinstance(exc, SystemExit) and getattr(exc, 'code', None) == 1
          and 'Traceback' not in out and len(dialogs) == 1)
    ok = ok and ('99.0.0' in out and '要求' in out and '当前引擎' in out)
    ok = ok and ('要求' in text and '当前引擎' in text and '版本' in text)
    return ok, text, out


def t_real_gate(tmp):
    print('=== A. 真实版本闸门（VK 路径也要拦） ===')
    err = None
    try:
        import scene_driver
        scene_driver.SceneDriver().load_from_data(_newer_scene())
    except BaseException as e:
        err = e
    check('A1 SceneDriver.load_from_data 抛 SceneVersionError',
          isinstance(err, sceneio.SceneVersionError), type(err).__name__)
    check('A2 原因含要求版本与当前版本',
          '99.0.0' in str(err) and sceneio.ENGINE_VERSION in str(err), str(err)[:80])
    err2 = None
    try:
        import runtime
        import moderngl
        ctx = moderngl.create_standalone_context(require=430)
        runtime.PlayerApp(scene_path=_scene_file(tmp), width=64, height=64, ctx=ctx)
    except BaseException as e:
        err2 = e
    check('A3 GL PlayerApp 同样拒绝更高版本场景',
          isinstance(err2, sceneio.SceneVersionError), type(err2).__name__)


def t_player_entries(tmp):
    print('=== B. 三条播放器入口 ===')
    for api in ('vulkan', 'opengl', 'auto'):
        h = _Harness(tmp)
        if api == 'opengl':
            h.gl_exc = _ver_error()
        else:
            h.vk_exc = _ver_error()
        h.install()
        try:
            out, exc = _capture(lambda: run_player.run_backend(api, 'x.json'))
        finally:
            h.restore()
        ok, text, out2 = _assert_visible(out, exc, h.dialogs)
        check('%-7s 可见失败：弹窗+原因+exit(1)+无 traceback' % api, ok,
              (type(exc).__name__, getattr(exc, 'code', None),
               h.dialogs[0][0] if h.dialogs else '', out2.strip()[-90:]))
        want = ['gl'] if api == 'opengl' else ['vk']
        check('%-7s 不重试另一个后端' % api, h.calls == want, h.calls)


def t_game_player(tmp):
    print('=== C. 发布链 game_player ===')
    import game_player
    h = _Harness(tmp)
    h.vk_exc = _ver_error()
    h.install()
    try:
        out, exc = _capture(lambda: game_player._run_backend_safe('vulkan', 'x.json'))
    finally:
        h.restore()
    ok, text, out2 = _assert_visible(out, exc, h.dialogs)
    check('C1 发布链同样优雅退出（不重试 GL / 无 traceback）', ok,
          (type(exc).__name__, h.calls, out2.strip()[-80:]))


def t_no_dialog(tmp):
    print('=== D. LOOM_NO_DIALOG=1 只打印不阻塞 ===')
    from loom_backend_guard import show_blocking_dialog
    os.environ['LOOM_NO_DIALOG'] = '1'
    ret = show_blocking_dialog('t', 'x')
    check('D1 禁用弹窗时立即返回 False（不阻塞）', ret is False, ret)
    h = _Harness(tmp)
    h.vk_exc = _ver_error()
    h.install()
    try:
        out, exc = _capture(lambda: run_player.run_backend('vulkan', 'x.json'))
    finally:
        h.restore()
    check('D2 仍打印完整原因并 exit(1)',
          isinstance(exc, SystemExit) and '99.0.0' in out and '当前引擎' in out,
          out.strip()[-90:])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t_real_gate(tmp)
        t_player_entries(tmp)
        t_game_player(tmp)
        t_no_dialog(tmp)
    print('=' * 60)
    if _fails:
        print('失败:', _fails)
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
