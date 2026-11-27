# -*- coding: utf-8 -*-
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith('FAIL') or '\nFAIL' in text):
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

"""test_ui_shape_depth_state.py — UI 描边/填充不依赖调用方深度状态（B14 回归, 2026-11-16）

为什么有这条测试：
  `engine.draw_screen_lines` / `draw_screen_polygon` 的 docstring 写着「不深度测试」，
  但旧实现**根本没关深度** —— UI 在 main/sky 之后画，深度测试仍开着，于是 3D 深度非 1
  的像素上整条描边被丢弃（实测 480x320 场景条线 **0 像素**）。更糟的是失败被
  `except: pass` 静默吞掉（engine 两层 + loom_ui 两层），**错了但没人知道**。
  当时 A/B 夹具是靠外部 `ctx.disable(DEPTH_TEST)` 绕过才没暴露（见 test_ab_gl_vk.py:209-216）。

修法（2026-11-16）：两个屏幕空间助手在 `ctx.scope` 内临时关深度（退出自动恢复），
并把吞异常改成每进程上报一次。

本测试锁三件事（**有牙**：第 2 条直接证明"修的是它"）：
  1. 走旧路径 `ed.draw_lines(...)` 直接画（不关深度）→ 在 3D 几何上**看不见**（≈0 像素）；
  2. 走新路径 `ed.draw_screen_lines(...)` → **看得见**（> 0 像素）；
  3. 画完之后深度测试状态被 scope **恢复原值**（不留状态污染），且 Shape 元素
     （`loom_ui.Shape`，真实元素路径）也能画出来。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'Loom'),
           os.path.join(ROOT, 'Loom', 'tests')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ['LOOM_NO_DIALOG'] = '1'

import moderngl                      # noqa: E402
import test_ab_gl_vk as AB           # noqa: E402

W, H = AB.W, AB.H
ok = True


def check(name, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + str(detail)) if detail else ''))
    if not cond:
        ok = False


def _build():
    """与 test_ab_gl_vk.render_gl 同一条生产路径（EditorApp.render），但保留 ctx 自己管。"""
    import editor as editor_mod
    import sceneio
    data = AB._load_scene(os.path.join(AB.SCENES_DIR, 'ab_scene.json'))
    ctx = moderngl.create_standalone_context(require=430)
    rb = ctx.renderbuffer((W, H), components=4)
    drb = ctx.depth_renderbuffer((W, H))
    fbo = ctx.framebuffer(color_attachments=[rb], depth_attachment=drb)
    ed = editor_mod.EditorApp(W, H, view=AB._NullView(), ctx=ctx)   # 复用 A/B 夹具的空视图
    ed._external_fb = fbo
    ed.show_grid = False
    ed.selected_index = ed.selected_light_index = ed.selected_camera_index = -1
    if hasattr(ed, 'clear_scene'):
        ed.clear_scene()
    sceneio.scene_from_dict(ed, data, base_dir=AB.SCENES_DIR)
    cam = data.get('camera') or {}
    if cam:
        ed.camera_target = tuple(cam.get('target', (0, 0, 0)))
        ed.camera_distance = float(cam.get('distance', 10.0))
        ed.camera_yaw = float(cam.get('yaw', 0.6))
        ed.camera_pitch = float(cam.get('pitch', -0.35))
    ed.orbit_mode = True
    ed.apply_orbit_camera()
    return ctx, fbo, ed


def _shoot(fbo):
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img)


def _diff(a, b, thr=2.0 / 255.0):
    return int((np.abs(a - b).max(axis=2) > thr).sum())


def main():
    ctx, fbo, ed = _build()
    for _ in range(3):
        ed.render(1 / 60.0)
    base = _shoot(fbo)

    # 注：moderngl 5.x 的 Context 没有 is_enabled 查询接口，所以"状态是否被恢复"用
    # **行为**验证：UI 画完之后重渲染一帧，画面必须与基线逐像素一致（深度/混合/裁剪
    # 任一被污染都会改变后续 3D 渲染结果）。

    # 屏幕空间一条横穿场景的折线（像素坐标）
    pts = [(40, 160), (440, 160)]
    color = (255, 40, 40, 255)
    verts, cols = [], []
    for (px, py) in pts:
        nx, ny = ed._px_to_ndc(px, py)
        verts.append((nx, ny, 0.0))
        cols.append([c / 255.0 for c in color])

    # ---- 旧路径：直接 draw_lines（不关深度）----
    ed.draw_lines(verts, cols, mode=moderngl.LINES,
                  view_proj=np.eye(4, dtype='f4'), line_width=2.0)
    old_px = _diff(base, _shoot(fbo))
    check('旧路径(不关深度)在 3D 几何上看不见 —— 这就是 B14 的现象', old_px == 0,
          'differing_pixels=%d' % old_px)

    # ---- 新路径：draw_screen_lines（内部 scope 关深度）----
    for _ in range(3):
        ed.render(1 / 60.0)
    base2 = _shoot(fbo)
    ed.draw_screen_lines(pts, color, width=2.0)
    new_px = _diff(base2, _shoot(fbo))
    check('新路径(draw_screen_lines)画得出来', new_px > 0, 'differing_pixels=%d' % new_px)
    check('有牙: 新路径显著多于旧路径', new_px > old_px,
          'new=%d old=%d' % (new_px, old_px))
    for _ in range(3):
        ed.render(1 / 60.0)
    polluted = _diff(base2, _shoot(fbo))
    check('画完 UI 后重渲染一帧与基线逐像素一致（scope 恢复了状态，无污染）',
          polluted == 0, 'differing_pixels=%d' % polluted)

    # ---- 真实元素路径：loom_ui.Shape（描边 + 填充）----
    from loom_ui import UIManager, Canvas, Shape
    for _ in range(3):
        ed.render(1 / 60.0)
    base3 = _shoot(fbo)
    ui = UIManager()
    cv = Canvas(width=W, height=H, z_order=0)
    sh = Shape('probe_shape', rect=(0, 0, W, H), shape_type='polygon',
               points=[(60, 60), (420, 60), (420, 260), (60, 260)],
               stroke_color=(40, 255, 40, 255), stroke_width=3,
               fill_color=(40, 40, 255, 255))
    cv.root.add_child(sh)
    ui.add_canvas(cv)
    ui.draw_all(ed)
    shape_px = _diff(base3, _shoot(fbo))
    check('Shape 元素（真实路径）画得出来', shape_px > 0, 'differing_pixels=%d' % shape_px)
    for _ in range(3):
        ed.render(1 / 60.0)
    polluted2 = _diff(base3, _shoot(fbo))
    check('Shape 之后重渲染一帧与基线一致（无状态污染）', polluted2 == 0,
          'differing_pixels=%d' % polluted2)

    try:
        ctx.release()
    except Exception:
        pass
    print()
    print('test_ui_shape_depth_state:', 'ALL PASS' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())