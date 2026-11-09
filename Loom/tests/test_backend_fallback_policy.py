# -*- coding: utf-8 -*-
"""test_backend_fallback_policy.py — 后端回退策略 (Q6) 的白盒契约.

基准 (2026-11-09 人类裁决 A，**取代旧 Q6「崩一次」**):
  · 默认后端仍是 vulkan (设置里的 render_api);
  · **Vulkan 初始化失败**（无 loader / 无适配器 / apiVersion < 1.1 / 设备创建失败）:
    打印 [VK] 诊断（设备/驱动/apiVersion）+ 弹窗 + 把用户层 游戏设置.json 的
    render_api 写成 opengl + **同进程立即改走 GL 4.3**（不退出、不闪退）；
  · 显式 --backend vulkan: 同样当场降级并落配置，但**额外记一条「用户手选」日志**；
  · --backend auto: 同样回退并落配置（下次启动不再空试 VK）；
  · GL 也不可用 -> 打印两条原因（[VK]+[GL]）后 SystemExit(1)；
  · 渲染循环内失败 (VkRunError) 不回退、不改配置。

同时锁住 scan_05 P-10 的"段"划分: 初始化失败 = 可回退信号, 循环内失败 = 不可回退；
以及 VK 地板 1.1（loom_backend_guard）与旧配置键名兼容。
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


def t_default_path_in_process_fallback(tmp):
    """非显式 (设置/默认走到 vulkan) 初始化失败 -> 诊断+落配置+同进程 GL（裁决 A）."""
    print("=== 默认路径: Vulkan 初始化失败 -> 同进程 GL ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError(
        "[VK] Vulkan API: 1.0.0（地板: 1.1）\n[VK] 设备: 假设备\n[VK] 驱动: 假驱动 (0.0.0)"))
    nxt = None
    try:
        out, exc = _run_captured(lambda: run_player.run_backend("vulkan", "x.json"))
        nxt = run_player.resolve_backend(None)      # 必须在 restore 之前（隔离目录仍生效）
    finally:
        h.restore()
    check("A1 不退出（不再崩一次）", exc is None, type(exc).__name__)
    check("A1 同进程依次调用 vk -> gl", h.calls == ["vk", "gl"], h.calls)
    check("A1 打印 [VK] 诊断（含 apiVersion/地板）",
          "[VK]" in out and "1.1" in out, out.strip()[:200])
    check("A1 提示已自动切换 OpenGL", "自动切换为 OpenGL" in out, "")
    check("A1 设置.json render_api 已写成 opengl",
          h.read_setting().get("render_api") == "opengl", h.read_setting())
    check("A1 下次启动解析为 opengl", nxt == "opengl", nxt)
    check("A1 非手选 -> 不出现「用户手选」日志", "用户手选" not in out, "")


def t_explicit_vulkan_falls_back_with_log(tmp):
    """显式 --backend vulkan: 同样当场降级并落配置, 但额外记「用户手选」日志."""
    print("=== 显式 --backend vulkan -> 降级 + 手选日志 ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("adapter 为空 (无 Vulkan 设备)"))
    try:
        out, exc = _run_captured(
            lambda: run_player.run_backend("vulkan", "x.json", explicit=True))
    finally:
        h.restore()
    check("B1 显式手选也当场降级（不退出）", exc is None and h.calls == ["vk", "gl"],
          (type(exc).__name__, h.calls))
    check("B1 设置仍被改写为 opengl",
          h.read_setting().get("render_api") == "opengl", h.read_setting())
    check("B1 记录「用户手选」日志（裁决 A 要求）", "用户手选" in out, out.strip()[-160:])


def t_auto_falls_back_and_persists(tmp):
    """--backend auto: 回退 GL 并落配置（下次启动不再空试 VK）."""
    print("=== --backend auto -> GL + 落配置 ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("adapter 为空"))
    try:
        out, exc = _run_captured(lambda: run_player.run_backend("auto", "x.json"))
    finally:
        h.restore()
    check("E1 auto: 回退到 GL", exc is None and h.calls == ["vk", "gl"], (exc, h.calls))
    check("E1 auto: 设置已写 opengl（下次直接走 GL）",
          h.read_setting().get("render_api") == "opengl", h.read_setting())


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
    _safe_ret = None
    try:
        buf = io.StringIO()
        exc = None
        with contextlib.redirect_stdout(buf):
            try:
                _safe_ret = game_player._run_backend_safe("vulkan", "x.json")
            except BaseException as e:     # noqa: BLE001 - 退出信号是断言对象
                exc = e
        out = buf.getvalue()
    finally:
        h.restore()
    check("VkInitError -> 同进程改走 GL（裁决 A），发布链拿到实际后端 opengl",
          exc is None and h.calls == ["vk", "gl"],
          (type(exc).__name__, h.calls))
    check("VkInitError -> 发布链返回的实际后端是 opengl",
          _safe_ret == "opengl", _safe_ret)

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


def t_double_fault_exits(tmp):
    """GL 也不可用 -> 两条原因都打印 + 非零退出（不静默、不假成功）."""
    print("=== 双后端都不可用 ===")
    h = _Harness(tmp)
    h.install(vk=run_player.VkInitError("[VK] 模拟: 无 Vulkan 设备"))

    def _gl_boom(scene=None, **kw):
        h.calls.append("gl")
        raise RuntimeError("[GL] 模拟: GL 4.3 不可用")

    run_player._run_opengl = _gl_boom
    try:
        out, exc = _run_captured(lambda: run_player.run_backend("vulkan", "x.json"))
    finally:
        h.restore()
    check("C1 双错 -> SystemExit(1)",
          isinstance(exc, SystemExit) and getattr(exc, 'code', None) == 1,
          (type(exc).__name__, getattr(exc, 'code', None)))
    check("C1 明确说两条后端都不可用", "两条后端都不可用" in out, out.strip()[-200:])
    check("C1 [VK] 与 [GL] 原因都在", "[VK]" in out and "[GL]" in out, "")


def t_vk_floor_99_end_to_end(tmp):
    """把 VK 地板抬到 9.9 -> **真实 vk_player** 过门失败 -> run_player 回退 GL."""
    print("=== VK 地板 9.9 桩（端到端）===")
    import loom_backend_guard as G
    old = (G.VK_MIN_API_MAJOR, G.VK_MIN_API_MINOR)
    try:
        G.VK_MIN_API_MAJOR, G.VK_MIN_API_MINOR = 9, 9
        err = None
        try:
            G.require_vulkan_api("地板桩")
        except G.VkBackendInitError as e:
            err = e
        check("F1 地板 9.9 被拒且带 apiVersion",
              err is not None and "9.9" in str(err), str(err)[:120])
        check("F1 诊断含 设备/驱动/API",
              all(k in str(err) for k in ("设备", "驱动", "Vulkan API")), "")
        check("F1 段标记可被 run_player 识别（可回退）",
              run_player._is_vk_error(err, "vulkan-init"), "")
        # 端到端: 真实 _run_vulkan -> vk_player 的初始化段检查（在开窗之前）触发回退；
        # GL 用桩，避免测试真的开窗。
        h = _Harness(tmp)
        run_player._SETTINGS_BASE = tmp
        run_player._run_opengl = lambda scene=None, **kw: "gl"
        buf = io.StringIO()
        ret = None
        try:
            with contextlib.redirect_stdout(buf):
                ret = run_player.run_backend("vulkan", _mini_scene(tmp))
        finally:
            h.restore()
        out = buf.getvalue()
        check("F2 真实 vk_player 地板失败 -> 回退 GL", ret == "gl", ret)
        check("F2 诊断来自 vk_player（含 9.9 / Vulkan）",
              "9.9" in out and "Vulkan" in out, out.strip()[:160])
    finally:
        G.VK_MIN_API_MAJOR, G.VK_MIN_API_MINOR = old


def _mini_scene(tmpdir):
    """最小场景文件（vk_player 走到初始化段即被地板挡住, 不会真开窗）."""
    p = os.path.join(tmpdir, "mini.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": 10, "objects": [], "lights": [], "materials": [],
                   "cameras": [], "active_camera": None}, f)
    return p


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        t_default_path_in_process_fallback(tmp)
        t_explicit_vulkan_falls_back_with_log(tmp)
        t_auto_falls_back_and_persists(tmp)
        t_double_fault_exits(tmp)
        t_vk_floor_99_end_to_end(tmp)
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
