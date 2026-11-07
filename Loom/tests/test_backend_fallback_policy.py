# -*- coding: utf-8 -*-
"""test_backend_fallback_policy.py — 后端回退策略 (Q6) 的白盒契约.

基准 (任务裁决 Q6):
  · 默认后端仍是 vulkan (设置里的 render_api);
  · **Vulkan 初始化失败**时 (非显式指定): 打印"Vulkan 后端不兼容（<原因>），
    已把设置回退为 OpenGL，下次启动将使用 OpenGL"; 把 设置.json 的
    render_api 写成 opengl; 本次进程**非零退出** (崩一次, 不伪装成功);
  · 显式 --backend vulkan: **不改写设置**, 只报错退出;
  · --backend auto: 仍自动回退 (不写设置);
  · 渲染循环内失败 (VkRunError) 不回退, 打印原因后失败退出。

同时锁住 scan_05 P-10 的"段"划分: 初始化失败 = 可回退信号, 循环内失败 = 不可回退。
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


import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')

import run_player

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


class _Harness:
    """把 run_player 的两个后端入口换成桩, 并把 设置.json 指到临时目录."""

    def __init__(self, tmpdir, api='vulkan'):
        self.tmpdir = tmpdir
        self.path = os.path.join(tmpdir, "设置.json")
        self.write_setting(api)
        self.calls = []
        self._orig = (run_player._run_vulkan, run_player._run_opengl,
                      run_player._SETTINGS_BASE)

    def write_setting(self, api):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({"gui": "LoomGUI", "render_api": api}, f)

    def read_setting(self):
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)

    def install(self, vk=None, gl=None):
        run_player._SETTINGS_BASE = self.tmpdir

        def _vk(scene, **kw):
            self.calls.append("vk")
            if vk is not None:
                raise vk
            return "vk"

        def _gl(scene, **kw):
            self.calls.append("gl")
            return "gl"

        run_player._run_vulkan = _vk
        run_player._run_opengl = _gl

    def restore(self):
        (run_player._run_vulkan, run_player._run_opengl,
         run_player._SETTINGS_BASE) = self._orig


def _run_captured(fn):
    buf = io.StringIO()
    out, exc = "", None
    with contextlib.redirect_stdout(buf):
        try:
            fn()
        except BaseException as e:        # noqa: BLE001 - 退出信号是断言对象
            exc = e
    out = buf.getvalue()
    return out, exc


def t_default_path_persists_opengl(tmp):
    """非显式 (设置/默认走到 vulkan) 初始化失败 -> 写 opengl + 非零退出."""
    print("=== 默认路径: Vulkan 初始化失败 (Q6) ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("adapter 为空 (无 Vulkan 设备)"))
    try:
        out, exc = _run_captured(lambda: run_player.run_backend("vulkan", "x.json"))
    finally:
        h.restore()
    code = getattr(exc, 'code', None) if isinstance(exc, SystemExit) else None
    check("本次进程非零退出 (SystemExit code != 0)",
          isinstance(exc, SystemExit) and code not in (None, 0), (type(exc).__name__, code))
    check("提示含「不兼容」", "不兼容" in out, out.strip())
    check("提示含「下次启动将使用 OpenGL」", "下次启动将使用 OpenGL" in out, "")
    check("设置.json render_api 已写成 opengl", h.read_setting().get("render_api") == "opengl",
          h.read_setting())
    check("没有在同进程里偷偷改走 GL (不伪装成功)", h.calls == ["vk"], h.calls)


def t_explicit_vulkan_keeps_setting(tmp):
    """显式 --backend vulkan: 不改写设置, 只报错退出."""
    print("=== 显式 --backend vulkan (Q6) ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("adapter 为空 (无 Vulkan 设备)"))
    try:
        out, exc = _run_captured(
            lambda: run_player.run_backend("vulkan", "x.json", explicit=True))
    finally:
        h.restore()
    code = getattr(exc, 'code', None) if isinstance(exc, SystemExit) else None
    check("显式 vulkan: 非零退出",
          isinstance(exc, SystemExit) and code not in (None, 0), (type(exc).__name__, code))
    check("显式 vulkan: 设置未被改写 (仍 vulkan)",
          h.read_setting().get("render_api") == "vulkan", h.read_setting())
    check("显式 vulkan: 提示写明不改写设置", "不改写设置" in out, out.strip())
    check("显式 vulkan: 不回退 GL", h.calls == ["vk"], h.calls)


def t_auto_falls_back_without_writing(tmp):
    """--backend auto: 自动回退 GL, 不写设置."""
    print("=== --backend auto (Q6) ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("adapter 为空"))
    try:
        out, exc = _run_captured(lambda: run_player.run_backend("auto", "x.json"))
    finally:
        h.restore()
    check("auto: 回退到 GL", exc is None and h.calls == ["vk", "gl"], (exc, h.calls))
    check("auto: 设置未被改写", h.read_setting().get("render_api") == "vulkan",
          h.read_setting())


def t_loop_failure_not_swallowed(tmp):
    """渲染循环内失败 (VkRunError) 不回退: auto / 显式 / 发布链都一样."""
    print("=== 运行期失败 (scan_05 P-10) ===")
    for tag, api, kw in (("auto", "auto", {}),
                         ("显式 vulkan", "vulkan", {"explicit": True}),
                         ("设置 vulkan", "vulkan", {})):
        h = _Harness(tmp)
        h.install(vk=run_player.VkRunError("渲染循环内 device lost"))
        try:
            out, exc = _run_captured(
                lambda: run_player.run_backend(api, "x.json", **kw))
        finally:
            h.restore()
        check("%s: VkRunError 原样上传 (不回退 GL)" % tag,
              isinstance(exc, run_player.VkRunError) and h.calls == ["vk"],
              (type(exc).__name__, h.calls))


def t_game_player_safe_layer(tmp):
    """发布链兜底层: 不吞 Vulkan 退出/运行期失败, 其余异常仍回退 GL."""
    print("=== 发布链 _run_backend_safe ===")
    import game_player

    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("adapter 为空"))
    try:
        out, exc = _run_captured(
            lambda: game_player._run_backend_safe("vulkan", "x.json"))
    finally:
        h.restore()
    check("VkInitError -> 转成非零退出 (发布链不伪装成功)",
          isinstance(exc, SystemExit) and getattr(exc, 'code', 1) not in (None, 0),
          type(exc).__name__)
    check("VkInitError -> 不改走 GL", h.calls == ["vk"], h.calls)

    h = _Harness(tmp)
    h.install(vk=run_player.VkRunError("loop 内异常"))
    try:
        out, exc = _run_captured(
            lambda: game_player._run_backend_safe("vulkan", "x.json"))
    finally:
        h.restore()
    check("VkRunError -> 上传 (不回退)", isinstance(exc, run_player.VkRunError)
          and h.calls == ["vk"], (type(exc).__name__, h.calls))

    h = _Harness(tmp)
    h.install(vk=RuntimeError("别的意外失败"))
    try:
        out, exc = _run_captured(
            lambda: game_player._run_backend_safe("vulkan", "x.json"))
    finally:
        h.restore()
    check("其它意外异常 -> 仍回退 GL (最后一道网)",
          exc is None and h.calls == ["vk", "gl"], (exc, h.calls))


def t_settings_key_named_backend(tmp):
    """旧配置用 backend 作键名时一并同步 (不留下两套口径)."""
    print("=== 设置键名兼容 ===")
    h = _Harness(tmp)
    with open(h.path, 'w', encoding='utf-8') as f:
        json.dump({"render_api": "vulkan", "backend": "vulkan"}, f)
    h.install(vk=run_player.VkInitError("adapter 为空"))
    try:
        _run_captured(lambda: run_player.run_backend("vulkan", "x.json"))
    finally:
        h.restore()
    s = h.read_setting()
    check("render_api 与 backend 都被写成 opengl",
          s.get("render_api") == "opengl" and s.get("backend") == "opengl", s)


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        t_default_path_persists_opengl(tmp)
        t_explicit_vulkan_keeps_setting(tmp)
        t_auto_falls_back_without_writing(tmp)
        t_loop_failure_not_swallowed(tmp)
        t_game_player_safe_layer(tmp)
        t_settings_key_named_backend(tmp)
    print("=" * 60)
    if _fails:
        print("失败:", _fails)
        return 1
    print("ALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
