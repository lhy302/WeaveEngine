# -*- coding: utf-8 -*-
# test_ab_gl_vk.py — GL / Vulkan 双后端**逐像素** A/B（受跟踪，2026-11-09 批次 A/阶段1）
#
# 来历: 从 tests/_tmp/ab_gl_vk.py（2026-11-06 起沿用至今的"唯一验收口径"）提升而来。
# 原探针在 gitignore 里 -> 干净 clone 无法复现"逐像素等价"的证据（R01 报告 R8）。
#
# 用法:
#   py tests/test_ab_gl_vk.py                  # 全部场景, 与基线比对
#   py tests/test_ab_gl_vk.py --update-baseline # 重写基线快照（只在有意变更时用）
#   LOOM_AB_SCENES=ab_sky.json,ab_scene.json   # 只跑指定场景
#   LOOM_AB_MAE_ABS=0                          # 收紧阈值（用于验证闸门真的会 FAIL）
#
# 判据（三指标全部打印, 闸门见 DEFAULT_GATE）:
#   · MAE  <= mae_abs(2e-4): 相机/几何/着色/投影的对齐口径（沿用 ab_active_gl_vk 门槛）
#   · MAE  <= 基线 + mae_drift(5e-5) 且 NCC >= 基线 - ncc_drift(1e-4): 防回归
#   · MAX  <= max(max_abs(0.20), 基线MAX + 0.03): 只在灾难性边缘破坏时触发
#     （MAX 天然被抗锯齿/描边边缘影响, 实测常态 0.05~0.13, 不做逐像素判据）
#
# 环境: 无 GPU / 无 Vulkan 时打印 SKIP 并以 0 退出（不把"没装 wgpu"当成渲染回归）。
#
# 覆盖边界（与历史口径一致, 不得悄悄扩大）: 3D 部分（几何/着色/光照/阴影/天空/贴图）。
# UI 不在本闸门内 —— GL 侧跑 EditorApp.render（不画 UI），UI 等价由 ab_gl_vk_ui.py 单独覆盖。
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

W, H = 480, 320
FOV = 60.0
SCENES_DIR = os.path.join(HERE, 'ab_scenes')
ASSETS_DIR = os.path.join(SCENES_DIR, 'assets')
BASELINE_PATH = os.path.join(HERE, 'ab_gl_vk_baseline.json')

DEFAULT_GATE = {
    'mae_abs': 0.0002,
    'mae_drift': 0.00005,
    'ncc_drift': 0.0001,
    'max_abs': 0.20,
}

_fails = []
_skips = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _gate():
    g = dict(DEFAULT_GATE)
    for k in list(g.keys()):
        v = os.environ.get('LOOM_AB_' + k.upper())
        if v:
            try:
                g[k] = float(v)
            except ValueError:
                pass
    return g


def _rebase_paths(obj):
    """场景里的贴图绝对路径（原探针写死 _tmp）-> 仓库内 assets 同名文件。

    只改"指向的文件不存在"的项；文件存在时原样保留（保持与历史基线同一份数据）。
    """
    if isinstance(obj, dict):
        p = obj.get('path')
        if isinstance(p, str) and p and not os.path.exists(p):
            cand = os.path.join(ASSETS_DIR, os.path.basename(p))
            if os.path.exists(cand):
                obj['path'] = cand
        for v in obj.values():
            _rebase_paths(v)
    elif isinstance(obj, list):
        for v in obj:
            _rebase_paths(v)
    return obj


def _scene_files():
    sel = (os.environ.get('LOOM_AB_SCENES') or '').strip()
    if sel:
        names = [s.strip() for s in sel.split(',') if s.strip()]
        return [os.path.join(SCENES_DIR, n) for n in names]
    return sorted(glob.glob(os.path.join(SCENES_DIR, 'ab_*.json')))


class _NullView:
    """空视图: 只满足 IEditorView 契约, 不画任何编辑器叠层（保证纯净 3D 画面）。"""

    def attach(self, ctl):
        self.ctl = ctl

    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': True,
                'focus_id': None}

    def handle_key_event(self, ev):
        return True

    def reset_interaction(self):
        pass

    def draw(self, controller, delta_time):
        pass


def render_gl(data):
    """GL 侧: 独立上下文 + 离屏 FBO（与编辑器同一条渲染路径, 不画叠层）。"""
    import moderngl
    import editor as editor_mod
    import sceneio
    try:
        ctx = moderngl.create_standalone_context(require=430)
    except Exception as e:
        raise RuntimeError('GL 4.3 上下文不可用: %r' % (e,))
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
    return np.flipud(img)


_VK = {}


def _vk_device():
    """进程内复用同一个 adapter/device（每场景重建设备既慢又容易撞上限）。"""
    if _VK.get('device') is not None:
        return _VK['device']
    import wgpu
    adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
    if adapter is None:
        raise RuntimeError('无可用 Vulkan 适配器')
    _VK['device'] = adapter.request_device_sync()
    return _VK['device']


def render_vk(data):
    """VK 侧: VkRenderer 直接对离屏纹理渲染（绕过 GLFW 窗口）。"""
    import wgpu
    import scene_driver as sd
    import vk_renderer as vr
    fmt = 'rgba8unorm'
    device = _vk_device()
    tex = device.create_texture(
        size=(W, H, 1), format=fmt,
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)

    class Ctx:
        physical_size = (W, H)

        def get_current_texture(self):
            return tex

    drv = sd.SceneDriver()
    drv.load_from_data(data)
    r = vr.VkRenderer(device, fmt)
    vp, cam_pos = drv.render_pose(aspect=W / H)
    # 口径与历史 ab_gl_vk.py 逐位一致：**不传 ui**。GL 侧走 EditorApp.render（不画 UI），
    # 单传 ui 会让 VK 多画一层 UI -> 假差异（实测 MAE 0.33）。UI 等价不在本闸门内，
    # 由 tests/_tmp/ab_gl_vk_ui.py 单独覆盖（契约: vk_ui.py:48-60 非逐像素等价）。
    r.draw_frame(Ctx(), drv.models, drv.lights, vp, cam_pos, interp=None,
                 sky=getattr(drv, 'skybox', None))
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
    # wgpu 纹理原点在左上, 与 GL 的 fbo.read(flipud) 对齐 -> 这里不再翻转
    img = arr[:, :W, :3].astype(np.float32) / 255.0
    try:
        tex.destroy()
    except Exception:
        pass
    return img


def metrics(a, b):
    d = np.abs(a - b)
    mae = float(d.mean())
    mx = float(d.max())
    la = a.mean(axis=2).ravel()
    lb = b.mean(axis=2).ravel()
    la = la - la.mean()
    lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-9))
    return mae, mx, ncc


def load_baseline():
    try:
        with open(BASELINE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_baseline(gate, rows):
    data = {
        'generated': '2026-11-09',
        'note': 'GL 4.3 vs VK 逐像素基线; 由 test_ab_gl_vk.py --update-baseline 生成',
        'resolution': [W, H],
        'gate': gate,
        'scenes': rows,
    }
    with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    print('[基线] 已写入 %s (%d 场景)' % (BASELINE_PATH, len(rows)))


def main(argv):
    import sceneio
    update = '--update-baseline' in argv
    gate = _gate()
    files = _scene_files()
    if not files:
        print('SKIP 没有场景文件 (%s)' % SCENES_DIR)
        return 0
    print('=== GL vs VK 逐像素 A/B: %d 场景 @ %dx%d ===' % (len(files), W, H))
    print('闸门: MAE<=%g 且 MAE<=基线+%g 且 NCC>=基线-%g 且 MAX<=%g'
          % (gate['mae_abs'], gate['mae_drift'], gate['ncc_drift'], gate['max_abs']))
    base = load_baseline()
    base_rows = base.get('scenes', {}) if isinstance(base, dict) else {}
    rows = {}
    for path in files:
        name = os.path.basename(path)
        data = sceneio.load_scene_data(path)
        if not isinstance(data, dict):
            check(name + ' 场景可读', False, 'load_scene_data 返回 %r' % (type(data),))
            continue
        _rebase_paths(data)
        try:
            g = render_gl(data)
        except Exception as e:
            check(name + ' GL 渲染', False, repr(e))
            continue
        try:
            v = render_vk(data)
        except Exception as e:
            _skips.append(name)
            print('SKIP %s VK 不可用: %r' % (name, e))
            continue
        mae, mx, ncc = metrics(g, v)
        rows[name] = {
            'mae': round(mae, 8),
            'max': round(mx, 6),
            'ncc': round(ncc, 8),
        }
        if update:
            print('BASE %-24s MAE=%.6f MAX=%.4f NCC=%.6f' % (name, mae, mx, ncc))
            continue
        b = base_rows.get(name)
        ok_abs = mae <= gate['mae_abs']
        ok_drift = (b is None) or (mae <= b.get('mae', 0.0) + gate['mae_drift']
                                  and ncc >= b.get('ncc', 1.0) - gate['ncc_drift'])
        ok_max = mx <= max(gate['max_abs'], (b or {}).get('max', 0.0) + 0.03)
        detail = 'MAE=%.6f MAX=%.4f NCC=%.6f' % (mae, mx, ncc)
        if b is not None:
            detail += ' (基线 %.6f)' % b.get('mae', 0.0)
        check('%-24s %s' % (name, detail), ok_abs and ok_drift and ok_max,
              '' if (ok_abs and ok_drift and ok_max) else
              'mae_abs=%s drift=%s max=%s' % (ok_abs, ok_drift, ok_max))
    if update:
        save_baseline(gate, rows)
        return 0
    print('--- 场景 %d, 失败 %d, 跳过 %d ---' % (len(files), len(_fails), len(_skips)))
    return 0 if not _fails else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
