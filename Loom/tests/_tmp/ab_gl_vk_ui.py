# -*- coding: utf-8 -*-
r"""ab_gl_vk_ui.py — GL / Vulkan 的 Canvas UI + HUD 离屏 A/B 对比 (2026-11-06)

与 ab_gl_vk.py 同一口径 (同场景 JSON / 同相机 / 同分辨率 / 逐像素 MAE/MAX/NCC),
差别只在于**渲染末尾额外叠加 HUD 文本 + UIManager 元素树**:

  GL 侧: EditorApp.render() 之后手工执行与 loom_render.render() 末尾同序的两步:
           ed._draw_hud()        (loom_hud.draw_text_quad)
           ed.ui.draw_all(ed)    (loom_render.py:796-798 的原地次序)
  Vk 侧: VkRenderer.draw_frame(..., ui=driver.ui, hud_lines=...)
         driver.ui 由 sceneio._apply_ui 从场景 'ui' 段恢复 (与 GL 同源, 同一棵树)

用法:
    python tests\_tmp\ab_gl_vk_ui.py [scene.json] [out_prefix] [--no-ui]
    --no-ui : Vulkan 侧不画 HUD/UI (= 改造前行为), 用于产出"改造前"基线数值

输出: <prefix>_gl.png / _vk.png / _side.png / _diff.png + 控制台指标
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
    """空视图: 只提供 IEditorView 契约, 不画任何编辑器叠层 (保证纯净 3D 画面)."""
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


def _camera(data, ed):
    cam = data.get('camera') or {}
    if cam:
        ed.camera_target = tuple(cam.get('target', (0, 0, 0)))
        ed.camera_distance = float(cam.get('distance', 10.0))
        ed.camera_yaw = float(cam.get('yaw', 0.6))
        ed.camera_pitch = float(cam.get('pitch', -0.35))


def _expand_dropdown(ui_mgr, name='quality'):
    """让 Dropdown 处于展开态 (测 _draw_expanded_list 这条最上层绘制路径)."""
    try:
        el = ui_mgr.find(name)
        if el is not None:
            el._expanded = True
            el._hover_item = 1
    except Exception as e:
        print('  (展开 Dropdown 失败: %r)' % e)


def render_gl(data, with_ui=True, expand=False, world=False):
    """GL 侧: 3D + HUD + Canvas UI, 全部落到同一个离屏 FBO.

    world=True 时在 ed.render() 之后手工补 _draw_world_canvases() ——
    EditorApp.render 自身不画 world Canvas (只有 PlayerApp/GLEngine.render
    的末尾画), 但它的位置语义 (几何/天空之后, HUD 之前) 与 loom_render 相同.
    """
    import moderngl
    import editor as editor_mod
    import sceneio
    ctx = moderngl.create_standalone_context()
    rb = ctx.renderbuffer((W, H), components=4)
    depth_rb = ctx.depth_renderbuffer((W, H))
    fbo = ctx.framebuffer(color_attachments=[rb], depth_attachment=depth_rb)
    ed = editor_mod.EditorApp(W, H, view=_NullView(), ctx=ctx)
    ed._external_fb = fbo
    ed.show_grid = False
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    if hasattr(ed, 'clear_scene'):
        ed.clear_scene()
    else:
        ed.models[:] = []
        ed.lights[:] = []
    sceneio.scene_from_dict(ed, data)        # 含 'ui' 段 -> ed.ui (UIManager)
    _camera(data, ed)
    ed.orbit_mode = True
    ed.apply_orbit_camera()
    for _ in range(3):
        ed.render(1 / 60.0)
    hud_lines = []
    if with_ui:
        if expand and getattr(ed, 'ui', None) is not None:
            _expand_dropdown(ed.ui)
        # 2026-11-06 R1: world Canvas (GL PlayerApp 的绘制位置: 天空/几何之后,
        # HUD 之前). EditorApp.render 不画, 这里补一次; 无 world Canvas 时零操作.
        if world:
            # 本机 moderngl 5.12 的 Context 没有可读的 depth_mask 属性 (只有
            # 赋值后才有), 而 loom_render._draw_world_canvases 第一行就读它 ->
            # 真实 GL 路径会抛 AttributeError 被吞, 世界 Canvas 不画. 为了拿到
            # 设计意图上的 GL 参考图, 这里在 A/B 工具里注入一个 depth_mask 初值
            # (不修改 loom_render.py; 该差异已写入残差报告).
            try:
                _ = ed.ctx.depth_mask
            except AttributeError:
                try:
                    ed.ctx.depth_mask = True
                except Exception:
                    pass
            ed._draw_world_canvases()
        # 与 loom_render.render() 末尾同序: _draw_hud() -> ui.draw_all()
        hud_lines = list(ed._hud_lines())
        ed._draw_hud()
        if getattr(ed, 'ui', None) is not None:
            ed.ui.draw_all(ed)
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img), ed, hud_lines


def _camera_basis(drv, cam_pos):
    """GL billboard 用的 right/up: mat4_view_yaw_pitch 的 V[0]/V[1] 行 (逐行照搬)."""
    from matlib import mat4_view_yaw_pitch
    if getattr(drv, 'orbit_mode', True):
        yaw, pitch, roll = drv.yaw, drv.pitch, 0.0
    else:
        yaw = drv.camera_yaw
        pitch = drv.camera_pitch
        roll = drv.camera_roll
    V = mat4_view_yaw_pitch(np, tuple(cam_pos), yaw, pitch, roll)
    return ((float(V[0, 0]), float(V[0, 1]), float(V[0, 2])),
            (float(V[1, 0]), float(V[1, 1]), float(V[1, 2])))


def render_vk(data, hud_lines=None, with_ui=True, expand=False):
    """Vk 侧: 同一场景 + 同一 UIManager 树 (从场景 'ui' 段恢复) 叠加渲染."""
    import wgpu
    import scene_driver as sd
    import vk_renderer as vr

    drv = sd.SceneDriver()
    drv.load_from_data(data)                 # 内部已 _apply_ui -> drv.ui
    if expand and getattr(drv, 'ui', None) is not None:
        _expand_dropdown(drv.ui)
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
    vp, cam_pos = drv.render_pose(aspect=W / H)
    r.draw_frame(Ctx(), drv.models, drv.lights, vp, cam_pos, interp=None,
                 sky=getattr(drv, 'skybox', None),
                 ui=(getattr(drv, 'ui', None) if with_ui else None),
                 hud_lines=(hud_lines if with_ui else None),
                 cam_basis=_camera_basis(drv, cam_pos))

    bpr = (W * 4 + 255) // 256 * 256
    buf = device.create_buffer(size=bpr * H,
                               usage=wgpu.BufferUsage.COPY_DST
                               | wgpu.BufferUsage.MAP_READ)
    enc = device.create_command_encoder()
    enc.copy_texture_to_buffer(
        {'texture': tex},
        {'buffer': buf, 'offset': 0, 'bytes_per_row': bpr, 'rows_per_image': H},
        (W, H, 1))
    device.queue.submit([enc.finish()])
    buf.map_sync(wgpu.MapMode.READ)
    arr = np.frombuffer(buf.read_mapped(), dtype='u1').reshape(H, bpr // 4, 4)
    img = arr[:, :W, :3].astype(np.float32) / 255.0
    return img, drv, r


def compare(a, b, prefix, tag=''):
    d = np.abs(a - b)
    mae = float(d.mean())
    mx = float(d.max())
    la = a.mean(axis=2).ravel(); lb = b.mean(axis=2).ravel()
    la = la - la.mean(); lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-9))
    try:
        from PIL import Image
        side = np.concatenate([a, np.ones((H, 8, 3)), b], axis=1)
        Image.fromarray((np.clip(side, 0, 1) * 255).astype('uint8')).save(
            prefix + '_side.png')
        Image.fromarray((np.clip(b, 0, 1) * 255).astype('uint8')).save(
            prefix + '_vk.png')
        Image.fromarray((np.clip(a, 0, 1) * 255).astype('uint8')).save(
            prefix + '_gl.png')
        heat = np.clip(d.max(axis=2) * 4.0, 0, 1)
        Image.fromarray((heat * 255).astype('uint8')).save(prefix + '_diff.png')
    except Exception as e:
        print('  (png 保存失败: %r)' % e)
    print('%s  MAE=%.8f  MAX=%.6f  NCC=%.8f  (diff>0 像素数=%d/%d)'
          % (tag, mae, mx, ncc, int((d.max(axis=2) > 0).sum()), d.shape[0] * d.shape[1]))
    return mae, mx, ncc


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    # GL 侧恒画 HUD+UI (它是对照基准); --no-vk-ui 时 Vulkan 侧不画 = 改造前基线
    with_ui = '--no-vk-ui' not in sys.argv
    scene = args[0] if args else os.path.join(ROOT, 'tests', '_tmp',
                                              'ab_ui_scene.json')
    prefix = args[1] if len(args) > 1 else os.path.join(ROOT, 'tests', '_tmp',
                                                        'ab_ui_result')
    data = _scene_data(scene)
    expand = '--expand-dropdown' in sys.argv
    world = '--world' in sys.argv
    print('[GL] 渲染中... (UI=True, expand=%s, world=%s)' % (expand, world))
    g, ed, hud_lines = render_gl(data, with_ui=True, expand=expand, world=world)
    print('[VK] 渲染中... (UI=%s)' % with_ui)
    v, drv, r = render_vk(data, hud_lines=hud_lines, with_ui=with_ui,
                          expand=expand)
    n_ui_gl = sum(1 for _ in ed.ui.canvases) if getattr(ed, 'ui', None) else 0
    print('模型数 GL=%d  VK=%d | HUD 行数=%d | UI canvas GL=%d VK=%d'
          % (len(ed.models), len(drv.models), len(hud_lines), n_ui_gl,
             len(getattr(drv.ui, 'canvases', []) or [])))
    if with_ui and getattr(r, '_ui_engine', None) is not None:
        print('VK UI 绘制统计:', r._ui_engine.draw_stats,
              '| 管线:', r._ui_pipe.stats())
    return compare(g, v, prefix,
                   'GL(UI) vs VK' + ('(UI)' if with_ui else '(无UI=改造前)'))


if __name__ == '__main__':
    main()
