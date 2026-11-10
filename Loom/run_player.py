# -*- coding: utf-8 -*-
"""
run_player.py — 播放器渲染 API 选择入口 (2026-08-29 P5)

后端选择优先级:
    命令行 --backend
  > 游戏设置.json 的 render_api（用户层 delta 覆盖 只读模板层）
  > 引擎 设置.json 的 render_api（同样 用户层 delta 覆盖 模板层）
  > 默认 vulkan
  auto 原样透传 (Vk 失败回退 GL)；只有未知取值才归一成 vulkan。
   - vulkan: wgpu-py + GLFW (vk_player.run_vk)
   - opengl: 现有引擎 PlayerApp (pygame 窗口, 保底路径)
   - auto  : 先试 vulkan; 初始化失败 (无 Vulkan 能力/设备) 自动回退 opengl

2026-11-09 人类裁决 A（VK 不兼容 -> 可见失败 + 持久化回退 GL）:
  初始化段失败 = 打印诊断（device/driver/apiVersion）+ 弹窗 + **同进程**立即按 GL 4.3
  继续（旧 Q6「崩一次」已废弃）；GL 也失败 -> 打印两条原因后非零退出；运行期失败
  （VkRunError）不回退、不改配置。
  写配置的边界（Q1/Q7=A）：只有「后端来自配置/默认」才把用户层 render_api 写成 opengl；
  显式 --backend vulkan 与 --backend auto 都**不改写配置**，只给可操作出口提示。

配置分层见 docs/design/用户配置目录契约_20261108.md：模板层只读、用户层只存 delta。

用法: py -3.12 run_player.py <场景.json> [--backend vulkan|opengl|auto]
发布版 (game_player.py) 走同一选择逻辑, 玩家可在启动参数里覆盖
(一般为厂商发布时配置; 运行时切换设置项见编辑器设置面板).
"""
import os
import sys

from loom_backend_guard import show_blocking_dialog   # 2026-11-09 A: 换后端前的可见失败


# 2026-11-07 scan_05 P-10 / Q6: 失败按"段"分类, 供上层决定能不能回退。
_VK_SEG_INIT = "vulkan-init"
_VK_SEG_RUN = "vulkan-run"


class VkInitError(RuntimeError):
    """Vulkan **初始化段**失败 (交换链/设备/管线) —— 可回退 OpenGL 的信号。"""
    segment = _VK_SEG_INIT


class VkRunError(RuntimeError):
    """Vulkan **渲染循环内**失败 —— 不可同进程回退, 打印原因后非零退出。"""
    segment = _VK_SEG_RUN


def _is_vk_error(exc, segment):
    """按"失败段"识别 Vk 异常 —— **不依赖类身份**（审计 P-02-06）。

    背景: `python run_player.py <场景>` 时本文件是 `__main__`; vk_player 里的
    `from run_player import VkInitError` 会**再执行一次**本文件, 得到第二份异常类,
    于是 `except VkInitError` 永远接不到 -> Q6「崩一次后用 GL」的回退链在该入口
    整体失效（实测: 异常冒泡成未捕获 traceback, 不写配置）。
    这里用类属性 segment 识别, 使直接跑脚本 / game_player 打包跑两个入口行为一致。
    """
    return getattr(exc, "segment", None) == segment


# 测试用: 配置所在目录 (None = 契约的 用户层 + 只读模板层)
# 非 None 时它同时作为**两层**的目录:
#   · 引擎 设置.json   -> guiloader 的 base
#   · 游戏 游戏设置.json -> game_settings 的 base_dir 与 LOOM_GAME_DIR 覆盖
# 这样「读」与「写」落在同一处（审计 P-02-09: 旧实现只重定向写侧）。
_SETTINGS_BASE = None

# 用户层初始化（含旧格式迁移）只做一次；键变化时重做（测试切换目录用）
_BOOTSTRAP_KEY = [None]


def _apply_settings_base():
    """把 _SETTINGS_BASE 同步成 game_settings 侧的最高优先级覆盖（测试/工具用）。"""
    if _SETTINGS_BASE:
        os.environ['LOOM_GAME_DIR'] = os.path.abspath(_SETTINGS_BASE)


def _ensure_game_config():
    """启动时把「游戏设置」用户层建好，并完成旧格式迁移（契约 §5 / §6）。

    写失败按 D5 如实报错，但**不阻断读取**（只读模板层仍可用）；真正需要
    持久化的场合由 `_persist_backend` 判定成败并由调用方报错退出。
    返回 True = 用户层可用。
    """
    key = (_SETTINGS_BASE, os.environ.get('LOOM_USER_ROOT'),
           os.environ.get('LOOM_GAME_DIR'))
    if _BOOTSTRAP_KEY[0] == key:
        return True
    _BOOTSTRAP_KEY[0] = key
    try:
        import game_settings
        _apply_settings_base()
        created = game_settings.bootstrap()
        if created:
            print("[run_player] 已初始化用户配置: %s" % (game_settings.user_path(),))
        return True
    except Exception as e:
        print("[run_player] 用户配置初始化失败 (%r) —— 本次按只读模板运行, "
              "配置改动无法持久化" % (e,))
        return False


def _read_setting(key, default):
    """读引擎 设置.json（默认 <- 模板层 <- 用户层 delta）。

    审计 P-02-09: base 必须与写侧对称, 否则测试隔离只覆盖写。
    """
    try:
        import guiloader
        s = guiloader.load_settings('loom', base=_SETTINGS_BASE)
        return s.get(key, default)
    except Exception as e:
        print("[run_player] 读 设置.json 失败 (%r) -> 用默认 %r" % (e, default))
        return default


_LAST_SOURCE = 'default'      # 本次后端来自哪: cli / game / engine / default
_SOURCE_TEXT = {'cli': '命令行 --backend', 'game': '游戏设置.json',
                'engine': '引擎 设置.json', 'default': '默认值'}


def _game_api():
    """读**游戏层** render_api（缺失/非法 -> None）。"""
    try:
        import game_settings
        _apply_settings_base()
        return game_settings.read_render_api()
    except Exception as e:
        print("[run_player] 读 游戏设置.json 失败 (%r) -> 视为未配置" % (e,))
        return None


def resolve_backend(requested=None):
    """解析渲染 API: 参数 > 游戏配置 > 引擎设置 > 默认 vulkan.

    返回 'vulkan'|'opengl'|'auto'。同时把来源记在 `_LAST_SOURCE`
    （用于 Q6 失败提示里说明"这个 vulkan 是谁要求的"）。

    2026-11-06 R-01 修复 (渲染 API 自由切换):
      旧实现只放行 'vulkan'/'opengl', 其它值一律归一成 'vulkan' —— 于是
      'auto' 永远到不了 run_backend 里的回退分支, 与设计文档 P5 明写的
      "auto: Vk 失败自动回退 GL" 直接矛盾。
      现在 'auto' 原样透传; 仅**未知**取值才归一为默认 vulkan。
    """
    global _LAST_SOURCE
    _ensure_game_config()
    api = requested
    if api:
        _LAST_SOURCE = 'cli'
    else:
        api = _game_api()
        if api:
            _LAST_SOURCE = 'game'
        else:
            api = _read_setting('render_api', 'vulkan')
            _LAST_SOURCE = 'engine'
    api = str(api).strip().lower()
    return api if api in ('vulkan', 'opengl', 'auto') else 'vulkan'


def _write_game_layer(api):
    """写**游戏层**（决定打包游戏 / --run 的下次启动）。返回 (ok, 错误信息)。"""
    try:
        import game_settings
        _apply_settings_base()
        ok, _val, err = game_settings.write_render_api(api, base_dir=_SETTINGS_BASE)
        return bool(ok), (None if ok else err)
    except Exception as e:
        return False, repr(e)


def _write_engine_layer(api):
    """写**引擎层** 设置.json（编辑器/开发环境的默认；尽力同步）。"""
    try:
        import guiloader
        s = guiloader.load_settings('loom', base=_SETTINGS_BASE)
        s['render_api'] = api
        if 'backend' in s:        # 少数旧配置用 backend 作键名, 一并同步免得分叉
            s['backend'] = api
        guiloader.save_settings('loom', s, base=_SETTINGS_BASE)
        return True, None
    except Exception as e:
        return False, repr(e)


def _persist_backend(api):
    """把 render_api 写进**用户层 游戏设置.json**，并**复核**下次启动是否真的会读到它。

    2026-11-09 裁决 Q2：**只写游戏层 delta，不动引擎层 设置.json** —— 后者是编辑器/
    开发环境的默认后端，改它超出「自动回退」的授权范围（会把编辑器也带偏）。

    返回 True = 复核通过（`resolve_backend(None)` 得到 api）。

    2026-11-08 审计 P-02-01 修复: 旧实现 `return ok_game or True` 让"游戏配置
    写失败"永远不可见，用户看到"下次启动将使用 OpenGL"却仍走 Vulkan。
    现在只认解析链的最终结果——"写成功了但被更高优先级层压过"同样算失败。
    失败原因一律如实打印（契约 §7 禁止 `or True` / 假成功）。
    """
    ok_game, err_game = _write_game_layer(api)
    if not ok_game:
        print("[run_player] 写 游戏设置.json（用户层）失败: %s" % (err_game,))
        return False
    try:
        got = resolve_backend(None)
    except Exception as e:
        print("[run_player] 回退复核失败 (%r)" % (e,))
        return False
    if got != api:
        print("[run_player] 回退未生效: 解析链下次仍得到 %r（用户层已写=%s）"
              % (got, ok_game))
        return False
    return True


# 2026-11-10 裁决 Q7=A: 显式 --backend vulkan 失败不改写配置，但必须给**可操作出口**。
# auto 同理不写配置：auto 的语义就是「先试 VK，不行再 GL」，本身没有偏好可持久化。
PERMANENT_GL_HINT = (
    '如需永久改用 OpenGL：在 LoomHub 设置里把渲染后端改为 OpenGL，'
    '或把 游戏设置.json 的 render_api 改成 opengl。')


def _handle_vk_init_failure(exc, explicit, api='vulkan'):
    """Vulkan 初始化失败的统一出口（2026-11-09 人类裁决 A：可见失败 + 持久化回退 GL）。

    · 打印诊断（device / driver / driver_info / apiVersion，见 loom_backend_guard）
      并弹窗告知「Vulkan 驱动不兼容（需要 1.1+），已自动切换为 OpenGL（需要 4.3）」；
    · 把**用户层** 游戏设置.json 的 render_api 写成 opengl 并复核（只动 delta 层，
      不碰只读模板）；
    · **不退出进程**：返回是否持久化成功，调用方随即同进程改走 GL 4.3；
    · 只在初始化段调用。运行期（VkRunError）不来回退、不改配置（见 run_backend）。

    与旧 Q6「崩一次」的差异：人类改判为「当场降级 + 落配置」，因为崩一次会让用户
    看到窗口闪退且下次仍要重试；现在一次启动内完成切换，下次直接走 GL。
    """
    reason = _reason_with_tag('[VK]', exc)
    src = _SOURCE_TEXT.get(_LAST_SOURCE, _LAST_SOURCE)
    # 手选判定必须在 _persist_backend 之前取 —— 它内部会 resolve 一次并把 _LAST_SOURCE
    # 改成 'game'，否则每次回退都会被误判成「用户手选」。
    was_hand_picked = (_LAST_SOURCE == 'game')
    print("[run_player] Vulkan 后端不可用 —— 本次进程改走 OpenGL（需要 4.3 core）")
    print(reason)
    if explicit:
        # 裁决 Q1/Q7=A: 显式 --backend vulkan 是用户明确选择 —— 不改写配置，只在本次降级。
        print("[run_player] 本次是显式 --backend vulkan：**不改写用户配置**（尊重显式选择）")
        print("[run_player] " + PERMANENT_GL_HINT)
        return reason, False
    if str(api).strip().lower() == 'auto':
        # 裁决 Q7=A: auto = 「先试 VK 再 GL」，没有偏好可持久化 —— 同样不写配置。
        print("[run_player] 本次是 --backend auto：**不改写配置**（auto 本身就是先试 VK 再 GL）")
        print("[run_player] " + PERMANENT_GL_HINT)
        return reason, False
    ok = _persist_backend('opengl')
    if ok:
        print("[run_player] 已把 render_api 回退为 opengl（只写用户层 游戏设置.json），"
              "下次启动直接走 OpenGL（本次后端来自: %s）" % src)
    else:
        print("[run_player] 回退**未能持久化** —— 下次启动仍会尝试 Vulkan；"
              "本次已切 GL，可用 --backend opengl 固定（本次后端来自: %s）" % src)
    if was_hand_picked:
        print("[run_player] 注意: 配置里的 vulkan 是用户手选（游戏设置.json）；"
              "已按裁决改写为 opengl，可在设置面板随时改回")
    return reason, ok


# 2026-11-10 Q-VER-1=A: 播放器遇到更高版本场景 -> 可见失败 + 优雅退出（不抛 traceback）。
_SCENE_VER_TITLE = '无法打开场景（引擎版本过低）'


def _scene_version_error_cls():
    """惰性取 sceneio.SceneVersionError（避免顶层 import 顺序耦合）。"""
    try:
        import sceneio
        return sceneio.SceneVersionError
    except Exception:
        return None


def handle_scene_version_error(exc):
    """打印原因（要求版本 / 当前版本）+ 弹窗 + SystemExit(1)。

    与 VK 回退同一套可见失败口径：release 版无控制台，必须弹窗；
    LOOM_NO_DIALOG=1（或非 Windows）时只打印、不阻塞。
    """
    msg = ('这个场景要求**更新的引擎版本**，当前播放器无法加载。\n\n'
           '%s\n\n'
           '请用更新版本的 Loom 打开该场景；或在旧版 Loom 里「导出兼容场景」后重试。'
           % (exc,))
    print('[场景] ' + msg)
    shown = show_blocking_dialog(_SCENE_VER_TITLE, msg)
    if not shown:
        print('[场景] (未弹窗: 无 GUI 或 LOOM_NO_DIALOG=1 —— 原因见上面的 [场景] 行)')
    raise SystemExit(1)


def _reason_with_tag(tag, exc):
    """异常原因统一加前缀；已带同一前缀就不重复（P3③: 不出现 [VK] [VK]）。"""
    s = str(exc) or repr(exc)
    return s if s.startswith(tag) else ('%s %s' % (tag, s))


def _open_opengl(scene, **kw):
    """**只构建** GL 播放器（不进入阻塞循环）。失败会抛（GLVersionError 等）。"""
    from runtime import PlayerApp
    if kw.get('scene_data') is not None:
        return PlayerApp(None, kw.get('width', 1280), kw.get('height', 800),
                         scene_data=kw['scene_data'], title=kw.get('title'),
                         assets_base=kw.get('assets_base'))
    return PlayerApp(scene, kw.get('width', 1280), kw.get('height', 800),
                     title=kw.get('title'))


def _report_gl_started(scene, eng):
    print("GL 播放器已启动: %s (%d 个对象)" % (scene or '<数据>', len(eng.models)))


def _run_gl_visible(scene, **kw):
    """只走 GL 时的可见失败（P1: 发布档无控制台 -> 必须弹窗 + 非 0 退出）。"""
    try:
        eng = _open_opengl(scene, **kw)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        _ve = _scene_version_error_cls()
        if _ve is not None and isinstance(e, _ve):
            raise                       # 版本问题交给 run_backend 统一报（不是 GL 故障）
        msg = 'OpenGL 后端无法启动（需要 4.3 core）。\n\n' + _reason_with_tag('[GL]', e)
        print('[backend] ' + msg)
        show_blocking_dialog('无法启动渲染（OpenGL 不可用）', msg)
        raise SystemExit(1)
    _report_gl_started(scene, eng)
    eng.run()
    return None


def _run_gl_or_double_fault(vk_reason, scene, **kw):
    """VK 初始化失败后**同进程**改走 GL 4.3；三条结局都可见，且**只弹一次**窗。

    先只构建 GL（不进入阻塞循环）再决定弹哪个窗：
      · GL 构建失败 -> 一个「两条后端都不可用」弹窗 + SystemExit(1)；
      · GL 构建成功 -> 一个「已切换 OpenGL」弹窗，然后才开始跑（否则弹窗要等游戏退出）。
    两条后端地板不同（VK 1.1 / GL 4.3），所以不允许「VK 失败就当 GL 能用」。
    """
    try:
        eng = _open_opengl(scene, **kw)
    except BaseException as gl_exc:
        if isinstance(gl_exc, (KeyboardInterrupt, SystemExit)):
            raise
        _ve = _scene_version_error_cls()
        if _ve is not None and isinstance(gl_exc, _ve):
            raise                       # 场景版本问题：不许伪装成「双后端都挂了」
        msg = ('两条后端都不可用（Vulkan 与 OpenGL 均启动失败）:\n\n'
               + vk_reason + '\n\n' + _reason_with_tag('[GL]', gl_exc))
        print('[backend] ' + msg)
        show_blocking_dialog('无法启动渲染（Vulkan 与 OpenGL 均不可用）', msg)
        raise SystemExit(1)
    msg = ('Vulkan 后端不可用，已自动切换为 OpenGL（需要 4.3 core）。\n\n'
           '你的 Vulkan 驱动可能不兼容（需要 1.1+），建议升级显卡驱动。\n\n'
           + vk_reason + '\n\n' + PERMANENT_GL_HINT)
    print('[backend] Vulkan 不可用 -> 本次已切换 OpenGL')
    shown = show_blocking_dialog('[VK] Vulkan 驱动不兼容（需要 1.1+）', msg)
    if not shown:
        print('[backend] (未弹窗: 无 GUI 或 LOOM_NO_DIALOG=1 —— 原因见上面的 [VK] 行)')
    _report_gl_started(scene, eng)
    eng.run()
    return None


def _maybe_remote_fallback(scene):
    """C5=B: VK 侧上屏连续失败时, 由本层做**一次**远程回读降级（与 Loom.py 同语义）。

    只在 LOOM_REMOTE_MODE=auto 且存在明文场景路径时生效（游戏包 dict 模式没法重启进程）。
    """
    try:
        if (os.environ.get('LOOM_REMOTE_MODE') or '').strip().lower() != 'auto':
            return False
        import vk_player
        if not vk_player.LAST_FALLBACK_REQUESTED[0]:
            return False
        if not scene or not os.path.exists(scene):
            print('[run_player] VK 上屏失败, 但当前为游戏包/无路径模式 -> 无法重启为远程回读')
            return False
        from loom_player_window import run_player_window
        run_player_window(scene)
        return True
    except Exception as e:
        print('[run_player] 远程回读降级失败 (%r)' % (e,))
        return False


def run_backend(api, scene=None, explicit=False, **kw):
    """按 api 启动播放器 (阻塞). api == 'auto' 时先 Vk 后回退 GL.
    kw 支持 scene_data= (游戏包 dict 模式) / title= / width= / height=.
    explicit=True = api 来自命令行 --backend (Q6: 显式 vulkan 失败不改写设置).

    2026-11-10 Q-VER-1=A: 场景版本过低**不是**后端问题 —— 在这里统一拦截，
    打印原因（要求版本/当前版本）+ 弹窗 + SystemExit(1)，不冒泡 traceback。
    """
    _ver_err = _scene_version_error_cls()
    if _ver_err is not None:
        try:
            return _run_backend_impl(api, scene, explicit=explicit, **kw)
        except _ver_err as e:
            handle_scene_version_error(e)
    return _run_backend_impl(api, scene, explicit=explicit, **kw)


def _run_backend_impl(api, scene=None, explicit=False, **kw):
    _ensure_game_config()
    if api == 'auto':
        try:
            return _run_vulkan(scene, **kw)
        except Exception as e:
            if isinstance(e, VkRunError) or _is_vk_error(e, _VK_SEG_RUN):
                raise                   # 运行期失败: 不回退, 如实失败
            _ve = _scene_version_error_cls()
            if _ve is not None and isinstance(e, _ve):
                raise                   # 场景版本问题不是「Vulkan 不可用」，别伪装后回退
            if isinstance(e, VkInitError) or _is_vk_error(e, _VK_SEG_INIT):
                # 2026-11-09 裁决 A: 初始化失败 -> 诊断+落配置, 然后同进程走 GL（弹窗只弹一次）
                reason, _ok = _handle_vk_init_failure(e, explicit, api)
            else:
                reason = _reason_with_tag('[VK]', e)
                print("[run_player] Vulkan 不可用 (%s), 回退 OpenGL" % e)
            return _run_gl_or_double_fault(reason, scene, **kw)
    if api == 'vulkan':
        try:
            _ret = _run_vulkan(scene, **kw)
            _maybe_remote_fallback(scene)
            return _ret
        except Exception as e:
            # 只把**初始化段**当可回退信号（VkRunError / 其它异常原样上抛）
            if isinstance(e, VkInitError) or _is_vk_error(e, _VK_SEG_INIT):
                reason, _ok = _handle_vk_init_failure(e, explicit, api)   # 不再 SystemExit: 当场降级
                return _run_gl_or_double_fault(reason, scene, **kw)
            raise
    # 只走 GL：失败同样必须可见（P1: 发布档无控制台时不能零反馈闪退）
    return _run_gl_visible(scene, **kw)


def _run_vulkan(scene, **kw):
    from vk_player import run_vk
    return run_vk(scene, **kw)


def _run_opengl(scene, **kw):
    """兼容旧调用面：构建 + 报告 + 阻塞运行（失败原样抛出）。"""
    eng = _open_opengl(scene, **kw)
    _report_gl_started(scene, eng)
    eng.run()
    return None


def main():
    args = sys.argv[1:]
    scene = args[0] if args and not args[0].startswith('--') else None
    backend = None
    for i, a in enumerate(args):
        if a == '--backend' and i + 1 < len(args):
            backend = args[i + 1]
    if not scene:
        print("用法: py -3.12 run_player.py <场景.json> [--backend vulkan|opengl|auto]")
        sys.exit(2)
    run_backend(resolve_backend(backend), scene, explicit=(backend is not None))


# 2026-11-08 审计 P-02-06 根因修复: 以脚本方式运行时, 把本模块**登记为** run_player。
# 这样 vk_player 的 `from run_player import VkInitError, VkRunError` 拿到的是同一个
# 模块对象（同一个类对象），两个入口的异常捕获行为才一致；不登记则模块会被二次执行。
if __name__ == '__main__':
    sys.modules.setdefault('run_player', sys.modules[__name__])
    main()