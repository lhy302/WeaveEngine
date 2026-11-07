# -*- coding: utf-8 -*-
"""
run_player.py — 播放器渲染 API 选择入口 (2026-08-29 P5)

后端选择优先级: 命令行 --backend > 设置.json 的 render_api (编辑器里选) > 默认 vulkan。\n  auto 原样透传 (Vk 失败回退 GL)；只有未知取值才归一成 vulkan。
  - vulkan: wgpu-py + GLFW (vk_player.run_vk)
  - opengl: 现有引擎 PlayerApp (pygame 窗口, 保底路径)
  - auto  : 先试 vulkan; 初始化失败 (无 Vulkan 能力/设备) 自动回退 opengl

用法: py -3.12 run_player.py <场景.json> [--backend vulkan|opengl|auto]
发布版 (game_player.py) 走同一选择逻辑, 玩家可在启动参数里覆盖
(一般为厂商发布时配置; 运行时切换设置项见编辑器设置面板).
"""
import sys


# 2026-11-07 scan_05 P-10 / Q6: 失败按"段"分类, 供上层决定能不能回退。
class VkInitError(RuntimeError):
    """Vulkan **初始化段**失败 (交换链/设备/管线) —— 可回退 OpenGL 的信号。"""


class VkRunError(RuntimeError):
    """Vulkan **渲染循环内**失败 —— 不可同进程回退, 打印原因后非零退出。"""


# 测试用: 设置.json 所在目录 (None = guiloader 默认, 即程序/exe 目录)
_SETTINGS_BASE = None


def _read_setting(key, default):
    try:
        import guiloader
        s = guiloader.load_settings('loom')
        return s.get(key, default)
    except Exception:
        return default


def resolve_backend(requested=None):
    """解析渲染 API: 参数 > 设置 > 默认 vulkan. 返回 'vulkan'|'opengl'|'auto'.

    2026-11-06 R-01 修复 (渲染 API 自由切换):
      旧实现只放行 'vulkan'/'opengl', 其它值一律归一成 'vulkan' —— 于是
      'auto' 永远到不了 run_backend 里的回退分支, 与设计文档 P5 明写的
      "auto: Vk 失败自动回退 GL" 直接矛盾 (CLI --backend auto、游戏配置
      render_api=auto、设置面板取值全部失效, 无 Vulkan 的机器必崩)。
      现在 'auto' 原样透传; 仅**未知**取值才归一为默认 vulkan。
    """
    api = (requested or _read_setting('render_api', 'vulkan') or 'vulkan')
    api = str(api).strip().lower()
    return api if api in ('vulkan', 'opengl', 'auto') else 'vulkan'


def _persist_backend(api):
    """把 render_api 写进 设置.json (下次启动生效). 返回 True = 写成功."""
    try:
        import guiloader
        s = guiloader.load_settings('loom', base=_SETTINGS_BASE)
        s['render_api'] = api
        if 'backend' in s:        # 少数旧配置用 backend 作键名, 一并同步免得分叉
            s['backend'] = api
        guiloader.save_settings('loom', s, base=_SETTINGS_BASE)
        return True
    except Exception as e:
        print("[run_player] 写入设置失败 (%r) —— 请手动把 设置.json 的 "
              "render_api 改成 %s" % (e, api))
        return False


def _handle_vk_init_failure(exc, explicit):
    """Vulkan 初始化失败的统一出口 (Q6 后端策略). 打印原因后非零退出.

    · 非显式 (设置/默认走到 vulkan): 把 设置.json 的 render_api 写成 opengl,
      提示"下次启动将使用 OpenGL", 本次进程**非零退出** (崩一次, 不伪装成功);
    · 显式 --backend vulkan: 不改写设置, 只报错退出 (用户明确要 vulkan);
    · --backend auto: 不走这里 (见 run_backend 的回退分支, 不写设置)。
    """
    reason = str(exc) or repr(exc)
    if explicit:
        print("[run_player] Vulkan 后端不可用 (%s)" % reason)
        print("[run_player] 显式 --backend vulkan: 不改写设置, 直接报错退出")
        raise SystemExit(1)
    ok = _persist_backend('opengl')
    print("[run_player] Vulkan 后端不兼容（%s），已把设置回退为 OpenGL，"
          "下次启动将使用 OpenGL" % reason)
    if not ok:
        print("[run_player] 警告: 设置写入失败, 下次启动仍会尝试 Vulkan")
    raise SystemExit(1)


def run_backend(api, scene=None, explicit=False, **kw):
    """按 api 启动播放器 (阻塞). api == 'auto' 时先 Vk 后回退 GL.
    kw 支持 scene_data= (游戏包 dict 模式) / title= / width= / height=.
    explicit=True = api 来自命令行 --backend (Q6: 显式 vulkan 失败不改写设置)."""
    if api == 'auto':
        try:
            return _run_vulkan(scene, **kw)
        except VkRunError:
            raise                       # 运行期失败: 不回退, 如实失败
        except Exception as e:
            print("[run_player] Vulkan 不可用 (%s), 回退 OpenGL" % e)
            return _run_opengl(scene, **kw)
    if api == 'vulkan':
        try:
            return _run_vulkan(scene, **kw)
        except VkInitError as e:
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


if __name__ == '__main__':
    main()
