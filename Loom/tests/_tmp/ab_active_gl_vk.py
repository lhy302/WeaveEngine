# -*- coding: utf-8 -*-
r"""ab_active_gl_vk.py — 带 active_camera 的场景 GL/VK 逐像素 A/B (2026-11-06).

为什么单独一个脚本: tests\_tmp\ab_gl_vk.py 的 GL 侧是 EditorApp 且**强制轨道相机**
(它是"编辑视角"的验收口径)。场景里有摄像机实体时, 播放器语义应是
"active_camera 优先" (runtime.PlayerApp) —— 这个脚本的 GL 侧走该语义,
用来给"Vulkan 播放器已对齐 GL 玩家相机"提供逐像素证据 (不只是 VP 相等).

两组指标 (避免把"相机对齐"和"阴影采样差异"混为一谈):
  · MAE(关阴影): 相机/几何/着色/投影的对齐口径 —— 门槛 0.0002
  · MAE(原样)  : 含阴影采样的整帧差异 —— 只作报告 (Vk/GL 阴影偏移差异是既有缺口,
                 同一场景换视角后会放大, 与本次相机对齐无关)

GL 侧: EditorApp(ctx=standalone) + 空视图 + scene_from_dict + PlayerApp 同款相机分支
Vk 侧: SceneDriver.load_from_data (内含同款 active_camera 分支) + VkRenderer 离屏

用法: py -3.12 tests\_tmp\ab_active_gl_vk.py [scene.json ...]
"""
import copy
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

import numpy as np                      # noqa: E402
import ab_gl_vk as AB                   # noqa: E402

W, H = AB.W, AB.H
THRESH = 0.0002


def render_gl_active(data):
    """GL 播放器语义: sceneio 加载 -> active_camera 优先 -> 逐帧渲染."""
    import moderngl
    import editor as editor_mod
    import sceneio
    from loom_camera import clamp_camera_distance

    ctx = moderngl.create_standalone_context()
    rb = ctx.renderbuffer((W, H), components=4)
    depth_rb = ctx.depth_renderbuffer((W, H))
    fbo = ctx.framebuffer(color_attachments=[rb], depth_attachment=depth_rb)
    ed = editor_mod.EditorApp(W, H, view=AB._NullView(), ctx=ctx)
    ed._external_fb = fbo
    ed.show_grid = False
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.clear_scene()
    cam_out = {}
    sceneio.scene_from_dict(ed, data, camera_out=cam_out)
    # —— 与 runtime.PlayerApp.__init__ 同款相机分支 ——
    if cam_out:
        ed.camera_target = cam_out['target']
        ed.camera_distance = clamp_camera_distance(cam_out['distance'])
        ed.camera_yaw = cam_out['yaw']
        ed.camera_pitch = cam_out['pitch']
    cam = ed.active_camera_object()
    if cam is not None:
        ed.apply_camera(cam)
    else:
        ed.orbit_mode = True
        ed.apply_orbit_camera()
    for _ in range(3):
        ed.render(1 / 60.0)
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img), ed, ctx


def _strip_shadows(data):
    d = copy.deepcopy(data)
    for l in d.get('lights', []):
        l['shadow'] = False
    return d


def _diff(a, b):
    d = np.abs(a - b)
    la = a.mean(axis=2).ravel(); lb = b.mean(axis=2).ravel()
    la = la - la.mean(); lb = lb - lb.mean()
    return (float(d.mean()), float(d.max()),
            float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-9)))


def _both(data):
    g, ed, ctx = render_gl_active(copy.deepcopy(data))
    v, drv = AB.render_vk(copy.deepcopy(data))
    ctx.release()
    return g, v, ed, drv


def main():
    scenes = sys.argv[1:] or [os.path.join(HERE, 'camact_root.json'),
                              os.path.join(HERE, 'camact_parent.json')]
    print("%-22s %-8s %-12s %-12s %-10s %-8s %s"
          % ("场景", "相机", "MAE(原样)", "MAE(关阴影)", "MAX(关阴影)", "NCC", "结论"))
    print("-" * 92)
    bad = []
    for f in scenes:
        name = os.path.basename(f)
        data = AB._scene_data(f)
        g1, v1, ed, drv = _both(data)
        mae1, mx1, ncc1 = _diff(g1, v1)
        g2, v2, ed2, drv2 = _both(_strip_shadows(data))
        mae2, mx2, ncc2 = _diff(g2, v2)
        ok = mae2 <= THRESH
        if not ok:
            bad.append((name, mae2))
        mode = "active" if getattr(drv, 'active_camera_object', lambda: None)() else "orbit"
        print("%-22s %-8s %-12.6f %-12.6f %-10.4f %-8.4f %s"
              % (name, mode, mae1, mae2, mx2, ncc2, "PASS" if ok else "FAIL"))
        print("    相机: GL pos=(%.3f,%.3f,%.3f) fov=%.3f | VK pos=(%.3f,%.3f,%.3f) fov=%.3f"
              % (ed2.camera.x, ed2.camera.y, ed2.camera.z, ed2._fov,
                 drv2.camera_pos[0], drv2.camera_pos[1], drv2.camera_pos[2], drv2.fov))
    print("-" * 92)
    print("门槛: MAE(关阴影) <= %g (相机/几何/投影口径); 含阴影整帧差异仅作报告."
          % THRESH)
    if bad:
        print("FAIL:", bad)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
