#! python3.12
# -*- coding: utf-8 -*-
"""
Loom.py — 入口: 命令行参数 + 数学管线基准 + 启动引擎

模块拆分:
  matlib.py   4×4 矩阵数学库 (MVP)
  mesh.py     顶点/索引缓冲 Mesh + cube/sphere 生成器
  engine.py   GLEngine 渲染引擎 (moderngl/OpenGL 真 GPU 渲染 + pygame 窗口/输入/HUD)

命令行:
  python Loom.py                          启动编辑器 (默认)
  python Loom.py --editor                 显式启动编辑器
  python Loom.py --run <scene.json>       播放场景 (运行时, 无编辑器 UI)
  python Loom.py --open <scene.json>      编辑器打开指定场景 (供项目管理器"打开项目")
  python Loom.py --benchmark [三角形数] [迭代数]  数学管线基准 (不弹窗口)
  python Loom.py --bench <scene.json> [帧数]     场景基准 (转交 build_entry._bench_scene; 结果写 bench_result.txt)
"""
import os
import sys


def _parse_args(argv):
    """解析命令行参数: --benchmark / --run <场景> / --open <场景> / --editor /
    --ui <视图> / 默认编辑器. --ui 选择编辑器 UI 实现 (IEditorView, UI 模块化):
    默认 = LoomGUI (Qt 核心视图), 'minimal'=极简只读视图 (MinimalEditorView)."""
    benchmark = False
    n_tri, n_iter = 5000, 100
    run_scene = None
    open_scene = None
    editor = False
    ui = 'qt'   # 2026-08-28 起默认 = LoomGUI (Qt 原生视图; 旧 pygame 即时模式
                # 视图已删除, 名字回归核心 GUI); --ui default 走 guiloader, minimal 遗留
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--benchmark':
            benchmark = True
            if i + 1 < len(argv) and argv[i + 1].isdigit():
                n_tri = int(argv[i + 1])
                i += 1
            if i + 1 < len(argv) and argv[i + 1].isdigit():
                n_iter = int(argv[i + 1])
                i += 1
        elif a == '--run' and i + 1 < len(argv):
            run_scene = argv[i + 1]
            i += 1
        elif a == '--open' and i + 1 < len(argv):
            open_scene = argv[i + 1]
            i += 1
        elif a == '--ui' and i + 1 < len(argv):
            # 2026-10-18 选项1: --ui 参数已无实际效果（旧 pygame 视图 --ui default/minimal
            # 已删，编辑器只剩 Qt）。保留参数解析是为了老启动脚本不报错。
            ui = argv[i + 1]
            i += 1
        elif a == '--editor':
            editor = True
        i += 1
    return benchmark, n_tri, n_iter, run_scene, open_scene, editor, ui


def _make_editor_view(ui_name, base=None):
    """按 --ui 选择编辑器视图实现 (IEditorView). 返回 None = 用默认 LoomGUI.
    2026-08-14: 'default' 时读设置选 GUI (自定义 GUI 来自 GUI/ 文件夹, 重启后生效;
    加载失败自动回退官方返回 None).
    2026-08-28: 默认官方 GUI = LoomGUI (ui/loom_gui.py, Qt 原生视图).
    2026-11-06 恢复: 487120c「剥离 pygame 窗口」把它与 MinimalEditorView 一并删除,
    但 editor.py:137 仍以 MinimalEditorView 作为"未注入 view 时的兜底", 且
    build_entry.py:77 仍调用本函数 —— 删除直接造成 ModuleNotFoundError。
    二者按当年实现恢复; Qt 编辑器仍是实际运行入口 (本函数只服务显式 --ui 路径)。"""
    if ui_name == 'minimal':
        from ui.minimal_editor_view import MinimalEditorView
        return MinimalEditorView()
    if ui_name in ('default', None, ''):
        from guiloader import resolve_gui
        return resolve_gui('loom', base=base)
    return None


def _cli_backend(argv):
    """取 --backend <vulkan|opengl|auto> (缺省 None = 交给设置/默认).

    2026-11-06 R-04 修复 (复核 B 指出): 本入口的 --run / 游戏配置.json 分支
    原来直连 runtime.PlayerApp (恒 OpenGL), 既不解析 --backend 也不读
    render_api —— 同一份发布物从 run_player/game_player 启动是 Vk,
    从 Loom.py 启动却是 GL, "API 自由切换"在这个入口完全失效。
    这里只解析参数, 真正的后端选择仍走 run_player.resolve_backend 单一事实。"""
    for i, a in enumerate(argv):
        if a == "--backend" and i + 1 < len(argv):
            return argv[i + 1]
    return None


# ==================== E2: 远程模式三态 (2026-11-09 beta5) ====================
# LOOM_REMOTE_MODE 取值 (Hub 默认**不注入** = off, 见版本计划 E2):
#   off(未设) / 0  -> 原生 present (旧行为, 不变)
#   on  / 1        -> 强制离屏回读 + Qt 窗口 (旧行为, 不变)
#   auto           -> **先试原生**; 引擎判"上屏连续失败 >= 阈值"时降级为 on 等价路径
#                     **只重启一次**(防死循环), 并打印一行明确原因。
# 判据只接 loom_render.should_fallback_remote(n) (引擎自己数 consecutive failures),
# 本层不复制阈值/不猜, 也不改进程形态之外的行为。
_REMOTE_ON_VALUES = ('1', 'on', 'true', 'yes', 'remote')


def _remote_mode():
    """归一 LOOM_REMOTE_MODE -> 'off' | 'on' | 'auto'（未知值按 off，保持旧语义）。"""
    v = (os.environ.get('LOOM_REMOTE_MODE') or '').strip().lower()
    if v == 'auto':
        return 'auto'
    if v in _REMOTE_ON_VALUES:
        return 'on'
    return 'off'


def _install_present_watch(threshold=3):
    """auto 模式: 装一个上屏健康监视，命中引擎判据后让原生循环退出。

    为什么包在 PlayerApp.run 上: 原生播放是**阻塞**调用 (run_backend -> eng.run())，
    入口层拿不到引擎实例；而 present 健康是引擎实例态 (loom_render.present_health /
    should_fallback_remote)。这里只做"观测 + 请求退出"——判据、阈值、计数全在引擎，
    本函数不复制。返回 state dict，调用方据此决定是否重启为 remote。
    """
    state = {'fallback': False, 'streak': 0, 'last_error': None}
    try:
        import threading
        from runtime import PlayerApp
    except Exception as e:
        print('[remote] auto: 无法安装上屏健康监视 (%r) -> 按原生模式运行' % (e,))
        return state
    if getattr(PlayerApp, '_loom_present_watch_installed', False):
        return state
    orig_run = PlayerApp.run

    def run(self, *a, **k):
        stop = threading.Event()

        def _watch():
            while not stop.is_set():
                try:
                    if self.should_fallback_remote(threshold):
                        h = self.present_health()
                        state['fallback'] = True
                        state['streak'] = h.get('fail_streak')
                        state['last_error'] = h.get('last_error')
                        # 结束原生渲染循环 -> 回到入口层做一次 remote 重启。
                        # 先等循环真正起来（run() 开头会 self._running=True），
                        # 否则起跑竞态里这一下会被覆盖，窗口就再也收不掉。
                        while not stop.is_set():
                            try:
                                if getattr(self, '_running', False):
                                    self._running = False
                                    return
                            except Exception:
                                return
                            stop.wait(0.02)
                        return
                except Exception:
                    return          # 引擎不支持下屏健康 (无 _present_*) -> 不监视
                stop.wait(0.1)   # 上屏失败后尽快收口 (白屏停留 <=100ms 级)

        threading.Thread(target=_watch, name='loom-present-watch',
                         daemon=True).start()
        try:
            return orig_run(self, *a, **k)
        finally:
            stop.set()

    PlayerApp.run = run
    PlayerApp._loom_present_watch_installed = True
    return state


def _launch_native(scene, width=1280, height=800):
    """原生 present 启动（--backend > 设置 render_api > 默认）。"""
    from run_player import resolve_backend, run_backend
    cli = _cli_backend(sys.argv)
    run_backend(resolve_backend(cli), scene, width=width, height=height,
                explicit=(cli is not None))


def _launch_player(scene, width=1280, height=800):
    """按 --backend > 设置 render_api > 默认 的统一策略启动播放器.

    LOOM_REMOTE_MODE:
      · on/1  (离屏 GL + Qt 窗口白屏兜底) 强制 GL —— 该模式本身就是"GL 不可见时
        改走离屏读回", 与 Vulkan 无关, 必须优先（2026-11-07 scan_11 P-07: 该优先
        规则必须在**本函数体**里实现, 否则"游戏配置.json 双击启动"那条路径没有兜底）。
      · auto  (2026-11-09 E2): 先按原生 present 启动; 若引擎判 should_fallback_remote(3)
        为真（连续上屏失败），**重启一次**为 on 等价路径并打印原因。
      · off/0 (默认): 原生启动, 旧行为。

    显式 --backend 由 _cli_backend 判定, 交给 run_player 的后端策略
    (Q6: 显式 vulkan 失败只报错不改写设置; 设置/默认走到 vulkan 失败则把
    设置回退成 opengl 并崩一次)。
    """
    mode = _remote_mode()
    if mode == 'on':
        from loom_player_window import run_player_window
        run_player_window(scene, width=width, height=height)
        return
    if mode != 'auto':
        _launch_native(scene, width, height)
        return
    # ---- auto: 原生优先, 只在引擎判定失败后降级一次 ----
    state = _install_present_watch(3)
    _launch_native(scene, width, height)
    if not state.get('fallback'):
        return
    print('[remote] 原生上屏连续失败 %s 次 (最近错误: %r) -> 自动降级为离屏回读'
          ' (等价于 LOOM_REMOTE_MODE=1), 本次只重启一次'
          % (state.get('streak'), state.get('last_error')))
    from loom_player_window import run_player_window
    run_player_window(scene, width=width, height=height)

def _benchmark_math(n_tri=5000, n_iter=100):
    """
    纯计算基准 (不弹窗口): 构造随机 mesh, 跑完整 MVP 批量管线
    (顶点变换/法线/背面剔除/光照/投影), 分别用 CPU(numpy) 与 GPU(cupy) 计时对比.
    前置: mat_validate 数值自检.
    """
    import math
    import time
    import numpy as np
    import matlib
    from matlib import mat4_translation, mat4_rotation, mat4_perspective, mat4_view_yaw_pitch

    print("=" * 60)
    print("Loom - 数学管线基准 (MVP / 顶点索引 / 批量)")
    print("=" * 60)

    # 1. 数值一致性自检 (矩阵库 vs 旧标量路径)
    err = matlib.mat_validate()
    ok = err < 1e-9
    print(f"[自检] matlib vs 旧标量 最大误差: {err:.3e} -> {'通过' if ok else '失败!'}")
    if not ok:
        raise RuntimeError("矩阵库与旧标量路径不一致, 存在算法错误")

    # 2. 构造随机 mesh (n_tri 个三角形)
    rng = np.random.default_rng(42)
    V = max(4, int(n_tri // 2))
    F = n_tri
    verts = rng.uniform(-1, 1, size=(V, 3))
    faces = rng.integers(0, V, size=(F, 3))

    cam = (0.0, 0.0, -5.0)
    yaw, pitch = 0.5, 0.2
    fov = math.radians(60.0)
    aspect, near, far = 1.0, 0.1, 100.0
    W = H = 800
    light = np.array([1.0, 1.0, -1.0]) / math.sqrt(3)

    def pipeline(xp, va, fa):
        """一次完整 MVP 批量管线 (与引擎 render_model 数学路径一致)"""
        vh = xp.concatenate([va, xp.ones((va.shape[0], 1), dtype=xp.float64)], axis=1)
        M = mat4_translation(xp, 0, 0, 0) @ mat4_rotation(xp, 0.3, 0.4, 0.2)
        Vm = mat4_view_yaw_pitch(xp, cam, yaw, pitch)
        P = mat4_perspective(xp, fov, aspect, near, far)
        view = vh @ (M @ Vm)                # (V,4)
        tri = view[fa][:, :, :3]            # (F,3,3)
        p1, p2, p3 = tri[:, 0, :], tri[:, 1, :], tri[:, 2, :]
        u = p2 - p1
        v = p3 - p1
        n = xp.cross(u, v)
        ln = xp.sqrt(xp.sum(n * n, axis=1))
        ln = xp.where(ln == 0, 1.0, ln)
        n = n / ln[:, None]
        keep = n[:, 2] < 0   # view 前方 z>0, 法线指向相机 (nz<0) 的面可见
        center = (p1 + p2 + p3) / 3.0
        lv = (xp.array((light[0], light[1], light[2], 0.0), dtype=xp.float64) @ Vm)[:3]
        lv = lv / xp.sqrt(xp.sum(lv * lv))
        bright = xp.clip((xp.sum(n * lv, axis=1) + 1) / 2.0, 0.2, 1.0)
        clip = view @ P
        w = clip[:, 3]
        valid = w > near
        ws = xp.where(w > 1e-6, w, 1.0)
        ndc = clip / ws[:, None]
        sp = xp.stack([ndc[:, 0] * (W / 2), ndc[:, 1] * (H / 2)], axis=1)
        tsp = sp[fa]
        face_ok = xp.all(valid[fa], axis=1) & keep
        depth = center[:, 2]
        # 聚合结果避免被优化掉
        return (xp.sum(tsp) + xp.sum(bright * face_ok) +
                xp.sum(xp.where(face_ok, depth, 0.0)))

    # 3. CPU 计时
    va = np.asarray(verts)
    fa = np.asarray(faces)
    for _ in range(5):
        pipeline(np, va, fa)   # 预热
    t0 = time.perf_counter()
    for _ in range(n_iter):
        pipeline(np, va, fa)
    cpu_ms = (time.perf_counter() - t0) / n_iter * 1000.0

    # 4. GPU 计时
    gpu_ms = None
    try:
        import cupy as cp
        cp.cuda.runtime.getDeviceCount()
        va_g = cp.asarray(verts)
        fa_g = cp.asarray(faces)
        for _ in range(5):
            pipeline(cp, va_g, fa_g)   # 预热 (编译/分配)
        cp.cuda.Stream.null.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_iter):
            pipeline(cp, va_g, fa_g)
        cp.cuda.Stream.null.synchronize()
        gpu_ms = (time.perf_counter() - t0) / n_iter * 1000.0
    except Exception as e:
        print(f"[GPU] CuPy 不可用: {e}")

    # 5. 报告
    print(f"[数据] 三角形: {F}, 顶点: {V}, 迭代: {n_iter}")
    print(f"[CPU] numpy 平均每帧: {cpu_ms:.4f} ms")
    if gpu_ms is not None:
        print(f"[GPU] cupy  平均每帧: {gpu_ms:.4f} ms")
        print(f"[结果] 加速比: {cpu_ms / gpu_ms:.2f}x")
    else:
        print("[结果] GPU 后端不可用, 仅测试了 CPU")
    print("=" * 60)
    return gpu_ms is not None


def _self_check_sources():
    """2026-10-19 启动自检: 检测 .py 文件是否被篡改（全零）。

    背景: 部分安全软件（360 等）在安装到 C:/Program Files 后会把 .py 文件
    改成全零字节（+128 字节差异），导致 Python 启动时抛
    "source code string cannot contain null bytes"，用户难以理解。

    本自检在启动最开始运行（<50ms 开销），发现问题时给出明确指引，
    引导用户重新解压安装包或关闭安全软件后重装。
    """
    import os as _os
    app_dir = _os.path.dirname(_os.path.abspath(__file__))
    bad = []
    try:
        for dirpath, dirnames, filenames in _os.walk(app_dir):
            # 跳过测试/缓存/资源目录
            dirnames[:] = [d for d in dirnames
                           if d not in ('tests', '__pycache__', '保存',
                                        'Projects', 'assets', '.git')]
            for fn in filenames:
                if not fn.endswith('.py'):
                    continue
                fp = _os.path.join(dirpath, fn)
                try:
                    with open(fp, 'rb') as f:
                        head = f.read(8192)
                    # 简单检测：前 8KB 全是零 -> 损坏
                    if len(head) >= 16 and head.count(b'\x00') == len(head):
                        bad.append(fp)
                except OSError:
                    pass
    except Exception:
        return
    if bad:
        print()
        print('=' * 60)
        print('[错误] 检测到引擎源码文件损坏（全零字节）')
        print('=' * 60)
        print('可能原因：安全软件（360 安全卫士 / Windows Defender 等）')
        print('在安装或首次扫描时篡改了 .py 文件。')
        print()
        print('受损文件：')
        for b in bad[:10]:
            print('  - %s' % b)
        if len(bad) > 10:
            print('  ... 还有 %d 个' % (len(bad) - 10))
        print()
        print('修复方法：')
        print('  1. 用 LoomHub 重新安装引擎（推荐）')
        print('  2. 或从 zip 重新解压覆盖上述文件')
        print('  3. 长期方案：把安全软件加入白名单，排除 Loom 安装目录')
        print('=' * 60)
        print()
        sys.exit(1)


# 主程序入口
if __name__ == "__main__":
    # 2026-11-09 修复（beta5）: --bench 只在 build_entry.py 里有实现，Loom.py 之前不解析它 →
    # `python Loom.py --bench <场景> <帧数>` 会掉进"默认编辑器"分支，表现为**卡住不退出**
    # （实测 90s 无任何输出）。这里显式转发到同一实现，避免两个入口口径分叉。
    _argv_bench = sys.argv[1:]
    if '--bench' in _argv_bench:
        import build_entry as _be
        _bi = _argv_bench.index('--bench')
        _scene = _argv_bench[_bi + 1] if _bi + 1 < len(_argv_bench) else None
        _frames = 300
        if _bi + 2 < len(_argv_bench) and _argv_bench[_bi + 2].isdigit():
            _frames = int(_argv_bench[_bi + 2])
        if not _scene:
            print('用法: python Loom.py --bench <scene.json> [帧数]')
            sys.exit(1)
        # 2026-11-09 第三轮审计 P-05-03: 转发分支此前不复刻 build_entry 的校验 ——
        # 场景不存在会先建窗再 ValueError traceback；帧数 0 会 ZeroDivisionError。
        # 这里补两条，与 build_entry 的行为对齐（失败要可见、且不要先建窗）。
        if not os.path.isfile(_scene):
            print('[错误] 场景不存在: %s' % _scene)
            sys.exit(1)
        if _frames <= 0:
            print('[错误] 帧数必须 > 0（收到 %r）' % (_frames,))
            sys.exit(1)
        _be._bench_scene(_scene, n_frames=_frames)
        sys.exit(0)

    # 2026-10-19 首行自检：损坏文件明确报错（防 AV 篡改导致神秘崩溃）
    _self_check_sources()
    benchmark, n_tri, n_iter, run_scene, open_scene, editor, ui = _parse_args(sys.argv[1:])

    if benchmark:
        _benchmark_math(n_tri=n_tri, n_iter=n_iter)
        sys.exit(0)

    try:
        import pygame
        import moderngl
    except ImportError as e:
        print("[错误] 缺少渲染依赖:", e)
        print("请使用 Python 3.12 运行本程序:")
        print('  py -3.12 -m pip install pygame moderngl -i https://pypi.tuna.tsinghua.edu.cn/simple')
        sys.exit(1)

    # L1 插件加载 (2026-08-20): plugins\ 目录投放, 坏插件自动跳过回退官方
    try:
        from plugin_loader import load_plugins
        load_plugins()
    except Exception as e:
        print("[插件] 加载失败: %r" % e)

    try:
        if run_scene is not None:
            # Player 模式 (运行时, 无编辑器)
            # 2026-10-20 P0-1 白屏修复 + 2026-11-09 E2(auto):
            # 远程模式三态**统一在 _launch_player 里收口**（on/1 = 离屏回读强制;
            # auto = 先原生、引擎判上屏连续失败才降级一次; off = 原生）。
            # 这里不再单独判断 LOOM_REMOTE_MODE，避免两条入口口径分叉。
            # 2026-11-06 R-04: 走统一后端选择 (--backend > 设置 render_api > 默认)
            _launch_player(run_scene)
            sys.exit(0)
        else:
            # 游戏封装 (M38, Unity Build 模型): 无参数时若 exe/脚本旁有 游戏配置.json
            # 且含 "scene" -> 直接进游戏 (玩家双击启动 exe 即玩, 无需命令行/编辑器).
            # 无配置 = 编辑器模式 (默认); --open <scene.json> 打开项目场景.
            import json as _json
            _exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            _scene = None
            try:
                with open(os.path.join(_exe_dir, "游戏配置.json"),
                          'r', encoding='utf-8') as _f:
                    _scene = _json.load(_f).get('scene')
            except Exception:
                _scene = None
            if _scene:
                if not os.path.isabs(_scene):
                    _scene = os.path.join(_exe_dir, _scene)
                # 2026-08-27: 双启=玩家进程语义 —— 装载同夹插件
                # (有 .lsc+哈希=secure 校验; 否则 MOD 目录投放式)
                try:
                    import game_pack
                    gm = None
                    try:
                        gm = game_pack.load(_exe_dir)
                    except Exception:
                        gm = None
                    game_pack.install_game_plugins(_exe_dir, gm)
                except SystemExit as e:
                    print(e)
                    sys.exit(1)
                # 2026-11-06 R-04: 同上 —— 该入口也必须遵守后端选择,
                # 否则"编辑器的游戏配置双击启动"与 run_player 行为不一致。
                _launch_player(_scene)
                sys.exit(0)
            else:
                # Qt 编辑器 (2026-08-17): 原生 Qt 控件全重写 —— pygame(SDL) 窗口
                # 会进程级污染中文输入法(IME)候选框, 编辑器弃用 pygame 做窗口;
                # QOpenGLWidget 承载 moderngl 视口 + Qt 原生面板 (见记忆
                # sdl-window-contaminates-ime). 控制器命令层/GL 渲染管线复用.
                # 2026-10-18 选项1: --ui default/minimal 旧 pygame 视图路径彻底删除.
                # 2026-10-19 单实例锁：仅编辑器模式加锁（--run / --benchmark / 游戏配置
                # 玩家模式不加锁，允许同时开多个游戏实例）。防止连点开 N 个编辑器。
                from loom_single_instance import ensure_editor_single_instance
                ensure_editor_single_instance(scene_path=open_scene)
                from ui.loom_gui import run_loom_gui
                run_loom_gui(scene_path=open_scene)
                sys.exit(0)
    except Exception as e:
        print(f"[错误] 无法启动渲染引擎: {e}")
        sys.exit(1)

    print(f"渲染后端: OpenGL ({engine.ctx.info['GL_VERSION']})")
    if run_scene is not None:
        print("运行时: 已加载 %d 个对象 | 左键拖=相机轨道, WASD=平移, 方向键=视角, 滚轮=缩放" % len(engine.models))
    else:
        print("编辑器: 工具栏加基元/保存/加载/Prefab/撤销, 层级树拖拽挂父, 检查器编辑变换/颜色/饱和度/脚本,")
        print("  层级面板可加平行光/点光源 (场景默认无光源, 需手动添加), 播放→=跑脚本/停止还原,")
        print("  Ctrl+Z/Y=撤销重做,")
        print("  视口左键=点选, 拖 gizmo=移动/旋转, Alt+左/中键=轨道相机, 滚轮=缩放,")
        print("  WASD=平移")
        if open_scene:
            print("  已打开项目场景:", open_scene)
    engine.run()
