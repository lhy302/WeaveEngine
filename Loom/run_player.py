# -*- coding: utf-8 -*-
"""
run_player.py — 播放器渲染 API 选择入口 (2026-08-29 P5)

后端选择优先级: 命令行 --backend > 设置.json 的 render_api (编辑器里选) > 默认 vulkan。
  - vulkan: wgpu-py + GLFW (vk_player.run_vk)
  - opengl: 现有引擎 PlayerApp (pygame 窗口, 保底路径)
  - auto  : 先试 vulkan; 初始化失败 (无 Vulkan 能力/设备) 自动回退 opengl

用法: py -3.12 run_player.py <场景.json> [--backend vulkan|opengl|auto]
发布版 (game_player.py) 走同一选择逻辑, 玩家可在启动参数里覆盖
(一般为厂商发布时配置; 运行时切换设置项见编辑器设置面板).
"""
import sys


def _read_setting(key, default):
    try:
        import guiloader
        s = guiloader.load_settings('loom')
        return s.get(key, default)
    except Exception:
        return default


def resolve_backend(requested=None):
    """解析渲染 API: 参数 > 设置 > 默认 vulkan. 返回 'vulkan'|'opengl'."""
    api = (requested or _read_setting('render_api', 'vulkan') or 'vulkan').lower()
    return api if api in ('vulkan', 'opengl') else 'vulkan'


def run_backend(api, scene=None, **kw):
    """按 api 启动播放器 (阻塞). api == 'auto' 时先 Vk 后回退 GL.
    kw 支持 scene_data= (游戏包 dict 模式) / title= / width= / height=."""
    if api == 'auto':
        try:
            return _run_vulkan(scene, **kw)
        except Exception as e:
            print("[run_player] Vulkan 不可用 (%s), 回退 OpenGL" % e)
            return _run_opengl(scene, **kw)
    if api == 'vulkan':
        return _run_vulkan(scene, **kw)
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
    run_backend(resolve_backend(backend), scene)


if __name__ == '__main__':
    main()
