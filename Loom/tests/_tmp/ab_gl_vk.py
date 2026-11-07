# -*- coding: utf-8 -*-
r"""ab_gl_vk.py — GL / Vulkan 双后端离屏 A/B 对比 (2026-11-06)

用途: Vulkan 对齐 OpenGL 的**唯一验收口径**（逐像素差异 + 并排图）。
两边吃同一份场景 JSON、同一相机参数、同一分辨率，仅渲染后端不同。

GL 侧: EditorApp(ctx=standalone) + 空视图 (不画编辑器叠层/网格)
Vk 侧: VkRenderer 直接对离屏纹理渲染 (绕过 GLFW 窗口)

用法: python tests\_tmp\ab_gl_vk.py <scene.json> [out_prefix]
输出: <prefix>_gl.png / <prefix>_vk.png / <prefix>_diff.png + 控制台指标
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'

W, H = 480, 320
FOV = 60.0


class _NullView:
    """空视图: 只提供 IEditorView 契约, 不画任何叠层 (保证纯净 3D 画面)."""
    def attach(self, ctl): self.ctl = ctl
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': True,
                'focus_id': None}
    def handle_key_event(self, ev): return True
    def reset_interaction(self): pass
    def draw(self, controller, delta_time): pass


def _scene_data(path):
    import sceneio
    return sceneio.load_scene_data(path)


def render_gl(data):
    import moderngl
    import editor as editor_mod
    import sceneio
    ctx = moderngl.create_standalone_context()
    rb = ctx.renderbuffer((W, H), components=4)
    # 2026-11-06: 必须带深度附件 —— 否则天空盒 (depth==1 才通过) 会盖住整个画面,
    # A/B 里 GL 侧看起来"只有天空"。
    depth_rb = ctx.depth_renderbuffer((W, H))
    fbo = ctx.framebuffer(color_attachments=[rb], depth_attachment=depth_rb)
    ed = editor_mod.EditorApp(W, H, view=_NullView(), ctx=ctx)
    ed._external_fb = fbo          # 渲染目标 = 我们的离屏 FBO
    ed.show_grid = False
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    if hasattr(ed, 'clear_scene'):
        ed.clear_scene()          # 清掉 EditorApp 默认场景, 只留 A/B 场景
    else:
        ed.models[:] = []
        ed.lights[:] = []
    sceneio.scene_from_dict(ed, data)
    cam = data.get('camera') or {}
    if cam:
        ed.camera_target = tuple(cam.get('target', (0, 0, 0)))
        ed.camera_distance = float(cam.get('distance', 10.0))
        ed.camera_yaw = float(cam.get('yaw', 0.6))
        ed.camera_pitch = float(cam.get('pitch', -0.35))
    ed.orbit_mode = True
    ed.apply_orbit_camera()
    for _ in range(3):
        ed.render(1 / 60.0)
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img), ed, ctx


def render_vk(data):
    import wgpu
    import scene_driver as sd
    import vk_renderer as vr

    drv = sd.SceneDriver()
    drv.load_from_data(data)
    fmt = 'rgba8unorm'

    adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
    device = adapter.request_device_sync()
    tex = device.create_texture(
        size=(W, H, 1), format=fmt,
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)

    class Ctx:
        physical_size = (W, H)
        def get_current_texture(self):
            return tex

    r = vr.VkRenderer(device, fmt)
    aspect = W / H
    vp, cam_pos = drv.render_pose(aspect=aspect)
    r.draw_frame(Ctx(), drv.models, drv.lights, vp, cam_pos, interp=None,
                 sky=getattr(drv, 'skybox', None))

    # 读回 (256 字节行对齐)
    bpr = (W * 4 + 255) // 256 * 256
    buf = device.create_buffer(size=bpr * H,
                               usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
    enc = device.create_command_encoder()
    enc.copy_texture_to_buffer(
        {'texture': tex},
        {'buffer': buf, 'offset': 0, 'bytes_per_row': bpr, 'rows_per_image': H},
        (W, H, 1))
    device.queue.submit([enc.finish()])
    buf.map_sync(wgpu.MapMode.READ)
    arr = np.frombuffer(buf.read_mapped(), dtype='u1').reshape(H, bpr // 4, 4)
    # wgpu 纹理原点在左上: 行序已是"从上到下", 与 GL 的 fbo.read (从下到上,
    # 调用方做了 flipud) 对齐 —— 这里**不再翻转**, 否则两图上下颠倒。
    img = arr[:, :W, :3].astype(np.float32) / 255.0
    return img, drv


def compare(a, b, prefix, tag=''):
    d = np.abs(a - b)
    mae = float(d.mean())
    mx = float(d.max())
    # 归一化互相关 (单通道亮度)
    la = a.mean(axis=2).ravel(); lb = b.mean(axis=2).ravel()
    la = la - la.mean(); lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-9))
    try:
        from PIL import Image
        side = np.concatenate([a, np.ones((H, 8, 3)), b], axis=1)
        Image.fromarray((np.clip(side, 0, 1) * 255).astype('uint8')).save(prefix + '_side.png')
        Image.fromarray((np.clip(b, 0, 1) * 255).astype('uint8')).save(prefix + '_vk.png')
        Image.fromarray((np.clip(a, 0, 1) * 255).astype('uint8')).save(prefix + '_gl.png')
        heat = np.clip(d.max(axis=2) * 4.0, 0, 1)
        Image.fromarray((heat * 255).astype('uint8')).save(prefix + '_diff.png')
    except Exception as e:
        print('  (png 保存失败: %r)' % e)
    print('%s  MAE=%.4f  MAX=%.4f  NCC=%.4f' % (tag, mae, mx, ncc))
    return mae, mx, ncc


def main():
    scene = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, 'tests', '_tmp', 'ab_scene.json')
    prefix = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        ROOT, 'tests', '_tmp', 'ab_result')
    data = _scene_data(scene)
    print('[GL] 渲染中...')
    g, ed, ctx = render_gl(data)
    print('[VK] 渲染中...')
    v, drv = render_vk(data)
    print('模型数 GL=%d  VK=%d   光源 GL=%d VK=%d'
          % (len(ed.models), len(drv.models), len(ed.lights), len(drv.lights)))
    return compare(g, v, prefix, 'GL vs VK')


if __name__ == '__main__':
    main()
