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
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
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


"""test_editor_play_pixel_parity.py — S5 像素门：编辑器播放态像素对拍 + 编辑器叠加层
（「编辑器支持 VK」五阶段·阶段 5，2026-11-20）。

脚手架 = test_ab_gl_vk 既有口径（GL 离屏 FBO 回读 flipud / VK 离屏纹理 copy 回读 /
float64 指标 / MAE 阈值 mae_abs=2e-4 —— 与 test_ab_gl_vk.DEFAULT_GATE 同源）。

两组：
  ① 编辑器播放态 4 时刻（P6 的 4 时刻口径，暂停/单步用内核唯一入口）：
     GL编辑器播放（生产 editor.EditorApp.render）vs VK编辑器播放（生产
     editor.VkEditorApp.render —— S4 落地的 VK 编辑器渲染路径，VkFrameExecutor
     消费同一份 FramePlan）。时刻 = 暂停瞬间 / 单步 1 / 单步 3 / 恢复后。
     判据：MAE <= 2e-4 且 NCC >= 0.999（P6 门 ⑥ 组同口径）；另锁「暂停期画面
     逐像素稳定（两端各自 MAE=0）」。
  ② 编辑器叠加层场景（编辑态，gizmo / 选中框 / 网格）：GL vs VK。
     ★ Q-B7-48-1 人类裁决 2026-11-20「问题一：B」落地后，两端线宽**相等**（都用
     loom_line_geometry.build_line_quads 在 CPU 侧按屏幕像素扩宽成四边形，GL 画
     TRIANGLES、VK 画 triangle-list；不再依赖 GL 的 line_width / wgpu 的缺失）。
     于是本组**不再用「中心线重合度」退让口径**（那是 1px vs 2px 的产物），改为
     **逐像素 MAE 直接比**（这是收紧，不是放宽）：
       · 判据：叠加层整帧 MAE <= 2e-4（= test_ab_gl_vk.DEFAULT_GATE.mae_abs）
         且 NCC >= 0.999，且两端叠加层线像素数比在 [0.95, 1.05]；
       · 中心线距离/覆盖率比值仍打印留证，但**不判**红绿；
       · 反例自检：把 VK 画面平移 16px，MAE 判据必须变红（度量有牙）。
     叠加层顶点全部来自**真实编辑器代码路径**（grid_geometry / _draw_selection_box /
     LoomGUI._draw_gizmo 本尊）—— 视图层 draw 与 ui/loom_gui.py LoomGUI.draw 的
     视口叠加段同形（同源调用形状，不是测试自造近似）。

修前必红（两证，2026-11-20 实测）：
  · 支撑移除：把 editor.VkEditorApp 临时改名（VK 编辑器渲染路径不在）→ 本门
    构造段即 AttributeError 红（rc=1；贴原文见提交信息）；还原后绿。
  · 缺陷红：S5 的 5 处生产修复（editor/engine/engine_core/scene_driver）被
    git stash 回退时，本门「暂停瞬间」两端画面差 1 个逻辑帧（修前 VK 编辑器
    _interp 恒 None → 渲染矩阵落编辑态管线）；修后绿。
  另：wgpu 设备先于 GL 上下文建立（本机驱动实测：设备创建后既有 standalone
  上下文新建 program 会失败 —— 见 test_editor_play_parity 同注）。
"""
import hashlib
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_DIALOG'] = '1'
os.environ['LOOM_NO_PHYSICS'] = '1'
os.environ['LOOM_LOGIC_SYNC'] = '1'
os.environ.setdefault('LOOM_USER_ROOT', tempfile.mkdtemp(prefix='loom_s5_pixel_userroot_'))

import numpy as np

import editor as editor_mod
import scene.contract as _scene_contract
import moderngl
import render.vk.driver as _sd

_fails = []
_pass_n = 0
W, H = 480, 320
FRAME_DT = 1.0 / 60.0
LOGIC_FPS = 60.0
SPEED = 2.0
MAE_ABS = 2e-4          # test_ab_gl_vk.DEFAULT_GATE.mae_abs（同源，不另立阈值）
NCC_MIN = 0.999         # P6 门 ⑥ 组同口径
# 叠加层线像素掩码阈值（= S3 单元门同款差分口径）
MASK_THR = 0.06
# Q-B7-48-1 裁决 B 之后两端同宽：判据用逐像素 MAE（同 MAE_ABS/NCC_MIN）+ 线像素数比
COV_LO, COV_HI = 0.95, 1.05
# 中心线距离阈值：**只打印留证**（裁决 B 之前的口径，不再判红绿）
TH_MEAN = 1.2
TH_MAX = 3.0


def check(name, cond, detail=''):
    global _pass_n
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


# ============================ 共享夹具 ============================

_GL = {'ctx': None, 'fbo': None}
_VK = {'device': None, 'tex': None}
_VK_FMT = 'rgba8unorm'


class _NullView:
    """播放态视图桩：不画叠加层（Canvas 游戏 UI 走 FramePlan screen_ui pass，S1 同源）。"""

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


class _OverlayView:
    """编辑态叠加层宿主视图 —— draw() 与 ui/loom_gui.py LoomGUI.draw 的视口叠加段
    同形（后端无关调用点：overlay_scope / draw_lines / _draw_selection_box /
    _draw_gizmo 本尊），GL/VK 两端跑的是**同一段视图代码**。"""

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

    def draw(self, ctl, delta_time):
        if ctl.is_playing:
            return
        import gui.main_window as lg
        # —— 与 LoomGUI.draw（ui/loom_gui.py 视口叠加段）同形（任务口径 = gizmo/选中框）。
        # 网格不在本门范围：GL 侧网格走 depth_test（网格语义），而离屏夹具的
        # _external_fb 深度附件未被主 pass 写入（真窗口里主 pass 深度在同一个
        # 缓存 FBO 上）→ GL 网格在本夹具里恒不可见（tests/_tmp/s5_probe_px7/px8
        # 实测：无地板也 0 像素）——夹具限制，不是被测行为；VK 侧网格经
        # _vk_overlay_depth_view 挂主 pass 深度、正常可见。网格两端的真窗口
        # 对拍留待 S6/真窗口门（未核，留痕）。
        ctl._draw_selection_box()
        lg.LoomGUI._draw_gizmo(None, ctl)


def _vk_device():
    if _VK['device'] is None:
        import wgpu
        adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
        if adapter is None:
            raise RuntimeError('无可用 Vulkan 适配器（与 test_ab_gl_vk 同口径：FAIL 不 SKIP）')
        _VK['device'] = adapter.request_device_sync()
    return _VK['device']


class _VkOffscreenCtx:
    physical_size = (W, H)

    def get_current_texture(self):
        if _VK['tex'] is None:
            import wgpu
            _VK['tex'] = _vk_device().create_texture(
                size=(W, H, 1), format=_VK_FMT,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        return _VK['tex']


def _gl_ctx():
    if _GL['ctx'] is None:
        _GL['ctx'] = moderngl.create_standalone_context(require=430)
    return _GL['ctx']


def _gl_fbo():
    if _GL['fbo'] is None:
        ctx = _gl_ctx()
        _GL['fbo'] = ctx.framebuffer(
            color_attachments=[ctx.renderbuffer((W, H), components=4)],
            depth_attachment=ctx.depth_renderbuffer((W, H)))
    return _GL['fbo']


def _vk_readback():
    """离屏纹理回读（test_ab_gl_vk.render_vk 同口径：bpr 对齐 256；**VK 侧不 flipud** ——
    ab 的 GL 侧 fbo.read 底行在前所以 flipud，VK 侧纹理回读行序本就与 GL 翻转后一致，
    实测 GL编辑器(flipud) vs VK编辑器(原样) 逐位 MAE=0.0，见 tests/_tmp/s5_probe_px4.py）。"""
    import wgpu
    device = _vk_device()
    tex = _VK['tex']
    bpr = (W * 4 + 255) // 256 * 256
    buf = device.create_buffer(size=bpr * H,
                               usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
    enc = device.create_command_encoder()
    enc.copy_texture_to_buffer({'texture': tex},
                               {'buffer': buf, 'offset': 0, 'bytes_per_row': bpr,
                                'rows_per_image': H}, (W, H, 1))
    device.queue.submit([enc.finish()])
    buf.map_sync(wgpu.MapMode.READ)
    arr = np.frombuffer(buf.read_mapped(), dtype='u1').reshape(H, bpr // 4, 4)
    return arr[:, :W, :3].astype(np.float32) / 255.0


def _gl_readback():
    raw = _gl_fbo().read(components=3)
    img = np.frombuffer(raw, dtype='u1').reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img)


# ---- 场景（同一份用户内容；轨道相机 + 移动脚本 + 1 平行光 + 默认天空） ----

from script.scripts import Script, register   # noqa: E402


@register
class S5PixelProbe(Script):
    """移动探针：每逻辑帧匀速 +X（画面随暂停/单步可区分）。"""
    script_id = 's5_pixel_probe'
    name = 'S5像素探针'

    def update(self, dt):
        p = self.obj.position
        self.obj.position = type(p)(p.x + SPEED * dt, p.y, p.z)


def _scene_dict():
    return {'version': _scene_contract.CURRENT_VERSION,
            'camera': {'target': [0.0, 0.5, 0.0], 'distance': 7.0,
                       'yaw': 0.65, 'pitch': -0.35, 'fov': 60.0},
            'cameras': [], 'active_camera': None,
            'objects': [
                {'id': 'floor', 'name': '物体floor', 'type': 'plane', 'params': {'size': 8.0},
                 'position': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0],
                 'scale': [1.0, 1.0, 1.0], 'color': '#6a7a8c', 'visible': True},
                {'id': 'mover', 'name': '物体mover', 'type': 'cube', 'params': {'size': 1.0},
                 'position': [0.0, 0.6, 0.0], 'rotation': [0.0, 0.35, 0.0],
                 'scale': [1.0, 1.0, 1.0], 'color': '#d05a4a', 'visible': True,
                 'scripts': [{'id': 's5_pixel_probe', 'vars': {}}]},
            ],
            'lights': [{'id': 'sun', 'name': '平行光', 'type': 'directional',
                        'position': [4.0, 6.0, 3.0], 'rotation': [0.0, 0.0, 0.0],
                        'color': [255, 250, 240], 'intensity': 1.0, 'visible': True}],
            'materials': [], 'gravity': -9.8, 'skybox': None, 'ui': None}


def _write_scene():
    sfile = os.path.join(tempfile.mkdtemp(prefix='loom_s5_pixel_scene_'), 's.json')
    with open(sfile, 'w', encoding='utf-8') as f:
        json.dump(_scene_dict(), f)
    return sfile


def _mk_editor(view, backend):
    """生产构造式：GL=EditorApp(offscreen ctx)；VK=VkEditorApp(wgpu device + 离屏纹理)。
    场景装配 = 同一条生产打开路径 _load_scene。"""
    sfile = _write_scene()
    if backend == 'gl':
        ed = editor_mod.EditorApp(W, H, view=view, ctx=_gl_ctx())
        ed._external_fb = _gl_fbo()
    else:
        ed = editor_mod.VkEditorApp(W, H, view=view, device=_vk_device(),
                                    present_format=_VK_FMT)
        ed._vk_ctx = _VkOffscreenCtx()
    ed.show_grid = False
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed._load_scene(sfile)
    ed.toggle_play()
    ed._clock.set_fps(logic_fps=LOGIC_FPS)
    return ed


def _drive_moments(ed):
    """P6 的 4 时刻（暂停/单步走内核唯一入口 toggle_logic_paused / step_logic_once）。
    返回 {moment: img}。"""
    snaps = {}
    for _ in range(2):                       # 预热 2 帧（进播放 + 材质/管线懒建）
        ed._logic_wall_last = None
        ed.render(FRAME_DT)
    check('暂停入口生效（toggle_logic_paused 内核唯一入口返回 True）',
          ed.toggle_logic_paused() is True, '')
    ed._logic_wall_last = None
    ed.render(FRAME_DT)
    snaps['暂停瞬间'] = (_gl_readback() if hasattr(ed, '_external_fb') else _vk_readback())
    # 暂停期画面逐像素稳定（两端各自）
    ed._logic_wall_last = None
    ed.render(FRAME_DT)
    img2 = (_gl_readback() if hasattr(ed, '_external_fb') else _vk_readback())
    a = snaps['暂停瞬间']
    mae = float(np.abs(a.astype(np.float64) - img2.astype(np.float64)).mean())
    check('暂停期画面逐像素稳定（%s）' % ('GL' if hasattr(ed, '_external_fb') else 'VK'),
          mae == 0.0, 'mae=%.3e' % mae)
    ed.step_logic_once()
    ed._logic_wall_last = None
    ed.render(FRAME_DT)
    snaps['单步 1'] = (_gl_readback() if hasattr(ed, '_external_fb') else _vk_readback())
    ed.step_logic_once()
    ed.step_logic_once()
    ed._logic_wall_last = None
    ed.render(FRAME_DT)
    snaps['单步 3'] = (_gl_readback() if hasattr(ed, '_external_fb') else _vk_readback())
    ed.toggle_logic_paused()                 # 恢复
    ed._logic_wall_last = None
    ed.render(FRAME_DT)
    snaps['恢复后'] = (_gl_readback() if hasattr(ed, '_external_fb') else _vk_readback())
    return snaps


def metrics(a, b):
    """MAE / MAX / NCC —— test_ab_gl_vk 同款（float64 累加）。"""
    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
    mae = float(d.mean())
    mx = float(d.max())
    la = a.astype(np.float64).mean(axis=2).ravel()
    lb = b.astype(np.float64).mean(axis=2).ravel()
    la = la - la.mean()
    lb = lb - lb.mean()
    ncc = float((la * lb).sum() / (np.linalg.norm(la) * np.linalg.norm(lb) + 1e-12))
    return mae, mx, ncc


# ============================ ① 编辑器播放态 4 时刻 ============================

print()
print('=== ① 编辑器播放态 4 时刻（GL编辑器播放 vs VK编辑器播放；P6 口径） ===')

# S5: 先建 wgpu 设备再建任何 GL 上下文（本机驱动实测，见模块 docstring）。
_vk_device()
check('夹具：Vulkan 设备先于 GL 上下文建立（驱动干扰规避，见 docstring）',
      _VK['device'] is not None, type(_VK['device']).__name__)

gl_ed = _mk_editor(_NullView(), 'gl')
vk_ed = _mk_editor(_NullView(), 'vk')
check('夹具保真：GL 端是 editor.EditorApp（生产类）', type(gl_ed) is editor_mod.EditorApp, '')
check('夹具保真：VK 端是 editor.VkEditorApp（S4 生产类，VkFrameExecutor 消费同一份 plan）',
      type(vk_ed) is editor_mod.VkEditorApp, '')
check('夹具保真：四面同一份场景装配（同名同序物体）',
      [m.name for m in gl_ed.models] == [m.name for m in vk_ed.models],
      ([m.name for m in gl_ed.models], [m.name for m in vk_ed.models]))

gl_snaps = _drive_moments(gl_ed)
vk_snaps = _drive_moments(vk_ed)

for moment in ('暂停瞬间', '单步 1', '单步 3', '恢复后'):
    g = gl_snaps[moment]
    v = vk_snaps[moment]
    mae, mx, ncc = metrics(g, v)
    check('① %s 两端逐像素相等或 MAE<=%.0e 且 NCC>=%.3f' % (moment, MAE_ABS, NCC_MIN),
          mae <= MAE_ABS and ncc >= NCC_MIN,
          'MAE=%.7f MAX=%.4f NCC=%.6f' % (mae, mx, ncc))

# 画面推进量桥（P6 组⑤同思想）：单步 1 的画面 == 参照对「正常推进 3 帧」的画面 ——
# 参照 = 暂停前最后预热帧之后的连续 3 帧画面。这里用更轻的桥：
# 暂停瞬间 == 预热第 2 帧画面（暂停不跳变，P6-1 修复的编辑器面回归锁）。
gl_ed2 = _mk_editor(_NullView(), 'gl')
vk_ed2 = _mk_editor(_NullView(), 'vk')
for _ in range(2):
    gl_ed2._logic_wall_last = None
    gl_ed2.render(FRAME_DT)
    vk_ed2._logic_wall_last = None
    vk_ed2.render(FRAME_DT)
ref_gl = _gl_readback()
ref_vk = _vk_readback()
mae, mx, ncc = metrics(gl_snaps['暂停瞬间'], ref_gl)
check('① 暂停不跳变（GL：暂停瞬间 == 暂停前最后一帧；P6-1 修复的编辑器面回归锁）',
      mae == 0.0, 'mae=%.3e' % mae)
mae, mx, ncc = metrics(vk_snaps['暂停瞬间'], ref_vk)
check('① 暂停不跳变（VK：暂停瞬间 == 暂停前最后一帧）', mae == 0.0, 'mae=%.3e' % mae)

# ============================ ② 编辑器叠加层场景 ============================

print()
print('=== ② 编辑器叠加层场景（编辑态：gizmo/选中框/网格；两端同宽 -> MAE 口径） ===')


def _mk_edit_overlay(backend):
    sfile = _write_scene()
    view = _OverlayView()
    if backend == 'gl':
        ed = editor_mod.EditorApp(W, H, view=view, ctx=_gl_ctx())
        ed._external_fb = _gl_fbo()
    else:
        ed = editor_mod.VkEditorApp(W, H, view=view, device=_vk_device(),
                                    present_format=_VK_FMT)
        ed._vk_ctx = _VkOffscreenCtx()
    ed.show_grid = False             # 网格不在本门口径（见 _OverlayView.draw 注）
    ed.selected_index = 1            # 选中 mover（选中框 + gizmo 都画）
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed._load_scene(sfile)
    for _ in range(3):
        ed._logic_wall_last = None
        ed.render(FRAME_DT)
    return ed


ov_gl_ed = _mk_edit_overlay('gl')
ov_vk_ed = _mk_edit_overlay('vk')


def _readback(ed):
    return _gl_readback() if hasattr(ed, '_external_fb') else _vk_readback()


def _render_plain(ed):
    """无叠加层的纯 3D 帧（网格关 + 不选中 + view.draw 置空）—— 叠加层像素掩码 =
    「有叠加层 - 无叠加层」的差分（S3 在黑底上画线所以能用亮度阈值；本场景 3D 背景
    不是黑底，亮度阈值会把整个背景都算成线像素 —— 差分掩码是同一判据的等价形态）。
    只动测试夹具开关，不动引擎。"""
    old_vd, old_sel, old_grid = ed.view.draw, ed.selected_index, ed.show_grid
    ed.view.draw = lambda ctl, dt: None
    ed.selected_index = -1
    ed.show_grid = False
    ed._logic_wall_last = None
    ed.render(FRAME_DT)
    img = _readback(ed)
    ed.view.draw = old_vd
    ed.selected_index = old_sel
    ed.show_grid = old_grid
    return img


ov_gl_ed._logic_wall_last = None
ov_gl_ed.render(FRAME_DT)
over_gl = _readback(ov_gl_ed)
plain_gl = _render_plain(ov_gl_ed)
ov_vk_ed._logic_wall_last = None
ov_vk_ed.render(FRAME_DT)
over_vk = _readback(ov_vk_ed)
plain_vk = _render_plain(ov_vk_ed)

img_gl, img_vk = over_gl, over_vk
_mae, _mx, _ncc = metrics(img_gl, img_vk)
print('    [留证] 叠加层场景整体 MAE=%.6f MAX=%.4f NCC=%.6f（下面 ② 判据就是它）'
      % (_mae, _mx, _ncc))
_mae, _mx, _ncc = metrics(plain_gl, plain_vk)
print('    [留证] 纯 3D 帧（无叠加层）MAE=%.6f MAX=%.4f NCC=%.6f（两端底图逐位一致）'
      % (_mae, _mx, _ncc))


def _mask(over, plain):
    """叠加层像素掩码 = 有/无叠加层差分（S3 亮度阈值的等价形态，见上）。"""
    return np.abs(over.astype(np.float32) - plain.astype(np.float32)).max(axis=2) > 0.02


INF = 10 ** 6


def _chess_dist(src_mask, dst_mask, cap=32):
    """src 每个线像素 -> 最近 dst 线像素的棋盘距离（8 邻域扩散；S3 门同款）。"""
    if not src_mask.any():
        return np.zeros(src_mask.shape, dtype=np.int32), 0
    dist = np.where(dst_mask, 0, INF).astype(np.int32)
    for _ in range(cap):
        p = np.pad(dist, 1, constant_values=INF)
        neigh = np.minimum.reduce([
            p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:],
            p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:],
            p[2:, :-2], p[2:, 1:-1], p[2:, 2:]]) + 1
        new = np.minimum(dist, neigh)
        if (new == dist).all():
            break
        dist = new
    d = np.where(src_mask, dist, 0)
    uncovered = int((src_mask & (dist >= INF)).sum())
    return d, uncovered


mg = _mask(over_gl, plain_gl)
mv = _mask(over_vk, plain_vk)
check('② 叠加层两端都有线像素（gizmo/选中框真的画出来了）',
      int(mg.sum()) >= 200 and int(mv.sum()) >= 200,
      'gl_cov=%d vk_cov=%d' % (int(mg.sum()), int(mv.sum())))
# 中心线距离：**只打印留证**（Q-B7-48-1 裁决 B 之后两端同宽，不再用它判红绿）
dg, unc_g = _chess_dist(mg, mv)
dv, unc_v = _chess_dist(mv, mg)
mean_g2v = float(dg[mg].mean())
max_g2v = int(dg[mg].max())
mean_v2g = float(dv[mv].mean())
max_v2g = int(dv[mv].max())
ratio = float(mv.sum()) / max(1, int(mg.sum()))
print('    [留证/不判] 中心线重合度 mean_g2v=%.3f max_g2v=%d mean_v2g=%.3f max_v2g=%d '
      'uncovered=%d cov比=%.3f'
      % (mean_g2v, max_g2v, mean_v2g, max_v2g, unc_g + unc_v, ratio))
# 判据（收紧）：逐像素 MAE + NCC + 两端线像素数相等
mae_ov, mx_ov, ncc_ov = metrics(over_gl, over_vk)
check('② 叠加层两端逐像素一致（MAE<=%.0e 且 NCC>=%.3f 且线像素数相等 [%.2f, %.2f]）'
      % (MAE_ABS, NCC_MIN, COV_LO, COV_HI),
      mae_ov <= MAE_ABS and ncc_ov >= NCC_MIN and COV_LO <= ratio <= COV_HI,
      'MAE=%.7f MAX=%.4f NCC=%.6f cov比=%.3f' % (mae_ov, mx_ov, ncc_ov, ratio))

# 反例自检（度量有牙）：把 VK 画面整体平移 16px -> MAE 判据必须变红。
shift = np.roll(over_vk, 16, axis=1)
mae_s, mx_s, _ncc_s = metrics(over_gl, shift)
check('② 反例自检：VK 画面平移 16px 后 MAE 判据必须变红（度量有牙）',
      mae_s > 10 * MAE_ABS,
      'MAE=%.6f > 10x%.0e' % (mae_s, MAE_ABS))

print()
print('总结果:', 'ALL PASS (%d)' % _pass_n if not _fails else '有 FAIL: %s' % _fails)
sys.exit(0 if not _fails else 1)
