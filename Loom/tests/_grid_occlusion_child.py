# -*- coding: utf-8 -*-
"""_grid_occlusion_child.py — 网格遮挡真窗口探针（子进程；run_all 不收下划线前缀）。

由 tests/test_grid_occlusion_parity.py 以 argv = [backend, verdict_path] 拉起：
  backend = 'gl' | 'vk'
真窗口 = LoomGUI（与 test_vk_editor_smoke / 编辑器生产入口同一个类），
场景 = 一个 3x3x3 立方体浮在地面网格上方（物体必然遮住一片网格区域），
判据（两端**同一份**取法，避免"取法不同"造成的假差异）：
  A1 前置：物体剪影够大（腐蚀 3px 去掉边缘后 > 3000 像素）—— 没有剪影就无从判遮挡；
  A2 网格在编辑态可见：物体藏起来时，开/关 show_grid 的像素差 > 1000；
  A3 网格线在物体前方区域不被画：物体剪影内 开/关网格的像素差 == 0
     （网格被物体正确遮挡 = 人类裁决 A 要的语义）；
  A4 物体后方的网格照常可见：剪影外差值 > 1000（防"整块不画"冒充"遮挡正确"）。
数值（A1/A2/A3/A4 的像素计数）一并落进 verdict['metrics']，供父门做两端量化对拍。

另有无窗口的 B 段（同一份门，先跑）：
  B1 网格绘制归属（GL 场景 pass 内 / VK 视图叠加层）；
  B2 播放态不画网格（两端各自的生产方法 + 桩控制器，断言零绘制）；
  B3 编辑态画网格且不重复画（GL 只由场景 pass 画 / VK 只由叠加层画）。

为什么必须真窗口：GL 侧网格的深度来自**场景目标**（后处理开启时是 color.hdr），
离屏夹具的 _external_fb 深度不是主 pass 写的（Q-B7-53-1 取证）；只有真窗口 +
生产后处理链才复现用户看到的组合。
"""
import os
import sys
import time
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 引擎根 = Loom/
BASE = ROOT
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ.setdefault('LOOM_NO_SAVE_MIGRATE', '1')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

def _arm_unattended_watchdog(seconds):
    """无人值守兜底（2026-11-27 人类反馈：测试不得留下要人点的窗口）。

    任何阻塞路径都不许把本进程及其真窗口留在桌面上等人点 —— 到点进程级硬退出
    （窗口随进程销毁）。正常路径末尾的 os._exit 更早发生，此定时器只是最后防线。
    """
    import threading

    def _bail():
        try:
            print('[child] watchdog %ds 到点硬退（流程未正常收口）' % seconds,
                  flush=True)
        except Exception:
            pass
        os._exit(4)

    threading.Timer(seconds, _bail).start()


_arm_unattended_watchdog(200)

BACKEND = (sys.argv[1] if len(sys.argv) > 1 else 'gl').lower()
VERDICT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'grid_occlusion_verdict.json')
if BACKEND == 'vk':
    os.environ.setdefault('WGPU_BACKEND_TYPE', 'Vulkan')

import numpy as np


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


_gate = _FailGateStream(sys.stdout)
sys.stdout = _gate

_fails = []
_pass_n = 0
# 判据数值（父门拿来做两端量化对拍：像素计数必须两端同量级）
_metrics = {}


def check(name, cond, detail=""):
    global _pass_n
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


def _guard(desc, fn):
    """跑一段 B 段判据；异常也算一条 FAIL（不中断后面的 A 段像素判据）。

    为什么必须容错：修前树里 _draw_grid_in_scene / grid_in_scene_pass 根本不存在，
    若让 AttributeError 冒泡，A 段（真窗口像素）就一条都跑不到 —— 修前红只剩
    「exception」而拿不到「网格 0 像素」这条最关键的证据。
    """
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
        check(desc + '（判据本身异常）', False, 'exception')


def cpu_gates():
    """B 段（不建窗口，纯 CPU）：网格绘制归属 + 播放态/编辑态门控（两端同一语义）。

    为什么这四条也要进同一份门：人类裁决「网格是编辑态辅助，播放态可以不画」——
    但**两端必须一致**（编辑器播放 vs 播放器都不画），且编辑态必须画（不许为了
    遮挡把网格修没了）。像素段（A 段）只能证明"编辑态可见 + 被物体遮挡"，
    播放态要另证：这里直接调**生产方法**（RenderMixin._draw_grid_in_scene /
    LoomGUI.draw）配桩控制器，断言零绘制。
    """
    import contextlib

    from render.gl.render import RenderMixin
    import gui.main_window as lg

    class _Ctl:
        """视图层/场景 pass 需要的最小控制器面（只记录网格相关调用）。"""

        def __init__(self, playing, has_scene_pass):
            self.is_playing = bool(playing)
            self.show_grid = True
            self.lights = []
            self.cameras = []
            self.grid_in_scene_pass = bool(has_scene_pass)
            self.calls = []

        def grid_geometry(self):
            self.calls.append('grid_geometry')
            return None

        def draw_lines(self, *a, **k):
            self.calls.append('draw_lines')

        def _draw_selection_box(self):
            pass                          # 叠加层后继调用，本段不关心

        def _screen_fb(self):
            return None

        def overlay_scope(self, **k):
            return contextlib.nullcontext()

    class _Win:
        def _draw_light_icons(self, ctl):
            pass

        def _draw_camera_icons(self, ctl):
            pass

        def _draw_gizmo(self, ctl):
            pass

    # ---- B1 归属：谁负责画网格 ----
    # B7-58：能力契约落在**类体**上（EngineCore 默认 False / GLEngine 覆写 True），所以
    # 断言读 GLEngine / SceneDriver 的类属性，不再读 RenderMixin / VkEditorApp ——
    # RenderMixin 已不定义该属性（写在那里会被 EngineCore 的同名默认值遮蔽：MRO 上
    # EngineCore 在 RenderMixin 前面，见 render/gl/render.py 的 B7-58 注释）。
    if BACKEND == 'gl':
        from render.gl.engine import GLEngine
        _guard('gl B1 网格绘制归属：GL 由场景 pass 内绘制（GLEngine.grid_in_scene_pass=True）',
               lambda: check('gl B1 网格绘制归属：GL 由场景 pass 内绘制（GLEngine.grid_in_scene_pass=True）',
                             getattr(GLEngine, 'grid_in_scene_pass', None) is True,
                             getattr(GLEngine, 'grid_in_scene_pass', None)))
    else:
        from render.vk.driver import SceneDriver
        _guard('vk B1 网格绘制归属：VK 由视图叠加层绘制（SceneDriver.grid_in_scene_pass=False）',
               lambda: check('vk B1 网格绘制归属：VK 由视图叠加层绘制（SceneDriver.grid_in_scene_pass=False）',
                             getattr(SceneDriver, 'grid_in_scene_pass', None) is False,
                             getattr(SceneDriver, 'grid_in_scene_pass', None)))

    # ---- B2 播放态：两端都不许画网格（与播放器一致：播放器没有 grid_geometry）----
    if BACKEND == 'gl':
        def _b2_gl():
            ctl = _Ctl(playing=True, has_scene_pass=True)
            RenderMixin._draw_grid_in_scene(ctl, object())
            check('gl B2 播放态不画网格（场景 pass 内网格几何/draw_lines 零调用）',
                  ctl.calls == [], ctl.calls)
        _guard('gl B2 播放态不画网格（场景 pass 内网格几何/draw_lines 零调用）', _b2_gl)
    else:
        def _b2_vk():
            ctl = _Ctl(playing=True, has_scene_pass=False)
            lg.LoomGUI.draw(_Win(), ctl, 0.0)
            check('vk B2 播放态不画网格（视图叠加层网格几何/draw_lines 零调用）',
                  ctl.calls == [], ctl.calls)
        _guard('vk B2 播放态不画网格（视图叠加层网格几何/draw_lines 零调用）', _b2_vk)

    # ---- B3 编辑态：画一次且只画一次（GL 归场景 pass / VK 归叠加层）----
    if BACKEND == 'gl':
        def _b3_gl():
            ctl = _Ctl(playing=False, has_scene_pass=True)
            lg.LoomGUI.draw(_Win(), ctl, 0.0)
            check('gl B3 编辑态不重复画网格（视图叠加层不再取 grid_geometry）',
                  ctl.calls == [], ctl.calls)
        _guard('gl B3 编辑态不重复画网格（视图叠加层不再取 grid_geometry）', _b3_gl)
    else:
        def _b3_vk():
            ctl = _Ctl(playing=False, has_scene_pass=False)
            lg.LoomGUI.draw(_Win(), ctl, 0.0)
            check('vk B3 编辑态画网格（视图叠加层取 grid_geometry）',
                  ctl.calls == ['grid_geometry'], ctl.calls)
        _guard('vk B3 编辑态画网格（视图叠加层取 grid_geometry）', _b3_vk)


def _close_gracefully(app, win):
    """优雅关窗（try/finally 兜底；失败/超时由模块末尾的 os._exit 进程级收口）。"""
    try:
        if win.editor is not None:
            win.editor.mark_saved()
        win._suppress_confirm = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, win.close)
        t0 = time.perf_counter()
        while win.isVisible() and time.perf_counter() - t0 < 10:
            app.processEvents()
            time.sleep(0.01)
        print('[child] 关窗 %s (耗时 %.1fs)' % (
              'OK' if not win.isVisible() else '超时(转 os._exit)',
              time.perf_counter() - t0), flush=True)
    except Exception as _ce:
        print('[child] 优雅关窗异常 (转 os._exit): %r' % (_ce,), flush=True)


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    import gui.main_window as lg

    cpu_gates()

    app = QApplication.instance() or QApplication(['grid-occlusion-%s' % BACKEND])
    win = lg.LoomGUI(scene_path=None, width=900, height=640,
                     backend=('vulkan' if BACKEND == 'vk' else 'gl'))
    win.show()
    # 2026-11-27（人类反馈：测试不得留下要人点的窗口）：无论走哪条分支（含早退、
    # 判据异常），离开 main 前都优雅关窗 —— mark_saved + 抑制「是否保存」三态框
    # （测试态不走人机确认）+ QTimer 关窗 + 有界泵；末尾 os._exit 兜底。
    try:
        _main_body(app, win, QImage)
    finally:
        _close_gracefully(app, win)


def _main_body(app, win, QImage):
    """真窗口判据段（原 main 主体，逐字保留；异常由模块级 try 收口）。"""
    def ready():
        vp = win.viewport
        if BACKEND == 'vk':
            return (getattr(vp, 'editor', None) is not None
                    and getattr(vp, 'init_error', None) is None
                    and getattr(vp, 'configured', False))
        return getattr(vp, 'editor', None) is not None

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 90 and not ready():
        app.processEvents()
        time.sleep(0.01)
    check('%s A0 真窗口编辑器就绪' % BACKEND, ready(),
          'init_error=%r 耗时 %.1fs' % (getattr(win.viewport, 'init_error', None),
                                        time.perf_counter() - t0))
    if not ready():
        return

    e = win.editor
    for m in list(e.models):
        e.remove_model(m)
    e.selected_index = -1
    e.selected_light_index = -1
    e.selected_camera_index = -1
    cube = e._add_primitive('cube')
    cube.position = (0.0, 1.5, 0.0)
    cube.scale = (3.0, 3.0, 3.0)
    e.selected_index = -1                 # 不画选中框（否则框线会打在物体上）
    e.camera_target = (0.0, 1.0, 0.0)
    e.camera_distance = 9.0
    e.camera_yaw = 0.6
    e.camera_pitch = -0.30
    e.apply_orbit_camera()

    def pump(n=25, dt=0.01):
        for _ in range(n):
            app.processEvents()
            time.sleep(dt)

    def grab():
        img = win.viewport.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        w, h = img.width(), img.height()
        return np.frombuffer(bytes(img.constBits()), dtype=np.uint8).reshape(
            h, img.bytesPerLine() // 4, 4)[:, :w, :3].copy()

    def diff(a, b, thr):
        return np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(axis=2) > thr

    def erode(mask, k=3):
        m = mask.copy()
        for _ in range(k):
            m = m & np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)
        return m

    def snap(show_grid, visible, n=25):
        e.show_grid = bool(show_grid)
        cube.visible = bool(visible)
        pump(n)
        return grab()

    img_obj = snap(False, True)
    img_bg = snap(False, False)
    obj_mask = diff(img_obj, img_bg, 8)
    obj_in = erode(obj_mask, 3)
    _metrics['object_pixels'] = int(obj_in.sum())
    check('%s A1 前置：物体剪影够大（腐蚀后 > 3000 像素）' % BACKEND,
          int(obj_in.sum()) > 3000, int(obj_in.sum()))

    img_grid_bg = snap(True, False)
    grid_no_obj = int(diff(img_grid_bg, img_bg, 12).sum())
    _metrics['grid_no_object'] = grid_no_obj
    check('%s A2 网格本身可见（无物体时开/关网格差 > 1000 像素）' % BACKEND,
          grid_no_obj > 1000, grid_no_obj)

    img_grid_obj = snap(True, True)
    gm = diff(img_grid_obj, img_obj, 12)
    over = int((gm & obj_in).sum())
    outside = int((gm & ~obj_mask).sum())
    _metrics['grid_over_object'] = over
    _metrics['grid_outside_object'] = outside
    check('%s A3 物体遮住的地方没有网格（剪影内网格像素 == 0）' % BACKEND,
          over == 0, over)
    check('%s A4 物体外网格照常可见（剪影外 > 1000 像素）' % BACKEND,
          outside > 1000, outside)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    _fails.append('exception')

print()
verdict = {'backend': BACKEND, 'ok': not _fails, 'fails': list(_fails),
           'pass_count': _pass_n, 'metrics': dict(_metrics)}
try:
    with open(VERDICT, 'w', encoding='utf-8') as fh:
        json.dump(verdict, fh)
except Exception as ex:
    print('FAIL verdict 落盘失败: %r' % (ex,))
print('子进程结论:', verdict)
sys.stdout.flush()
# Qt + wgpu 真窗口进程收尾会非确定性卡在驱动 teardown（test_vk_editor_smoke 同款
# 已知问题），判定已落盘 -> 直接硬退，父门只认 verdict 文件。
os._exit(0 if verdict['ok'] else 1)