# -*- coding: utf-8 -*-
"""loom_pass_vk.py — VK 后端的叠加层绘制原语 + FramePlan 执行器（S3，Q-B7-47-1 阶段 3）。

与 loom_pass_gl.py（GL 执行器）/ loom_render.RenderMixin（GL 叠加层钩子）对称：
  · VkLineBatch          —— draw_lines 的 VK 实现（line-list 管线 + 动态 VBO +
                            u_view_proj uniform + 深度开关），语义对齐 engine.draw_lines
                            （engine.py:652：顶点 + 颜色数组，一次性提交；不光照）；
  · VkEditorRenderMixin  —— overlay_scope / draw_lines / _backend_execute_frame 的
                            VK 侧实现，与 loom_render.RenderMixin 的 GL 钩子**同签名**
                            （同源契约，规则 5.5：编辑器叠加层代码不改就能两端跑）；
  · VkFrameExecutor      —— 消费 loom_pass.frame_plan() 的**同一份** plan（与
                            GLFrameExecutor 同源：plan 是共享描述，GL/VK 各有执行器），
                            内部转 vk_renderer.VkRenderer.draw_frame(...)。

★ 线宽（Q-B7-48-1 人类裁决 2026-11-20「问题一：B」= 两端统一改成「用四边形
  模拟粗线」）：wgpu 0.33 的 PrimitiveState **没有 line_width 字段**（实测传 2.0 ->
  ValueError），GL 原本是 ctx.line_width=2.0 —— 两端实测 2:1。裁决后两端都**不再依赖
  任何后端的线宽光栅化能力**：线段在 CPU 侧由 loom_line_geometry.build_line_quads
  按**屏幕空间像素宽度**膨胀成 2 个三角形（扩宽数学唯一一份，GL 侧 engine.draw_lines
  调的是同一个函数），本模块只负责把三角形画出来（triangle-list）。
  于是 line_width 参数在两端**真的生效**（单位 = 像素，默认 2.0）。

与 GL 的语义差异（诚实边界，别假装统一了）：
  · GL 的立即模式 draw_lines 在调用时立刻画；VK 命令流是一次性录制的，叠加层
    draw_lines 只能**收集**进 pending 批次，overlay_scope 退出时一次性 flush
    （无深度写、按需 blend 的独立 render pass，视觉等价于 GL 的
    ctx.scope(framebuffer=..., enable_only=0) + draw_lines）；
  · GL DepthState.write 是 advisory（moderngl 无 depth_mask）；VK 侧深度状态是
    不可变管线的一部分，本模块按批次键烘焙（depth on = less + 写，与 GL 网格
    「开深度测试」语义一致；depth off = 不碰深度附件，与 enable_only=0 一致）；
  · 嵌套 overlay_scope 不支持（报错可见）。
"""
from contextlib import contextmanager

import numpy as np
import wgpu

from render.contract.shaders import CLEAR_COLOR_RGBA
# Q-B7-48-1 裁决 B：粗线 = 四边形（扩宽数学的唯一一份实现，与 GL engine.draw_lines 同源）
from mathlib.line_geometry import build_line_quads


# ---------------- WGSL：线批着色器（镜像 loom_shaders._LINE_VERT/_LINE_FRAG）----------------
# GL: gl_Position = u_view_proj * vec4(in_pos, 1.0); frag = v_color（不光照不采样）。
# 交错布局与 GL 完全一致：28 字节/顶点 = pos 3f + color 4f（顶点布局 '3f 4f'）。
_LINE_WGSL = """
struct LineUniform {
    vp: mat4x4<f32>,
}
@group(0) @binding(0) var<uniform> u: LineUniform;
struct VSOut {
    @builtin(position) pos: vec4f,
    @location(0) color: vec4f,
}
@vertex fn vs(@location(0) in_pos: vec3f, @location(1) in_color: vec4f) -> VSOut {
    var o: VSOut;
    o.pos = u.vp * vec4f(in_pos, 1.0);
    o.color = in_color;
    return o;
}
@fragment fn fs(in: VSOut) -> @location(0) vec4f {
    return in.color;
}
"""

# 顶点模式映射：GL 的 mode 是 int 常量（moderngl.LINES==1 / TRIANGLES==4，GL 枚举值）；
# 接受 GL 枚举值与字符串两种形态。线宽由 loom_line_geometry 在 CPU 侧扩宽成
# 三角形（Q-B7-48-1 裁决 B），本映射只决定「扩宽前」的段分组（lines/line-strip）。
_TOPOLOGY = {
    1: 'line-list', 'lines': 'line-list', 'line-list': 'line-list',
    4: 'triangle-list', 'triangles': 'triangle-list', 'triangle-list': 'triangle-list',
}
_LINE_BYTES = 7 * 4          # 每顶点 28 字节（pos3f + color4f），与 GL '3f 4f' 一致

# 恒等 VP（draw_screen_rect 的顶点已预算成 NDC，屏幕空间原语用它直出）
_IDENTITY4 = np.eye(4, dtype=np.float32)


def _pack_lines(verts, colors):
    """(N,3)+(N,3|4) -> 交错 (N,7) f4（与 engine.draw_lines 的 packed 同一规则）。"""
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    c = np.asarray(colors, dtype=np.float32)
    if c.ndim != 2 or c.shape[0] != v.shape[0] or c.shape[1] not in (3, 4):
        raise ValueError('draw_lines: verts (%r) 与 colors (%r) 形状不匹配'
                         % (v.shape, c.shape))
    if c.shape[1] == 3:
        c = np.concatenate(
            [c, np.ones((c.shape[0], 1), dtype=np.float32)], axis=1)
    return np.ascontiguousarray(np.concatenate([v, c], axis=1), dtype=np.float32)


class VkLineBatch:
    """draw_lines 的 VK 实现（line-list 管线 + 动态 VBO + u_view_proj + 深度开关）。

    线宽：不在这里决定 —— 扩宽（屏幕空间像素宽度 -> 四边形）由
    loom_line_geometry.build_line_quads 在 CPU 侧完成，本类只按 triangle-list
    画三角形（Q-B7-48-1 裁决 B：两端同一份扩宽数学）。
    """

    def __init__(self, device, format='rgba8unorm'):
        self.device = device
        self.format = format
        self._module = device.create_shader_module(code=_LINE_WGSL)
        self._bgl = device.create_bind_group_layout(entries=[
            {'binding': 0, 'visibility': wgpu.ShaderStage.VERTEX,
             'buffer': {'type': 'uniform'}}])
        self._layout = device.create_pipeline_layout(bind_group_layouts=[self._bgl])
        self._pipes = {}              # (topology, depth_on, blend) -> pipeline
        self._ubo_cache = {}          # vp bytes -> (ubo, bind_group)
        self._vbo = None
        self._vbo_cap = 0
        self._cursor = 0              # 已用字节数（flush 多批次时按偏移追加）

    # ---------- 管线 ----------
    def _pipeline(self, topology, depth_on, blend, has_depth=True):
        """depth_on=False 且 render pass 挂了深度附件时，用 always+不写表达
        「不测不写但附件仍挂着」（V2-01 语义，与 vk_renderer._ensure_main_pipe 同款）——
        否则管线与 pass 的深度附件格式不兼容（wgpu 校验拒绝）。"""
        key = (topology, bool(depth_on), bool(blend), bool(has_depth))
        pipe = self._pipes.get(key)
        if pipe is not None:
            return pipe
        target = {'format': self.format}
        if blend:
            # 与 GL blend_func=(SRC_ALPHA, ONE_MINUS_SRC_ALPHA) 同一语义
            target['blend'] = {
                'color': {'src_factor': 'src-alpha',
                          'dst_factor': 'one-minus-src-alpha', 'operation': 'add'},
                'alpha': {'src_factor': 'src-alpha',
                          'dst_factor': 'one-minus-src-alpha', 'operation': 'add'}}
        di = None
        if has_depth:
            if depth_on:
                # 深度开（网格语义）：less + 写 —— 与 GL「enable(DEPTH_TEST)
                # （func 默认 <）且深度掩码开」一致。
                di = {'format': 'depth32float', 'depth_write_enabled': True,
                      'depth_compare': 'less'}
            else:
                # 深度关（叠加层语义）：不测不写，但深度附件仍挂着（保留内容）。
                di = {'format': 'depth32float', 'depth_write_enabled': False,
                      'depth_compare': 'always'}
        pipe = self.device.create_render_pipeline(
            layout=self._layout,
            vertex={'module': self._module, 'entry_point': 'vs',
                    'buffers': [{'array_stride': _LINE_BYTES, 'step_mode': 'vertex',
                                 'attributes': [
                                     {'shader_location': 0, 'offset': 0,
                                      'format': 'float32x3'},
                                     {'shader_location': 1, 'offset': 12,
                                      'format': 'float32x4'}]}]},
            primitive={'topology': topology, 'front_face': 'ccw',
                       'cull_mode': 'none'},
            depth_stencil=di,
            fragment={'module': self._module, 'entry_point': 'fs',
                      'targets': [target]})
        self._pipes[key] = pipe
        return pipe

    # ---------- uniform / VBO ----------
    def _uniform(self, view_proj):
        vp = np.ascontiguousarray(np.asarray(view_proj, dtype=np.float32).reshape(4, 4))
        key = vp.tobytes()
        ent = self._ubo_cache.get(key)
        if ent is not None:
            return ent
        if len(self._ubo_cache) > 64:      # 防 VP 逐帧变化撑爆缓存
            self._ubo_cache.clear()
        ubo = self.device.create_buffer(
            size=64, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.device.queue.write_buffer(ubo, 0, key)
        bg = self.device.create_bind_group(
            layout=self._bgl,
            entries=[{'binding': 0,
                      'resource': {'buffer': ubo, 'offset': 0, 'size': 64}}])
        self._ubo_cache[key] = (ubo, bg)
        return ubo, bg

    def _ensure_vbo(self, n_bytes):
        if self._vbo is None or self._vbo_cap < n_bytes:
            cap = max(4096, 2 * n_bytes)   # 与 GL D10 同款：初量 4KB，生长 2x
            self._vbo = self.device.create_buffer(
                size=cap,
                usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
            self._vbo_cap = cap
            self._cursor = 0

    def reset(self):
        """帧首/flush 首复位 VBO 追加游标（缓冲内容无需清零：只读 [0, cursor)）。"""
        self._cursor = 0

    def stage(self, packed):
        """把一包交错顶点写进动态 VBO（追加），返回 (byte_offset, 顶点数)。"""
        data = np.ascontiguousarray(packed, dtype=np.float32).tobytes()
        if self._cursor + len(data) > self._vbo_cap:
            self._ensure_vbo(self._cursor + len(data))
        off = self._cursor
        self.device.queue.write_buffer(self._vbo, off, data)
        self._cursor += len(data)
        return off, len(data) // _LINE_BYTES

    # ---------- 绘制 ----------
    def draw(self, rp, verts, colors, view_proj, mode=1,
             depth_test=False, blend=False, has_depth=True):
        """单批次直画（已有活动 render pass）。顶点模式由调用方给（扩宽后= triangle-list）。

        has_depth：当前 render pass 是否挂了 depth32float 附件（挂了就必须声明，
        见 _pipeline 的 V2-01 注）。
        """
        topology = _TOPOLOGY.get(mode)
        if topology is None:
            raise NotImplementedError('VkLineBatch 不支持的顶点模式: %r'
                                      '（支持 LINES/TRIANGLES）' % (mode,))
        self.reset()
        off, n = self.stage(_pack_lines(verts, colors))
        self._record(rp, off, n, view_proj, topology, depth_test, blend, has_depth)

    def _record(self, rp, byte_offset, n_verts, view_proj, topology,
                depth_test, blend, has_depth=True):
        rp.set_pipeline(self._pipeline(topology, depth_test, blend, has_depth))
        _ubo, bg = self._uniform(view_proj)
        rp.set_bind_group(0, bg)
        rp.set_vertex_buffer(0, self._vbo, byte_offset, n_verts * _LINE_BYTES)
        rp.draw(n_verts, 1, 0, 0)


class VkFrameExecutor:
    """FramePlan 的 VK 执行器 —— 与 loom_pass_gl.GLFrameExecutor 同源对称。

    消费 **同一份** loom_pass.frame_plan()（共享描述，GL/VK 各有执行器）；内部把
    plan 的 pass 集合翻成 vk_renderer.VkRenderer.draw_frame(...) 的既有实现
    （VK 的命令流在 draw_frame 内按 plan.passes 顺序一次性录制，见 vk_renderer.py
    「阶段 2a（真遍历）」）。execute 返回后断言 renderer 消费的就是同一份 plan
    对象（frame_plan 按参数缓存，同 flags 必返回同一对象）——「同源」的硬证据。

    宿主协议（S4 的 VK 编辑器内核提供 / 测试桩）：
      _vk_ctx       宿主窗口/离屏上下文（physical_size + get_current_texture）
      models/lights 场景实体
      _vp           渲染 VP（4x4）
      camera        有 .x/.y/.z（GL 形态）；否则回退 current_camera_position 属性（VK 形态）
      effective_skybox()  生效天空盒（可缺失）
      ui            UIManager（可 None）
      _interp       插值平面（可缺省）
    """

    def __init__(self, renderer, engine):
        self.renderer = renderer
        self.engine = engine

    # ---- plan -> draw_frame 参数翻译（逐项可核）----
    def execute(self, plan, prepare=None, before_pass=None, after_pass=None):
        errs = plan.validate()
        if errs:
            raise ValueError('FramePlan 非法: %s' % '; '.join(errs))
        r = self.renderer
        eng = self.engine
        ids = {p.id for p in plan.passes}
        # VK 的清屏发生在 render pass 的 load_op，清屏色取自 draw_frame 内部
        # frame_plan 的默认值（CLEAR_COLOR_RGBA）—— 非默认清屏色 S4 再接线。
        main = plan.pass_by_id('main')
        if main is not None and tuple(main.clear or ()) != tuple(CLEAR_COLOR_RGBA):
            raise NotImplementedError(
                'VK 执行器当前只支持默认清屏色（plan.main.clear=%r，需要 %r）；'
                ' S4 接真窗口时再放宽' % (main.clear, CLEAR_COLOR_RGBA))
        screen = plan.target_by_name('color.ldr')
        fmt = getattr(screen, 'format', None)
        if fmt is not None and fmt != r.format:
            raise NotImplementedError('VK 执行器要求 plan 的 SCREEN 目标格式(%r)与'
                                      ' 渲染器表面格式(%r)一致（S4 接线）'
                                      % (fmt, r.format))
        if any(p.id in ('bloom.bright', 'bloom.down', 'tonemap')
               for p in plan.passes) != bool(getattr(r, '_post_on', False)):
            raise NotImplementedError('VK 执行器要求 plan 的后处理 pass 与 renderer.'
                                      '_post_on 一致（S4 接线）')
        if prepare is not None:
            # GL 在第一个屏幕 pass 清屏后调（相机/VP/uniform）；VK 的清屏在 pass
            # load_op 里、命令录制在 draw_frame 内 —— 帧前完成等价且时序一致。
            prepare()
        # before_pass / after_pass：VK 命令流一次性录制，无法逐 pass 插桩 ——
        # 两个钩子在**帧级**触发（before 帧前逐 spec、after 帧后逐 spec），
        # 供剖面/计时用；逐 pass 精确时机 S4 接真窗口时再收紧（诚实边界，非等价）。
        if before_pass is not None:
            for spec in plan.passes:
                before_pass(spec)
        ctx = getattr(eng, '_vk_ctx', None)
        if ctx is None:
            raise RuntimeError('VK 宿主未提供 _vk_ctx（physical_size + '
                               'get_current_texture）—— 无法提交帧')
        # plan 驱动：plan 没有 sky pass 时明确传 None（draw_frame 按 sky is not None
        # 推导 include_sky —— 与 ui 的处理同理，保证消费的就是调用方那份 plan）。
        sky = None
        if 'sky' in ids:
            eff = getattr(eng, 'effective_skybox', None)
            if callable(eff):
                try:
                    sky = eff()
                except Exception as e:
                    print('[vk-exec] 取生效天空盒失败 (按无天空处理):', repr(e))
        ui = getattr(eng, 'ui', None)
        if 'ui' not in ids and 'world_ui' not in ids:
            ui = None          # plan 不画 UI（如编辑态）：明确传 None，而非引擎现值
        elif ui is None:
            raise NotImplementedError(
                'plan 声明了 ui/world_ui pass 但 engine.ui 为空（S4 接线）')
        hud_lines = getattr(eng, 'hud_lines', None) if 'hud' in ids else None
        hud = getattr(eng, 'hud', None) if 'hud' in ids else None
        cam = getattr(eng, 'camera', None)
        if cam is not None and all(hasattr(cam, a) for a in ('x', 'y', 'z')):
            camera_pos = (cam.x, cam.y, cam.z)
        else:
            camera_pos = tuple(getattr(eng, 'current_camera_position', (0.0, 0.0, 0.0)))
        r.draw_frame(ctx, eng.models, eng.lights,
                     np.asarray(getattr(eng, '_vp', None), dtype=np.float32),
                     camera_pos,
                     interp=getattr(eng, '_interp', None),
                     sky=sky, ui=ui, hud_lines=hud_lines, hud=hud,
                     cam_basis=getattr(eng, '_frame_cam_basis', None),
                     engine=eng)
        if r._frame_plan is not plan:
            raise RuntimeError('VK 渲染器未消费同一份 FramePlan（同源破坏: %r vs %r）'
                               % (type(r._frame_plan), type(plan)))
        if after_pass is not None:
            for spec in plan.passes:
                after_pass(spec)
        return plan


class VkEditorRenderMixin:
    """VK 侧「叠加层 + 帧执行」钩子 —— 与 loom_render.RenderMixin 的 GL 钩子同签名。

    宿主协议（S4 的 VK 编辑器内核提供 / 测试桩）：
      _vk_line_device          wgpu.Device（线批管线/缓冲所属设备）
      _vk_line_format          目标格式 str（与交换链/离屏目标一致）
      _vk_overlay_view         当前叠加层目标 TextureView（宿主每帧更新）
      _vk_overlay_depth_view   深度附件视图（可 None；深度批次需要而缺省时报错可见）
      _vk_renderer             vk_renderer.VkRenderer（VkFrameExecutor 转 draw_frame）
      _vp                      渲染 VP（draw_lines 缺省 view_proj）
    """

    # ---- ②③：叠加层状态作用域（与 GL 同签名；VK = 收集 + 退出时 flush）----
    @contextmanager
    def overlay_scope(self, framebuffer=None, enable_only=None, enable=()):
        """叠加层状态作用域（VK 实现）。

        VK 没有 GL 的全局固定功能状态 —— 语义映射（与 GL 视觉等价）：
          enable_only=0                     -> 深度/混合全关（gizmo/选中框「恒可见」）；
          enable=('depth_test','blend')     -> 深度开(less+写) + alpha 混合（网格语义）；
          其余 enable_only 位串             -> 不支持，报错可见（诚实边界）。
        作用域内 draw_lines 收集进 pending 批次，退出时一次性提交到 framebuffer
        （无深度写、按需 blend 的独立 render pass，颜色 LoadOp.load 画在已有帧之上）。
        """
        if enable_only not in (None, 0):
            raise NotImplementedError(
                'VK overlay_scope 只支持 enable_only=None/0（收到 %r）；位串映射待'
                ' S4 按需补' % (enable_only,))
        pend = getattr(self, '_vk_pending', None)
        if pend is not None:
            raise RuntimeError('VK overlay_scope 不支持嵌套')
        depth_on = 'depth_test' in tuple(enable)
        blend_on = 'blend' in tuple(enable)
        self._vk_pending = {'view': framebuffer, 'depth': depth_on,
                            'blend': blend_on, 'draws': []}
        try:
            yield
        finally:
            pend = self._vk_pending
            self._vk_pending = None
            self._flush_overlay(pend)

    def _flush_overlay(self, pend):
        """把 pending 批次按「无深度写、按需 blend」提交到目标视图。"""
        draws = pend['draws']
        if not draws:
            return
        view = pend['view']
        if view is None:
            view = getattr(self, '_vk_overlay_view', None)
        if view is None:
            raise RuntimeError(
                'VK 叠加层 flush 无目标视图（overlay_scope(framebuffer=...) 或宿主 '
                '_vk_overlay_view）')
        d = self._vk_line_batch()
        needs_depth = any(dd[3] for dd in draws)
        depth_view = None
        if needs_depth:
            depth_view = getattr(self, '_vk_overlay_depth_view', None)
            if depth_view is None:
                raise RuntimeError(
                    'VK 叠加层有深度批次但宿主未提供 _vk_overlay_depth_view')
        device = d.device
        d.reset()
        staged = []
        for packed, vp, mode, depth_on in draws:
            topology = _TOPOLOGY.get(mode)
            if topology is None:
                raise NotImplementedError(
                    'VkLineBatch 不支持的顶点模式: %r' % (mode,))
            off, n = d.stage(packed)
            staged.append((off, n, vp, topology, depth_on))
        enc = device.create_command_encoder()
        att = [{'view': view, 'load_op': wgpu.LoadOp.load,
                'store_op': wgpu.StoreOp.store}]
        kw = {}
        # 深度附件：宿主有就挂（off 批次用 always+不写表达「不测不写」，V2-01）；
        # 宿主没有且无深度批次 -> 管线走无深度变体、pass 不挂深度附件。
        has_depth = needs_depth or depth_view is not None
        if has_depth:
            kw['depth_stencil_attachment'] = {
                'view': depth_view, 'depth_load_op': wgpu.LoadOp.load,
                'depth_store_op': wgpu.StoreOp.store}
        rp = enc.begin_render_pass(color_attachments=att, **kw)
        try:
            for off, n, vp, topology, depth_on in staged:
                d._record(rp, off, n, vp, topology, depth_on, pend['blend'],
                          has_depth)
        finally:
            rp.end()
        device.queue.submit([enc.finish()])

    def _vk_line_batch(self):
        batch = getattr(self, '_vk_line_batch_obj', None)
        if batch is None:
            device = getattr(self, '_vk_line_device', None)
            if device is None:
                raise RuntimeError(
                    'VK 叠加层宿主未提供 _vk_line_device（wgpu.Device）')
            batch = VkLineBatch(device, getattr(self, '_vk_line_format', 'rgba8unorm'))
            self._vk_line_batch_obj = batch
        return batch

    # ---- ①：draw_lines（与 engine.draw_lines 同签名；GL 立即模式，VK 收集）----
    def _overlay_viewport_size(self):
        """叠加层渲染目标的像素尺寸 (W, H) —— 线宽扩宽的屏幕空间基准。

        宿主协议：优先 self.width/self.height（EditorApp / VkEditorApp 同名同语义），
        其次 _vk_ctx.physical_size（rendercanvas 上下文）；都没有就报错可见
        （静默用 0 会把扩宽算成 0 像素 = 线消失，属不可接受的假绿）。
        """
        w = int(getattr(self, 'width', 0) or 0)
        h = int(getattr(self, 'height', 0) or 0)
        if w > 0 and h > 0:
            return (w, h)
        ctx = getattr(self, '_vk_ctx', None)
        ps = getattr(ctx, 'physical_size', None) if ctx is not None else None
        if ps:
            return (int(ps[0]), int(ps[1]))
        raise RuntimeError(
            'VK draw_lines 缺少视口像素尺寸（宿主需提供 width/height 或 '
            '_vk_ctx.physical_size）—— 线宽扩宽必须有屏幕空间基准')

    def draw_lines(self, verts, colors, mode=1, view_proj=None, line_width=2.0):
        """渲染世界空间折线（逐顶点颜色，不光照）。

        签名与 GL engine.draw_lines(verts, colors, mode, view_proj, line_width)
        完全一致 —— 编辑器叠加层代码不改就能两端跑（同源）。
        ★ 线宽（Q-B7-48-1 裁决 B）：**line_width 是像素宽度且真的生效** —— 线段由
        loom_line_geometry.build_line_quads（与 GL 同一份扩宽数学）在 CPU 侧膨胀成
        屏幕空间四边形，这里收集的就是 triangle-list（mode=4）+ 恒等 VP。
        旧实现「wgpu 只能 1px、line_width 收下不生效」的语义留痕到此结束。
        """
        if getattr(self, '_vk_pending', None) is None:
            raise RuntimeError(
                'VK draw_lines 只能在 overlay_scope 内调用（无全局立即模式；'
                ' GL 侧语义是调用即画，VK 侧收集到 scope 退出时提交）')
        vp = view_proj if view_proj is not None else getattr(self, '_vp', None)
        if vp is None:
            raise ValueError('VK draw_lines 缺少 view_proj（宿主也未提供 _vp）')
        q_verts, q_colors, q_vp = build_line_quads(
            verts, colors, vp, width_px=line_width,
            viewport_size=self._overlay_viewport_size(), mode=mode)
        if len(q_verts) == 0:
            return
        # 扩宽后一律 triangle-list（TRIANGLES 直通的也还是三角形）
        self._vk_pending['draws'].append(
            (_pack_lines(q_verts, q_colors), q_vp, 4, self._vk_pending['depth']))

    # ---- ③：帧执行钩子（与 loom_render.RenderMixin._backend_execute_frame 同签名）----
    def _backend_execute_frame(self, plan, prepare=None, before_pass=None,
                               after_pass=None):
        """钩子（VK）：FramePlan 执行 —— 转发 VkFrameExecutor（消费同一份 plan）。"""
        ex = getattr(self, '_frame_executor', None)
        if ex is None:
            ex = VkFrameExecutor(self._vk_renderer, self)
            self._frame_executor = ex
        return ex.execute(plan, prepare=prepare, before_pass=before_pass,
                          after_pass=after_pass)

    @property
    def _vk_renderer(self):
        """宿主持有的 VkRenderer（S4 由 VK 编辑器内核装配；测试桩直接赋属性）。"""
        r = getattr(self, '_vk_renderer_obj', None)
        if r is None:
            raise RuntimeError('VK 宿主未装配 _vk_renderer（S4 接线）')
        return r

    # ---- ④（S4）：屏幕空间原语 + 渲染目标（与 GL loom_hud/loom_render 同名同语义）----
    def _screen_fb(self):
        """当前渲染目标（VK）—— 与 loom_render.RenderMixin._screen_fb 同签名同语义。

        GL 语义 = "叠加层画到当前帧的屏幕目标"；VK 的等价物 = 交换链当前帧纹理视图。
        rendercanvas 语义保证：同一次 draw 回调内 get_current_texture() 返回同一张
        帧纹理（帧末 present 才轮换），所以主 pass / 叠加层 flush 画到同一张图上。
        """
        ctx = getattr(self, '_vk_ctx', None)
        if ctx is None:
            raise RuntimeError('VK 宿主未提供 _vk_ctx（rendercanvas wgpu 上下文）')
        return ctx.get_current_texture().create_view()

    def draw_screen_rect(self, rect, color):
        """屏幕像素填充矩形（VK）—— 与 loom_hud.HudMixin.draw_screen_rect 同签名同语义。

        GL：ctx.scope(framebuffer=fb, enable_only=BLEND) + u_origin/u_size quad
        （调用即画，无深度测试，alpha 生效）。VK：矩形两三角形，屏幕像素 -> NDC
        （y 翻转）后配恒等 VP 走 VkLineBatch 的 triangle-list + blend 批次：
          · 已在 overlay_scope 内 -> 收进 pending（随 scope flush，同批同语义）；
          · scope 外 -> 临时 pending 立即 flush（保持 GL「调用即画」时序，目标 =
            _screen_fb()，无深度附件 = 不测不写，与 GL enable_only=BLEND 等价）。
        """
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        a = (color[3] / 255.0) if len(color) > 3 else 1.0
        rgba = (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, a)
        W = float(getattr(self, 'width', 0) or 0)
        H = float(getattr(self, 'height', 0) or 0)
        if W <= 0 or H <= 0:
            return
        # 屏幕像素（左上原点，y 向下）-> NDC（[-1,1]，y 向上）。z=0（GL quad
        # 无深度写入，深度比较对无深度附件无意义；带附件的 scope 内由管线
        # always+不写表达「不测不写」，见 _pipeline 的 depth_on=False 语义）。
        x0 = 2.0 * x / W - 1.0
        x1 = 2.0 * (x + w) / W - 1.0
        y0 = 1.0 - 2.0 * y / H
        y1 = 1.0 - 2.0 * (y + h) / H
        verts = [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0),
                 (x0, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]
        cols = [rgba] * 6
        pend = getattr(self, '_vk_pending', None)
        if pend is not None:
            pend['draws'].append((_pack_lines(verts, cols), _IDENTITY4, 4, False))
            return
        # scope 外：临时 pending 立即 flush（GL 调用即画语义；深度批次不存在，
        # 不需要 _vk_overlay_depth_view —— 临时 pass 不挂深度附件）。
        self._vk_pending = {'view': self._screen_fb(), 'depth': False,
                            'blend': True, 'draws': []}
        try:
            self._vk_pending['draws'].append(
                (_pack_lines(verts, cols), _IDENTITY4, 4, False))
        finally:
            pend = self._vk_pending
            self._vk_pending = None
            self._flush_overlay(pend)
