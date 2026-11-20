# -*- coding: utf-8 -*-
"""test_vk_editor_smoke.py — S4 门：VK 编辑器视口（「编辑器支持 VK」五阶段·阶段 4）。

五件事的门面（Q-B7-47-1 路线 S4）：
  ① VkViewport（ui/vk_viewport.py）：rendercanvas.qt.QRenderWidget + get_context("wgpu")
     + 事件桥（写引擎状态字段的后端无关 11 方法）；
  ② VkEditorApp(_EditorCore, SceneDriver)（editor.py，S2 占位落地）：
     编辑器能力唯一实现仍在 _EditorCore（同源不同步，规则 5.5），本类只做装配 + VK 钩子；
  ③ present_method=bitmap（默认）：grab() 截图可用（编辑器截图/远程兜底硬需求）；
  ④ 编辑态操作在 VK 视口可用：选中 / 拖 gizmo / 加物体（同一套 _EditorCore 方法）；
  ⑤ 真窗口 60 帧无异常。

修前必红：VkViewport / VkEditorApp 不存在时本门 import 段即红。

线宽：沿用 S3 的 1px（待 Q-B7-48-1 裁决；wgpu 0.33 无原生线宽）。
"""
import atexit
import json
import os
import sys
import time

# 子进程模式：verdict 落盘路径由父门传入（argv[1]），否则用默认临时路径。
_VERDICT_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 's4_smoke_verdict.json')


class _FailGateStream:
    """与 test_vk_overlay_primitives 同款：出现 FAIL 行就把退出码改成 1。"""

    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(sys.stdout)
sys.stdout = _fail_gate


@atexit.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 子进程住在 tests/，引擎根 = Loom/
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_DIALOG', '1')
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('WGPU_BACKEND_TYPE', 'Vulkan')
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

_fails = []
_pass_n = 0
_watchdog_armed = [False]


def _arm_watchdog(seconds=180):
    """真窗口测试防卡死：超时强制退出（ EXIT 2 = 超时，也是红）。"""
    if _watchdog_armed[0]:
        return
    _watchdog_armed[0] = True
    import threading

    def _kill():
        time.sleep(seconds)
        print('FAIL 冒烟超时 %ds（真窗口卡死）' % seconds)
        sys.stdout.flush()
        os._exit(2)

    threading.Thread(target=_kill, daemon=True).start()


def check(name, cond, detail=""):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        global _pass_n
        _pass_n += 1
    if not cond:
        _fails.append(name)


# ============================ A. 结构段（无窗口） ============================

def section_a():
    print('=== A. 结构：装配形状 / 同源唯一实现 ===')
    try:
        import editor as editor_mod
        check('A1 editor.VkEditorApp 存在（S2 占位落地）',
              hasattr(editor_mod, 'VkEditorApp'))
        from ui.vk_viewport import VkViewport
        check('A2 ui.vk_viewport.VkViewport 存在', VkViewport is not None)
    except Exception as e:
        check('A0 VK 编辑器模块可导入', False, repr(e))
        return None, None
    VkEditorApp = editor_mod.VkEditorApp
    # MRO：VkEditorApp -> _EditorCore -> SceneDriver -> ... -> EngineCore
    from scene_driver import SceneDriver
    mro = [c.__name__ for c in VkEditorApp.__mro__]
    check('A3 MRO: VkEditorApp -> _EditorCore -> SceneDriver(VkWindowMixin+VkEditorRenderMixin) -> EngineCore',
          mro[:3] == ['VkEditorApp', '_EditorCore', 'SceneDriver']
          and 'VkWindowMixin' in mro[:6] and 'VkEditorRenderMixin' in mro[:6]
          and mro.index('EngineCore') < 7, mro)
    check('A4 GL 装配不受影响：EditorApp(_EditorCore, GLEngine) 仍在',
          [c.__name__ for c in editor_mod.EditorApp.__mro__][:3]
          == ['EditorApp', '_EditorCore', 'GLEngine'])
    # 同源唯一实现：编辑器 140 方法不允在 VkEditorApp 里出现第二份
    core_methods = {k for k, v in editor_mod._EditorCore.__dict__.items()
                    if callable(v) and not k.startswith('__')}
    vk_own = {k for k, v in VkEditorApp.__dict__.items()
              if callable(v) and not k.startswith('__')}
    dup = sorted(core_methods & vk_own - {'_backend_upload_lights',
                                          '_backend_prepare_bucket_frame',
                                          '_backend_parallel_shadow_and_collision',
                                          '_framebuf_prefetch'})
    check('A5 编辑器方法唯一实现仍在 _EditorCore（VkEditorApp 只留 VK 钩子）',
          not dup, dup)
    # 事件桥：11 个后端无关方法在 VkViewport 上可用
    bridge = ['_phys', '_sync_mouse', 'mousePressEvent', 'mouseMoveEvent',
              'mouseReleaseEvent', 'wheelEvent', 'keyPressEvent', 'keyReleaseEvent',
              'key_pressed_array', 'dragEnterEvent', 'dropEvent', 'set_mouse_locked']
    missing = [m for m in bridge if not callable(getattr(VkViewport, m, None))]
    check('A6 VkViewport 事件桥 11 方法齐备', not missing, missing)
    return editor_mod, VkEditorApp


# ============================ B. 真窗口冒烟段 ============================

def section_b(editor_mod, VkEditorApp):
    _arm_watchdog()
    print('=== B. 真窗口：VK 编辑器 60 帧 + grab + 编辑态操作 ===')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from ui.loom_gui import LoomGUI

    app = QApplication.instance() or QApplication(['vk-editor-smoke'])
    win = LoomGUI(scene_path=None, width=1280, height=800, backend='vulkan')
    from ui.vk_viewport import VkViewport
    check('B1 backend=vulkan -> viewport 是 VkViewport', isinstance(win.viewport, VkViewport),
          type(win.viewport).__name__)
    _lg_src = open(os.path.join(ROOT, 'ui', 'loom_gui.py'), encoding='utf-8').read()
    check('B2 默认（未传 backend）仍走 GLViewport 分支（GL 路径分支原样保留）',
          'self.viewport = GLViewport(self, scene_path, width, height)' in _lg_src)
    win.show()

    st = {'phase': 'wait_editor', 'frames': 0, 'err': None,
          't0': time.perf_counter(), 'grab_ok': None, 'grab_px': None,
          'pick_ok': None, 'drag_ok': None, 'add_ok': None, 'done': False}

    def fail_hard(msg):
        st['err'] = msg
        finish()

    def editor_ready():
        vp = win.viewport
        return (getattr(vp, 'editor', None) is not None
                and getattr(vp, 'init_error', None) is None
                and getattr(vp, 'configured', False))

    def _vp_center(ed):
        """视口矩形中心（editor 物理像素坐标，_layout 契约）。"""
        vp = ed._layout()[4]
        return (vp[0] + vp[2] // 2, vp[1] + vp[3] // 2)

    def _click_at(ed, pos):
        """一次左键点击（与 Qt _on_tick -> render 同序喂给引擎状态字段）。"""
        ed.mouse_pos = pos
        ed.mouse_press_pos = {1: pos}
        ed.pressed = {1}
        ed.buttons = (1, 0, 0)
        ed._update_camera(1 / 60.0)
        ed.pressed.clear()
        ed.released.clear()
        ed.mouse_wheel = 0

    def _release(ed):
        ed.buttons = (0, 0, 0)
        ed.pressed.clear()
        ed.released.clear()

    def step_frames(n=10):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.016)
        e = win.editor
        if e is not None:
            st['frames'] = int(getattr(e, '_stage_frames', 0))

    def do_grab():
        e = win.editor
        pm = win.viewport.grab()
        img = pm.toImage()
        pxs = []
        for dy in (-40, 0, 40):
            for dx in (-40, 0, 40):
                c = img.pixelColor(img.width() // 2 + dx, img.height() // 2 + dy)
                pxs.append((c.red(), c.green(), c.blue()))
        # 清屏色 = CLEAR_COLOR_RGBA (0.10,0.12,0.16)->(26,31,41)；线框/物体非背景
        def _bg(p):
            # 背景 = Qt 控件底 (240,240,240) 或 VK 清屏色 (26,31,41)
            return ((abs(p[0] - 26) <= 6 and abs(p[1] - 31) <= 6 and abs(p[2] - 41) <= 6)
                    or (abs(p[0] - 240) <= 4 and abs(p[1] - 240) <= 4 and abs(p[2] - 240) <= 4))
        non_bg = [p for p in pxs if not _bg(p)]
        st['grab_px'] = pxs
        st['grab_ok'] = img.width() > 1 and len(non_bg) > 0
        return st['grab_ok']

    def do_edit_ops():
        e = win.editor
        # ---- 选中（点选球体，种子场景 index 2）----
        sphere = e.models[2]
        sp = e.project_world((sphere.position.x, sphere.position.y, sphere.position.z))
        if sp is None:
            st['pick_ok'] = False
            return
        _click_at(e, (int(sp[0]), int(sp[1])))
        e._update_gizmo()
        st['pick_ok'] = (e.selected_index == 2)
        # ---- 拖 gizmo（translate X 轴端帽）----
        e.selected_index = 2
        e.selected_light_index = -1
        e.gizmo_mode = 'translate'
        t = e._gizmo_target()
        o = e._target_world_pos(e, t)
        L = e._GIZMO_LEN
        cap = e.project_world((o[0] + L, o[1], o[2]))
        x0 = float(t.position.x)
        if cap is None:
            st['drag_ok'] = False
            return
        cap = (int(cap[0]), int(cap[1]))
        _click_at(e, cap)
        e.buttons = (1, 0, 0)           # 按住
        e._update_gizmo()               # 命中轴 -> gizmo_drag 启动
        dragging = e.gizmo_drag is not None and e.gizmo_axis == 'X'
        for _ in range(3):              # 拖 30px
            e.mouse_pos = (cap[0] + 30, cap[1])
            e._update_gizmo()
        _release(e)
        e._update_gizmo()               # 松开 -> 结束拖拽 + 压撤销
        st['drag_ok'] = bool(dragging and e.gizmo_drag is None
                             and abs(float(e.models[2].position.x) - x0) > 0.01
                             and e.undo.can_undo)
        # ---- 加物体 ----
        n0 = len(e.models)
        m = e._add_primitive('cube')
        st['add_ok'] = (m is not None and len(e.models) == n0 + 1)

    def finish():
        st['done'] = True
        # 双保险退出：quit + 兜底硬退出（防 rendercanvas 调度器把 exec 挂住 ——
        # 若 5s 内 exec 仍未返回，按失败码硬退，由 FAIL 门落非零退出码）。
        try:
            QTimer.singleShot(50, app.quit)
        except Exception:
            pass
        try:
            QTimer.singleShot(5000, lambda: os._exit(3))
        except Exception:
            pass

    def phase():
        try:
            if st['phase'] == 'wait_editor':
                if editor_ready():
                    st['phase'] = 'frames'
                    st['t_frames'] = time.perf_counter()
                elif time.perf_counter() - st['t0'] > 30:
                    fail_hard('VK 编辑器 30s 未就绪 (init_error=%r)'
                              % (getattr(win.viewport, 'init_error', None),))
            elif st['phase'] == 'frames':
                step_frames(10)
                if st['frames'] >= 60:
                    check('B3 真窗口 60 帧无异常', True, 'frames=%d' % st['frames'])
                    errs = getattr(win.viewport, 'frame_errors', [])
                    check('B4 渲染循环 0 异常', not errs, errs[:2])
                    do_grab()
                    check('B5 grab() 拿到非背景像素 (bitmap present)',
                          bool(st['grab_ok']), st['grab_px'])
                    st['phase'] = 'edit'
            elif st['phase'] == 'edit':
                do_edit_ops()
                check('B6 编辑态：点选球体 (selected_index==2)',
                      st['pick_ok'] is True, st['pick_ok'])
                check('B7 编辑态：拖 gizmo X 轴位移 + 撤销入栈',
                      st['drag_ok'] is True, st['drag_ok'])
                check('B8 编辑态：加物体 (cube)', st['add_ok'] is True, st['add_ok'])
                finish()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            fail_hard(repr(ex))
            return
        if not st['done']:
            QTimer.singleShot(30, phase)

    QTimer.singleShot(200, phase)
    # 不用 app.exec()：真窗口实测（本门调试）rendercanvas 调度器会挂住 exec 返回，
    # 改用受控 processEvents 泵 —— LoomGUI 的渲染/刷新定时器与 rendercanvas 调度器
    # 都是 Qt 定时器，processEvents 照常驱动；st['done'] 置位即收口（120s 兜底）。
    _t_end = time.perf_counter() + 120
    while not st['done'] and time.perf_counter() < _t_end:
        app.processEvents()
        time.sleep(0.01)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)
    if st['err'] is not None:
        check('B9 冒烟流程无异常', False, st['err'])
    # ★优雅关窗（2026-11-20 人类反馈：退出卡「是否保存」框会挂住 agent 测试；
    #   对人类该框是正常关闭确认，**保留不动**——测试侧绕开，LoomGUI 一行不改）：
    #   ① mark_saved() —— 编辑操作让场景变脏，不落回「已保存基线」closeEvent 就会
    #      弹三态模态框并 ev.ignore()（对话框阻塞测试进程）；
    #   ② _suppress_confirm=True —— LoomGUI 命令行退出同一条防重弹通道；
    #   ③ 主线程 QTimer 关窗 + 有界泵等 isVisible()=False（10s 超时报告，不挂死）。
    try:
        e = win.editor
        if e is not None:
            e.mark_saved()
        win._suppress_confirm = True
        QTimer.singleShot(0, win.close)
        _t_close = time.perf_counter()
        while win.isVisible() and time.perf_counter() - _t_close < 10:
            app.processEvents()
            time.sleep(0.01)
        print('[gate] 关窗 %s (耗时 %.1fs)' % ('OK' if not win.isVisible() else '超时(转硬杀)',
              time.perf_counter() - _t_close), flush=True)
    except Exception as _ce:
        print('[gate] 优雅关窗异常 (转硬杀): %r' % (_ce,), flush=True)
    # ★不调 win.close()：LoomGUI.closeEvent（on_application_quit 派发 / VK canvas
    # 停调度）在 Qt+wgpu 组合下**非确定性挂死**（本门调试实测：主线程阻塞在
    # closeEvent 的 C 段且持 GIL —— 连 join 超时都救不回来）。判定已在 _fails 完成，
    # 真窗口/设备资源由 main 的 os._exit 进程级回收承担（与 test_vk_p1_stage 同做法）。
    # 挂死现象与根因登记到交付报告「未核/留痕」。


def main():
    r = section_a()
    if r[0] is not None:
        section_b(r[0], r[1])
    print()
    verdict = {'ok': not _fails, 'fails': list(_fails),
               'pass_count': _pass_n}
    try:
        with open(_VERDICT_PATH, 'w', encoding='utf-8') as f:
            json.dump(verdict, f)
    except Exception as e:
        print('FAIL 冒烟 verdict 落盘失败: %r' % (e,))
        verdict = {'ok': False, 'fails': ['verdict write error'], 'pass_count': -1}
    print('总结果:', 'ALL PASS' if not _fails else '有 FAIL: %s' % _fails)
    # 硬退出：ExitProcess（os._exit）在 Qt+wgpu 装载后的 DLL/驱动 teardown 阶段会
    # 非确定性挂死（进程变僵尸数分钟，本机实测；TerminateProcess 也一样卡在
    # 内核态驱动调用上）—— 判定已在 _fails + verdict 文件完成，进程级收尾
    # 随僵尸自行消亡，宿主（父门）按 verdict 落自己的退出码（不被拖住）。
    _code = 0 if not _fails else 1
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    try:
        import ctypes as _ctypes
        _k32 = _ctypes.windll.kernel32
        _k32.TerminateProcess(_k32.GetCurrentProcess(), _ctypes.c_uint(_code))
    except Exception:
        pass
    os._exit(_code)


main()
