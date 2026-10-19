# -*- coding: utf-8 -*-
"""loom_render.py — GLEngine 渲染管线子系统 (主 pass 帧准备 / 绘制 / 帧循环)。

从 engine.py 抽出 (作为 RenderMixin 供 GLEngine 继承):
  _clear_main_fbo         (清主渲染目标: 颜色+深度)
  _screen_fb              (当前渲染目标 FBO: pygame 窗口 / Qt 宿主 widget FBO)
  _prepare_bucket_frame   (每帧实例化批数据准备: f32 世界矩阵 + 桶重排 + 实例缓冲写入)
  _draw_main_buckets      (主 pass 实例化批绘制)
  render                  (渲染一帧: 逻辑/物理步进 -> 世界矩阵 -> 阴影 -> 主 pass -> HUD)
  run                     (pygame 主循环; 嵌入式 (Qt) 模式由宿主驱动, 不进本循环)

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self.ctx / self._external_ctx / self._external_fb / self.width / self.height
  self.models / self._render_buckets / self._bucket_geo / self._bucket_inst
  self._fw32 / self._bucket_mat_cache / self._bucket_grp_sig / self._bucket_frame_sig
  self._struct_gen / self._soa_last_keys / self._logic_gen / self._render_world
  self._interp / self._clock / self._vp / self._u_last
  self._prof_t0 / self._prof_add / self._profile
  self._mesh_key / self._build_bucket_geo / self._grow_bucket_inst
  self._upload_lights / self._uniform / self._render_shadow_maps / self._draw_hud
  self._parallel_shadow_and_collision / self.compute_render_matrices / self._consume_xform_gen
  self._ensure_split / self._framebuf_prefetch / self._update_fps
  self.active_camera_object / self.apply_camera / self.apply_orbit_camera
  self.camera / self.camera_yaw / self.camera_pitch / self.camera_roll / self._fov
  self.near / self.far / self.orbit_mode / self.ui
"""
import os
import time

import numpy as np
# 2026-10-18 A2: import pygame 已删（GLFW 窗口剥离；本文件不再引用 pygame 常量）
import moderngl

from matlib import mat4_perspective, mat4_view_yaw_pitch
from loom_game_object import GameObject


class RenderMixin:
    def _draw_skybox(self):
        """2026-10-19 第1档序13 天空盒（B1 先画几何后画天空, depth==1.0 才画）。

        用户拍板 A1+B1: 全屏 quad + fragment 反投影采样 cubemap。
        绘制时机: _draw_main_buckets 之后、_draw_hud 之前。
        深度机制:
          - 清屏时深度清成 1.0（_clear_main_fbo 已调用 clear）
          - 几何体绘制时写 depth <1.0，覆盖的像素深度被更新
          - 天空盒 quad 在 z=1.0（远平面），depth_func='<=' 允许等值通过
          - 几何覆盖的像素 depth<1.0 无法通过（1.0 > 实际深度）-> 跳过（无 overdraw）
        状态管理: 临时关 CULL_FACE（quad 从相机看是背面绕序）+ 不写 depth mask（防污染）。
        """
        if self._skybox is None:
            return
        # 2026-10-19 修复：编译失败用 False 哨兵（不是 None），避免每帧重试刷屏；
        # 同时不 nuke _skybox（保留数据，用户改 shader 后可 _sky_prog=None 恢复）。
        if self._sky_prog is False:
            return
        if self._sky_prog is None:
            from loom_shaders import _SKY_VERT, _SKY_FRAG
            try:
                self._sky_prog = self.ctx.program(
                    vertex_shader=_SKY_VERT, fragment_shader=_SKY_FRAG)
                # 2026-10-19 关键修复（天空盒一直是黑的根因）：
                # _SKY_VERT 只声明 in_pos（1 个 vec2），但旧代码绑 'in_pos','in_uv' 两个属性名
                # → moderngl 对未声明属性抛 KeyError → 被 except 吞掉 → 天空盒永久禁用。
                # 修复：只绑 in_pos，格式用 '2f 2x'（2x = 8 字节填充，跳过 UV，stride 仍 16）。
                self._sky_vao = self.ctx.vertex_array(
                    self._sky_prog, [(self._quad_vbo, '2f 2x', 'in_pos')])
                # sampler 单元固定 0（program 建后设一次即可）
                try:
                    self._sky_prog['u_skybox'].value = 0
                except Exception:
                    pass
            except Exception as e:
                print("[渲染] 天空盒 shader 编译失败: %r" % (e,))
                self._sky_prog = False   # 哨兵：永久跳过，但保留 _skybox 数据
                return
        # 反投影矩阵: inv(VP) —— numpy 行主序 tobytes 后 GLSL 按列解读 = M^T
        # 配合 GLSL 的 u_inv_view_proj * clip（列向量乘）恰好等价 numpy 行向量 v @ M
        try:
            inv_vp = np.linalg.inv(self._vp)
        except Exception:
            return
        self._sky_prog['u_inv_view_proj'].write(
            np.ascontiguousarray(inv_vp.astype('f4')).tobytes())
        cam_pos = (self.camera.x, self.camera.y, self.camera.z)
        self._sky_prog['u_camera_pos'].value = cam_pos
        self._sky_prog['u_skybox_tint'].value = self._skybox_tint
        # 绑定 cubemap 到单元 0
        try:
            self._skybox.ensure_gl(self.ctx)
            self._skybox.use(0)
        except Exception as e:
            print("[渲染] 天空盒 cubemap 绑定失败: %r" % (e,))
            return
        # 保存状态并临时修改
        try:
            old_depth_mask = self.ctx.depth_mask
            old_depth_func = self.ctx.depth_func
        except Exception:
            old_depth_mask, old_depth_func = True, '<'
        try:
            self.ctx.depth_mask = False
            self.ctx.depth_func = '<='
            self.ctx.disable(moderngl.CULL_FACE)
            self._sky_vao.render(moderngl.TRIANGLES, vertices=6)
        finally:
            self.ctx.depth_mask = old_depth_mask
            self.ctx.depth_func = old_depth_func
            self.ctx.enable(moderngl.CULL_FACE)

    # ================ World Space UI（2026-10-19 第1档序3阶段4）================
    def _draw_world_canvases(self):
        """World Space UI：把 canvas_type='world' 的 Canvas 离屏渲染成纹理，
        再在 3D 世界贴 quad（用户拍板 A 离屏纹理贴 quad 路线）。

        朝向由 Canvas.billboard 决定：
          - True（默认）：永远正对相机（血条/名字常用）
          - False：跟随 target GameObject 的旋转（告示牌常用）
        缩放由 Canvas.world_scale 决定（默认 0.01 = 100px = 1m，Unity 对齐）。
        交互（点击）留到第2档，当前只渲染不拾取。
        """
        if getattr(self, 'ui', None) is None:
            return
        world_canvases = [c for c in self.ui.canvases
                          if getattr(c, 'canvas_type', 'screen') == 'world']
        if not world_canvases:
            return
        # 惰性建 program / vao（4 顶点动态 buffer：3f world_pos + 2f uv）
        if getattr(self, '_world_ui_prog', None) is None:
            try:
                from loom_shaders import _WORLD_UI_VERT, _WORLD_UI_FRAG
                self._world_ui_prog = self.ctx.program(
                    vertex_shader=_WORLD_UI_VERT, fragment_shader=_WORLD_UI_FRAG)
                self._world_ui_vbo = self.ctx.buffer(reserve=4 * 5 * 4)
                self._world_ui_vao = self.ctx.vertex_array(
                    self._world_ui_prog,
                    [(self._world_ui_vbo, '3f 2f', 'in_world_pos', 'in_uv')])
                try:
                    self._world_ui_prog['u_tex'].value = 0
                except Exception:
                    pass
            except Exception as e:
                print("[渲染] World UI shader 编译失败: %r" % (e,))
                self._world_ui_prog = None
                return
        # 相机 right/up（billboard 用）：view 矩阵行 0/1 即基向量
        V = mat4_view_yaw_pitch(np,
                                (self.camera.x, self.camera.y, self.camera.z),
                                self.camera_yaw, self.camera_pitch,
                                self.camera_roll)
        cam_right = (float(V[0, 0]), float(V[0, 1]), float(V[0, 2]))
        cam_up = (float(V[1, 0]), float(V[1, 1]), float(V[1, 2]))
        models_by_id = {id(m): m for m in self.models}
        for c in world_canvases:
            try:
                self._draw_one_world_canvas(c, cam_right, cam_up, models_by_id)
            except Exception as e:
                print("[渲染] World Canvas 绘制失败: %r" % (e,))

    def _draw_one_world_canvas(self, c, cam_right, cam_up, models_by_id):
        """单个 world Canvas 的完整绘制：离屏渲染 -> 3D quad 贴图."""
        target = getattr(c, 'target', None)
        if target is None or id(target) not in models_by_id:
            return   # target 未绑定/已被删除 -> 跳过
        # 离屏纹理（每 Canvas 一个，尺寸变化时重建）
        cur_size = (int(c.width), int(c.height))
        if (getattr(c, '_gl_tex', None) is None
                or getattr(c, '_gl_tex_size', None) != cur_size):
            old_fbo = getattr(c, '_gl_fbo', None)
            old_tex = getattr(c, '_gl_tex', None)
            try:
                if old_fbo is not None:
                    old_fbo.release()
                if old_tex is not None:
                    old_tex.release()
            except Exception:
                pass
            try:
                c._gl_tex = self.ctx.texture(cur_size, 4)
                c._gl_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                c._gl_fbo = self.ctx.framebuffer(color_attachments=[c._gl_tex])
                c._gl_tex_size = cur_size
            except Exception as e:
                print("[渲染] World UI 离屏纹理创建失败: %r" % (e,))
                c._gl_tex = None
                return
        # 离屏渲染：临时让 _screen_fb() 返回离屏 FBO，UI 绘制全部落到纹理
        old_ext_ctx = getattr(self, '_external_ctx', False)
        old_ext_fb = getattr(self, '_external_fb', None)
        old_w, old_h = self.width, self.height
        render_ok = True
        try:
            self._external_ctx = True
            self._external_fb = c._gl_fbo
            self.width = cur_size[0]
            self.height = cur_size[1]
            c._gl_fbo.use()
            self.ctx.viewport = (0, 0, cur_size[0], cur_size[1])
            self.ctx.scissor = None
            self.ctx.clear(0.0, 0.0, 0.0, 0.0)   # 透明底：透明处不遮挡场景
            self.ui._draw_elem(
                c.root, self, (0.0, 0.0, float(cur_size[0]), float(cur_size[1])))
        except Exception as e:
            print("[渲染] World UI 离屏渲染失败: %r" % (e,))
            render_ok = False
        finally:
            self._external_ctx = old_ext_ctx
            self._external_fb = old_ext_fb
            self.width = old_w
            self.height = old_h
            self.ctx.viewport = (0, 0, old_w, old_h)
            self._screen_fb().use()
        if not render_ok:
            return
        # 3D 世界坐标 + 4 角（世界尺度由 world_scale 换算）
        center = self.world_position(target)
        if getattr(c, 'billboard', True):
            right, up = cam_right, cam_up
        else:
            try:
                W = self.world_rotation_matrix(target)
                right = (float(W[0, 0]), float(W[0, 1]), float(W[0, 2]))
                up = (float(W[1, 0]), float(W[1, 1]), float(W[1, 2]))
            except Exception:
                right, up = cam_right, cam_up
        scale = float(getattr(c, 'world_scale', 0.01))
        hw = cur_size[0] * scale * 0.5
        hh = cur_size[1] * scale * 0.5
        cx, cy, cz = center.x, center.y, center.z

        def corner(rx, ry):
            return (cx + right[0] * rx + up[0] * ry,
                    cy + right[1] * rx + up[1] * ry,
                    cz + right[2] * rx + up[2] * ry)

        TL = corner(-hw, +hh)
        TR = corner(+hw, +hh)
        BL = corner(-hw, -hh)
        BR = corner(+hw, -hh)
        # 顶点数据（TRIANGLE_STRIP: TL, BL, TR, BR）
        import struct
        verts = struct.pack(
            '20f',
            TL[0], TL[1], TL[2], 0.0, 1.0,
            BL[0], BL[1], BL[2], 0.0, 0.0,
            TR[0], TR[1], TR[2], 1.0, 1.0,
            BR[0], BR[1], BR[2], 1.0, 0.0,
        )
        self._world_ui_vbo.write(verts)
        self._world_ui_prog['u_view_proj'].write(
            np.ascontiguousarray(self._vp.astype('f4')).tobytes())
        # 绘制（透明像素不遮挡场景 + 双面可见 + 不写深度）
        old_depth_mask = self.ctx.depth_mask
        try:
            self.ctx.depth_mask = False
            self.ctx.disable(moderngl.CULL_FACE)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = (moderngl.SRC_ALPHA,
                                   moderngl.ONE_MINUS_SRC_ALPHA)
            c._gl_tex.use(0)
            self._world_ui_vao.render(moderngl.TRIANGLE_STRIP, vertices=4)
        finally:
            self.ctx.depth_mask = old_depth_mask
            self.ctx.enable(moderngl.CULL_FACE)
            self.ctx.disable(moderngl.BLEND)


    def _clear_main_fbo(self, r, g, b, a=1.0):
        """清主渲染目标 (颜色+深度). pygame 与 Qt 外部模式同一路径.
        2026-08-18 关键结论: 之前"ctx.clear 在 Qt 多采样 FBO 无效"是误判 ——
        实际是 moderngl scope 退出把 framebuffer 绑定破坏成 0 (窗口默认 FBO),
        clear 清到了 id 0 所以看不到. 宿主 (qt_view.paintGL) 每帧缓存 widget FBO
        到 _external_fb, 绑定它再 clear 完全有效 (含 depth=1.0 清深度到 far).
        深度每帧清到 far 是物体稳定渲染的前提 (否则深度残留/初始 0 会把物体
        和网格线全部 LESS 剔除: 静止消失/转动闪烁)."""
        if getattr(self, '_external_ctx', False):
            self._screen_fb().use()
            self.ctx.clear(r, g, b, a, depth=1.0)
            return
        self.ctx.clear(r, g, b, a)

    def _screen_fb(self):
        """当前渲染目标 FBO. pygame 模式 = ctx.screen (窗口默认 FBO);
        嵌入式模式 (Qt QOpenGLWidget) = 宿主缓存的 widget FBO (qt_view.paintGL
        每帧开头 detect 并写入 self._external_fb). 2026-08-18 关键: moderngl
        scope 退出会把绑定恢复成 id 0, detect_framebuffer() 只拿"当前绑定"——
        若已被破坏成 0 就画到 0 (不可见). 统一走缓存."""
        if getattr(self, '_external_ctx', False):
            fb = getattr(self, '_external_fb', None)
            return fb if fb is not None else self.ctx.detect_framebuffer()
        return self.ctx.screen

    # ================ A2: 实例化批绘制帧准备 / 主 pass 绘制 ================
    def _update_lod(self):
        """M36 LOD (2026-10-14): 按相机距离为配了 lod_levels 的物体切换网格精度。
        无 lod_levels 的物体零开销 (getattr 检查)。级别按距离升序, 选首个 dist<=限 的级别;
        超出最后一级用最后一级 (最粗)。切换走 GameObject.mesh/primitive/params setter
        (bump 结构+外观 -> 下帧重分桶, 桶几何随之换精度)。_lod_cur 防每帧重复切换。"""
        models = self.models
        fw = getattr(self, '_frame_world', None)
        if not models or fw is None:
            return
        cam = self.camera
        cx, cy, cz = cam.x, cam.y, cam.z
        import math as _math
        tan_half = _math.tan(self._fov * 0.5)      # 屏幕占比用垂直 FOV
        for i, m in enumerate(models):
            r = getattr(m, 'renderer', None)
            if r is None:
                continue
            lv_screen = getattr(r, 'lod_screen_levels', None)
            lv_dist = getattr(r, 'lod_levels', None)
            if not lv_screen and not lv_dist:
                continue
            row = fw[i]
            dx = float(row[3][0]) - cx
            dy = float(row[3][1]) - cy
            dz = float(row[3][2]) - cz
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if lv_screen:
                # 屏幕占比模式 (对标 Unity LODGroup): ratio = 半径 / (距离 × tan(fov/2))
                rad = getattr(r, '_lod_radius', None)
                if rad is None:
                    _v = np.asarray(getattr(m.mesh, 'vertices', []), dtype=np.float64)
                    rad = float(np.sqrt((_v * _v).sum(axis=1)).max()) if len(_v) else 1.0
                    r._lod_radius = rad
                denom = max(dist, 1e-3) * tan_half
                bias = float(getattr(r, 'lod_bias', 1.0) or 1.0)
                ratio = (rad / denom) * bias
                pick = lv_screen[-1][1]
                for thr, mesh in lv_screen:         # 阈值降序, 选首个 ratio>=thr
                    if ratio >= thr:
                        pick = mesh
                        break
            else:
                pick = lv_dist[-1][1]               # 距离模式: 升序, 选首个 dist<=lim
                for lim, mesh in lv_dist:
                    if dist <= lim:
                        pick = mesh
                        break
            if getattr(r, '_lod_cur', None) is not pick:
                r._lod_cur = pick
                m.mesh = pick
                m.primitive = getattr(pick, 'primitive', None)
                m.params = getattr(pick, 'params', None)

    def _frustum_planes(self, vp):
        """从 view-proj 提取 6 个视锥平面 (行向量约定 clip = p @ vp)。
        返回归一化 (6,4): 平面 a*x+b*y+c*z+d>=0 为视锥内侧 (Gribb-Hartmann)。"""
        m = np.asarray(vp, dtype=np.float64).reshape(4, 4)
        rows = np.stack([m[:, 3] + m[:, 0],   # left
                         m[:, 3] - m[:, 0],   # right
                         m[:, 3] + m[:, 1],   # bottom
                         m[:, 3] - m[:, 1],   # top
                         m[:, 3] + m[:, 2],   # near
                         m[:, 3] - m[:, 2]])  # far
        n = np.linalg.norm(rows[:, :3], axis=1, keepdims=True)
        n = np.where(n < 1e-12, 1.0, n)
        return rows / n

    def _spheres_in_frustum(self, centers, radius, planes):
        """球(中心 centers (k,3), 统一半径 radius)是否与视锥相交 -> (k,) bool。
        保守: 球心到每个内侧平面距离 >= -radius 即可能可见 (不误剔)。"""
        vis = np.ones(centers.shape[0], dtype=bool)
        for a, b, c, d in planes:
            dist = centers[:, 0] * a + centers[:, 1] * b + centers[:, 2] * c + d
            vis &= (dist >= -radius)
        return vis

    def _frustum_keep(self, world_rows, planes, radius):
        """桶实例可见性: world_rows (k,4,4) 行向量约定 (物体中心 = 行[:,3,:3]),
        半径=网格最大顶点距。返回 (k,) bool (保守, 不误剔)。"""
        centers = np.asarray(world_rows, dtype=np.float64)[:, 3, :3]
        return self._spheres_in_frustum(centers, radius, planes)

    def _prepare_bucket_frame(self):
        """A2 (2026-08-29) 每帧一次: 当帧世界矩阵 f32 化 + 按 mesh 桶重排 +
        桶级实例缓冲写入 (主 pass 96B/实例: world16+sat4+color4; 阴影 64B:
        world16 与主 pass 共享同一批矩阵). 主 pass/阴影 pass 桶序一致,
        两 pass 都只做"每桶一次 draw" (逐物体 uniform+draw 循环已取消).
        组1 (2026-08-30): 消每帧逐物体属性链/hex 解析 (Material._rgba/
        _sat_f32 缓存) + 消每帧 np.zeros 分配 (staging 随桶持久, 原地写)
        + write 零拷贝 (memoryview 切片, 免 tobytes 全量拷贝).
        GC 批 (2026-09-01): _fw32 改持久容量缓冲 (cap>=n, 仅扩容帧分配), f64→f4
        走原地赋值 cast (与 ascontiguousarray 同一 RNE 舍入, 逐位一致); 桶内花式
        索引改 np.take(..., out=持久 gather 缓冲, mode='clip') —— 消每帧
        1×(n,4,4) + 每桶 2×(k,4,4) f4 临时分配; sha 写复用同一份 gather 缓冲
        (主/阴影上传字节与旧路径逐位相同). 消费方一律 [:n]/[:k] 切片读取,
        cap-n 残留行不被消费 (与旧行为一致)."""
        # 分离批2: 桶/实例/绘制消费渲染矩阵 (插值); _frame_world 保持逻辑
        # 位姿 (碰撞/阴影共享源, R3). 分离未开 = _render_world 即逻辑矩阵
        # (compute_render_matrices 内部回退) — 行为与旧逐位一致.
        fw = getattr(self, '_render_world', None)
        if fw is None:
            fw = self._render_world = self.compute_render_matrices(self.models)
        # 组6件1 (2026-09-02): 桶实例数据 _dirty 总闸 —— 三类脏信号任一为真才
        # 重排/重填/上传, 否则整段跳过 (上帧实例缓冲与 _render_buckets 原样保留,
        # 相机/灯光/VP 变化不影响实例数据):
        #   ① 结构: _struct_gen (增删/挂父/换 mesh/normal/params 均会 bump 或换键);
        #   ② 外观: GameObject._appearance_gen (Material.color/saturation/visible/mesh);
        #   ③ 变换: 变换对象 id keys 失配 (件4 快照 keys, Point3D 不可变改值必换对象).
        # 保守取向: 桶重排本身极廉价 (50-500 物体 µs 级), 闸只挡"整段实例上传";
        # 漏脏=渲染错误, 宁可多提交不可少提交 (信号面按构造穷尽, 无启发式).
        n = fw.shape[0]
        # 视锥剔除 (2026-10-14): 主 pass 只画视锥内实例 (阴影仍全量)。
        # 用上帧 self._vp (相机静止帧精确; 移动帧保守外扩不误剔)。
        # ★B7b (2026-10-16): 关剔除改设置项 frustum_cull=false (排错后门;
        #   原 LOOM_NO_FRUSTUM env 已退役)。
        planes = None
        if getattr(self, '_frustum_cull', True):
            vp = getattr(self, '_vp', None)
            if vp is not None:
                try:
                    planes = self._frustum_planes(vp)
                except Exception:
                    planes = None
        stamp3 = (getattr(self, '_struct_gen', 0), GameObject._appearance_gen)
        keys = getattr(self, '_soa_last_keys', None)   # 件4 快照已暴露当帧 keys
        bk = getattr(self, '_bucket_frame_sig', None)
        # 分离批2 (D4): 闸加 pose 维 — 分离模式插值平面逐渲染帧可能变化而
        # keys 不变; pose=(alpha, 逻辑步计数, 静止判定): 逻辑帧跑了→强制重填;
        # 静止帧 (prev==curr) 插值输出恒等→闸仍命中 (保留静止免上传红利).
        it = getattr(self, '_interp', None)
        if it is not None:
            pose = (round(it.alpha, 6), getattr(self, '_logic_gen', 0),
                    it.static_frame())
        else:
            pose = ()
        # 视锥剔除 (2026-10-14): 相机纳入脏闸签名 —— 相机移动时可见子集变,
        # 需重排/重传主缓冲 (阴影全量不受相机影响)。相机静止 -> 命中复用。
        _cam_sig = None
        if planes is not None:
            _cam_sig = (round(self.camera.x, 4), round(self.camera.y, 4),
                        round(self.camera.z, 4), round(self.camera_yaw, 5),
                        round(self.camera_pitch, 5), round(self.camera_roll, 5))
        sig = (stamp3, keys, pose, _cam_sig)
        if bk is not None and bk == sig and self._render_buckets:
            return
        self._bucket_frame_sig = sig
        buf = self._fw32
        if buf is None or buf.shape[0] < n:
            cap = max(64, n) if buf is None else max(n, buf.shape[0] * 2)
            buf = self._fw32 = np.empty((cap, 4, 4), dtype='f4')
        buf[:n] = fw                       # f64→f4 原地 cast (RNE, 与 astype 逐位同)
        fw32 = buf
        buckets = {}
        # ★M3-P2: 桶分组缓存 —— 分组只依赖 (结构 stamp, 外观 stamp) [visible/mesh/
        #   material 均在 GameObject._appearance_gen 覆盖面内], 与位姿无关; 播放态
        #   位姿每帧变 (脏闸必开) 但分组通常不变 → 省掉每帧 501 次属性链 + dict 分组。
        #   实测该段属 buckets 1.35 ms/帧 的主体 (物证 mt_profile_on_p1b.json)。
        if (getattr(self, '_bucket_grp_sig', None) != stamp3
                or not getattr(self, '_render_buckets', None)):
            for i, m in enumerate(self.models):
                if m.visible and m.mesh is not None:
                    buckets.setdefault(self._mesh_key(m), []).append(i)
            self._render_buckets = list(buckets.items())
            self._bucket_grp_sig = stamp3
            # ★M3-P4: 每实例材质列 (sat / rgba) 一并缓存 —— 它们只依赖外观
            #   (Material.color/saturation 走 _appearance_gen), 与位姿无关。
            #   原每帧 501 次属性链 + 逐行标量写, 现改为向量化整块赋值。
            mats = {}
            for key, idxs in self._render_buckets:
                kk = len(idxs)
                sat = np.empty(kk, dtype='f4')
                col = np.zeros((kk, 4), dtype='f4')
                for q, i in enumerate(idxs):
                    mat = self.models[i].renderer.material
                    sat[q] = mat._sat_f32
                    r = mat._rgba                  # Material setter 已算; None=网格面色
                    if r is not None:
                        col[q] = r
                mats[key] = (sat, col)
            self._bucket_mat_cache = mats
            # M36 贴图: 每桶 albedo/normal GL 纹理 (桶键含 guid -> 同桶同贴图)
            alb = {}
            nrm = {}
            for key, idxs in self._render_buckets:
                mat = self.models[idxs[0]].renderer.material
                tex = getattr(mat, 'albedo', None)
                try:
                    alb[key] = tex.ensure_gl(self.ctx) if tex is not None else None
                except Exception:
                    alb[key] = None
                ntex = getattr(mat, 'normal_map', None)
                try:
                    nrm[key] = ntex.ensure_gl(self.ctx) if ntex is not None else None
                except Exception:
                    nrm[key] = None
            self._bucket_albedo = alb
            self._bucket_normal = nrm
            # M36 环境反射: 每桶 env cubemap GL (材质级)
            env = {}
            for key, idxs in self._render_buckets:
                mat = self.models[idxs[0]].renderer.material
                etex = getattr(mat, 'env_map', None)
                try:
                    env[key] = etex.ensure_gl(self.ctx) if etex is not None else None
                except Exception:
                    env[key] = None
            self._bucket_env = env
        mats = getattr(self, '_bucket_mat_cache', None) or {}
        for key, idxs in self._render_buckets:
            ent = self._bucket_geo.get(key)
            if ent is None:                    # 防御: 桶资源未建 (attach 路径遗漏)
                ent = self._build_bucket_geo(key, self.models[idxs[0]])
            k = len(idxs)
            self._grow_bucket_inst(key, k)
            inst = self._bucket_inst[key]
            st = inst.get('stage')
            if st is None:                     # 组1: staging 随桶持久 (release 一并清)
                st = inst['stage'] = np.zeros((inst['n'], 24), dtype='f4')
            elif st.shape[0] < k:              # _grow_bucket_inst 已扩容, stage 跟随
                st = inst['stage'] = np.zeros((inst['n'], 24), dtype='f4')
            g = inst.get('gath')               # GC 批: 持久 gather 缓冲 (与 stage 同寿命)
            if g is None:
                g = inst['gath'] = np.empty((inst['n'], 4, 4), dtype='f4')
            elif g.shape[0] < k:
                g = inst['gath'] = np.empty((inst['n'], 4, 4), dtype='f4')
            # ★M3 DLL 剥离: 优先走 pipeline.dll 原生 C 打包 (消灭 take+切片分配)
            packed = False
            _fr_culled = False
            if planes is not None and k > 1:
                # 视锥剔除路径: 主 pass 只画视锥内实例 (重排到前部), 阴影全量。
                np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')
                mr = getattr(self, '_bucket_radius', None)
                if mr is None:
                    mr = self._bucket_radius = {}
                r = mr.get(key)
                if r is None:
                    _mesh = self.models[idxs[0]].mesh
                    _v = np.asarray(_mesh.vertices, dtype=np.float64)
                    r = float(np.sqrt((_v * _v).sum(axis=1)).max()) if len(_v) else 1.0
                    mr[key] = r
                keep = self._frustum_keep(g[:k], planes, r)
                n_main = int(keep.sum())
                if not hasattr(self, '_main_bucket_n'):
                    self._main_bucket_n = {}
                self._main_bucket_n[key] = n_main
                inst['sha'].write(g[:k], 0)        # 阴影: 全量实例 (不动)
                if n_main:
                    sel = np.where(keep)[0]
                    gm = g[:k][sel]
                    st[:n_main, 0:16] = gm.reshape(n_main, 16)
                    mc = mats.get(key)
                    if mc is not None and mc[0].shape[0] == k:
                        st[:n_main, 16] = mc[0][sel]
                        st[:n_main, 20:24] = mc[1][sel]
                    else:
                        st[:n_main, 16] = 0.0
                        st[:n_main, 20:24] = 0.0
                    inst['main'].write(st[:n_main], 0)
                packed = True
                _fr_culled = True
            if not packed and not getattr(self, '_no_bucket_pack_dll', False):
                try:
                    import pipeline_glue as _pg
                    mc = mats.get(key)
                    sat = mc[0] if (mc is not None and mc[0].shape[0] == k) else None
                    rgba = mc[1] if (mc is not None and mc[1].shape[0] == k) else None
                    if _pg.pack_bucket_instances(fw32, n, idxs, sat, rgba, st[:k], g[:k]) == 0:
                        packed = True
                except Exception:
                    packed = False
            if not packed:
                np.take(fw32, idxs, axis=0, out=g[:k], mode='clip')
                st[:k, 0:16] = g[:k].reshape(k, 16)
                mc = mats.get(key)
                if mc is not None and mc[0].shape[0] == k:
                    st[:k, 16] = mc[0]
                    st[:k, 20:24] = mc[1]
                else:
                    st[:k, 16] = 0.0
                    st[:k, 20:24] = 0.0                # color=None 的实例留 0 (旧语义)
            if not _fr_culled:
                if not hasattr(self, '_main_bucket_n'):
                    self._main_bucket_n = {}
                self._main_bucket_n[key] = k
                inst['main'].write(st[:k], 0)      # moderngl 吃 buffer 协议, 部分写入
                inst['sha'].write(g[:k], 0)        # 同一 gather 缓冲 = 旧 _fw32[idxs] 同字节

    def _draw_main_buckets(self):
        """A2: 主 pass 实例化批绘制 —— 每桶一次 draw (旧法: 每物体
        u_model/u_saturation uniform + 单独 draw)."""
        if os.environ.get('LOOM_PROFILE') == '1':
            self._draw_calls_total = getattr(self, '_draw_calls_total', 0) + \
                len(self._render_buckets)
        mbn = getattr(self, '_main_bucket_n', None) or {}
        alb = getattr(self, '_bucket_albedo', None) or {}
        nrm = getattr(self, '_bucket_normal', None) or {}
        env = getattr(self, '_bucket_env', None) or {}
        # M36: u_albedo=单元0, u_normal_map=单元1, u_env=单元2 (每帧设一次)
        try:
            self.prog['u_albedo'].value = 0
            self.prog['u_normal_map'].value = 1
            self.prog['u_env'].value = 2
            # M36 PBR 全局开关 (★B7b 2026-10-16: 改设置项 pbr_enabled=false, 排错后门;
            #   原 LOOM_NO_PBR env 已退役; 材质级 u_material_pbr 仍门控)
            self.prog['u_pbr_mode'].value = (1.0 if getattr(self, '_pbr_enabled', True)
                                             else 0.0)
        except Exception:
            pass
        white = self._white_gl_tex()
        for key, idxs in self._render_buckets:
            ent = self._bucket_geo.get(key)
            if ent is None or ent['vao'] is None:
                continue
            cnt = mbn.get(key, len(idxs))
            if cnt <= 0:
                continue
            tex = alb.get(key) or white
            if tex is not None:
                tex.use(0)
            ntex = nrm.get(key)
            try:
                self.prog['u_has_normal_map'].value = 1.0 if ntex is not None else 0.0
            except Exception:
                pass
            if ntex is not None:
                ntex.use(1)
            # M36 PBR: 每桶设材质级 PBR uniform (从桶键取, 同桶一致)
            try:
                _pbr = key[5] if len(key) > 5 else (0.0, 0.5, 0)
                self.prog['u_metallic'].value = float(_pbr[0])
                self.prog['u_roughness'].value = float(_pbr[1])
                self.prog['u_material_pbr'].value = float(_pbr[2])
            except Exception:
                pass
            # M36 环境反射: 每桶绑 env cubemap (单元 2)
            etex = env.get(key)
            try:
                self.prog['u_has_env'].value = 1.0 if etex is not None else 0.0
            except Exception:
                pass
            if etex is not None:
                etex.use(2)
                try:
                    import math as _m
                    self.prog['u_env_max_lod'].value = float(
                        max(0, int(_m.log2(etex.size[0]))))
                except Exception:
                    pass
            ent['vao'].render(moderngl.TRIANGLES, instances=cnt)

    def _white_gl_tex(self):
        """M36: 1x1 白纹理 GPU 资源 (延迟创建, 需 current context)。"""
        tex = getattr(self, '_white_tex', None)
        if tex is not None:
            return tex
        try:
            import numpy as _np
            tex = self.ctx.texture((1, 1), 4, dtype='f1')
            tex.write(_np.array([255, 255, 255, 255], dtype='uint8').tobytes())
            self._white_tex = tex
        except Exception:
            self._white_tex = None
        return self._white_tex

    def render(self, delta_time):
        """渲染一帧 (分离批1): 时钟 advance 排 0~N 逻辑步 + 0~M 物理步 ->
        世界矩阵 -> 阴影 pass -> MVP -> GPU 绘制 -> HUD -> 交换缓冲.
        logic_fps<=0: 旧绑死模式 (四段直跑, 行为同旧; ★B7b 2026-10-16 删 LOOM_NO_SPLIT env).
        分离批3: 宿主若已调 advance_logic (编辑器 paintGL), 本帧不重复推进."""
        # 脚本 (M27): PlayerApp (--run 运行时) 每次渲染都跑脚本 —— 打包的游戏才会动.
        # 编辑器 (EditorApp) 覆写本方法, 只在播放模式调 update_scripts.
        # M32: 鼠标相对移动 (玩家控制器转向用).
        # 2026-10-18 A2: GLFW 下 mouse_rel 由 _handle_events 的 _update_mouse_rel
        # 维护（光标禁用模式用 cursor_pos 差值），外部模式（Qt 编辑器）由宿主喂。
        # TPS 缓冲: 帧首打点 (渲染帧尾预取预算=帧已消耗墙钟的基准)
        self._frame_start = time.perf_counter()
        # ★M3 插桩: 帧计数 + render() 总耗时 (paintgl_total 的对照项)
        self._stage_frames = getattr(self, '_stage_frames', 0) + 1
        _t_render = self._prof_t0()
        # 2026-08-16 相机物体化: 挂父激活相机每帧重应用 -> 世界位姿随父移动
        # (Unity 父子语义). 仅挂父相机触发; 根相机/无激活相机行为不变; 脚本在
        # _run_scripts 里后写仍覆盖 (玩家控制器契约不变).
        _cam = self.active_camera_object()
        if _cam is not None and _cam.parent is not None:
            self.apply_camera(_cam)
        if self._ensure_split() is not None:
            # 分离模式: 宿主已推进 (批3 advance_logic) 则跳过; 否则在此推进
            # (批1: run()/--bench/测试直调一处生效). 输入采集已在渲染帧.
            # 批5: F9 暂停/F10 步进与 advance_logic 同一套判定 (直调路径
            # 一处生效 — 暂停=零逻辑+alpha0; 步进=step_once 恰好 1 帧).
            clk = self._clock
            # 核心任务流水线彻底解耦 (2026-10-01):
            # 仅在 Qt 宿主激活异步线程 (_external_ctx=True) 时由独立逻辑流水线推进;
            # 无头探针/直调测试环境 (_external_ctx=False) 由主线程同步推进 (防无头死锁)。
            is_async_active = getattr(self, '_logic_async', False) and getattr(self, '_external_ctx', False)
            if not is_async_active:
                if not getattr(self, '_advanced_this_frame', False):
                    if getattr(self, '_logic_paused', False):
                        if getattr(self, '_step_requested', False):
                            self._step_requested = False
                            self._profile('logic_step', lambda: clk.step_once())
                            self._logic_steps = clk.steps
                        else:
                            self._logic_steps = 0
                            it0 = getattr(self, '_interp', None)
                            if it0 is not None:
                                it0.alpha = 0.0
                    else:
                        self._profile('logic_step',
                                      lambda: clk.advance(delta_time))
                        self._logic_steps = clk.steps        # HUD/对拍用
            self._advanced_this_frame = False   # 消费本帧标记
            # 分离批2: 时钟 alpha -> 插值层 (插值与时钟解耦, 批3 可独立设)
            it = getattr(self, '_interp', None)
            if it is not None and not getattr(self, '_logic_paused', False):
                it.alpha = clk.alpha
        else:
            # 逃生门: 旧绑死模式逐位复现 (脚本→物理→音频→动画, 原 4241-4248)
            self._run_scripts(delta_time)
            # M31: 刚体步进 (碰撞事件延迟到矩阵后与阴影 VP 并行; 直调方仍 events=True)
            self._profile('physics',
                          lambda: self.update_physics(delta_time, events=False))
            # M34: AudioSource 组件播放状态同步
            self.update_audio(delta_time)
            # M35: 动画推进 (关键帧插值应用变换)
            self.update_animations(delta_time)
        # 2026-10-18 阶段1档序11 LateUpdate：两模式汇合后、世界矩阵重算前派发
        # （分离模式逻辑帧已跑完 → 此处即"所有 update 之后"；非分离模式 483-490 刚跑完）
        self._dispatch_late_update(delta_time)
        # 编辑态插值失同步修复 (2026-09-06): 物体被直接改位 → 快照对齐
        self._consume_xform_gen()
        # 多核优化: 当帧批量世界矩阵 (脚本/物理已改位形, 阴影与主 pass 共享同一批)
        self._frame_world = self._profile(
            'world_matrices', lambda: self.compute_world_matrices(self.models))
        # M36 LOD: 按相机距离切换网格精度 (无 LOD 物体零开销)
        self._profile('lod', lambda: self._update_lod())
        # 分离批2: 渲染矩阵 (插值) 与逻辑矩阵分账 (R3); 批5: 静止帧复用上帧
        # 对象 (static_frame 命中 → 插值输出逐位同上帧, 跳 S@R@T+层级 matmul)
        it = getattr(self, '_interp', None)
        if (it is not None and getattr(self, '_render_world', None) is not None
                and it.static_frame()):
            pass                            # 静止: _render_world 原样复用
        else:
            self._render_world = self._profile(
                'interp', lambda: self.compute_render_matrices(self.models))
        # 批5: 阴影/碰撞 prep 在逻辑帧尾已缓存; 渲染帧只派发事件+挂 VP
        # (旧路径逐位保留在 _parallel_shadow_and_collision 逃生门/编辑态分支)
        self._profile('shadow_prep',
                      lambda: self._parallel_shadow_and_collision(delta_time,
                                                                  with_events=True))
        # A2: 当帧实例数据准备 (f32 矩阵 + 桶重排 + 桶级实例缓冲写入), 阴影/
        # 主 pass 共享同一批桶 (旧逐物体 uniform/upload 循环已取消)
        # 2026-09-01 组8 插桩: buckets 子阶段 (原未插桩, 残段口径闭合用)
        self._profile('buckets', lambda: self._prepare_bucket_frame())
        # M29: 先画完全部阴影贴图, 主 pass 再采样到物理遮挡
        _t = self._prof_t0()
        self._render_shadow_maps()
        self._prof_add('mt_shadow_maps', _t)

        _t = self._prof_t0()
        self._screen_fb().use()
        self._clear_main_fbo(0.05, 0.05, 0.1, 1.0)
        # MVP: 每帧 CPU 算一次 view_proj, 每模型 model.
        # uniform 上传: matlib 是行向量约定 v@M (numpy M 存的是标准矩阵的转置),
        # 要 GLSL 的 u*v 等价 numpy 的 v@M, GPU 需得 M^T = 行主序 M 直接 tobytes (不转置).
        if self.orbit_mode:
            self.apply_orbit_camera()
        V = mat4_view_yaw_pitch(np, (self.camera.x, self.camera.y, self.camera.z),
                                self.camera_yaw, self.camera_pitch, self.camera_roll)
        P = mat4_perspective(np, self._fov, self.width / self.height, self.near, self.far)
        self._vp = V @ P                                      # 供 draw_lines / 射线拾取
        # 组6件3: u_view_proj / u_view_pos 差分上传 (相机静止帧跳过 GL 调用)
        vp4 = self._vp.astype('f4').tobytes()
        if self._u_last.get('u_view_proj') != vp4:
            self._uniform('u_view_proj').write(vp4)
            self._u_last['u_view_proj'] = vp4
        self._upload_lights()
        campos = (self.camera.x, self.camera.y, self.camera.z)
        if self._u_last.get('u_view_pos') != campos:
            self._uniform('u_view_pos').value = campos
            self._u_last['u_view_pos'] = campos

        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.CULL_FACE)
        # A2: 主 pass 实例化批绘制 (桶已在 _prepare_bucket_frame 备好)
        self._draw_main_buckets()
        # 2026-10-19 第1档序13 天空盒: 几何后、HUD 前（B1 depth==1.0 才画）
        if self._skybox is not None:
            self._draw_skybox()
        # 2026-10-19 第1档序3阶段4 World Space UI: 天空盒后、HUD 前
        self._draw_world_canvases()
        self._prof_add('mt_main_pass', _t)

        _t = self._prof_t0()
        self._draw_hud()
        if getattr(self, 'ui', None) is not None:
            self.ui.draw_all(self)  # 2026-10-18: Canvas UI (保留模式, 元素树渲染)
        self._prof_add('mt_hud', _t)
        _t = self._prof_t0()
        self._update_fps()
        # TPS 缓冲 (2026-09-06): 渲染帧尾富余预取 (与 editor.render 同款挂点);
        # FPS 预画帧 (_preframing) 不预取 — 它不是真实节拍帧
        if not getattr(self, '_preframing', False):
            self._framebuf_prefetch(getattr(self, '_frame_start', time.perf_counter()))
        if not self._external_ctx:      # 外部模式: 宿主 (QOpenGLWidget) 自动交换缓冲
            self._glfw_swap_buffers()   # 2026-10-18 A2: GLFW swap（原 pygame.display.flip）
        self._prof_add('mt_render_tail', _t)
        self._prof_add('mt_render_total', _t_render)


    # ================ 主循环 ================
    def run(self):
        """主运行循环. 嵌入式模式 (Qt 宿主) 由宿主驱动渲染, 不进入本循环."""
        if self._external_ctx:
            print("[engine] 嵌入式模式: 主循环由宿主驱动, 忽略 run()")
            return
        self._running = True
        # 2026-10-18 A2: GLFW 下不用 pygame.time.Clock，改 perf_counter 手动限帧 120FPS。
        # 语义与 clock.tick(120) 等价：算帧耗时 -> 不足 1/120 秒则 sleep 补足。
        _frame_dur = 1.0 / 120.0
        self.last_frame_time = time.perf_counter()
        while self._running:
            _frame_start = time.perf_counter()
            self._handle_events()
            now = time.perf_counter()   # 高精度单调钟 (与 Qt 宿主/相机 dt 同源)
            delta_time = min(now - self.last_frame_time, 0.1)  # 防窗口拖动时 dt 过大
            self.last_frame_time = now
            self.move_camera(delta_time)
            self.rotate_camera(delta_time)
            self.render(delta_time)
            # 限帧 120：算剩余时间 sleep（对齐 pygame.Clock.tick(120) 语义）
            _elapsed = time.perf_counter() - _frame_start
            if _elapsed < _frame_dur:
                time.sleep(_frame_dur - _elapsed)
        # 2026-10-19 第1档序7 应用级钩子：退出前派发 on_application_quit
        # （脚本存档/清理）。必须在 _stop_parallel 前 —— 脚本线程还在, 引擎可用。
        try:
            self._dispatch_application_quit()
        except Exception as ex:
            print("[engine] on_application_quit 派发异常 (忽略): %r" % (ex,))
        self._stop_parallel()          # 多核优化: 停脚本线程/碰撞池
        # B2 (2026-08-30): 音频后端 shutdown —— miniaudio 设备线程不关会挂死进程
        # (pygame.mixer 无此问题, 但 shutdown 幂等对两种情况都安全)
        try:
            self.audio.shutdown()
        except Exception:
            pass
        # 2026-10-18 A2: GLFW terminate（原 pygame.quit）
        self._glfw_shutdown()

