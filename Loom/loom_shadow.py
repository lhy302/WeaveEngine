# -*- coding: utf-8 -*-
"""loom_shadow.py — GLEngine 的 M29 阴影贴图子系统 (深度 pass)。

从 engine.py 抽出的 4 个方法 (作为 ShadowMixin 供 GLEngine 继承):
  _release_shadow_map / _ensure_shadow_map / _render_shadow_maps / _render_to_shadow_map
以及 __init__ 期资源初始化 _init_shadow。

依赖宿主 GLEngine 运行时提供:
  - self.ctx / self.lights / self._light_vps
  - self._render_buckets / self._bucket_geo
  - self._dir_light_vp / self._point_light_vp
以上仍由 GLEngine 主体持有, mixin 只通过 self 按需访问 (语义与拆分前逐位一致)。
"""

import moderngl
import numpy as np

from loom_shaders import _SHADOW_VERT, _SHADOW_FRAG


class ShadowMixin:
    """M29 阴影贴图子系统 (深度 pass).

    宿主类必须 (在 __init__ 里) 调用一次 `self._init_shadow()` 完成资源初始化。
    """

    def _init_shadow(self):
        """引擎 __init__ 调用: 建阴影 depth program + 阴影贴图缓存 + 分辨率参数."""
        self._shadow_prog = self.ctx.program(vertex_shader=_SHADOW_VERT,
                                             fragment_shader=_SHADOW_FRAG)
        self._shadow_maps = {}
        self._shadow_res = 1024        # 平行光阴影分辨率
        self._shadow_point_res = 512   # 点光阴影面分辨率
        self._shadow_point_far = 30.0  # 点光阴影远平面 (距离归一)

    def _release_shadow_map(self, sm):
        try:
            for f in sm.get('fbo', []):
                f.release()
            for t in sm.get('tex', []):
                t.release()
        except Exception:
            pass

    def _ensure_shadow_map(self, light):
        """取/建光源阴影贴图: 平行光=1 张 2D depth; 点光=6 张 2D depth (面)."""
        sm = self._shadow_maps.get(light.guid)
        if sm is not None:
            return sm
        if light.kind == 'directional':
            tex = self.ctx.depth_texture((self._shadow_res, self._shadow_res))
            # 阴影采样: 存真实深度 + pcf_shadow 传 ref=depth-bias
            # (此驱动实测固定 stored>=ref=照亮, 忽略 compare_func; 反转深度方案已废弃)
            sm = {'type': 'dir', 'tex': [tex],
                  'fbo': [self.ctx.framebuffer(depth_attachment=tex)]}
        else:
            res = self._shadow_point_res
            texs = [self.ctx.depth_texture((res, res)) for _ in range(6)]
            sm = {'type': 'point', 'tex': texs,
                  'fbo': [self.ctx.framebuffer(depth_attachment=t) for t in texs]}
        self._shadow_maps[light.guid] = sm
        return sm

    def _render_shadow_maps(self):
        """先画完全部阴影贴图 (深度 pass), 主 pass 再采样. 每帧重渲 (光源/物体可动).
        复用模型 m.vao (in_pos 槽位与 _SHADOW_VERT 一致), 关闭背面剔除 (防背面漏光/acne)."""
        if not self.lights:
            return
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)
        vps = self._light_vps or {}
        for i, light in enumerate(self.lights[:8]):
            if not light.shadow:
                continue
            if light.kind == 'directional':
                vp = vps.get(light.guid)
                if vp is None:
                    vp = self._dir_light_vp(light)      # 兜底: 无缓存时现算
                if vp is None:
                    continue
                sm = self._ensure_shadow_map(light)
                self._shadow_prog['u_depth_kind'].value = 0
                self._render_to_shadow_map(sm, [vp])
            else:
                sm = self._ensure_shadow_map(light)
                self._shadow_prog['u_depth_kind'].value = 1
                self._shadow_prog['u_light_pos'].value = (
                    light.position.x, light.position.y, light.position.z)
                self._shadow_prog['u_light_far'].value = self._shadow_point_far
                lv = vps.get(light.guid)
                vps6 = lv if lv is not None else self._point_light_vp(light)
                self._render_to_shadow_map(sm, vps6)

    def _render_to_shadow_map(self, sm, vp_list):
        """把一个光源的所有可见模型实例化渲染进它的各面 (A2: 每面清深度后逐桶
        draw; 桶实例 world 矩阵已在 _prepare_bucket_frame 写入桶级缓冲, 每面只换
        u_light_vp uniform —— 旧版逐模型 u_model 上传+draw 已取消)."""
        for fbo, vp in zip(sm['fbo'], vp_list):
            fbo.clear(depth=1.0)
            fbo.use()
            self._shadow_prog['u_light_vp'].write(
                np.ascontiguousarray(vp, dtype='f4').tobytes())
            for key, idxs in self._render_buckets:
                ent = self._bucket_geo.get(key)
                if ent is None or ent['sha_vao'] is None:
                    continue
                ent['sha_vao'].render(moderngl.TRIANGLES, instances=len(idxs))
