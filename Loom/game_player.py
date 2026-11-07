# -*- coding: utf-8 -*-
"""
game_player.py — 纯 Player 游戏入口 (M38, Unity Build 模型)
2026-08-22 升级为"游戏包"发布链路 (Unity exe+_Data 对齐):

为什么独立入口: 打包成玩家 exe 时只 import runtime(PlayerApp) 与 engine,
  **不 import editor(EditorApp)** → Nuitka 不会把编辑器编进 exe →
  玩家拿到的 exe 只有运行时, 无法打开编辑器看场景/脚本 (Unity 剥离编辑器).

启动逻辑 (模仿 Unity 双击 exe 进游戏, 优先级):
  1. 读 exe 旁 游戏包.lsc (游戏包 = 场景+游戏脚本+配置, LOOMSC 混淆)
     → 先注册脚本 (register_sources, 顺序关键: 未注册脚本被引擎静默跳过)
     → PlayerApp 直接喂场景字典 (场景不出明文) → 进游戏.
     缺 .lsc = (_Data 缺失) → 报错提示, 不启动 (与 Unity 同语义).
  2. 兼容旧发布 (开发调试): --run <场景> / 游戏配置.json {"scene": "..."}
     → 明文场景文件直接跑.

打包 (开发者, 见《制作游戏完整流程教学.txt》第八节):
  py -3.12 -m nuitka --standalone --msvc=latest --assume-yes-for-downloads \
    --enable-plugin=tk-inter --windows-disable-console \
    --output-dir=Game --output-filename=MyGame.exe game_player.py
分发: exe + 游戏包.lsc 放一个文件夹 (二者不可分离).
"""
import json
import os
import sys

_EXE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))


def _run_from_pack():
    """游戏包启动: 返回 PlayerApp 实例或 None (无有效包 = 不启动).
    包查找: exe 目录优先, 其次当前目录 (源码开发时 Ctrl+F5 便捷)."""
    import game_pack
    gm = None
    for d in (_EXE_DIR, os.getcwd()):
        gm = game_pack.load(d)
        if gm is not None:
            break
    if gm is None:
        return None
    # 2026-08-27: 播放器层插件装载 —— secure 校验 .lpc 哈希后内存注册;
    # open/MOD 装发布夹 plugins/player/ 目录. 缺/被改 -> SystemExit 报错.
    import game_pack
    n_plug = game_pack.install_game_plugins(_EXE_DIR, gm)
    from scripts import register_sources
    n = register_sources(gm.get('scripts') or [])
    cf = gm.get('config') or {}
    from runtime import PlayerApp
    engine = PlayerApp(None, 1280, 800, scene_data=gm.get('scene'),
                       title=cf.get('title'))
    print("游戏已启动: %s (%d 个对象, %d 个游戏脚本, %d 个插件)" %
          (cf.get('name', '未命名游戏'), len(engine.models), n, n_plug))
    return engine


def _run_from_scene(scene):
    """明文场景启动 (兼容旧发布/开发调试)."""
    if not os.path.isabs(scene):
        scene = os.path.join(_EXE_DIR, scene)
    from runtime import PlayerApp
    engine = PlayerApp(scene, 1280, 800)
    print("游戏已启动: %s (%d 个对象)" % (scene, len(engine.models)))
    return engine


def _pick_backend(overridden=None):
    """发布游戏渲染 API: --backend 参数 > <exe目录>/游戏配置.json 的 render_api
    > 应用设置 render_api (编辑器里选) > 默认 vulkan. 玩家可自行调整
    (参数覆盖; 配置持久化见 run_player.resolve_backend)."""
    try:
        with open(os.path.join(_EXE_DIR, "游戏配置.json"),
                  'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            overridden = overridden or cfg.get('render_api')
    except Exception:
        pass
    import run_player
    return run_player.resolve_backend(overridden)


def _run_backend_safe(backend, scene=None, explicit=False, **kw):
    """发布链最后防线: 渲染后端启动失败时醒目告警并回退 OpenGL.

    2026-11-06 R-06 (复核 B 指出): 发布链原来直接 run_backend(), 没有任何兜底;
    打包版是 --windows-disable-console, Vulkan 初始化失败 (无 Vk 驱动/虚拟机/
    远程桌面) 时用户只看到"双击没反应"。

    2026-11-07 (P-10 + Q6): 分工改成 ——
      · Vulkan **初始化**失败: 由 run_player 统一处理 (非显式时把设置回退成
        opengl 并以非零码退出, 下次启动即 OpenGL; 显式 --backend vulkan 只报错),
        这里**不**吞掉那个 SystemExit (崩一次, 不伪装成功);
      · Vulkan **渲染循环内**失败 (VkRunError): 同样不回退 —— 已初始化的后端
        半路改道只会把问题藏起来;
      · 其余意外异常: 仍兜底回退 OpenGL (发布链最后一道网)。

    返回**实际生效**的后端名 ('vulkan'/'opengl'), 供 _start_pack 打印日志
    (scan_05 P-11: 原来只回传 run_backend 的结果, 回退后日志仍写入参)。
    """
    import run_player
    # 2026-11-07 R5 (P-11): run_backend 的 'auto' 分支会在内部把 Vulkan
    # 失败改走 OpenGL, 外层拿不到这个事实。启动期临时包一层两个后端入口,
    # 只观测实际调用 (不改行为), 结束后恢复; 最后被调用的就是实际后端。
    used = []
    orig_vk = run_player._run_vulkan
    orig_gl = run_player._run_opengl

    def _track_vk(*a, **k):
        ret = orig_vk(*a, **k)      # 只有真正跑完的后端才算"实际生效"
        used.append('vulkan')
        return ret

    def _track_gl(*a, **k):
        ret = orig_gl(*a, **k)
        used.append('opengl')
        return ret

    run_player._run_vulkan = _track_vk
    run_player._run_opengl = _track_gl
    try:
        try:
            run_player.run_backend(backend, scene, explicit=explicit, **kw)
        except (SystemExit, run_player.VkRunError):
            raise
        except Exception as e:      # noqa: BLE001 - 发布链必须兜住一切初始化失败
            print("[game_player] 渲染后端启动失败: %s (%r)" % (backend, e))
            print("[game_player] 已自动回退 OpenGL；若仍失败请把上面这行发给开发者")
            run_player.run_backend("opengl", scene, **kw)
    finally:
        run_player._run_vulkan = orig_vk
        run_player._run_opengl = orig_gl
    return used[-1] if used else backend


def _start_pack(backend, explicit=False):
    """游戏包启动: 解包+插件/脚本注册后按渲染 API 进入播放器 (Vk/GL)."""
    import game_pack
    gm = None
    for d in (_EXE_DIR, os.getcwd()):
        gm = game_pack.load(d)
        if gm is not None:
            break
    if gm is None:
        return None
    n_plug = game_pack.install_game_plugins(_EXE_DIR, gm)
    from scripts import register_sources
    n = register_sources(gm.get('scripts') or [])
    cf = gm.get('config') or {}
    actual = _run_backend_safe(backend, scene_data=gm.get('scene'),
                               title=cf.get('title'), explicit=explicit)
    print("游戏已启动: %s (%d 个游戏脚本, %d 个插件, 渲染API=%s)" %
          (cf.get('name', '未命名游戏'), n, n_plug, actual))
    return True


def main():
    args = sys.argv[1:]
    backend = None
    for i, a in enumerate(args):
        if a == "--backend" and i + 1 < len(args):
            backend = args[i + 1]
    explicit = backend is not None      # 命令行 --backend = 显式选择 (不改写设置)
    if "--run" in args:
        i = args.index("--run")
        if i + 1 < len(args):
            import run_player
            _run_backend_safe(_pick_backend(backend), args[i + 1], explicit=explicit)
            return
    if _start_pack(_pick_backend(backend), explicit=explicit) is not None:
        return
    # 兼容旧发布: exe 旁 游戏配置.json
    try:
        with open(os.path.join(_EXE_DIR, "游戏配置.json"),
                  'r', encoding='utf-8') as f:
            scene = json.load(f).get('scene')
        if scene:
            import run_player
            _run_backend_safe(_pick_backend(backend), scene, explicit=explicit)
            return
    except Exception:
        pass
    print("缺少游戏包: 请把 游戏包.lsc 放到 exe 同目录 "
          "(或 --run <场景> / 旧式 游戏配置.json)")
    sys.exit(1)


if __name__ == "__main__":
    main()
