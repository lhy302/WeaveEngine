# -*- coding: utf-8 -*-
"""test_vk_overlay_primitives.py — S3 门：VK 绘制原语补齐（「编辑器支持 VK」五阶段·阶段 3）。

四件事的门面（Q-B7-47-1 路线 S3）：
  ① VkLineBatch（draw_lines 的 VK 实现：line-list 管线 + 动态 VBO + u_view_proj + 深度开关）；
  ② overlay_scope(framebuffer, enable_only, enable) 的 VK 实现（与 GL RenderMixin 同签名）；
  ③ VkFrameExecutor 消费 loom_pass.frame_plan() 的**同一份** plan（与 GLFrameExecutor 同源）；
  ④ 同一组顶点/颜色数组，GL 离屏渲染 vs VK 离屏渲染的像素门（修前必红：loom_pass_vk 不存在）。

★ 线宽口径（Q-B7-48-1 人类裁决 2026-11-20「问题一：B」= 两端统一改成
  「用四边形模拟粗线」）：GL 的 ctx.line_width 与 wgpu 的「无 line_width 字段」
  **都不再被依赖** —— 线段在 CPU 侧由 loom_line_geometry.build_line_quads 按
  **屏幕空间像素宽度**膨胀成 2 个三角形，两端只负责画三角形（GL TRIANGLES /
  VK triangle-list）。于是两端线宽像素数**相等**，本门因此**改用逐像素 MAE 直接
  比**（修前是「中心线重合度」口径，那是 1px vs 2px 的退让；裁决 B 之后没有
  退让的理由，属**收紧**）：
    · B8a：同一线宽参数下，单条水平线的「线宽像素数」两端相等；
    · B8b：真实夹具（网格/选中框/gizmo）两端线像素数比在 [0.95, 1.05]；
    · B/B5/B6/B7：MAE <= 2e-4（= test_ab_gl_vk.DEFAULT_GATE.mae_abs，同源阈值）
      且线像素数相等 —— 中心线距离/覆盖率比值只打印留证，不再当判据。
  反例自检（B5）：把 VK 画面整体平移 16px，MAE 判据必须变红 —— 证明度量真能抓错位。

同源证据：
  · 夹具顶点/颜色数组全部来自**真实编辑器代码路径**（grid_geometry /
    _draw_selection_box / LoomGUI._draw_gizmo 捕获），不是测试自造的近似；
  · GL 侧渲染走 engine.draw_lines 本尊，VK 侧走 VkLineBatch 本尊；
  · A7 断言 VkFrameExecutor.execute 后 renderer._frame_plan **is** 传入的 plan 对象
    （frame_plan 按参数缓存，同 flags 必返回同一对象 —— 「消费同一份 plan」的硬证据）。
"""
import atexit
import inspect
import os
import sys


class _FailGateStream:
    """与 test_vk_p1_stage 同款：出现 FAIL 行就把退出码改成 1。"""

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
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import numpy as np

W, H = 480, 320
# Q-B7-48-1 裁决 B 之后两端同宽 -> 判据 = 逐像素 MAE（与 test_ab_gl_vk 同源阈值
# DEFAULT_GATE.mae_abs=2e-4），并锁「两端线像素数相等」（覆盖比 [0.95, 1.05]）。
# 旧的中心线距离阈值只保留**打印留证**用，不再参与判红绿。
MAE_ABS = float(os.environ.get('LOOM_VKPRIM_MAE_ABS', '2e-4'))
COV_LO, COV_HI = 0.95, 1.05
TH_MEAN = float(os.environ.get('LOOM_VKPRIM_TH_MEAN', '1.2'))   # 仅打印留证
TH_MAX = float(os.environ.get('LOOM_VKPRIM_TH_MAX', '3.0'))     # 仅打印留证
MASK_THR = 0.06
_fails = []


def check(name, cond, detail=""):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


# ============================ 共享夹具 ============================


class _NullView:
    """空视图：与 test_ab_gl_vk 同款，不画叠加层。"""

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


def _scene_dict():
    """最小场景：一个立方体（供选中框/gizmo 用真实 AABB），无灯无天空。"""
    return {
        'version': 10,
        'camera': {'target': [0, 0.5, 0], 'distance': 8.0, 'yaw': 0.65, 'pitch': -0.35},
        'objects': [{'id': 'cube1', 'type': 'cube', 'params': {'size': 1.2},
                     'position': [0, 0.6, 0], 'rotation': [0, 0.4, 0],
                     'scale': [1, 1, 1], 'color': '#d05a4a', 'visible': True}],
        'lights': [],
    }


_ED = {}


def _editor():
    """真 EditorApp 离屏装配（与 test_ab_gl_vk.render_gl 同一条路），渲染 3 帧
    后返回 (ctx, fbo, ed, vp)—— vp = 生产 VP（ed._vp，gizmo/拾取同源）。"""
    if _ED.get('ed') is not None:
        return _ED['ctx'], _ED['fbo'], _ED['ed'], _ED['vp']
    import moderngl
    import editor as editor_mod
    import sceneio
    ctx = moderngl.create_standalone_context(require=430)
    rb = ctx.renderbuffer((W, H), components=4)
    drb = ctx.depth_renderbuffer((W, H))
    fbo = ctx.framebuffer(color_attachments=[rb], depth_attachment=drb)
    ed = editor_mod.EditorApp(W, H, view=_NullView(), ctx=ctx)
    ed._external_fb = fbo
    ed.show_grid = False
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    if hasattr(ed, "clear_scene"):
        ed.clear_scene()
    sceneio.scene_from_dict(ed, _scene_dict())
    ed.camera_target = (0, 0.5, 0)
    ed.camera_distance = 8.0
    ed.camera_yaw = 0.65
    ed.camera_pitch = -0.35
    ed.orbit_mode = True
    ed.apply_orbit_camera()
    for _ in range(3):
        ed.render(1 / 60.0)
    vp = np.asarray(ed._vp, dtype="f4")
    _ED.update(ctx=ctx, fbo=fbo, ed=ed, vp=vp)
    return ctx, fbo, ed, vp


def _capture_fixtures(ed):
    """从**真实编辑器代码路径**提取叠加层顶点/颜色数组（不是测试自造）。
    网格 = grid_geometry() 本尊；选中框 = _draw_selection_box 内部那次 draw_lines；
    gizmo = ui.loom_gui.LoomGUI._draw_gizmo（真实视图层代码）内部的 draw_lines。"""
    out = {}
    out['grid'] = ed.grid_geometry()
    cap = []
    orig = ed.draw_lines

    def _rec(verts, colors, *a, **k):
        cap.append((np.asarray(verts, dtype="f4").copy(),
                    np.asarray(colors, dtype="f4").copy()))

    ed.draw_lines = _rec
    try:
        ed.selected_index = 0
        ed._draw_selection_box()
        out['selection'] = cap.pop(0) if cap else None
        import gui.main_window as lg
        ed.gizmo_mode = 'translate'
        lg.LoomGUI._draw_gizmo(None, ed)   # (self 未用; ctl=ed 走真实视图层代码)
        out['gizmo_translate'] = cap.pop(0) if cap else None
        ed.gizmo_mode = 'rotate'
        lg.LoomGUI._draw_gizmo(None, ed)   # (self 未用; ctl=ed 走真实视图层代码)
        out['gizmo_rotate'] = cap.pop(0) if cap else None
    finally:
        ed.draw_lines = orig
    return out


# ---------------- GL 渲染（engine.draw_lines 本尊 + 调用方状态） ----------------


def _gl_render_lines(ctx, fbo, ed, verts, cols, vp, depth_on, blend=False,
                     depth_clear=1.0, width=2.0):
    import moderngl
    fbo.use()
    ctx.clear(0.0, 0.0, 0.0, 1.0, depth=float(depth_clear))
    if depth_on:
        ctx.enable(moderngl.DEPTH_TEST)
    else:
        ctx.disable(moderngl.DEPTH_TEST)
    if blend:
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
    try:
        ed.draw_lines(verts, cols, view_proj=np.asarray(vp, dtype="f4"),
                      line_width=float(width))
    finally:
        if blend:
            ctx.disable(moderngl.BLEND)
    raw = fbo.read(components=3)
    img = np.frombuffer(raw, dtype="u1").reshape(H, W, 3).astype(np.float32) / 255.0
    return np.flipud(img)   # 与 test_ab_gl_vk 同一口径：读回底行在前，翻成顶行在前


# ---------------- VK 设备 / 回读 ----------------

_VK = {}


def _vk_device():
    if _VK.get("device") is None:
        import wgpu
        adapter = wgpu.gpu.request_adapter_sync(power_preference='high-performance')
        if adapter is None:
            raise RuntimeError('无可用 Vulkan 适配器')
        _VK["device"] = adapter.request_device_sync()
    return _VK["device"]


def _vk_read(device, tex):
    import wgpu
    bpr = (W * 4 + 255) // 256 * 256
    buf = device.create_buffer(size=bpr * H, usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
    enc = device.create_command_encoder()
    enc.copy_texture_to_buffer({'texture': tex},
                               {'buffer': buf, 'offset': 0, 'bytes_per_row': bpr,
                                'rows_per_image': H}, (W, H, 1))
    device.queue.submit([enc.finish()])
    buf.map_sync(wgpu.MapMode.READ)
    arr = np.frombuffer(buf.read_mapped(), dtype="u1").reshape(H, bpr // 4, 4)
    img = arr[:, :W, :3].astype(np.float32) / 255.0
    try:
        tex.destroy()
    except Exception:
        pass
    return img


# ---------------- VK 渲染（生产路径 VkEditorRenderMixin 本尊） ----------------


_VK_HOST_CLS = None


def _vk_host_cls():
    """惰性构造宿主桩类（基类 = loom_pass_vk.VkEditorRenderMixin，生产代码）。

    惰性是为了保住「loom_pass_vk 不存在 -> 本门构造段即红」的修前红语义
    （模块顶层不 import 它）。"""
    global _VK_HOST_CLS
    if _VK_HOST_CLS is None:
        import render.vk.pass_vk as lpv

        class _VkLineHost(lpv.VkEditorRenderMixin):
            """最小 VK 叠加层宿主桩：只提供 mixin 需要的东西
            （设备/格式/视图/视口尺寸）。

            ★ 走的是**生产代码**（VkEditorRenderMixin.overlay_scope +
            draw_lines），不是绕过 mixin 直调 VkLineBatch —— 这样本门测的是
            两端真实绘制路径（线宽扩宽发生在 mixin 的 draw_lines 里）。
            宿主协议新增 width/height（视口像素尺寸，扩宽数学需要），与真实
            宿主（EditorApp / VkEditorApp）同名同语义。
            """

            def __init__(self, device, view, depth_view, width, height,
                         fmt="rgba8unorm"):
                self._vk_line_device = device
                self._vk_line_format = fmt
                self._vk_overlay_view = view
                self._vk_overlay_depth_view = depth_view
                self.width = int(width)
                self.height = int(height)

        _VK_HOST_CLS = _VkLineHost
    return _VK_HOST_CLS


def _vk_render_lines(device, verts, cols, vp, depth_on=False, blend=False,
                     depth_clear=1.0, width=2.0):
    import wgpu
    import render.vk.pass_vk as lpv
    tex = device.create_texture(
        size=(W, H, 1), format="rgba8unorm",
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
    dtex = device.create_texture(size=(W, H, 1), format="depth32float",
                                 usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
    view, dview = tex.create_view(), dtex.create_view()
    # mixin 的 flush 是 LoadOp.load（画在已有帧内容之上，与 GL 语义一致）——
    # 目标必须先清好（颜色黑 + 深度按用例指定）。
    enc = device.create_command_encoder()
    rp = enc.begin_render_pass(
        color_attachments=[{'view': view, 'load_op': wgpu.LoadOp.clear,
                            'clear_value': (0, 0, 0, 1),
                            'store_op': wgpu.StoreOp.store}],
        depth_stencil_attachment={
            'view': dview, 'depth_load_op': wgpu.LoadOp.clear,
            'depth_clear_value': float(depth_clear),
            'depth_store_op': wgpu.StoreOp.store})
    rp.end()
    device.queue.submit([enc.finish()])
    host = _vk_host_cls()(device, view, dview, W, H)
    flags = tuple(f for f, on in (("depth_test", depth_on), ("blend", blend)) if on)
    kw = {"enable": flags} if flags else {"enable_only": 0}
    with host.overlay_scope(framebuffer=view, **kw):
        host.draw_lines(verts, cols, view_proj=np.asarray(vp, dtype="f4"),
                        line_width=float(width))
    return _vk_read(device, tex)


# ---------------- 中心线重合度度量 ----------------


INF = 10 ** 6


def _mask(img, thr=MASK_THR):
    return img.astype(np.float32).max(axis=2) > thr


def _chess_dist(src_mask, dst_mask, cap=32):
    """src 每个线像素 -> 最近 dst 线像素的棋盘距离（8 邻域扩散）。
    返回 (距离图, 没够到的 src 像素数)。"""
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


def _ncc(a, b):
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    return float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def _compare(gl_img, vk_img):
    mg = _mask(gl_img)
    mv = _mask(vk_img)
    res = {"gl_cov": int(mg.sum()), "vk_cov": int(mv.sum())}
    if res["gl_cov"] and res["vk_cov"]:
        dg, unc_g = _chess_dist(mg, mv)
        dv, unc_v = _chess_dist(mv, mg)
        res["mean_g2v"] = float(dg[mg].mean())
        res["max_g2v"] = int(dg[mg].max())
        res["mean_v2g"] = float(dv[mv].mean())
        res["max_v2g"] = int(dv[mv].max())
        res["uncovered"] = unc_g + unc_v
    res["mae"] = float(np.abs(gl_img.astype(np.float64) - vk_img.astype(np.float64)).mean())
    res["ncc"] = _ncc(gl_img.mean(axis=2), vk_img.mean(axis=2))
    return res


def _parity_ok(res):
    """两端逐像素判据（Q-B7-48-1 裁决 B 后两端同宽，故**不再**用中心线退让口径）。

    判据：MAE <= 2e-4（= test_ab_gl_vk.DEFAULT_GATE.mae_abs，同源不另立阈值）
          且两端线像素数比在 [0.95, 1.05]（= 线宽像素数相等）。
    中心线距离/覆盖率比值仍在 _metrics_text 里打印留证，但**不判**红绿。
    """
    gl_cov = res.get("gl_cov", 0)
    vk_cov = res.get("vk_cov", 0)
    return (gl_cov >= 30 and vk_cov >= 30
            and res.get("mae", 1.0) <= MAE_ABS
            and COV_LO <= vk_cov / max(1, gl_cov) <= COV_HI)


def _metrics_text(res):
    keys = ("gl_cov", "vk_cov", "mean_g2v", "max_g2v", "mean_v2g", "max_v2g",
            "uncovered", "mae", "ncc")
    return " ".join("%s=%s" % (k, res.get(k)) for k in keys)


# ============================ A 结构/同源段 ============================


def _sig_eq(sa, sb):
    pa, pb = list(sa.parameters.values()), list(sb.parameters.values())
    if len(pa) != len(pb):
        return False
    for x, y in zip(pa, pb):
        if x.name != y.name or x.kind != y.kind:
            return False
        if (x.default is inspect.Parameter.empty) != (y.default is inspect.Parameter.empty):
            return False
        if x.default is not inspect.Parameter.empty and x.default != y.default:
            return False
    return True


def _read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def section_a():
    print("=" * 60)
    print("A. 结构/同源段")
    print("=" * 60)
    try:
        import render.vk.pass_vk as lpv
    except Exception as e:
        check('A0 loom_pass_vk 可导入（修前红：不存在）', False, repr(e))
        return
    check("A1 loom_pass_vk 导出 VkLineBatch / VkFrameExecutor / VkEditorRenderMixin",
          all(hasattr(lpv, n) for n in ("VkLineBatch", "VkFrameExecutor", "VkEditorRenderMixin")))
    from render.gl.render import RenderMixin
    import engine as E
    sg = inspect.signature(RenderMixin.overlay_scope)
    sv = inspect.signature(lpv.VkEditorRenderMixin.overlay_scope)
    check("A2 overlay_scope 与 GL RenderMixin 签名逐参一致", _sig_eq(sg, sv), (sg, sv))
    sg2 = inspect.signature(E.GLEngine.draw_lines)
    sv2 = inspect.signature(lpv.VkEditorRenderMixin.draw_lines)
    check("A3 draw_lines 与 GL engine.draw_lines 签名逐参一致", _sig_eq(sg2, sv2), (sg2, sv2))
    import render.vk.driver as SD
    check("A4 SceneDriver 装配 VK 叠加层（公开 overlay_scope/draw_lines 两端同名）",
          all(hasattr(SD.SceneDriver, n) for n in ("overlay_scope", "draw_lines")))
    src_ed = _read(os.path.join("editor", "core.py"))
    src_gui = _read(os.path.join("gui", "main_window.py"))
    check("A5a editor._draw_selection_box 走 overlay_scope（不直接摸 ctx.scope）",
          "with self.overlay_scope(framebuffer=self._screen_fb(), enable_only=0):" in src_ed
          and "self.ctx.scope" not in src_ed)
    check("A5b loom_gui.draw 网格走 ctl.overlay_scope（叠加层调用点不区分后端）",
          src_gui.count("ctl.overlay_scope") >= 4 and "ctl.ctx.scope" not in src_gui)
    src_vk = inspect.getsource(lpv)
    # Q-B7-48-1 裁决 B 落地后：源码必须标注「裁决 B = 四边形扩宽」并指向共享实现
    check("A6 loom_pass_vk 源码标注「Q-B7-48-1 裁决 B：四边形模拟粗线 + build_line_quads」",
          "Q-B7-48-1" in src_vk and "build_line_quads" in src_vk
          and "问题一：B" in src_vk)


def section_a7(device):
    print("=" * 60)
    print("A7. VkFrameExecutor 消费同一份 frame_plan")
    print("=" * 60)
    try:
        import render.vk.pass_vk as lpv
    except Exception as e:
        check('A7 前置 loom_pass_vk 可导入', False, repr(e))
        return
    import wgpu
    import render.contract.frame_plan as loom_pass
    import render.vk.driver as sd
    import render.vk.renderer as vr
    fmt = "rgba8unorm"
    drv = sd.SceneDriver()
    drv.load_from_data(_scene_dict())
    tex = device.create_texture(
        size=(64, 64, 1), format=fmt,
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)

    class _Ctx:
        physical_size = (64, 64)

        def get_current_texture(self):
            return tex

    drv._vk_ctx = _Ctx()
    vp, cam_pos = drv.render_pose(aspect=1.0)
    drv._vp = np.asarray(vp, dtype="f4")
    r = vr.VkRenderer(device, fmt)
    ex = lpv.VkFrameExecutor(r, drv)
    # 与编辑器同一条构造式：flags 取自引擎自身状态
    from render.contract.post import post_enabled
    plan = loom_pass.frame_plan(include_shadow=bool(drv.lights),
                                include_sky=(drv.effective_skybox() is not None),
                                include_world_canvas=False,
                                include_ui=False,
                                include_post=post_enabled(),
                                screen_format=fmt)
    ex.execute(plan)
    check("A7a execute 后 renderer 消费的就是同一份 plan 对象（is）", r._frame_plan is plan,
          type(r._frame_plan))
    plan2 = loom_pass.frame_plan(include_shadow=bool(drv.lights),
                                 include_sky=False,
                                 include_world_canvas=False,
                                 include_ui=False,
                                 include_post=post_enabled(),
                                 screen_format=fmt)
    ex.execute(plan2)
    check("A7b 换一份 plan（无天空）同样逐对象消费", r._frame_plan is plan2 and plan2 is not plan,
          (r._frame_plan is plan2, plan2 is not plan))


# ============================ B 像素段 ============================


FIXTURE_ORDER = ("grid", "selection", "gizmo_translate", "gizmo_rotate")


def section_b():
    print("=" * 60)
    print("B. 像素门：同一组顶点/颜色数组，GL 离屏 vs VK 离屏（MAE，两端同宽）")
    print("=" * 60)
    try:
        import render.vk.pass_vk as loom_pass_vk  # noqa: F401
    except Exception as e:
        check('B 前置 loom_pass_vk 可导入（修前红：不存在）', False, repr(e))
        return
    device = _vk_device()
    ctx, fbo, ed, vp = _editor()
    fx = _capture_fixtures(ed)
    for name in FIXTURE_ORDER:
        item = fx.get(name)
        if not item or len(item[0]) == 0:
            check("B 夹具非空: " + name, False, "捕获为空")
            continue
        verts, cols = item
        # 网格 = 编辑器真实语义（深度开 + alpha 混合，见 loom_gui.draw）；
        # 其余 = enable_only=0 语义（深度关，恒可见）。
        depth_on = (name == "grid")
        blend = (name == "grid")
        g = _gl_render_lines(ctx, fbo, ed, verts, cols, vp, depth_on=depth_on, blend=blend)
        v = _vk_render_lines(device, verts, cols, vp, depth_on=depth_on, blend=blend)
        res = _compare(g, v)
        print("  [%s] %s" % (name, _metrics_text(res)))
        check("B 像素门(MAE<=%.0e 且线像素数相等): %s" % (MAE_ABS, name),
              _parity_ok(res), _metrics_text(res))


def section_b5():
    print("=" * 60)
    print("B5. 反例自检：VK 整体平移 16px 必须把门打红")
    print("=" * 60)
    try:
        import render.vk.pass_vk as loom_pass_vk  # noqa: F401
    except Exception as e:
        check('B5 前置 loom_pass_vk 可导入', False, repr(e))
        return
    device = _vk_device()
    ctx, fbo, ed, _vp = _editor()
    # 恒等 VP（clip = 顶点 + x 平移），w=1：NDC x = x + dx —— 平移量屏幕像素可手算。
    dx = 2.0 * 16.0 / W
    vp_base = np.eye(4, dtype="f4")
    vp_off = np.eye(4, dtype="f4")
    vp_off[3, 0] = dx
    verts = [(-0.9, -0.5, 0.0), (0.9, -0.5, 0.0),   # 横线
             (-0.5, -0.6, 0.0), (-0.5, 0.6, 0.0),   # 竖线
             (0.6, -0.5, 0.0), (0.8, 0.2, 0.0)]     # 右侧短斜线（打破 x 对称）
    cols = [(1, 0, 0), (1, 0, 0), (0, 1, 0), (0, 1, 0), (0, 0.5, 1), (0, 0.5, 1)]
    g = _gl_render_lines(ctx, fbo, ed, verts, cols, vp_base, depth_on=False)
    v0 = _vk_render_lines(device, verts, cols, vp_base, depth_on=False)
    v1 = _vk_render_lines(device, verts, cols, vp_off, depth_on=False)
    r0 = _compare(g, v0)
    r1 = _compare(g, v1)
    print("  [对齐] %s" % _metrics_text(r0))
    print("  [平移16px] %s" % _metrics_text(r1))
    check("B5a 恒等 VP 下两端逐像素一致", _parity_ok(r0), _metrics_text(r0))
    check("B5b 平移 16px 的 MAE 显著劣化（门会真红）",
          r1.get("mae", 0.0) > 10 * MAE_ABS,
          "mae=%.6f > 10x%.0e" % (r1.get("mae", 0.0), MAE_ABS))


def section_b6():
    print("=" * 60)
    print("B6. overlay_scope 端到端（VK mixin 自动 flush vs GL scope(enable_only=0)）")
    print("=" * 60)
    try:
        import render.vk.pass_vk as lpv
    except Exception as e:
        check('B6 前置 loom_pass_vk 可导入', False, repr(e))
        return
    import wgpu
    device = _vk_device()
    ctx, fbo, ed, vp = _editor()
    fx = _capture_fixtures(ed)
    sel_v, sel_c = fx["selection"]
    # GL：真实 overlay_scope 路径（GL 转发 moderngl scope）
    fbo.use()
    ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
    with ed.overlay_scope(framebuffer=fbo, enable_only=0):
        ed.draw_lines(sel_v, sel_c, view_proj=vp)
    raw = fbo.read(components=3)
    g = np.flipud(np.frombuffer(raw, dtype="u1").reshape(H, W, 3).astype(np.float32) / 255.0)
    # VK：目标先清黑（叠加层 flush 是 LoadOp.load，画在已有帧内容之上）
    tex = device.create_texture(
        size=(W, H, 1), format="rgba8unorm",
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
    view = tex.create_view()
    dtex = device.create_texture(size=(W, H, 1), format="depth32float",
                                 usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
    enc = device.create_command_encoder()
    rp = enc.begin_render_pass(
        color_attachments=[{'view': view, 'load_op': wgpu.LoadOp.clear,
                            'clear_value': (0, 0, 0, 1),
                            'store_op': wgpu.StoreOp.store}])
    rp.end()
    device.queue.submit([enc.finish()])

    # 宿主桩与 B 段同一份（_vk_host_cls = VkEditorRenderMixin 子类，带视口尺寸）
    host = _vk_host_cls()(device, view, dtex.create_view(), W, H)
    with host.overlay_scope(framebuffer=view, enable_only=0):
        host.draw_lines(sel_v, sel_c, view_proj=vp)
    v = _vk_read(device, tex)
    res = _compare(g, v)
    print("  [selection/overlay_scope] %s" % _metrics_text(res))
    check("B6 overlay_scope 端到端逐像素一致（MAE 口径）", _parity_ok(res),
          _metrics_text(res))


def section_b7():
    print("=" * 60)
    print("B7. 深度开关语义（深度缓冲 0.5 前景遮挡 / 1.0 全通，两端一致）")
    print("=" * 60)
    try:
        import render.vk.pass_vk as loom_pass_vk  # noqa: F401
    except Exception as e:
        check('B7 前置 loom_pass_vk 可导入', False, repr(e))
        return
    device = _vk_device()
    ctx, fbo, ed, _vp = _editor()
    # 恒等 VP：clip = 顶点。GL 窗口深度 = (z+1)/2 = 0.875，VK 深度 = z = 0.75 ——
    # 都 > 0.5（被遮挡）/ < 1.0（通过），深度语义两端一致（口径见模块 docstring）。
    verts = [(-0.9, -0.5, 0.75), (0.9, -0.5, 0.75)]
    cols = [(1, 1, 0), (1, 1, 0)]
    vp_id = np.eye(4, dtype="f4")
    for depth_on in (True, False):
        clear = 0.5 if depth_on else 1.0
        g = _gl_render_lines(ctx, fbo, ed, verts, cols, vp_id,
                             depth_on=depth_on, depth_clear=clear)
        v = _vk_render_lines(device, verts, cols, vp_id,
                             depth_on=depth_on, depth_clear=clear)
        mg = _mask(g)
        mv = _mask(v)
        tag = "遮挡(0.5)" if depth_on else "通过(1.0)"
        if depth_on:
            check("B7 %s: 两端都被深度丢弃（GL/GL 行为一致，VK 深度开关真生效）" % tag,
                  int(mg.sum()) <= 5 and int(mv.sum()) <= 5,
                  (int(mg.sum()), int(mv.sum())))
        else:
            _r = int(mv.sum()) / max(1, int(mg.sum()))
            check("B7 %s: 两端都可见且线像素数相等（覆盖比 [%.2f, %.2f]）" % (tag, COV_LO, COV_HI),
                  int(mg.sum()) >= 200 and int(mv.sum()) >= 200
                  and COV_LO <= _r <= COV_HI,
                  (int(mg.sum()), int(mv.sum()), round(_r, 4)))


def _line_width_px(img):
    """水平线的「线宽像素数」= 线覆盖区域中间那批列上亮像素数的中位数。

    对**水平线**而言这就是线宽本身（GL 2px 线 = 每列 2 个亮像素；VK 1px = 1 个）。
    取中位数而非均值：端点处（butt cap）列只有部分覆盖，不污染口径。"""
    m = _mask(img)
    cols = [x for x in range(W // 4, 3 * W // 4) if m[:, x].any()]
    if not cols:
        return 0.0
    return float(np.median([int(m[:, x].sum()) for x in cols]))


def section_b8():
    print("=" * 60)
    print("B8. 线宽像素数两端相等（Q-B7-48-1 裁决 B：四边形模拟粗线）")
    print("=" * 60)
    try:
        import render.vk.pass_vk as loom_pass_vk  # noqa: F401
    except Exception as e:
        check('B8 前置 loom_pass_vk 可导入', False, repr(e))
        return
    device = _vk_device()
    ctx, fbo, ed, _vp = _editor()
    # ---- B8a：同一线宽参数下，单条水平线的线宽像素数两端相等 ----
    vp_id = np.eye(4, dtype="f4")
    lv = [(-0.8, 0.0, 0.0), (0.8, 0.0, 0.0)]
    lc = [(1.0, 1.0, 1.0), (1.0, 1.0, 1.0)]
    g = _gl_render_lines(ctx, fbo, ed, lv, lc, vp_id, depth_on=False)
    v = _vk_render_lines(device, lv, lc, vp_id, depth_on=False)
    wg, wv = _line_width_px(g), _line_width_px(v)
    print("  [水平线 width=2px] 线宽像素数 GL=%s VK=%s" % (wg, wv))
    check("B8a 同一线宽参数(2px)下两端线宽像素数相等", wg == wv and wg >= 1.0,
          (wg, wv))
    # ---- B8b：真实夹具（网格/选中框/gizmo）两端线像素数相等 ----
    fx = _capture_fixtures(ed)
    for name in FIXTURE_ORDER:
        item = fx.get(name)
        if not item or len(item[0]) == 0:
            check("B8b 夹具非空: " + name, False, "捕获为空")
            continue
        verts, cols = item
        depth_on = (name == "grid")          # 网格 = 深度开 + alpha 混合（同 B 段）
        blend = (name == "grid")
        g = _gl_render_lines(ctx, fbo, ed, verts, cols, _vp, depth_on=depth_on,
                             blend=blend)
        v = _vk_render_lines(device, verts, cols, _vp, depth_on=depth_on,
                             blend=blend)
        res = _compare(g, v)
        ratio = res["vk_cov"] / max(1, res["gl_cov"])
        print("  [%s] gl_cov=%d vk_cov=%d 覆盖比=%.3f mae=%.6f"
              % (name, res["gl_cov"], res["vk_cov"], ratio, res["mae"]))
        check("B8b 两端线宽像素数相等: " + name, COV_LO <= ratio <= COV_HI,
              "gl_cov=%d vk_cov=%d 比=%.3f" % (res["gl_cov"], res["vk_cov"], ratio))


def main():
    print("=" * 60)
    print("S3 门：VK 绘制原语补齐（MAE 口径；线宽 = Q-B7-48-1 裁决 B 四边形扩宽）")
    print("=" * 60)
    section_a()
    device = None
    try:
        device = _vk_device()
    except Exception as e:
        check("VK 设备可用", False, repr(e))
    if device is not None:
        section_a7(device)
    section_b()
    section_b5()
    section_b6()
    section_b7()
    section_b8()
    print("=" * 60)
    if _fails:
        print("FAIL 汇总: %d 项 —— %s" % (len(_fails), ", ".join(_fails)))
    else:
        print("S3 VK 绘制原语门 全部 PASS")
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())