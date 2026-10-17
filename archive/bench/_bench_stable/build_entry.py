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
  python Loom.py --bench <scene.json> [帧数]     场景基准 (加载->预热->测量, 编译版测速用;
                                          结果打印 stdout 并写 bench_result.txt —
                                          编译版是 windows-disable-console, 靠文件收结果)
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
    bench_scene = None
    bench_frames = 300
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
        elif a == '--bench' and i + 1 < len(argv):
            bench_scene = argv[i + 1]
            i += 1
            if i + 1 < len(argv) and argv[i + 1].isdigit():
                bench_frames = int(argv[i + 1])
                i += 1
        elif a == '--run' and i + 1 < len(argv):
            run_scene = argv[i + 1]
            i += 1
        elif a == '--open' and i + 1 < len(argv):
            open_scene = argv[i + 1]
            i += 1
        elif a == '--ui' and i + 1 < len(argv):
            ui = argv[i + 1]
            i += 1
        elif a == '--editor':
            editor = True
        i += 1
    return (benchmark, n_tri, n_iter, run_scene, open_scene, editor, ui,
            bench_scene, bench_frames)


def _make_editor_view(ui_name, base=None):
    """按 --ui 选择编辑器视图实现 (IEditorView). 返回 None = 用默认 LoomGUI.
    2026-08-14: 'default' 时读设置选 GUI (自定义 GUI 来自 GUI/ 文件夹, 重启后生效;
    加载失败自动回退官方返回 None). 播放器 (PlayerApp) 运行时 UI 不分离, 不受影响.
    2026-08-28: 默认官方 GUI = LoomGUI (ui/loom_gui.py, Qt 原生视图)."""
    if ui_name == 'minimal':
        from ui.minimal_editor_view import MinimalEditorView
        return MinimalEditorView()
    if ui_name in ('default', None, ''):
        from guiloader import resolve_gui
        return resolve_gui('loom', base=base)
    return None


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
    fov = math.radians(45.0)
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


def _bench_scene(scene_path, n_frames=300):
    """场景基准 (2026-09-02, 编译版测速用): 加载场景 -> 预热 -> GC 冻结 ->
    测量窗口逐帧 render -> 汇总 FPS/帧稳定性/逐阶段耗时.
    口径与 tests/_tmp/stress_probe.py 一致 (关 vsync, dt=1/120, LOOM_PROFILE=1),
    但结果同时写 bench_result.txt (编译版 --windows-disable-console 无 stdout,
    靠文件收结果; 路径相对 exe/脚本工作目录)."""
    import time
    os.environ.setdefault('LOOM_PROFILE', '1')   # 逐阶段计时 (render 内插桩)
    import pygame
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_SWAP_CONTROL, 0)  # 关 vsync = 真 FPS
    import runtime
    eng = runtime.PlayerApp(scene_path, 1024, 768)
    eng.set_mouse_locked(False)                  # 探针不锁鼠标 (与 stress_probe 同)

    for _ in range(40):                          # 预热 (脚本实例/阴影贴图/缓存就位)
        eng.render(1.0 / 120.0)

    from engine import gc_play_enter             # 与 stress_probe 同款叠加冻结
    gc_play_enter()

    eng._stage_times.clear()
    dts = []
    t0 = time.perf_counter()
    for _ in range(n_frames):
        _f0 = time.perf_counter()
        eng.render(1.0 / 120.0)
        dts.append(time.perf_counter() - _f0)
    wall = time.perf_counter() - t0

    fps = n_frames / wall
    lines = []
    lines.append("========== 场景基准 %s (%d 帧, 墙钟 %.2fs) =========="
                 % (os.path.basename(scene_path), n_frames, wall))
    lines.append("FPS: %.1f  (平均帧时间 %.3f ms)" % (fps, 1000.0 / fps))
    dms = sorted(d * 1000.0 for d in dts)
    p50 = dms[int(0.50 * len(dms))]
    p99 = dms[min(int(0.99 * len(dms)), len(dms) - 1)]
    lines.append("帧稳定性: p50=%.3f p99=%.3f max=%.3f ms"
                 % (p50, p99, dms[-1]))
    st = eng._stage_times
    lines.append("逐阶段累计耗时 (LOOM_PROFILE, ms/帧):")
    keys = ('physics', 'phys_bridge_ensure', 'phys_bridge_pre', 'phys_bridge_step',
            'phys_bridge_post', 'world_matrices', 'aabbs', 'shadow_prep',
            'shadow_bounds', 'shadow_cornerfill', 'shadow_matmul',
            'collide_pairs', 'shadow_jobs', 'dispatch', 'buckets')
    tot = 0.0
    for k in keys:
        v = st.get(k, 0.0) / n_frames
        tot += v
        lines.append("  %-22s %7.2f" % (k, v))
    lines.append("  已插桩阶段合计          %7.2f (帧时间 %.3f, 其余=GL/脚本/事件)"
                 % (tot, 1000.0 / fps))
    lines.append("完成。")

    report = "\n".join(lines)
    print(report)                                # 源码跑时直读 stdout
    out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                       'bench_result.txt')
    try:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(report + "\n")
    except OSError as e:
        print("[bench] 结果写盘失败 (%r), 仅有 stdout" % e)
    eng._stop_parallel()
    pygame.quit()
    return fps


# 主程序入口
if __name__ == "__main__":
    (benchmark, n_tri, n_iter, run_scene, open_scene, editor, ui,
     bench_scene, bench_frames) = _parse_args(sys.argv[1:])

    if benchmark:
        _benchmark_math(n_tri=n_tri, n_iter=n_iter)
        sys.exit(0)

    if bench_scene is not None:
        if not os.path.isabs(bench_scene):
            # 相对路径按 exe/脚本所在目录解析 (编译版从任意 cwd 启动都稳)
            bench_scene = os.path.join(
                os.path.dirname(os.path.abspath(sys.argv[0])), bench_scene)
        if not os.path.isfile(bench_scene):
            print("[错误] 场景不存在: %s" % bench_scene)
            sys.exit(1)
        _bench_scene(bench_scene, n_frames=bench_frames)
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
            from runtime import PlayerApp
            engine = PlayerApp(run_scene, 1280, 800)
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
                from runtime import PlayerApp
                engine = PlayerApp(_scene, 1280, 800)
            elif ui == 'qt':
                # Qt 编辑器 (2026-08-17): 原生 Qt 控件全重写 —— pygame(SDL) 窗口
                # 会进程级污染中文输入法(IME)候选框, 编辑器弃用 pygame 做窗口;
                # QOpenGLWidget 承载 moderngl 视口 + Qt 原生面板 (见记忆
                # sdl-window-contaminates-ime). 控制器命令层/GL 渲染管线复用.
                from ui.loom_gui import run_loom_gui
                run_loom_gui(scene_path=open_scene)
                sys.exit(0)
            else:
                # --ui default / minimal: 走 guiloader (自定义 GUI 投放机制) 或
                # 遗留 pygame 视图 (仅参考, 有 IME 污染)
                from editor import EditorApp
                engine = EditorApp(1280, 800, scene_path=open_scene,
                                   view=_make_editor_view(ui))
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
