# -*- coding: utf-8 -*-
"""loom_hud.py — GLEngine HUD / 文字渲染子系统。

从 engine.py 抽出 (作为 HudMixin 供 GLEngine 继承):
  _primary_font_path / _load_font  (字体定位 + 加载)
  _draw_hud                        (HUD 文本行绘制)
  _surf_to_tex / _get_font / _render_text / _measure_text  (文字纹理管线)
  draw_text_quad / draw_screen_rect / blit_texture  (屏幕四边形绘制)
  _hud_lines / _update_fps / get_frame_jitter  (HUD 内容 + 帧统计)

依赖宿主 GLEngine 运行时提供:
  self.ctx / self.hud_prog / self._quad_vao / self._screen_fb
  self.font / self._font_cache / self._text_cache / self._text_cache_max
  self._hud_white_tex / self.width / self.height
  self.models / self.camera / self.camera_yaw / self.camera_pitch
  self.current_model_index / self.fps / self._clock / self._logic_paused
  self._external_ctx / self.frame_count / self.last_time /
  self._last_frame_stamp / self._frame_dt / self._preframing
mixin 只通过 self 按需访问 (语义与拆分前逐位一致)。
"""
import os
import time

import moderngl
import numpy as np
import pygame

from loom_font import FontChain


# 模块级单例: 字符->字体映射缓存进程内共享 (契约 §2.5.2)
_FONT_CHAIN = None


def _get_font_chain():
    global _FONT_CHAIN
    if _FONT_CHAIN is None:
        _FONT_CHAIN = FontChain()
    return _FONT_CHAIN


class HudMixin:

    @staticmethod
    def _primary_font_path():
        """主字体文件: 雅黑 > 黑体 > 雅黑Light; 全缺返回 None (用 pygame 默认字体)"""
        for path in ("C:/Windows/Fonts/msyh.ttc",
                     "C:/Windows/Fonts/simhei.ttf",
                     "C:/Windows/Fonts/msyhl.ttc"):
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def _load_font(size):
        """主字体 (雅黑, 含中文; 找不到退回默认).
        嵌入式模式 (Qt 宿主) 未 pygame.init: font 模块需单独 init —— 只初始化
        SDL_ttf 栅格化, 不建窗口, 与 IME 污染源 (SDL 窗口) 无关."""
        try:
            pygame.font.init()
        except Exception:
            pass
        path = HudMixin._primary_font_path()
        if path is not None:
            return pygame.font.Font(path, size)
        return pygame.font.Font(None, size)

    def _draw_hud(self):
        """HUD: 走 draw_text_quad (LRU 文字纹理缓存), 编辑器场景可覆写为不画"""
        lines = self._hud_lines()
        padx, pady, line_h = 10, 10, 24
        for i, text in enumerate(lines):
            self.draw_text_quad(text, padx, pady + i * line_h, (255, 255, 255))

    def _surf_to_tex(self, surf):
        """pygame Surface -> GL 纹理. 关键坑: surfarray 宽在前 (w,h), GL 纹理需
        逐行扫描线 (h,w) -> 先转置再翻转 y (行0=图像底部)."""
        w, h = surf.get_size()
        rgb = pygame.surfarray.array3d(surf)            # (w,h,3)
        alpha = pygame.surfarray.array_alpha(surf)      # (w,h)
        rgba = np.concatenate([rgb, alpha[:, :, None]], axis=2).astype('u1')  # (w,h,4)
        rgba = np.ascontiguousarray(np.transpose(rgba, (1, 0, 2))[::-1])
        tex = self.ctx.texture((w, h), 4, rgba.tobytes())
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return tex

    def _get_font(self, size):
        """按字号取字体 (缓存, 避免每帧创建)"""
        if size is None:
            return self.font
        f = self._font_cache.get(size)
        if f is None:
            f = self._load_font(size)
            self._font_cache[size] = f
        return f

    def _render_text(self, text, color, size=None):
        """文本渲染 -> Surface. 2026-10-18: 走 FontChain 多字体回退
        (契约 CanvasUI系统契约_20261018.md §2.5), 支持 UTF-8 全字符集
        (中文/emoji/符号/日文/韩文). 字符->字体映射缓存, 第二次起零 freetype 调用."""
        return _get_font_chain().render(text, color, size or 16)

    def _measure_text(self, text, size=None):
        """文本尺寸 (供居中/裁剪). 2026-10-18: 与 _render_text 同源走 FontChain,
        保证测量宽度与实际渲染宽度一致 (混排 emoji 场景下尤其重要)."""
        return _get_font_chain().measure(text, size or 16)

    def draw_text_quad(self, text, x, y, color=(255, 255, 255), size=None):
        """
        屏幕像素坐标 (x,y 左上角, pygame y 向下) 画文字.
        LRU 缓存文字纹理; 用 ctx.scope 保存/恢复混合与深度/剔除状态.
        """
        key = (text, color, size)
        item = self._text_cache.pop(key, None)     # 命中则置顶
        if item is None:
            surf = self._render_text(text, color, size)   # 单字体渲染 (M40 逐字符回退已删)
            w, h = surf.get_size()
            tex = self._surf_to_tex(surf)
            item = (tex, w, h)
            while len(self._text_cache) >= self._text_cache_max:
                _, (old_tex, _, _) = self._text_cache.popitem(last=False)
                old_tex.release()
        else:
            tex, w, h = item
        self._text_cache[key] = item

        # 只开混合 (关深度/剔除), scope 退出自动恢复原状态.
        # 坑: 不带 framebuffer 的 scope 会绑默认 FBO(屏幕) 而非当前绑定的离屏目标,
        # 必须把当前 FBO 显式传进去 (moderngl 5.12).
        # 坑2 (2026-08-15): scope(enable_only=BLEND) 会把 GL_SCISSOR_TEST 关掉 -> GUI
        # 文字无视面板/列表 scissor 画出范围 (检查器滚动时顶部文字不消失的根因).
        # 修: 不用 enable_only (保留全部状态含 scissor), 内部显式开混合/关深度/剔除.
        fb = self._screen_fb()   # 2026-08-18: 外部模式用缓存 widget FBO
        _prev_sc = self.ctx.scissor       # g.render 设的裁剪 box (或 None)
        with self.ctx.scope(framebuffer=fb):
            self.ctx.enable(moderngl.BLEND)
            self.ctx.disable(moderngl.DEPTH_TEST)
            self.ctx.disable(moderngl.CULL_FACE)
            # 坑2 (2026-08-15): moderngl scope 会把 GL_SCISSOR_TEST 启用标志重置掉
            # (box 还在但测试关) -> GUI 文字无视面板 scissor 画出范围. 显式重设.
            if _prev_sc is not None:
                self.ctx.scissor = _prev_sc
            else:
                self.ctx.scissor = None
            tex.use(0)
            self.hud_prog['u_tex'].value = 0
            self.hud_prog['u_color'].value = (1.0, 1.0, 1.0, 1.0)   # M33: 防纯色矩形染色残留
            ox = 2.0 * x / self.width - 1.0               # NDC x 左
            oy = 1.0 - 2.0 * (y + h) / self.height        # NDC y 底
            sx = 2.0 * w / self.width
            sy = 2.0 * h / self.height
            self.hud_prog['u_origin'].value = (ox, oy)
            self.hud_prog['u_size'].value = (sx, sy)
            self._quad_vao.render(moderngl.TRIANGLES)

    def draw_texture_quad(self, tex, rect, tint=(255, 255, 255, 255)):
        """屏幕像素坐标绘制任意纹理 quad (2026-10-18: Image 元素用).
        tint=(r,g,b,a) 0..255, 乘到纹理上 (片元着色器 frag = texture * u_color)."""
        if tex is None:
            return
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        fb = self._screen_fb()
        with self.ctx.scope(framebuffer=fb, enable_only=moderngl.BLEND):
            tex.use(0)
            self.hud_prog['u_tex'].value = 0
            self.hud_prog['u_color'].value = (
                tint[0] / 255.0, tint[1] / 255.0, tint[2] / 255.0,
                (tint[3] / 255.0) if len(tint) > 3 else 1.0)
            self.hud_prog['u_origin'].value = (2.0 * x / self.width - 1.0,
                                               1.0 - 2.0 * (y + h) / self.height)
            self.hud_prog['u_size'].value = (2.0 * w / self.width,
                                             2.0 * h / self.height)
            self._quad_vao.render(moderngl.TRIANGLES)

    # ---- scissor 裁剪栈 (2026-10-18: UI ScrollView 用) ----
    def push_scissor(self, rect):
        """推入一个屏幕矩形裁剪区 (x, y, w, h, 左上原点). 嵌套时求交. 需与 pop_scissor 配对."""
        if not hasattr(self, '_ui_scissor_stack'):
            self._ui_scissor_stack = []
            self._ui_scissor_cur = None
        self._ui_scissor_stack.append(self._ui_scissor_cur)
        x, y, w, h = rect
        if self._ui_scissor_cur is not None:
            # 与现有裁剪区求交
            ox, oy, ow, oh = self._ui_scissor_cur
            nx = max(x, ox)
            ny = max(y, oy)
            nw = max(0, min(x + w, ox + ow) - nx)
            nh = max(0, min(y + h, oy + oh) - ny)
            self._ui_scissor_cur = (nx, ny, nw, nh)
        else:
            self._ui_scissor_cur = (max(0, x), max(0, y), max(0, w), max(0, h))
        self._apply_ui_scissor()

    def pop_scissor(self):
        """弹出上一个裁剪区 (与 push_scissor 配对)."""
        if not hasattr(self, '_ui_scissor_stack') or not self._ui_scissor_stack:
            return
        self._ui_scissor_cur = self._ui_scissor_stack.pop()
        self._apply_ui_scissor()

    def _apply_ui_scissor(self):
        """把当前裁剪区写到 GL. None -> 关闭裁剪."""
        sc = self._ui_scissor_cur
        if sc is None:
            self.ctx.scissor = None
            return
        x, y, w, h = sc
        # GL 原点在左下: y_gl = height - (y+h)
        self.ctx.scissor = (int(x), int(self.height - (y + h)), int(w), int(h))

    def draw_screen_rect(self, rect, color):
        """M33: 屏幕像素填充矩形 (运行时 UI 用). rect=(x,y,w,h) 左上角.
        color=(r,g,b) 或 (r,g,b,a) 0..255; 2026-10-18 起支持 alpha (Panel 半透明)."""
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        a = (color[3] / 255.0) if len(color) > 3 else 1.0
        fb = self._screen_fb()   # 2026-08-18: 外部模式用缓存 widget FBO
        with self.ctx.scope(framebuffer=fb, enable_only=moderngl.BLEND):
            self._hud_white_tex.use(0)
            self.hud_prog['u_tex'].value = 0
            self.hud_prog['u_color'].value = (
                color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, a)
            self.hud_prog['u_origin'].value = (2.0 * x / self.width - 1.0,
                                               1.0 - 2.0 * (y + h) / self.height)
            self.hud_prog['u_size'].value = (2.0 * w / self.width,
                                             2.0 * h / self.height)
            self._quad_vao.render(moderngl.TRIANGLES)

    def blit_texture(self, tex):
        """异步GUI: 全屏混合离屏 GUI 纹理到屏幕 (面板 FBO 合成). tex 须 = engine 尺寸.
        方向已核验: rect shader 顶部内容在高 NDC y, blit 的 v_uv=0 在底部顶点, 无需翻转."""
        if tex is None:
            return
        try:
            with self.ctx.scope(framebuffer=self._screen_fb(), enable_only=moderngl.BLEND):
                tex.use(0)
                self.hud_prog['u_tex'].value = 0
                self.hud_prog['u_color'].value = (1.0, 1.0, 1.0, 1.0)   # 防纯色矩形染色残留
                self.hud_prog['u_origin'].value = (-1.0, -1.0)
                self.hud_prog['u_size'].value = (2.0, 2.0)
                self._quad_vao.render(moderngl.TRIANGLES)
        except Exception:
            pass

    def _hud_lines(self):
        """HUD 文本行 (与旧 turtle 版 _draw_hud 一致)"""
        import math
        m = self.get_current_model()
        yaw_deg = 360 - math.degrees(self.camera_yaw) % 360
        pitch_deg = math.degrees(self.camera_pitch)
        total_faces = sum(len(x.mesh.faces) for x in self.models)
        if not self._external_ctx and pygame.key.get_focused():
            if m is not None:
                model_line = (f"模型 {self.current_model_index + 1}/{len(self.models)}: "
                              f"位置=({m.position.x:.2f}, {m.position.y:.2f}, "
                              f"{m.position.z:.2f}) | FPS: {self.fps} | 三角形: {total_faces}")
                rot_line = (f"旋转角度: X:{math.degrees(m.rotation.x):.1f}° "
                            f"Y:{math.degrees(m.rotation.y):.1f}° "
                            f"Z:{math.degrees(m.rotation.z):.1f}°")
            else:
                model_line = "模型: (无)"
                rot_line = "旋转角度: (无)"
            lines = [
                f"相机位置: ({self.camera.x:.2f}, {self.camera.y:.2f}, {self.camera.z:.2f}) | "
                f"视角: 偏航角={yaw_deg:.1f}°, 俯仰角={pitch_deg:.1f}°",
                model_line,
                rot_line,
                "渲染后端: OpenGL (moderngl) | 硬件深度测试 + 背面剔除",
                # 方案一② 帧长方差观测 (2026-09-05): std/max 量化抖动
                (lambda _j: "帧长: std=%.2fms max=%.2fms (滑窗%d)" % _j)(
                    self.get_frame_jitter()),
                # 分离批1: 逻辑帧/渲染帧分离状态 (HUD)
                (f"逻辑帧: {self._clock.logic_fps:.0f}Hz x{self._clock.steps} | "
                 f"物理子步 x{self._clock.phys_steps} (dt={self._clock.sub_dt*1000.0:.1f}ms) | "
                 f"alpha={self._clock.alpha:.2f}"
                 + (" | [F9 已暂停 — F10 步进]" if getattr(self, '_logic_paused', False) else ""))
                if getattr(self, '_clock', None) is not None else "逻辑帧: 绑死模式 (logic_fps<=0)",
                "切换模型: Tab",
                "相机移动: W-前, S-后, A-左, D-右, Q-上, E-下 | "
                "视角控制: 方向键",
            ]
            # ★B4c (2026-10-16): 物理线程建失败 (系统极限工况) 醒目提示
            if getattr(self, '_phys_pipe_sysfail', False):
                lines.append(
                    "!!! 物理线程创建失败 (系统资源耗尽?) — 立即保存并关闭软件! "
                    "Physics thread failed (sys resource?) - SAVE & CLOSE NOW !!!")
        else:
            # 窗口没键盘焦点时按键无效 -> 用醒目提示引导点击窗口
            lines = [
                "!!! 窗口未激活: 请点击本窗口后再按按键 !!!",
                " (点击窗口使其获得键盘焦点; 若仍无效请切换输入法为英文)",
            ]
        return lines

    def _update_fps(self):
        """每秒更新一次 FPS + 帧长滑窗统计 (方案一② 帧长方差观测, 2026-09-05):
        _frame_dt deque(120, maxlen 固定=长寿命不换对象, GC 冻结兼容) 记录
        每渲染帧墙钟; std/max 量化"抖不抖" (Panda3D calc_frame_rate_deviation
        同款 chugginess 指标) — 双峰/限帧器抖动从体感变数字.
        FPS 缓冲预画帧跳过 (不虚计 FPS/不污染帧长窗)."""
        if getattr(self, '_preframing', False):
            return
        self.frame_count += 1
        now = time.perf_counter()   # 高精度单调钟 (帧长滑窗; 与帧 dt 同源)
        # 帧长滑窗: deque 持久 (初始化建, 此处只 append; 窗 120 帧 ≈ 高帧率 1-2s)
        fdt = now - self._last_frame_stamp
        self._last_frame_stamp = now
        if 0.0 < fdt < 0.5:            # 滤掉首帧/窗口拖动冻结的伪长帧
            self._frame_dt.append(fdt)
        if now - self.last_time >= 1.0:
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_time = now

    def get_frame_jitter(self):
        """帧长统计 (方案一②): 返回 (std_ms, max_ms, n) — 滑窗 120 帧;
        n<8 时返回 (0,0,n) (样本不足不误导). HUD 第三行/验收基线用."""
        d = getattr(self, '_frame_dt', None)
        if not d or len(d) < 8:
            return (0.0, 0.0, len(d) if d else 0)
        a = np.asarray(d, dtype=np.float64)
        return (float(a.std() * 1000.0), float(a.max() * 1000.0), int(a.size))
