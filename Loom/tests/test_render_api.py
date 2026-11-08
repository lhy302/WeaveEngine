# -*- coding: utf-8 -*-
"""test_render_api.py — 渲染 API 与 API 切换契约 (2026-11-06)

设计基准 (白盒契约):
  · GPU性能优化-Vulkan双后端方案.txt 四/五节:
      - 引擎必须同时支持 Vulkan 与 OpenGL 两种后端;
      - 编辑器维持 Qt+OpenGL (P6 用户拍板), 播放器/发布游戏走可切换后端;
      - 选择优先级: --backend > 游戏设置.json render_api > 设置.json
        render_api > 默认 vulkan;
        (2026-11-08 用户配置目录契约 §1/§6: 配置分 只读模板层 与 用户层 delta,
         旧 游戏配置.json 的 render_api 一次性迁移进用户层, 不再单独占优先级;
         审计 P-02-03)
      - 'auto': 先试 Vulkan, 初始化失败自动回退 OpenGL。
  · 逻辑层 (场景/脚本/物理) 与后端无关, 后端只负责"画"。

本文件锁三条不变量:
  A. 取值解析: 三个合法取值原样透传 (含大小写/空白), 未知值才归一 vulkan。
  B. 分发与回退: auto 在 Vulkan 抛错时回退 GL; 显式 vulkan 不静默改道。
  C. 后端一致性: 同一场景在两条后端下的相机/视距契约一致 (far、距离钳制),
     否则"自由切换"会变成"切了就变样"。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate
import tempfile as _tempfile_gate

# 2026-11-08: 本测试会触达 game_settings 用户层 (bootstrap/迁移), 必须隔离 ——
# 契约 §8: 跑测试不得污染 %LOCALAPPDATA%, 也不得在仓库里留文件。
_os_gate.environ.setdefault('LOOM_USER_ROOT',
                               _tempfile_gate.mkdtemp(prefix='loom_test_userroot_'))


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

import run_player

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


# ============ A. 取值解析 (含 auto) ============
def t_resolve():
    cases = [
        ("vulkan", "vulkan"),
        ("opengl", "opengl"),
        ("auto", "auto"),          # R-01: 曾经被归一成 vulkan, 回退分支永不触达
        ("AUTO", "auto"),
        (" OpenGL ", "opengl"),
        ("nonsense", "vulkan"),    # 未知值 -> 默认
        ("", "vulkan"),
    ]
    for raw, want in cases:
        got = run_player.resolve_backend(raw)
        check("resolve_backend(%r) -> %r" % (raw, want), got == want, got)


# ============ B. 分发与回退语义 ============
def t_dispatch():
    calls = []
    orig_vk, orig_gl = run_player._run_vulkan, run_player._run_opengl
    try:
        def fake_vk(scene, **kw):
            calls.append("vk")
            if kw.pop("boom", False) is True:
                raise RuntimeError("no vulkan device")
            return "vk"

        def fake_gl(scene, **kw):
            calls.append("gl")
            return "gl"

        run_player._run_vulkan = fake_vk
        run_player._run_opengl = fake_gl

        calls.clear()
        check("vulkan 分发到 Vk", run_player.run_backend("vulkan", "s.json") == "vk"
              and calls == ["vk"], calls)

        calls.clear()
        check("opengl 分发到 GL", run_player.run_backend("opengl", "s.json") == "gl"
              and calls == ["gl"], calls)

        # auto: Vk 成功 -> 不回落
        calls.clear()
        run_player._run_vulkan = lambda scene, **kw: (calls.append("vk"), "vk")[1]
        check("auto: Vk 可用时走 Vk", run_player.run_backend("auto", "s.json") == "vk"
              and calls == ["vk"], calls)

        # auto: Vk 抛错 -> 回退 GL (设计文档 P5 原话)
        calls.clear()
        def vk_boom(scene, **kw):
            calls.append("vk")
            raise RuntimeError("no vulkan device")
        run_player._run_vulkan = vk_boom
        got = run_player.run_backend("auto", "s.json")
        check("auto: Vk 失败自动回退 GL", got == "gl" and calls == ["vk", "gl"], calls)

        # 显式 vulkan: 失败必须抛出 (不静默改道 —— 否则用户以为在用 Vk)
        calls.clear()
        raised = None
        try:
            run_player.run_backend("vulkan", "s.json")
        except RuntimeError as e:
            raised = e
        check("显式 vulkan 失败不静默回退 (如实抛错)", raised is not None
              and calls == ["vk"], calls)
    finally:
        run_player._run_vulkan, run_player._run_opengl = orig_vk, orig_gl


# ============ B2. 选择优先级 (--backend > 游戏配置.json > 设置) ============
def t_precedence():
    import json
    import tempfile
    import game_player

    real = json.dumps  # noqa: F841  (仅表明无外部依赖)
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = game_player._EXE_DIR
        old_resolve = run_player.resolve_backend
        seen = {}

        def spy_resolve(requested=None):
            seen['requested'] = requested
            return requested or 'vulkan'

        try:
            game_player._EXE_DIR = tmp
            run_player.resolve_backend = spy_resolve
            # ① 无 游戏配置.json -> 不覆盖 (None 交给 resolve 读设置)
            game_player._pick_backend(None)
            check("无游戏配置: 交回 resolve_backend(None)", seen.get('requested') is None,
                  seen)
            # ② 旧 游戏配置.json 的 render_api **不再**作为 requested 注入
            #    (2026-11-08 契约 §6-2: 它已一次性迁移进用户层, 由 游戏设置.json 生效;
            #     这条断言锁住审计 P-02-03 的修复 —— 旧文件不得抢新配置的优先级)
            with open(os.path.join(tmp, "游戏配置.json"), 'w', encoding='utf-8') as f:
                json.dump({"render_api": "opengl"}, f)
            game_player._pick_backend(None)
            check("旧 游戏配置.json render_api 不再作为 requested 注入",
                  seen.get('requested') is None, seen)
            # ③ --backend 优先级最高 (压过游戏配置)
            game_player._pick_backend("vulkan")
            check("--backend 压过游戏配置", seen.get('requested') == 'vulkan', seen)
            # ④ 坏 JSON 不影响启动
            with open(os.path.join(tmp, "游戏配置.json"), 'w', encoding='utf-8') as f:
                f.write("{ 坏 json")
            game_player._pick_backend(None)
            check("游戏配置 JSON 损坏 -> 忽略, 不崩", seen.get('requested') is None, seen)
        finally:
            game_player._EXE_DIR = old_dir
            run_player.resolve_backend = old_resolve


# ============ B4. 解锁键采样等价 (N4) ============
def t_unlock_sampling_parity():
    """解锁键必须**每渲染帧**采样（短按 < 1 逻辑步也能解锁），且两后端同一实现.

    基准: D6=A（解锁键归引擎独占）+ N4 裁决（VK 采样改每渲染帧）。
    锁住四件事:
      ① 不推进任何逻辑时钟, 单次渲染帧采样就能翻转（短按不丢）;
      ② 按住不放 / 松开帧不重复翻转（按下沿去重）;
      ③ 渲染帧采样会把 locked=True 且 unlock_requested=True 的矛盾态按玩家意图消除;
      ④ VK 不复制解锁语义, 且与 GL 走的是同一实现（同按键同结果）。
    """
    import vk_player
    import scene_driver
    import engine as E

    d = scene_driver.SceneDriver()
    d.mouse_lock_allowed = True
    d.set_mouse_locked(True)
    d.mouse_unlock_requested = False
    d.key_state['Tab'] = True                 # 短按: 从未推进逻辑时钟
    toggled = vk_player.poll_unlock_frame(d)
    check('VK 渲染帧采样: 未跑任何逻辑步也能解锁 (短按不丢)',
          toggled and d.mouse_locked is False and d.mouse_unlock_requested is True,
          (toggled, d.mouse_locked, d.mouse_unlock_requested))
    check('按住不放不重复翻转', vk_player.poll_unlock_frame(d) is False,
          d.mouse_unlock_requested)
    d.key_state['Tab'] = False
    check('松开帧不翻转', vk_player.poll_unlock_frame(d) is False)

    # 矛盾态: 脚本直接 set_mouse_locked(True) 撞上玩家解锁意图
    d.set_mouse_locked(True)
    check('复现矛盾态 (locked=True 且 requested=True)',
          d.mouse_locked is True and d.mouse_unlock_requested is True,
          (d.mouse_locked, d.mouse_unlock_requested))
    vk_player.poll_unlock_frame(d)
    check('渲染帧采样消除矛盾态 (按玩家意图解锁, locked=False)',
          d.mouse_locked is False and d.mouse_unlock_requested is True,
          (d.mouse_locked, d.mouse_unlock_requested))

    vk_src = open(os.path.join(ROOT, 'vk_player.py'), encoding='utf-8').read()
    check('VK 侧不复制解锁语义 (无 def _poll_mouse_unlock_key)',
          'def _poll_mouse_unlock_key' not in vk_src)
    sd_src = open(os.path.join(ROOT, 'scene_driver.py'), encoding='utf-8').read()
    check('SceneDriver.poll_unlock 委托 engine.GLEngine 唯一实现',
          'GLEngine._poll_mouse_unlock_key' in sd_src)

    class _Stub:
        # 补齐 engine.GLEngine._poll_mouse_unlock_key 的前置（N3 契约: script_keys + 一次性告警助手）
        mouse_lock_allowed = True
        mouse_locked = True
        mouse_unlock_requested = False
        actions = {'解锁鼠标': ['Tab']}
        script_keys = {'Tab': True}
        _warn_unlock_poll_unavailable = E.GLEngine._warn_unlock_poll_unavailable

        def get_action(self, name):
            return any(self.script_keys.get(k, False)
                       for k in self.actions.get(name, ()))

        def set_mouse_locked(self, v):
            self.mouse_locked = bool(v)

        def toggle_mouse_locked(self):
            self.mouse_unlock_requested = not self.mouse_unlock_requested
            self.mouse_locked = not self.mouse_unlock_requested

    s = _Stub()
    gl_toggled = E.GLEngine._poll_mouse_unlock_key(s)
    check('GL 侧同一按键同样翻转 (两后端同一实现 -> 采样等价)',
          gl_toggled and s.mouse_locked is False,
          (gl_toggled, s.mouse_locked))


# ============ B5. run_player 脚本入口的异常身份 (P-02-06) ============
def t_run_player_entry_identity():
    """`python run_player.py` 入口: VkInitError 必须仍被捕获并走 Q6 回退.

    根因: 以 __main__ 运行时 vk_player 的 `from run_player import ...` 会二次执行
    run_player.py, 产生第二份异常类 -> `except VkInitError` 漏捕 -> 回退链整体失效。
    """
    import types
    import tempfile

    path = os.path.join(ROOT, 'run_player.py')
    src = open(path, encoding='utf-8').read()
    mod = types.ModuleType('__main__')
    mod.__file__ = path
    saved_main = sys.modules.get('__main__')
    saved_rp = sys.modules.pop('run_player', None)
    saved_vk = sys.modules.pop('vk_player', None)   # 让它重新 import -> 走新登记的 run_player
    saved_argv = sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        try:
            sys.modules['__main__'] = mod
            sys.argv = ['run_player.py']
            try:
                exec(compile(src, path, 'exec'), mod.__dict__)  # main() -> 用法 + exit(2)
            except SystemExit:
                pass
            check('脚本入口把自身登记为 run_player 模块',
                  sys.modules.get('run_player') is mod,
                  sys.modules.get('run_player'))
            import vk_player
            check('VkInitError 类身份唯一 (脚本入口)',
                  vk_player.VkInitError is mod.VkInitError,
                  (vk_player.VkInitError, mod.VkInitError))
            def _boom(scene, **kw):
                raise vk_player.VkInitError('模拟: 无 Vulkan 设备')
            mod._run_vulkan = _boom
            mod._SETTINGS_BASE = tmp
            mod._BOOTSTRAP_KEY[0] = None
            import contextlib
            import io
            buf = io.StringIO()
            exc = None
            with contextlib.redirect_stdout(buf):
                try:
                    mod.run_backend('vulkan', 'x.json')
                except BaseException as e:
                    exc = e
            out = buf.getvalue()
            code = getattr(exc, 'code', None) if isinstance(exc, SystemExit) else None
            check('脚本入口: 初始化失败 -> 非零退出 (不再冒泡成未捕获异常)',
                  isinstance(exc, SystemExit) and code not in (None, 0),
                  (type(exc).__name__, code))
            check('脚本入口: 提示含「不兼容」并走回退', '不兼容' in out, out.strip()[:120])
            setting = os.path.join(tmp, '设置.json')
            wrote = os.path.isfile(setting)
            check('脚本入口: 回退已写入配置 (Q6 持久化真的发生)', wrote, setting)
        finally:
            sys.modules['__main__'] = saved_main
            if saved_rp is not None:
                sys.modules['run_player'] = saved_rp
            else:
                sys.modules.pop('run_player', None)
            if saved_vk is not None:
                sys.modules['vk_player'] = saved_vk
            else:
                sys.modules.pop('vk_player', None)
            sys.argv = saved_argv

# ============ B3. 旧格式迁移 (契约 §6-2 / 审计 P-02-03) ============
def t_legacy_config_migration():
    """旧 游戏配置.json 的 render_api 一次性迁移进用户层, 之后由 游戏设置.json 生效.

    锁住三件事: ① 迁移后 resolve_backend 真的读到 opengl (不是"写了但读不到");
               ② 落点是 游戏设置.json 用户层且只存 delta;
               ③ 旧文件保持只读模板语义 (运行时不得改写它)。
    """
    import json
    import tempfile

    old_base = run_player._SETTINGS_BASE
    old_key = run_player._BOOTSTRAP_KEY[0]
    old_env = {k: os.environ.get(k)
               for k in ("LOOM_GAME_DIR", "LOOM_USER_ROOT")}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_player._SETTINGS_BASE = tmp
            run_player._BOOTSTRAP_KEY[0] = None
            os.environ["LOOM_GAME_DIR"] = tmp
            os.environ["LOOM_USER_ROOT"] = os.path.join(tmp, "userroot")
            legacy = os.path.join(tmp, "游戏配置.json")
            with open(legacy, "w", encoding="utf-8") as f:
                json.dump({"scene": "s.json", "render_api": "opengl"}, f)
            got = run_player.resolve_backend(None)
            check("旧 游戏配置.json 的 render_api 迁移后生效 (resolve -> opengl)",
                  got == "opengl", got)
            user = os.path.join(tmp, "游戏设置.json")
            check("迁移落点是 游戏设置.json 用户层", os.path.isfile(user), user)
            data = {}
            if os.path.isfile(user):
                with open(user, encoding="utf-8") as f:
                    data = json.load(f)
            check("用户层只存 delta (schema=1 / values.render_api)",
                  data.get("schema") == 1
                  and (data.get("values") or {}).get("render_api") == "opengl", data)
            with open(legacy, encoding="utf-8") as f:
                legacy_after = json.load(f)
            check("旧 游戏配置.json 保持只读 (运行时不改写它)",
                  legacy_after.get("render_api") == "opengl", legacy_after)
        finally:
            run_player._SETTINGS_BASE = old_base
            run_player._BOOTSTRAP_KEY[0] = old_key
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


# ============ C. 双后端一致性 (2026-11-06 复核 B 后修正) ============
# 复核 B 指出原 C 段是半自证: 用 __new__ 跳过 __init__、从不断言 far、只对 engine.py
# 做文本断言。这里改为用真实 SceneDriver 实例 + 走真实加载路径, 断言"数据入口钳制"
# 与"运行期裸写(与 GL 属性语义一致)"两件事分开验证。
def t_backend_parity():
    import scene_driver
    from loom_camera import clamp_camera_distance, CAM_DIST_MIN, CAM_DIST_MAX

    # far: 两后端必须同值 (engine.py 的 1000.0 是 GL 契约基准)
    src = open(os.path.join(ROOT, "engine.py"), encoding="utf-8").read()
    check("GL 引擎视距契约 = 1000.0", "self.far = 1000.0" in src)
    d = scene_driver.SceneDriver()          # 真实实例 (不建 GL)
    check("Vulkan 路径 far 与 GL 对齐 = 1000.0", abs(d.far - 1000.0) < 1e-9, d.far)
    check("Vulkan 路径 near 与 GL 对齐 = 0.1", abs(d.near - 0.1) < 1e-9, d.near)

    # 场景加载是"数据入口": 必须在两个后端都钳制 (否则 5000 直接把目标顶出视锥)
    data = {"objects": [], "lights": [],
            "camera": {"target": [0, 0, 0], "distance": 5000.0,
                       "yaw": 0.6, "pitch": -0.35}}
    d.load_from_data(data)
    check("加载 distance=5000 -> 钳制到 1000", abs(d.distance - CAM_DIST_MAX) < 1e-9,
          d.distance)
    data["camera"]["distance"] = 0.01
    d.load_from_data(data)
    check("加载 distance=0.01 -> 钳制到 0.5", abs(d.distance - CAM_DIST_MIN) < 1e-9,
          d.distance)

    # 运行期写入: 两个后端都裸接受 (与 GL 的 camera_distance 属性语义一致,
    # 钳制只发生在数据入口和 GL 滚轮交互里 —— 避免"脚本赋值时 Vk 钳 / GL 不钳"分叉)
    d.camera_distance = 5000.0
    check("运行期写入 5000 原样保留 (与 GL 属性语义一致)",
          abs(d.distance - 5000.0) < 1e-9, d.distance)
    d.camera_distance = 0.1
    check("运行期写入 0.1 原样保留", abs(d.distance - 0.1) < 1e-9, d.distance)

    # 钳制工具本身: 坏数据降级不抛
    for bad, want in ((None, 10.0), ("x", 10.0), (float("nan"), 10.0), (float("inf"), 10.0)):
        check("clamp_camera_distance(%r) -> %.1f" % (bad, want),
              abs(clamp_camera_distance(bad) - want) < 1e-9, clamp_camera_distance(bad))

# ============ D. 编辑器不变式 (P6: 编辑器不上 Vk) ============
def t_editor_invariant():
    src = open(os.path.join(ROOT, "editor.py"), encoding="utf-8").read()
    check("编辑器不读取 render_api (P6: 编辑器固定 Qt+OpenGL)",
          "render_api" not in src)
    gl = open(os.path.join(ROOT, "loom_render.py"), encoding="utf-8").read()
    check("GL 渲染层不用 wgpu (后端边界清晰)", "import wgpu" not in gl)
    vk = open(os.path.join(ROOT, "vk_renderer.py"), encoding="utf-8").read()
    check("Vk 渲染层不用 moderngl (后端边界清晰)", "moderngl" not in vk)


if __name__ == "__main__":
    print("========== 渲染 API 切换契约测试 ==========")
    t_resolve()
    t_dispatch()
    t_precedence()
    t_legacy_config_migration()
    t_unlock_sampling_parity()
    t_run_player_entry_identity()
    t_backend_parity()
    t_editor_invariant()
    print()
    if _fails:
        print("有 FAIL:", _fails)
        sys.exit(1)
    print("总结果: ALL PASS ✅")