# -*- coding: utf-8 -*-
# test_ab_gl_vk.py — GL / Vulkan 逐像素 A/B（受跟踪，2026-11-09 批次 A）
#
# 承诺（人类裁决）: **渲染画面不回归**（不只是两端等价）。因此基线存两类证据：
#   · tests/ab_scenes_ref/*.png   —— GL 参考图（480x320）；
#   · tests/ab_gl_vk_baseline.json —— 每场景三指标 + 参考图 sha256 + 门限。
# 判定（每场景全部要过）:
#   ① GL vs 参考 <= mae_abs   ② VK vs 参考 <= mae_abs   ③ GL vs VK <= mae_abs
#   ④ 相对基线不漂移: MAE <= 基线 + mae_drift 且 NCC >= 基线 - ncc_drift（float64 累加）
#   ⑤ MAX <= max(max_abs, 基线MAX+0.03)（只在灾难性边缘破坏时触发）
#   ⑥ UI 场景（有 canvas 的）额外比 UI 三路（阈值 ui_mae_abs，契约见 vk_ui.py:48-60）
#
# 为什么 ① ② 必须有: 只比 GL/VK 时，两端**同时**回归（例如投影矩阵一起改）会让端间
# 差异反而变小 -> 闸门 PASS。实测: fov 两端同 +15% 时端间 MAE 从 6.8e-5 降到 4.9e-5。
#
# 用法:
#   py tests/test_ab_gl_vk.py                    # 全场景对基线（失败即 rc=1）
#   py tests/test_ab_gl_vk.py --update-baseline  # 重建参考图+基线（有 FAIL 不写）
#   py tests/test_ab_gl_vk.py --update-baseline --force   # 允许场景数变少
#   py tests/test_ab_gl_vk.py                   # 自动跟随 LOOM_POST（默认=后处理口径的新基线）
#   py tests/test_ab_gl_vk.py --legacy           # 强制旧参考/旧基线（= LOOM_POST=0 口径）
#   LOOM_POST=0 py tests/test_ab_gl_vk.py         # 关后处理 -> 旧基线必须全绿（回退证明）
#   py tests/test_ab_gl_vk.py --self-test        # 自检：反例必须让闸门变红
#   LOOM_AB_SCENES=a.json,b.json                 # 只跑子集（对基线，不改基线）
#   LOOM_AB_ALLOW_NO_VK=1                        # 显式允许"本机没有 Vulkan"（否则 FAIL）
#   LOOM_AB_MAE_ABS=0                            # 收紧阈值（验证闸门真会红）
#
# 覆盖: 3D（几何/着色/光照/阴影/天空/贴图）+ UI（有 canvas 的场景）。
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

W, H = 480, 320
SCENES_DIR = os.path.join(HERE, 'ab_scenes')
ASSETS_DIR = os.path.join(SCENES_DIR, 'assets')
REF_DIR = os.path.join(HERE, 'ab_scenes_ref')
BASELINE_PATH = os.path.join(HERE, 'ab_gl_vk_baseline.json')
# 2026-11-10 阶段 2B2: 后处理上线后 GL 画面**故意变化** -> 新参考图另存一份，
# 旧参考/旧基线原样保留（LOOM_POST=0 时仍必须全绿，证明开关真能回退）。
REF_DIR_NEXT = os.path.join(HERE, 'ab_scenes_ref_next')
BASELINE_NEXT = os.path.join(HERE, 'ab_gl_vk_baseline_next.json')
SCHEMA = 2
# 只在后处理口径存在的场景：旧基线（LOOM_POST=0）里没有它们，
# legacy 模式下按**显式白名单**跳过（不是静默放过——其它新场景仍然 FAIL）。
POST_ONLY = {'ab_bloom.json'}

DEFAULT_GATE = {
    'mae_abs': 0.0002,
    'mae_drift': 0.00005,
    'ncc_drift': 0.0001,
    'max_abs': 0.20,
    'ui_mae_abs': 0.005,
    'ui_mae_drift': 0.002,
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
    """场景里的贴图绝对路径（原探针写死 _tmp）-> 仓库内 assets 同名文件。"""
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


def has_ui(data):
    ui = (data or {}).get('ui') or {}
    return bool(ui.get('canvases'))


def _scene_files():
    sel = (os.environ.get('LOOM_AB_SCENES') or '').strip()
    if sel:
        names = [s.strip() for s in sel.split(',') if s.strip()]
        return [os.path.join(SCENES_DIR, n) for n in names]
    return sorted(glob.glob(os.path.join(SCENES_DIR, 'ab_*.json')))


class _NullView:
    """空视图: 只满足 IEditorView 契约, 不画编辑器叠层（保证纯净 3D 画面）。"""

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


def render_gl(data, with_ui=False):
    """GL 侧: 独立上下文 + 离屏 FBO（编辑器同一条渲染路径）。with_ui 时补画 UI 层。"""
    import moderngl
    import editor as editor_mod
    import sceneio
    ctx = moderngl.create_standalone_context(require=430)
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
    if with_ui:
        ui = getattr(ed, 'ui', None)
        if ui is not None:
            ui.draw_all(ed)          # 画进 ed._screen_fb() = 我们的 fbo
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    out = np.flipud(img)
    try:
        ctx.release()
    except Exception:
        pass
    return out


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


def render_vk(data, with_ui=False):
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
    kw = {}
    if with_ui:
        kw['ui'] = getattr(drv, 'ui', None)
    r.draw_frame(Ctx(), drv.models, drv.lights, vp, cam_pos, interp=None,
                 sky=getattr(drv, 'skybox', None), **kw)
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
    img = arr[:, :W, :3].astype(np.float32) / 255.0
    try:
        tex.destroy()
    except Exception:
        pass
    return img


def metrics(a, b):
    """MAE / MAX / NCC。**float64 累加**（float32 会把 NCC 算到 >1）。"""
    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
    mae = float(d.mean())
    mx = float(d.max())
    la = a.astype(np.float64).mean(axis=2).ravel()
    lb = b.astype(np.float64).mean(axis=2).ravel()
    la = la - la.mean()
    lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-12))
    return mae, mx, ncc


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


def _save_png(img, path):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype('uint8')).save(path)


def _load_png(path):
    from PIL import Image
    a = np.asarray(Image.open(path).convert('RGB'))
    return a.astype(np.float32) / 255.0

def _baseline_load(path=None):
    """读基线；返回 (data, error)。error 非空 = 基线不可用（调用方按 FAIL 处理, 不是 PASS）。"""
    p = path or BASELINE_PATH
    if not os.path.isfile(p):
        return None, '基线文件缺失: %s（需先 --update-baseline）' % p
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return None, '基线文件损坏: %r' % (e,)
    if not isinstance(data, dict):
        return None, '基线结构非法（不是对象）'
    if data.get('schema') != SCHEMA:
        return None, '基线 schema=%r != %d（需重建）' % (data.get('schema'), SCHEMA)
    if list(data.get('resolution') or []) != [W, H]:
        return None, '基线分辨率=%r != %r' % (data.get('resolution'), [W, H])
    scenes = data.get('scenes')
    if not isinstance(scenes, dict) or not scenes:
        return None, '基线没有场景条目'
    if int(data.get('scene_count') or 0) != len(scenes):
        return None, '基线 scene_count=%r 与条目数 %d 不一致' % (data.get('scene_count'), len(scenes))
    return data, None


def _ref_path(name, ui=False, ref_dir=None):
    stem = os.path.splitext(name)[0]
    return os.path.join(ref_dir or REF_DIR, stem + ('__ui' if ui else '') + '.png')


def _fmt3(t):
    return '%.6f/%.6f/%.6f' % (t[0], t[1], t[2])


def _check_scene(name, g, v, base, ref_dir, gate):
    """返回 (ok, reasons, line)。三路（GL/参考、VK/参考、GL/VK）+ 漂移 + MAX + UI。"""
    reasons = []
    rp = _ref_path(name, False, ref_dir)
    if not os.path.isfile(rp):
        reasons.append('参考图缺失: %s' % rp)
        ref = None
    else:
        ref = _load_png(rp)
    if base is None:
        reasons.append('基线缺本场景条目（新场景需 --update-baseline）')
    else:
        want_sha = base.get('ref_sha256')
        if not want_sha:
            reasons.append('基线缺 ref_sha256 字段')
        elif ref is not None:
            got = _sha(rp)
            if got != want_sha:
                reasons.append('参考图哈希不符（被改过/重建未同步）')
    mgr = mvr = None
    if ref is not None:
        mgr = metrics(g, ref)
        mvr = metrics(v, ref)
        if mgr[0] > gate['mae_abs']:
            reasons.append('GL vs 参考 MAE=%.6f > %.6f（共享回归）' % (mgr[0], gate['mae_abs']))
        if mvr[0] > gate['mae_abs']:
            reasons.append('VK vs 参考 MAE=%.6f > %.6f' % (mvr[0], gate['mae_abs']))
    mgv = metrics(g, v)
    if mgv[0] > gate['mae_abs']:
        reasons.append('GL vs VK MAE=%.6f > %.6f' % (mgv[0], gate['mae_abs']))
    if base is not None:
        if mgv[0] > float(base.get('mae', 0.0)) + gate['mae_drift']:
            reasons.append('MAE 漂移 %.6f > 基线 %.6f + %.6f'
                           % (mgv[0], float(base.get('mae', 0.0)), gate['mae_drift']))
        if mgv[2] < float(base.get('ncc', 1.0)) - gate['ncc_drift']:
            reasons.append('NCC 劣化 %.6f < 基线 %.6f - %.6f'
                           % (mgv[2], float(base.get('ncc', 1.0)), gate['ncc_drift']))
        mx_cap = max(gate['max_abs'], float(base.get('max', 0.0)) + 0.03)
        if mgv[1] > mx_cap:
            reasons.append('MAX %.4f > 上限 %.4f' % (mgv[1], mx_cap))
    else:
        mx_cap = gate['max_abs']
    line = format_line(mgr, mvr, mgv, base)
    return (not reasons), reasons, line


def format_line(mgr, mvr, mgv, base):
    parts = []
    if mgr is not None and mvr is not None:
        parts.append('MAE(gl/ref,vk/ref,gl/vk)=%s/%s/%s'
                     % (format_mae(mgr[0]), format_mae(mvr[0]), format_mae(mgv[0])))
    else:
        parts.append('MAE(gl/vk)=%s' % format_mae(mgv[0]))
    parts.append('MAX=%.4f' % mgv[1])
    parts.append('NCC=%.6f' % mgv[2])
    if base is not None:
        parts.append('基线 %.6f' % float(base.get('mae', 0.0)))
    return '  '.join(parts)


def format_mae(x):
    return '%.6f' % x


def _ui_check(name, g_ui, v_ui, base, ref_dir, gate):
    """UI 三路（GL/参考、VK/参考、GL/VK）。基线没有 ui 段 -> 视为基线不完整（FAIL）。"""
    reasons = []
    rp = _ref_path(name, True, ref_dir)
    ref = _load_png(rp) if os.path.isfile(rp) else None
    base_ui = (base or {}).get('ui') if base else None
    if ref is None:
        reasons.append('UI 参考图缺失: %s' % rp)
    if not isinstance(base_ui, dict):
        reasons.append('基线缺 UI 段（--update-baseline 需重跑）')
    if ref is not None:
        mgr = metrics(g_ui, ref)
        mvr = metrics(v_ui, ref)
        if mgr[0] > gate['ui_mae_abs']:
            reasons.append('UI GL vs 参考 MAE=%.6f > %.6f' % (mgr[0], gate['ui_mae_abs']))
        if mvr[0] > gate['ui_mae_abs']:
            reasons.append('UI VK vs 参考 MAE=%.6f > %.6f' % (mvr[0], gate['ui_mae_abs']))
    mgv = metrics(g_ui, v_ui)
    if mgv[0] > gate['ui_mae_abs']:
        reasons.append('UI GL vs VK MAE=%.6f > %.6f（契约上限）' % (mgv[0], gate['ui_mae_abs']))
    if isinstance(base_ui, dict):
        if mgv[0] > float(base_ui.get('mae', 0.0)) + gate['ui_mae_drift']:
            reasons.append('UI MAE 漂移 %.6f > 基线 %.6f + %.6f'
                           % (mgv[0], float(base_ui.get('mae', 0.0)), gate['ui_mae_drift']))
    line = format_ui_line(mgv, base_ui)
    return (not reasons), reasons, line


def format_ui_line(mgv, base_ui):
    s = 'UI MAE(gl/vk)=%.6f MAX=%.4f NCC=%.6f' % (mgv[0], mgv[1], mgv[2])
    if isinstance(base_ui, dict):
        s += ' 基线 %.6f' % float(base_ui.get('mae', 0.0))
    return s


def run_gate(files, baseline_path=None, ref_dir=None, gate=None, allow_no_vk=None,
             legacy=False):
    """对基线跑闸门；返回 rc。基线缺失/损坏/场景无条目一律 FAIL（P1-2）。"""
    gate = gate or _gate()
    if allow_no_vk is None:
        allow_no_vk = (os.environ.get('LOOM_AB_ALLOW_NO_VK') == '1')
    if not files:
        # P2④: 空场景集必须是失败（否则「跑了个寂寞」也算绿）
        print('[ab] 错误: 场景集为空（tests/ab_scenes 无 ab_*.json, 或 LOOM_AB_SCENES 解析为空）')
        return 1
    data, err = _baseline_load(baseline_path)
    print('=== GL vs VK 逐像素 A/B: %d 场景 @ %dx%d ===' % (len(files), W, H))
    print('闸门: MAE<=%g（GL/参考 + VK/参考 + GL/VK 三路）且 <=基线+%g, NCC>=基线-%g, MAX<=%g, UI MAE<=%g'
          % (gate['mae_abs'], gate['mae_drift'], gate['ncc_drift'],
             gate['max_abs'], gate['ui_mae_abs']))
    if err:
        check('基线可用', False, err)
        print('--- 场景 %d, 失败 %d, 跳过 %d ---' % (len(files), len(_fails), len(_skips)))
        return 1
    base_rows = data.get('scenes', {})
    vk_broken = False
    for path in files:
        name = os.path.basename(path)
        if legacy and name in POST_ONLY and name not in base_rows:
            _skips.append(name)
            print('SKIP %s 旧基线不含该场景（后处理专用，POST_ONLY 白名单）' % name)
            continue
        data_s = _load_scene(path)
        if data_s is None:
            check(name + ' 场景可读', False, '读取/解析失败')
            continue
        try:
            g = render_gl(data_s)
        except Exception as e:
            check(name + ' GL 渲染', False, repr(e))
            continue
        v = None
        try:
            v = render_vk(data_s)
        except Exception as e:
            vk_broken = True
            if allow_no_vk:
                _skips.append(name)
                print('SKIP %s VK 不可用（已显式允许 LOOM_AB_ALLOW_NO_VK=1）: %r' % (name, e))
            else:
                check(name + ' VK 渲染', False, repr(e))
        ref = _load_png(_ref_path(name, False, ref_dir)) \
            if os.path.isfile(_ref_path(name, False, ref_dir)) else None
        if v is None:
            if ref is None:
                continue
            mgr = metrics(g, ref)
            ok = mgr[0] <= gate['mae_abs']
            check('%-16s GL vs 参考 MAE=%.6f（VK 已跳过）' % (name, mgr[0]), ok)
            continue
        ok, reasons, line = _check_scene(name, g, v, base_rows.get(name), ref_dir, gate)
        check('%-24s %s' % (name, line), ok, '; '.join(reasons))
        if has_ui(data_s):
            try:
                g_ui = render_gl(data_s, with_ui=True)
                v_ui = render_vk(data_s, with_ui=True)
                ok2, reasons2, line2 = _ui_check(name, g_ui, v_ui,
                                                 base_rows.get(name), ref_dir, gate)
                check('%-24s %s' % (name + ' [UI]', line2), ok2, '; '.join(reasons2))
            except Exception as e:
                check(name + ' [UI] 渲染', False, repr(e))
    print('--- 场景 %d, 失败 %d, 跳过 %d ---' % (len(files), len(_fails), len(_skips)))
    return 0 if not _fails else 1
def _load_scene(path):
    """读场景 dict 并把历史绝对贴图路径重定位到仓库内 assets。"""
    import sceneio
    data = sceneio.load_scene_data(path)
    if not isinstance(data, dict):
        return None
    return _rebase_paths(data)


def run_update(files, baseline_path=None, ref_dir=None, gate=None, force=False):
    """重建参考图 + 基线。任何渲染失败 -> **不写**、rc=1（P1-4）。"""
    gate = gate or _gate()
    bp = baseline_path or BASELINE_PATH
    rd = ref_dir or REF_DIR
    if not files:
        print('[基线] 拒绝写入: 场景集为空（先确认 tests/ab_scenes 或 LOOM_AB_SCENES）')
        return 1
    rows = {}
    failures = []
    for path in files:
        name = os.path.basename(path)
        data = _load_scene(path)
        if data is None:
            failures.append('%s: 场景读取失败' % name)
            continue
        try:
            g = render_gl(data)
            v = render_vk(data)
        except Exception as e:
            failures.append('%s: 渲染失败 %r' % (name, e))
            continue
        rp = _ref_path(name, False, rd)
        _save_png(g, rp)
        mgv = metrics(g, v)
        row = {
            'mae': round(mgv[0], 8),
            'max': round(mgv[1], 6),
            'ncc': round(mgv[2], 8),
            'ref_sha256': _sha(rp),
        }
        if has_ui(data):
            try:
                g_ui = render_gl(data, with_ui=True)
                v_ui = render_vk(data, with_ui=True)
                urp = _ref_path(name, True, rd)
                _save_png(g_ui, urp)
                mu = metrics(g_ui, v_ui)
                row['ui'] = {'mae': round(mu[0], 8), 'max': round(mu[1], 6),
                             'ncc': round(mu[2], 8), 'ref_sha256': _sha(urp)}
            except Exception as e:
                failures.append('%s: UI 渲染失败 %r' % (name, e))
                continue
        rows[name] = row
        print('BASE %-24s MAE=%.6f MAX=%.4f NCC=%.6f' % (name, mgv[0], mgv[1], mgv[2]))
    if failures:
        print('[基线] 拒绝写入: 有 %d 个场景失败' % len(failures))
        for f in failures:
            print('  失败:', f)
        return 1
    old, _err = _baseline_load(bp)
    if old is not None and not force:
        old_n = int(old.get('scene_count') or 0)
        if len(rows) < old_n:
            print('[基线] 拒绝覆盖: 本次 %d 场景 < 已有 %d 场景（防误删锚点；确需如此请加 --force）'
                  % (len(rows), old_n))
            return 1
    payload = {
        'schema': SCHEMA,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'resolution': [W, H],
        'scene_count': len(rows),
        'reference_dir': os.path.basename(rd),
        'gate': gate,
        'scenes': rows,
    }
    os.makedirs(os.path.dirname(bp), exist_ok=True)
    tmpw = bp + '.tmp'
    with open(tmpw, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmpw, bp)
    if force:
        keep = set()
        for n in rows:
            keep.add(os.path.basename(_ref_path(n, False, rd)))
            keep.add(os.path.basename(_ref_path(n, True, rd)))
        for p in glob.glob(os.path.join(rd, '*.png')):
            if os.path.basename(p) not in keep:
                try:
                    os.remove(p)
                except OSError:
                    pass
    print('[基线] 已写入 %s（%d 场景, 参考图目录 %s）' % (bp, len(rows), rd))
    return 0
def _capture(fn):
    """跑 fn 并捕获 stdout，同时把其内部 FAIL 从全局计数里隔离出去。"""
    import contextlib
    import io
    saved = list(_fails)
    _fails.clear()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = fn()
    finally:
        _fails.clear()
        _fails.extend(saved)
    return buf.getvalue(), rc


def _patch_perspective(factor):
    """把所有模块里**已绑定**的 mat4_perspective 一起换掉（模拟两端同时回归）。

    注意: 必须先把渲染模块 import 进来再打补丁 —— 否则它们在补丁窗口内才 import，
    会把补丁函数绑进模块全局并在还原后继续泄漏（实测导致后续用例假红）。
    """
    import editor  # noqa: F401  （渲染链入口，必须先加载）
    import loom_render  # noqa: F401
    import scene_driver  # noqa: F401
    import vk_renderer  # noqa: F401
    import matlib
    orig = matlib.mat4_perspective

    def patched(np_mod, fov, aspect, near, far, *a, **k):
        return orig(np_mod, fov * factor, aspect, near, far, *a, **k)

    for mod in list(sys.modules.values()):
        try:
            if getattr(mod, 'mat4_perspective', None) is orig:
                mod.mat4_perspective = patched
        except Exception:
            pass
    return orig, patched


def _unpatch_perspective(orig, patched):
    """按**函数对象身份**还原（不依赖 touched 列表，防补丁窗口内新 import 的泄漏）。"""
    for mod in list(sys.modules.values()):
        try:
            if getattr(mod, 'mat4_perspective', None) is patched:
                mod.mat4_perspective = orig
        except Exception:
            pass


def self_test():
    """反例自检: 闸门必须能对 ①共享回归 ②缺基线 ③VK 坏 ④update 有 FAIL 变红。"""
    print('=== 自检: 闸门反向验证 ===')
    gate = _gate()
    scene_one = os.path.join(SCENES_DIR, 'ab_sky.json')
    tmp = tempfile.mkdtemp(prefix='loom_ab_self_')
    try:
        # 1) 两端同时 fov+15%: 端间差异会变小, 但两边都偏离参考 -> 必须红
        orig, patched = _patch_perspective(1.15)
        try:
            out, rc = _capture(lambda: run_gate(
                [scene_one], BASELINE_PATH, REF_DIR, gate))
        finally:
            _unpatch_perspective(orig, patched)
        check('自检1 共享回归（两端 fov+15%）-> 闸门红',
              rc == 1 and '共享回归' in out, 'rc=%r' % (rc,))
        # 2) 基线缺失 -> 红（不是 PASS）
        miss = os.path.join(tmp, 'nope.json')
        out, rc = _capture(lambda: run_gate(
            [scene_one], miss, REF_DIR, gate))
        check('自检2 基线缺失 -> 闸门红',
              rc == 1 and '基线文件缺失' in out, 'rc=%r' % (rc,))
        # 3) VK 坏（模拟 wgpu API 改名）: 默认红; 显式白名单才 SKIP
        saved_dev = globals()['_vk_device']

        def _boom_vk():
            raise RuntimeError('模拟: wgpu 升级后 API 改名')

        globals()['_vk_device'] = _boom_vk
        try:
            os.environ.pop('LOOM_AB_ALLOW_NO_VK', None)
            out, rc = _capture(lambda: run_gate(
                [scene_one], BASELINE_PATH, REF_DIR, gate, allow_no_vk=False))
            check('自检3 VK 坏 -> 默认闸门红（不再静默 SKIP）',
                  rc == 1 and 'VK 渲染' in out, 'rc=%r' % (rc,))
            out, rc = _capture(lambda: run_gate(
                [scene_one], BASELINE_PATH, REF_DIR, gate, allow_no_vk=True))
            check('自检3b 显式允许后才 SKIP 且仍比 GL/参考',
                  rc == 0 and '已显式允许' in out, 'rc=%r' % (rc,))
        finally:
            globals()['_vk_device'] = saved_dev
        # 4) --update-baseline 有 FAIL -> 不写、rc=1
        saved_gl = globals()['render_gl']

        def _boom_gl(*a, **k):
            raise RuntimeError('模拟: GL 渲染失败')

        globals()['render_gl'] = _boom_gl
        try:
            bl = os.path.join(tmp, 'bl.json')
            rd = os.path.join(tmp, 'ref')
            rc = run_update([scene_one], bl, rd, gate)
            check('自检4 --update-baseline 有 FAIL -> 不写且 rc=1',
                  rc == 1 and not os.path.isfile(bl), (rc, os.path.isfile(bl)))
        finally:
            globals()['render_gl'] = saved_gl
        # 5) 空场景集 -> rc=1
        out, rc = _capture(lambda: run_gate([], BASELINE_PATH, REF_DIR, gate))
        check('自检5 空场景集 -> rc=1', rc == 1, 'rc=%r' % (rc,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('--- 自检失败 %d 项 ---' % len(_fails))
    return 0 if not _fails else 1


def main(argv):
    global REF_DIR, BASELINE_PATH
    files = _scene_files()
    # 口径自动跟随开关（人类裁决 2B2）：
    #   · LOOM_POST=1（默认）-> 新参考图/新基线；
    #   · LOOM_POST=0        -> 旧参考图/旧基线（回退证明）；
    #   · --update-baseline 默认重建**旧**那套，加 --next 才重建新那套（旧文件不被覆盖）。
    from loom_post import post_enabled
    use_next = ('--next' in argv) or \
               ('--update-baseline' not in argv and post_enabled())
    if '--legacy' in argv:
        use_next = False
    if use_next:
        REF_DIR = REF_DIR_NEXT
        BASELINE_PATH = BASELINE_NEXT
    if '--self-test' in argv:
        return self_test()
    update = '--update-baseline' in argv
    if not files:
        print('错误: 场景集为空（tests/ab_scenes 无 ab_*.json, 或 LOOM_AB_SCENES 解析为空）')
        return 1
    if update:
        return run_update(files, BASELINE_PATH, REF_DIR, _gate(),
                          force=('--force' in argv))
    return run_gate(files, BASELINE_PATH, REF_DIR, _gate(), legacy=(not use_next))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))



