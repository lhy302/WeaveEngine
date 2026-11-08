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

配置分层见 docs/design/用户配置目录契约_20261108.md：模板层只读、用户层只存 delta。

用法: py -3.12 run_player.py <场景.json> [--backend vulkan|opengl|auto]
发布版 (game_player.py) 走同一选择逻辑, 玩家可在启动参数里覆盖
(一般为厂商发布时配置; 运行时切换设置项见编辑器设置面板).
"""
import os
import sys


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
    """把 render_api 写进配置，并**复核**下次启动是否真的会读到它。

    返回 True = 复核通过（`resolve_backend(None)` 得到 api）。

    2026-11-08 审计 P-02-01 修复: 旧实现 `return ok_game or True` 让"游戏配置
    写失败"永远不可见，用户看到"下次启动将使用 OpenGL"却仍走 Vulkan。
    现在只认解析链的最终结果——"写成功了但被更高优先级层压过"同样算失败。
    失败原因一律如实打印（契约 §7 禁止 `or True` / 假成功）。
    """
    ok_game, err_game = _write_game_layer(api)
    ok_engine, err_engine = _write_engine_layer(api)
    if not ok_game:
        print("[run_player] 写 游戏设置.json 失败: %s" % (err_game,))
    if not ok_engine:
        print("[run_player] 写 引擎 设置.json 失败: %s" % (err_engine,))
    if not (ok_game or ok_engine):
        return False
    try:
        got = resolve_backend(None)
    except Exception as e:
        print("[run_player] 回退复核失败 (%r)" % (e,))
        return False
    if got != api:
        print("[run_player] 回退未生效: 解析链下次仍得到 %r（游戏层=%s / 引擎层=%s）"
              % (got, '已写' if ok_game else '写失败',
                 '已写' if ok_engine else '写失败'))
        return False
    return True


def _handle_vk_init_failure(exc, explicit):
    """Vulkan 初始化失败的统一出口 (Q6 后端策略). 打印原因后非零退出.

    · 非显式 (设置/默认走到 vulkan): 把 render_api 写成 opengl 并**复核**,
      成功才提示"下次启动将使用 OpenGL"; 失败如实报错 —— 两种情况都非零退出
      (崩一次, 不伪装成功);
    · 显式 --backend vulkan: 不改写设置, 只报错退出 (用户明确要 vulkan);
    · --backend auto: 不走这里 (见 run_backend 的回退分支, 不写设置)。
    """
    reason = str(exc) or repr(exc)
    src = _SOURCE_TEXT.get(_LAST_SOURCE, _LAST_SOURCE)
    if explicit:
        print("[run_player] Vulkan 后端不可用 (%s)" % reason)
        print("[run_player] 显式 --backend vulkan: 不改写设置, 只报错退出")
        raise SystemExit(1)
    ok = _persist_backend('opengl')
    if ok:
        print("[run_player] Vulkan 后端不兼容（%s），已把 render_api 回退为 OpenGL，"
              "下次启动将使用 OpenGL（本次后端来自: %s）" % (reason, src))
    else:
        print("[run_player] Vulkan 后端不兼容（%s），且**回退未能持久化** —— "
              "下次启动仍会尝试 Vulkan（本次后端来自: %s）" % (reason, src))
        print("[run_player] 请手动把 游戏设置.json / 设置.json 的 render_api 改成 "
              "opengl；本次可直接用 --backend opengl 启动")
    raise SystemExit(1)


def run_backend(api, scene=None, explicit=False, **kw):
    """按 api 启动播放器 (阻塞). api == 'auto' 时先 Vk 后回退 GL.
    kw 支持 scene_data= (游戏包 dict 模式) / title= / width= / height=.
    explicit=True = api 来自命令行 --backend (Q6: 显式 vulkan 失败不改写设置)."""
    _ensure_game_config()
    if api == 'auto':
        try:
            return _run_vulkan(scene, **kw)
        except Exception as e:
            if isinstance(e, VkRunError) or _is_vk_error(e, _VK_SEG_RUN):
                raise                   # 运行期失败: 不回退, 如实失败
            print("[run_player] Vulkan 不可用 (%s), 回退 OpenGL" % e)
            return _run_opengl(scene, **kw)
    if api == 'vulkan':
        try:
            return _run_vulkan(scene, **kw)
        except Exception as e:
            # 只把**初始化段**当可回退信号（VkRunError / 其它异常原样上抛）
            if isinstance(e, VkInitError) or _is_vk_error(e, _VK_SEG_INIT):
                _handle_vk_init_failure(e, explicit)     # 内部 SystemExit(1)
            raise
    return _run_opengl(scene, **kw)


def _run_vulkan(scene, **kw):
    from vk_player import run_vk
    return run_vk(scene, **kw)


def _run_opengl(scene, **kw):
    from runtime import PlayerApp
    if kw.get('scene_data') is not None:
        eng = PlayerApp(None, kw.get('width', 1280), kw.get('height', 800),
                        scene_data=kw['scene_data'], title=kw.get('title'))
    else:
        eng = PlayerApp(scene, kw.get('width', 1280), kw.get('height', 800),
                        title=kw.get('title'))
    print("GL 播放器已启动: %s (%d 个对象)" % (scene or '<数据>', len(eng.models)))
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