# -*- coding: utf-8 -*-
"""loom_lighting.py — GLEngine 光源/光照上传/阴影 VP 子系统。

从 engine.py 抽出 (作为 LightingMixin 供 GLEngine 继承):
  add_light / remove_light / find_model_by_guid / _uniform / _upload_lights
  _scene_light_bounds / _model_aabbs_par / _aabbs_batched / _scene_light_bounds_par
  _dir_light_vp / _parallel_shadow_and_collision / _pipeline_light_vps
  _compute_light_vps / _point_light_vp

★行为红线 (2026-10-13 上一轮 Agent 确认): 本块含分离模式/旧绑死模式双分支
  (_parallel_shadow_and_collision 的批5 缓存路径 + 编辑态旧路径),
  以及 pipeline.dll 路径 (_pipeline_light_vps)。
  ★B2 退役 (2026-10-16): 相关逃生门 (LOOM_NO_PREP/NO_PIPELINE/NO_SHADOW_CACHE) 已删。
  纯搬家, 双分支逐位保留, 不得借重构删/改任何分支。

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self.lights / self.models / self._frame_world / self._light_vps / self._u_last / self._u
  self._shadow_maps / self._shadow_res / self._shadow_point_res / self._shadow_point_far
  self._light_bufs / self._aabb_row_cache / self._aabb_shadow_rows / self._aabb_shadow_gen
  self._aabb_staging / self._frame_pool / self._AABB_POOL_THRESHOLD / self._AABB_DIRTY_POOL_MIN
  self._AABB_PAR_MIN_WORK / self._COLLISION_PAR_THRESHOLD
  self._split_enable / self.is_playing / self._disp_gen / self._stage_times / self._stage_calls
  self.prog / self._frame_world / self._struct_gen / self._u_last
  self._release_shadow_map / self._collision_pairs_parallel / self._dispatch_collision_events
  self._update_collision_events / self._logic_snapshot / self._profile / self._prof_t0 / self._prof_add
  self.get_bounding_box / self._homogeneous_vertices
"""
import math
import os
import threading
import time

import numpy as np

from matlib import (mat4_ortho, mat4_perspective, mat4_view_forward)
import fastpath   # AABB 批量归约 (aabbs_minmax 串行 / aabbs_minmax_par 逃生门)
from loom_types import Point3D
from loom_game_object import GameObject
from loom_scene_entities import LightState


class LightingMixin:
    # ================ 光源管理 (M21: 场景光源实体; M29 阴影) ================
    def add_light(self, kind='directional', position=None, direction=None,
                  color=(1.0, 1.0, 1.0), intensity=1.0, name=None, guid=None,
                  mode='full', shape='circle', size=5.0, shadow=True,
                  azimuth=None, elevation=None, roll=None, range=10.0):
        """添加场景光源 (不可见实体, 不渲染网格/不参与拾取). 返回 LightState.
        M29: mode='full'|'beam', shape='circle'|'rect', size=截面尺寸, shadow=是否投射阴影.
        M30: 平行光方向用 azimuth/elevation/roll (度); 旧 direction 向量仍兼容 (自动反算).
        range: 点光影响半径 (对齐 Unity Light.range, 默认 10)."""
        light = LightState(kind=kind, position=position, direction=direction,
                           color=color, intensity=intensity, name=name, guid=guid,
                           mode=mode, shape=shape, size=size, shadow=shadow,
                           azimuth=azimuth, elevation=elevation, roll=roll,
                           range=range)
        self.lights.append(light)
        return light

    def remove_light(self, light):
        """从场景移除光源 (释放其阴影贴图)"""
        sm = self._shadow_maps.pop(light.guid, None)
        if sm is not None:
            self._release_shadow_map(sm)
        if light in self.lights:
            self.lights.remove(light)


    def find_model_by_guid(self, guid):
        """按 guid 找普通物体 (GameObject), 找不到返回 None. 相机挂父/撤销解析用."""
        for m in self.models:
            if m.guid == guid:
                return m
        return None


    def _uniform(self, name):
        """组6件3: self.prog uniform 句柄缓存 (消每帧字符串哈希+查找).
        program 构建一次无热重载, 句柄生命周期 = program."""
        u = self._u.get(name)
        if u is None:
            u = self._u[name] = self.prog[name]
        return u

    def _upload_lights(self):
        """把场景光源写到着色器 uniform 数组 + 绑定阴影贴图 (render 每帧调用).
        M29: 附加 mode/shape/ortho/shadow_slot; 阴影贴图从纹理单元 1 起绑定
        (单元 0 留给文字/HUD). u_ambient_scale: 无光源时压暗环境光.
        多核优化 (2026-08-14): 缓冲惰性建一次, 每帧原地清零复用, 消除每帧 ~9 次
        numpy 数组分配 (GC/CPU 开销)."""
        n = min(len(self.lights), 8)
        if self._u_last.get('u_light_count') != n:
            self._uniform('u_light_count').value = n
            self._u_last['u_light_count'] = n
        b = getattr(self, '_light_bufs', None)
        if b is None:
            b = self._light_bufs = {
                'dirs': np.zeros((8, 3), dtype='f4'),
                'poss': np.zeros((8, 3), dtype='f4'),
                'cols': np.zeros((8, 3), dtype='f4'),
                'ints': np.zeros(8, dtype='f4'),
                'kinds': np.zeros(8, dtype='f4'),
                'ranges': np.zeros(8, dtype='f4'),  # 点光 range (对齐 Unity Light.range)
                'modes': np.zeros(8, dtype='f4'),   # M29: 平行光 0=full 1=beam
                'shapes': np.zeros(8, dtype='f4'),  # M29: beam 0=circle 1=rect
                'orthos': np.zeros((8, 16), dtype='f4'),  # M29: 平行光 view-proj
                'slots': np.full(8, -1, dtype='i4'),      # M29: 阴影数组下标
                'sampler_units': [0] * 16,
            }
        # 每帧原地清零 (复用缓冲)
        b['dirs'][:] = 0
        b['poss'][:] = 0
        b['cols'][:] = 0
        b['ints'][:] = 0
        b['kinds'][:] = 0
        b['ranges'][:] = 0
        b['modes'][:] = 0
        b['shapes'][:] = 0
        b['orthos'][:] = 0
        b['slots'][:] = -1
        # 孤儿阴影贴图清理 (光源被删)
        for guid in list(self._shadow_maps):
            if not any(getattr(l, 'guid', None) == guid for l in self.lights):
                self._release_shadow_map(self._shadow_maps.pop(guid))
        unit = 1                                # 阴影贴图从单元 1 起 (0 留给文字)
        sampler_units = b['sampler_units']      # 全 16 个 sampler 元素一次设
        sampler_units[:] = [0] * 16
        for i, light in enumerate(self.lights[:8]):
            b['dirs'][i] = (light.direction.x, light.direction.y, light.direction.z)
            b['poss'][i] = (light.position.x, light.position.y, light.position.z)
            b['cols'][i] = (light.color[0], light.color[1], light.color[2])
            b['ints'][i] = light.intensity
            b['kinds'][i] = 1.0 if light.kind == 'point' else 0.0
            b['ranges'][i] = getattr(light, 'range', 10.0)
            b['modes'][i] = 1.0 if light.mode == 'beam' else 0.0
            b['shapes'][i] = 1.0 if light.shape == 'rect' else 0.0
            if light.kind == 'directional':
                # ★M3-N5 (2026-09-09): 仅在真正需要时算 VP —— 着色器读 u_light_ortho
                #   只有两处: (a) mode=='beam' 的光束截面遮罩 (b) u_shadow_slot>=0 的
                #   阴影采样。旧代码无条件兜底 _dir_light_vp → 该函数内部会做
                #   _model_aabbs_par(全场景 501 物体包围盒) + 场景界计算; 关阴影时
                #   _light_vps 为空 → 每帧重算, 实测 main_pass 0.65 → 18.16 ms/帧
                #   (FPS 158 → 37.5, 同会话交错 A/B: tests\_tmp\_m3_gpu_ab.json)。
                if light.shadow or light.mode == 'beam':
                    vp = (self._light_vps or {}).get(light.guid)
                    if vp is None:
                        vp = self._dir_light_vp(light)
                    if vp is not None:
                        b['orthos'][i] = np.asarray(vp, dtype='f4').ravel()
            # 阴影贴图槽位: 平行光 1 张 / 点光 6 面, 平铺进 u_shadow_maps
            if light.shadow:
                sm = self._shadow_maps.get(light.guid)
                need = 6 if light.kind == 'point' else 1
                if sm is not None and unit + need - 1 <= 15:
                    b['slots'][i] = unit - 1     # 数组下标 = 物理单元号 - 1
                    for k, tex in enumerate(sm['tex']):
                        tex.use(unit + k)
                        sampler_units[unit - 1 + k] = unit + k
                    unit += need
        # 组6件3: 8 组灯光 uniform 差分上传 —— 缓冲原地填充后 bytes 比较,
        # 同值跳过 glBufferSubData (GL uniform 状态机语义等价); u_ascontiguousarray
        # 对本缓冲是 no-op (C 连续), 保留与旧路径同形. 消每帧 8×tobytes+8×write.
        ul = self._u_last
        for name, arr in (('u_light_dir', b['dirs']), ('u_light_pos', b['poss']),
                          ('u_light_color', b['cols']), ('u_light_intensity', b['ints']),
                          ('u_light_kind', b['kinds']), ('u_light_range', b['ranges']),
                          ('u_light_mode', b['modes']),
                          ('u_light_shape', b['shapes']), ('u_light_ortho', b['orthos'])):
            raw = arr.tobytes()
            if ul.get(name) != raw:
                self._uniform(name).write(raw)
                ul[name] = raw
        slots_t = tuple(int(x) for x in b['slots'])
        samplers_t = tuple(sampler_units)
        if ul.get('u_shadow_maps') != samplers_t:
            self._uniform('u_shadow_maps').value = samplers_t
            ul['u_shadow_maps'] = samplers_t
        if ul.get('u_shadow_slot') != slots_t:
            self._uniform('u_shadow_slot').value = slots_t       # int 数组用 tuple
            ul['u_shadow_slot'] = slots_t
        for name, val in (('u_shadow_res', self._shadow_res),
                          ('u_shadow_point_res', self._shadow_point_res),
                          ('u_shadow_bias', 0.002),
                          ('u_shadow_point_bias', 0.004),
                          ('u_light_far', self._shadow_point_far),
                          ('u_ambient_scale', 1.0 if n > 0 else 0.2)):
            if ul.get(name) != val:
                self._uniform(name).value = val
                ul[name] = val

    # ================ M29 阴影贴图 (深度 pass) → loom_shadow.ShadowMixin ================

    def _scene_light_bounds(self, view):
        """场景全部可见物体世界 AABB 8 角变换到 view 空间, 返回 x/y/z 的 (min, max).
        (串行回退版: 无预计算池时用; 有池走 _model_aabbs_par + _scene_light_bounds_par.)"""
        aabbs = self._model_aabbs_par(self.models, self._frame_world)
        # getattr 防御: 测试桩 (__new__ 无 __init__) 无 _stage_times (test_parallel 抓过)
        return self._scene_light_bounds_par(
            view, aabbs, times=getattr(self, '_stage_times', None))

    def _model_aabbs_par(self, models, fw=None, visible_only=True):
        """模型世界 AABB (用当帧矩阵), 与 models 下标对齐 (visible_only=False 全量对齐).
        2026-08-15 8 核均摊: 逐模型 get_bounding_box 是 numpy 重活 (高面数球体 = 几万顶点
        批量变换), 池上分块 -> 释放 GIL 真并行; 结果按序拼接, 与逐模型串行逐位一致.
        visible_only=False: 返回全部模型 (含不可见, 下标与 models 对齐) —— 阴影与碰撞
        共享一次包围盒计算用 (阴影再过滤可见).
        组3层3 (2026-08-31): 逐模型 Python 循环改批量化 _aabbs_batched —— 按顶点数
        分组堆叠, 每组一次批量归约 (消每模型 3 次 numpy 调用开销); 每模型仍是同参数
        matmul (k=4 求和序不变) + min/max 纯比较 -> 与逐模型串行逐位一致 (对拍
        aabb_par_check.py). 池路径 (n>=阈值) 分块内同款批量化.
        ★行级缓存层级修正 (2026-09-06 编译版 9FPS 定案): 行级缓存**只在本层**
        (整 fw 查/写, 池分块路径禁用) —— 旧设计把缓存放进 _aabbs_batched, 池分块
        时每个 worker 拿 fw 切片当"整表"判/写: ①切片行数≠缓存行数恒 miss;
        ②多 worker 写回互相覆盖; ③播放态 fw 每帧新对象雪上加霜 → 编译版
        (numpy 全量慢) 恒 miss 26-37ms/帧 9FPS, 源码 numba 快被掩盖。
        现在本层: 缓存命中 (含 fw 值全等) → 直接返回上帧 out (零计算快路径);
        未命中 → 池分块/串行照旧, 算完写回整缓存。行级变化=值比较 (身份无关)。
        LOOM_PROFILE: 阶段名 'aabbs' (shadow_prep 内部大头, 单独观测)."""
        n = len(models)
        if n == 0:
            return []
        _p = os.environ.get('LOOM_PROFILE') == '1'
        if _p:
            t0 = time.time()
        fw = fw if fw is not None else getattr(self, '_frame_world', None)
        fw_ok = (fw is not None and hasattr(fw, 'ndim') and fw.ndim == 3
                 and fw.shape[1:] == (4, 4) and fw.shape[0] == n)
        stamp3 = (getattr(self, '_struct_gen', 0), GameObject._appearance_gen,
                  bool(visible_only))
        cache = getattr(self, '_aabb_row_cache', None)
        if (visible_only is False and fw_ok and cache is not None
                and cache[1] == stamp3 and cache[2] == n
                and cache[3] is not None
                and cache[4] is not None and len(cache[4]) == n):
            # 行级复用仅 visible_only=False (全量下标对齐; 播放态 prep 用)。
            # visible_only=True 时 out 长度=可见数与 fw 行数不对齐, 不入缓存
            # (走下方原路径全算, 语义与旧版逐位一致)。
            # 行级变化判定: 值比较 (对象身份无关 — 播放态 fw 每帧新对象)
            changed = np.any(fw != cache[3], axis=(1, 2))
            c_aabbs = cache[4]
        else:
            changed = None
            c_aabbs = None
        pool = getattr(self, '_frame_pool', None)
        use_pool = pool is not None and n >= self._AABB_POOL_THRESHOLD
        if changed is not None:
            # 行级复用路径: 静止行直接抄上帧, 只把 changed 行 (可见的) 送去算
            out = list(c_aabbs)
            dirty = [i for i in range(n) if changed[i]]
            if _p:
                # ★M3 观测量: 脏行占比 (决定池内实际工作量) —— 计数类, 非耗时
                self._stage_calls['aabb_calls'] = self._stage_calls.get('aabb_calls', 0) + 1
                self._stage_calls['aabb_rows'] = self._stage_calls.get('aabb_rows', 0) + n
                self._stage_calls['aabb_dirty'] = self._stage_calls.get('aabb_dirty', 0) + len(dirty)
            # 直通行发布 (2026-09-07): rows_full 与 out 按下标对齐 (值配对, 身份
            # 无关 —— 上帧表行值=上帧 out 行值, list() 浅拷贝不改行值); prev
            # 形状匹配即复用, 免每帧 501 行 Point3D 回填。
            prev = getattr(self, '_aabb_shadow_rows', None)
            prev_ok = (prev is not None and prev.shape == (n, 6)
                       and prev.dtype == np.float64)
            rows_full = prev if prev_ok else np.empty((n, 6), dtype=np.float64)
            if not dirty:
                self._aabb_shadow_rows = rows_full if prev_ok else None
                self._aabb_shadow_gen = ((id(out), n) if prev_ok else None)
                if _p:
                    # ★M3: 原写 'aabbs' 与外层 _profile('aabbs') 重复计数 → 改名
                    self._stage_times['aabbs_inner'] = \
                        self._stage_times.get('aabbs_inner', 0.0) + (time.time() - t0) * 1000.0
                return out
            sub_models = [models[i] for i in dirty]
            sub_fw = fw[dirty]
            if (use_pool and len(dirty) >= self._AABB_POOL_THRESHOLD
                    and len(dirty) >= self._AABB_DIRTY_POOL_MIN):
                d_segs = []                      # 连续段 [(起,止) in dirty 域]
                s0 = 0
                for q in range(1, len(dirty) + 1):
                    if q == len(dirty) or dirty[q] != dirty[q - 1] + 1:
                        d_segs.append((s0, q)); s0 = q
                def _chunk(idx_iter):
                    idxs = list(idx_iter)
                    # dirty 连续段 -> rows_full **位置切片视图** (map_indexed 恒产
                    # range(a,b) 连续块; 块落在单段内时写回零拷贝)。★勿用
                    # rows_full[dirty[a:b]] —— 列表下标是 fancy indexing 产副本,
                    # 写副本即丢行 (跨段块直接走无行表回退 + 出口按需回填)。
                    a, b = idxs[0], idxs[-1] + 1
                    seg = next((s for s in d_segs if s[0] <= a and b <= s[1]), None)
                    if seg is not None:
                        rc = rows_full[seg[0] + a:seg[0] + b]
                        part = self._aabbs_batched([sub_models[i] for i in idxs],
                                                   sub_fw[idxs],
                                                   False, _row_cache=False,
                                                   out_rows=rc)
                    else:
                        part = self._aabbs_batched([sub_models[i] for i in idxs],
                                                   sub_fw[idxs],
                                                   False, _row_cache=False)
                    return part
                part = pool.map_indexed(len(dirty), _chunk, batches_per_thread=2)
                for i, aabb in zip(dirty, part):
                    out[i] = aabb
                # 段未覆盖 (块跨段) 的行: 从 out 回填 (罕见)
                if not any(s[0] == 0 and s[1] == len(dirty) for s in d_segs):
                    for q, i in enumerate(dirty):
                        mn_, mx_ = out[i]
                        rows_full[i, 0] = mn_.x; rows_full[i, 1] = mn_.y
                        rows_full[i, 2] = mn_.z
                        rows_full[i, 3] = mx_.x; rows_full[i, 4] = mx_.y
                        rows_full[i, 5] = mx_.z
            else:
                rc = np.empty((len(dirty), 6), dtype=np.float64)
                part = self._aabbs_batched(sub_models, sub_fw, False,
                                           _row_cache=False, out_rows=rc)
                for i, aabb in zip(dirty, part):
                    out[i] = aabb
                rows_full[dirty] = rc
            if not prev_ok:
                # 首帧无配对上帧表: 静止行从 out 回填 (首帧 changed≈全量, 罕见)
                for j in range(n):
                    if changed[j]:
                        continue
                    mn_, mx_ = out[j]
                    rows_full[j, 0] = mn_.x; rows_full[j, 1] = mn_.y
                    rows_full[j, 2] = mn_.z
                    rows_full[j, 3] = mx_.x; rows_full[j, 4] = mx_.y
                    rows_full[j, 5] = mx_.z
            self._aabb_shadow_rows = rows_full
            self._aabb_shadow_gen = (id(out), n)
            if _p:
                # ★M3: 同上, 避免与外层 _profile('aabbs') 重复计数
                self._stage_times['aabbs_inner'] = \
                    self._stage_times.get('aabbs_inner', 0.0) + (time.time() - t0) * 1000.0
            return out
        if pool is not None and n >= self._AABB_POOL_THRESHOLD:
            if visible_only is False:
                # 行表只在全量对齐路径分发 (visible_only=True 时 sel=可见子集,
                # 按 sel 下标散写会与 models 下标错位 —— 该路径消费者走属性链回退)。
                rows_full = np.empty((n, 6), dtype=np.float64)
                def _chunk(idx_iter):
                    idxs = list(idx_iter)
                    # map_indexed 恒产连续 range(a,b) (parallel._split_bounds), 行表按
                    # 连续切片视图分发, worker 各写互斥段 (与 out 分块拼接同构)。
                    a, b = idxs[0], idxs[-1] + 1
                    return self._aabbs_batched([models[i] for i in idxs],
                                               [fw[i] for i in idxs] if fw is not None else None,
                                               visible_only, _row_cache=False,
                                               out_rows=rows_full[a:b])
            else:
                rows_full = None
                def _chunk(idx_iter):
                    idxs = list(idx_iter)
                    return self._aabbs_batched([models[i] for i in idxs],
                                               [fw[i] for i in idxs] if fw is not None else None,
                                               visible_only, _row_cache=False)
            out = pool.map_indexed(n, _chunk, batches_per_thread=2)
            self._aabb_shadow_rows = rows_full
            self._aabb_shadow_gen = ((id(out), n) if rows_full is not None else None)
        else:
            if visible_only is False:
                rows_full = np.empty((n, 6), dtype=np.float64)
                out = self._aabbs_batched(models, fw, visible_only,
                                          _row_cache=False, out_rows=rows_full)
                self._aabb_shadow_rows = rows_full
                self._aabb_shadow_gen = (id(out), n)
            else:
                out = self._aabbs_batched(models, fw, visible_only,
                                          _row_cache=False)
                self._aabb_shadow_rows = None
                self._aabb_shadow_gen = None
        if fw_ok and visible_only is False:
            self._aabb_row_cache = (None, stamp3, n, fw, out)
        if _p:
            # ★M3: 同上, 避免与外层 _profile('aabbs') 重复计数
            self._stage_times['aabbs_inner'] = self._stage_times.get('aabbs_inner', 0.0) \
                + (time.time() - t0) * 1000.0
        return out

    def _aabbs_batched(self, models, fw, visible_only=True, _row_cache=True,
                       out_rows=None):
        """批量化 AABB (组3层3): 逐模型 vh 复用 _homogeneous_vertices 缓存, 按顶点数
        V 分组, fastpath.aabbs_minmax 逐组一次算全组 min/max —— 每顶点 9乘6加标量
        循环, BLAS 调用/大缓冲/transpose 全消. 数值 = D6 标准 "逐位/1e-7 内" (vs
        numpy dgemm ~4 ULP 舍入差, 实测 8.9e-16, 见 aabb_par_check.py 对拍).
        M 缺失/罕见形态兜底走 get_bounding_box 旧路径 (行为不变). 顺序 = models
        过滤 visible 后的原序 (旧语义). 纯 Python 降级同算法.
        ★spin 治理 (2026-08-31): 默认 aabbs_minmax **串行** njit (nogil, 不碰
        numba 线程池 —— 消 18 worker 帧间 busy-wait 空烧); 仅单组工作量 n×V >=
        _AABB_PAR_MIN_WORK 才切并行版 aabbs_minmax_par (工作量摊得开
        线程创建税的大规模逃生门; 批4A 2026-09-07 由 n-only 闸门 512 改工作量
        判据). 两版同算法逐位同源.
        组1+ 堆叠缓冲复用: vhN/m3N/mn/mx 堆叠分配按 (n,V) 键缓存
        (thread-local —— 阴影/碰撞池 worker 线程都会进本方法, 免锁), 尺寸
        匹配即原地复用, 消每帧 4 次 np.empty 大分配 (51球 V=2035 ≈ 3.3MB/帧).
        ★_row_cache (2026-09-06): 行级缓存已上移到 _model_aabbs_par 本层 (整 fw
        查/写); 本方法内旧缓存逻辑**移除** —— 池分块时每 worker 拿 fw 切片当整表
        判/写会恒 miss + 互相覆盖 (编译版 9FPS 根因)。_row_cache 参数保留兼容
        旧调用签名, 分块路径显式传 False。
        ★组装段去重 (2026-09-07): vh 逐行写改 "唯一行表 + 行→唯一行 gather +
        行身份序列命中跳写" (同网格样本共享同一 vh 缓存对象, 混合500 501 行仅
        35 唯一); m3 段仍逐行原地写。对拍 aabb_assembly_check.py, 三方案
        微基准 aabb_assembly_bench.py (逐行 2.78ms -> 命中 0.26ms, 10.5x)。
        ★shadow_prep 族直通行 (2026-09-07): out_rows 可选 (N,6) f64 行表 ——
        行序=sel 序 (与返回列表一致), 逐组 2 次 strided 段拷贝回填; 兜底行
        (fw 不全/形态防御走 get_bounding_box) 的行段由出口从 out 回填 (罕见
        路径, µs 级)。由 _model_aabbs_par 分发 (池 worker 各写互斥切片视图,
        worker 不碰实例字段); _scene_light_bounds_par row_input 直喂省
        n×2×3 属性链拆包 (取证 633µs/帧, n=501 编译等效口径)。"""
        sel = []
        for k, m in enumerate(models):
            M = fw[k] if fw is not None and k < len(fw) else None
            if visible_only and not getattr(m, 'visible', True):
                continue
            sel.append((m, M))
        if not sel:
            return []
        # shadow_prep 族直通行 (2026-09-07): out_rows 给定且容量足够时, 行序=sel 序
        # (=out 序); 组按 V 分桶与 sel 序交错 -> 逐组按 sel 下标 k 花式散写 (单组
        # 场景 k_idx=arange 等价连续段); 兜底行出口按 sel 下标回填。发布统一在
        # _model_aabbs_par (配对守卫 id(out)); out_rows=None 的旧调用零新增成本。
        N = len(sel)
        rows = out_rows if (out_rows is not None
                            and getattr(out_rows, 'shape', (0, 0))[0] >= N
                            and out_rows.ndim == 2 and out_rows.shape[1] == 6
                            and out_rows.dtype == np.float64) else None
        holes = []                            # 兜底行 sel 下标 [(起,止), ...] (出口回填)
        out = [None] * len(sel)
        groups = {}                       # V -> [(sel序号, vh, M3)]
        for k, (m, M) in enumerate(sel):
            if M is None:
                out[k] = self.get_bounding_box(m, None)   # 旧路径兜底 (fw 不全罕见)
                if holes and holes[-1][1] == k:
                    holes[-1] = (holes[-1][0], k + 1)
                else:
                    holes.append((k, k + 1))
                continue
            vh = self._homogeneous_vertices(m.mesh)
            if vh.shape[1] != 4 or M.shape != (4, 4):
                # 罕见形态防御: 退回单模型旧路径 (行为不变)
                out[k] = self.get_bounding_box(m, M)
                if holes and holes[-1][1] == k:
                    holes[-1] = (holes[-1][0], k + 1)
                else:
                    holes.append((k, k + 1))
                continue
            groups.setdefault(vh.shape[0], []).append((k, vh, M[:, :3]))
        # thread-local 堆叠缓冲缓存 (键=(组序号, V); 线程局部免锁,
        # 主线程/池 worker 各持一份, 生命周期 = 引擎实例).
        # 项B1 (2026-09-02 多物体批): 键去 n —— 缓冲按**容量**复用 (grow-only,
        # cap>=n 即用前 n 行), 物体数逐帧波动 (visible 过滤/增删) 不再触发重分配;
        # 旧 (gi,n,V) 键在 n 变化帧整组 4 缓冲全换 (500球 vhN 32.6MB/帧).
        tlc = getattr(self, '_aabb_staging', None)
        if tlc is None:
            tlc = self._aabb_staging = threading.local()
        buf_cache = getattr(tlc, 'bufs', None)
        if buf_cache is None:
            buf_cache = tlc.bufs = {}
        elif len(buf_cache) > 64:
            # 键集护栏: 键含首行 vh 身份, 池分块组合漂移会累积键; 超限整体
            # 清空 (代价 = 下帧一轮 miss 重建, 稳态键集远低于阈值不触发)。
            buf_cache.clear()
        for gi, lst in enumerate(groups.values()):
            n = len(lst)
            V = lst[0][1].shape[0]
            # ★组装段去重 (2026-09-07, 键=身份序列): 混合500 实测 7 组 501 行
            # 仅 35 个唯一 vh (同网格样本共享 _homogeneous_vertices 缓存对象),
            # 逐行写 = 同一数据重复拷贝 ~10 次。微基准三方案对比见
            # aabb_assembly_bench.py: 逐行写 3.07ms -> 身份命中 0.31ms (10x,
            # 源码口径; 编译版解释循环更慢收益更大); 每帧 gather 无收益,
            # fancy 临时分配 11-12ms 倒退 (第 11 版 32MB 教训同源)。
            # 缓存键 = (gi, V, 完整行身份序列): 键即命中判定 —— 全等命中帧
            # vhN 前 n 行内容=上帧同对象同值 (vh 按 id(mesh) 缓存 + 网格
            # 不可变契约) -> vh 段整段跳过; 键含全部行 id, 池分块 (map_indexed
            # 每个 worker 分块从 gi=0 重新枚举, "同 V 不同内容"组间) 不互踩
            # (纯 (gi,V) 键在分块间碰撞 -> 恒 miss, A/B 实测 -3.6% 教训);
            # 条目持 vh_refs 引用表, 缓存存活期旧数组不被 GC -> 活对象 id
            # 唯一, 同键必同内容 (假命中数学不可能)。键集护栏 64: 池分块组合
            # 漂移累积键超限整体清空 (代价=下帧一轮 miss 重建, 稳态远低于
            # 阈值不触发); miss 路径组内无重复 (nu==n) 时直接旧行为逐行写
            # (精确旧成本, 免 dict/take 固定开销)。
            key = (gi, V, tuple([id(row[1]) for row in lst]))
            ent = buf_cache.get(key)
            if ent is None or ent[0].shape[0] < n:
                # 分配/扩容 (首次/换组形态/容量不足): 容量 = max(n, 旧 cap*2)
                cap = n if ent is None else max(n, ent[0].shape[0] * 2)
                vhN = np.empty((cap, V, 4), dtype=np.float64)
                m3N = np.empty((cap, 4, 3), dtype=np.float64)
                mn = np.empty((cap, 3), dtype=np.float64)
                mx = np.empty((cap, 3), dtype=np.float64)
                # uniq = 唯一行表 (n,V,4) f64, 惰性按唯一数 grow-only (混合500
                # 仅 ~6 行/组, 不随 cap 翻倍 — 免 vhN 之外再压 32MB);
                # inv = 行→唯一行索引 intp; vh_refs = 唯一 vh 引用表。
                old_uniq = ent[4] if ent is not None else None
                if old_uniq is not None and old_uniq.shape[1:] != (V, 4):
                    old_uniq = None                   # 换组形态: 重建
                old_inv = ent[5] if ent is not None else None
                if old_inv is not None and old_inv.shape[0] < n:
                    old_inv = None                    # 容量不足: miss 分支重建
                ent = (vhN, m3N, mn, mx, old_uniq, old_inv, None)
                buf_cache[key] = ent
            # 单一解包点 (7 元组: 缓冲 + uniq/inv + miss 哨兵)
            vhN, m3N, mn, mx, uniq, inv, fresh = ent
            vhN_v = vhN[:n]
            m3N_v = m3N[:n]
            mn_v = mn[:n]
            mx_v = mx[:n]
            if not fresh:
                # miss (新键/换形态/扩容): 重建唯一行表 + gather/逐行写。
                if inv is None or inv.shape[0] < n:
                    inv = np.empty(max(n, 64), dtype=np.intp)  # grow-only
                seen = {}
                uniq_rows = []
                for r, row in enumerate(lst):
                    k = id(row[1])
                    j = seen.get(k, -1)
                    if j < 0:
                        j = len(uniq_rows); seen[k] = j
                        uniq_rows.append(row[1])
                    inv[r] = j
                nu = len(uniq_rows)
                if nu == n:
                    # 无重复行 (独立网格场景): gather 无意义, 直接旧行为逐行写
                    # (精确旧成本, 免 dict/take 固定开销)。
                    for r in range(n):
                        vhN_v[r] = lst[r][1]
                else:
                    if uniq is None or uniq.shape[0] < nu:
                        ucap = nu if uniq is None else max(nu, uniq.shape[0] * 2)
                        uniq = np.empty((ucap, V, 4), dtype=np.float64)
                    uniq_v = uniq[:nu]
                    for j in range(nu):
                        uniq_v[j] = uniq_rows[j]
                    # ★np.take 必须 mode='clip': 默认 mode='raise' 时 out= 被
                    # numpy 强制走内部临时缓冲 (文档: "out is always buffered
                    # if mode='raise'"), 每帧 n*V*4 f64 临时 (实测 17.7ms +
                    # 9.65MB —— 第 11 版 np.stack 32MB 倒退同源坑); inv 值域
                    # [0,nu) 受控, clip 语义等价且真零临时。
                    np.take(uniq_v, inv[:n], axis=0, out=vhN_v, mode='clip')
                ent = (vhN, m3N, mn, mx, uniq, inv, True)
                buf_cache[key] = ent
            # 命中帧 (fresh=True): vhN 前 n 行无需重写 —— 键即上帧同内容。
            # m3 段保持逐行原地写 (小缓冲 96B/行, 别动大的; 第 11 版教训:
            # 大缓冲每帧新建临时必倒退, 矩阵每帧变也无命中空间)。
            _t = self._prof_t0()
            for r in range(n):
                m3N_v[r] = lst[r][2]
            self._prof_add('mt_aabb_m3', _t)
            _t = self._prof_t0()
            if n * V >= self._AABB_PAR_MIN_WORK:
                fastpath.aabbs_minmax_par(vhN_v, m3N_v, mn_v, mx_v)  # 逃生门: 大规模 prange
            else:
                fastpath.aabbs_minmax(vhN_v, m3N_v, mn_v, mx_v)      # C/numba/numpy 三级分派
            self._prof_add('mt_aabb_minmax', _t)
            if os.environ.get('LOOM_PROFILE') == '1':
                # ★M3 观测量: 实际 kernel 工作量 (n×V), 用于算 ns/顶点 与规模分布
                self._stage_calls['aabb_work'] = \
                    self._stage_calls.get('aabb_work', 0) + n * V
                self._stage_calls['aabb_groups'] = \
                    self._stage_calls.get('aabb_groups', 0) + 1
            # shadow_prep 族直通行 (2026-09-07): mn/mx 本来就是连续 numpy (n,3) 行,
            # 按 sel 下标散写进行表 (组序与 sel 序交错, 不能连续段拷); 行表行序
            # 恒与 out 对齐。tolist+Point3D 包装照旧 (公共契约)。
            _t = self._prof_t0()
            if rows is not None:
                k_idx = np.array([row[0] for row in lst], dtype=np.intp)
                rows[k_idx, 0:3] = mn_v
                rows[k_idx, 3:6] = mx_v
            mn_rows = mn_v.tolist()
            mx_rows = mx_v.tolist()
            for r in range(n):
                a, b = mn_rows[r], mx_rows[r]
                out[lst[r][0]] = (Point3D(a[0], a[1], a[2]),
                                  Point3D(b[0], b[1], b[2]))
            self._prof_add('mt_aabb_out', _t)
        # 直通行兜底回填 (2026-09-07): get_bounding_box 行段从 out 取值 (罕见路径)。
        if rows is not None:
            for a, b in holes:
                for j in range(a, b):
                    mn_, mx_ = out[j]
                    rows[j, 0] = mn_.x; rows[j, 1] = mn_.y; rows[j, 2] = mn_.z
                    rows[j, 3] = mx_.x; rows[j, 4] = mx_.y; rows[j, 5] = mx_.z
        return out
    @staticmethod
    def _scene_light_bounds_par(view, aabbs, times=None, row_input=None):
        """把已算好的模型 AABB 列表 8 角变换到 view 空间, 返回 numpy (min, max) 或 None.
        向量化: 所有模型全部角点拼一个大 (n*8, 4) 批量一次 matmul + min/max (释放 GIL).
        times: 可选 _stage_times dict (staticmethod 无 self, 由调用方传入; 组8 细拆用).
        row_input: 可选 (n,6) float64 numpy 行 [[mn.x,mn.y,mn.z, mx.x,mx.y,mx.z], ...]
        (shadow_prep 族直通行, 2026-09-07: 调用方已持有 numpy AABB 行时直喂, 跳过
        下方 n×2×3 属性链拆包循环 —— 取证该循环 633µs/帧 ≈ 整体 60%, n=501 编译等效
        口径; 行序必须与 aabbs 列表序一致). aabbs 仍传 (数量源), row_input None 走旧
        逐位路径 (公共契约不变)."""
        if not aabbs:
            return None
        n = len(aabbs)
        _pr = os.environ.get('LOOM_PROFILE') == '1'
        _t0 = time.time() if _pr else None
        # 项D (2026-09-02 多物体批): 角点填充 numpy 花式索引一次展开 —— 旧实现
        # n*8 行逐行 Python 赋值 (500球 = 4008 行循环), 现在拆三轴分量列一次组装:
        #   xs 列 = [a.x, b.x] 交替 (np.tile), ys 列 = [a.y, b.y, b.y, a.y] 周期
        #   (np.tile), z 列 = [a.z, a.z, b.z, b.z] 周期 (np.repeat), 与旧 c[0..7]
        #   行序逐位一致: (ax,ay,az)(bx,ay,az)(ax,by,az)(bx,by,az)(ax,ay,bz)
        #   (bx,ay,bz)(ax,by,bz)(bx,by,bz). w 列常 1.0.
        # shadow_prep 族直通行 (2026-09-07): ab/cd 零拷贝列视图 (rows[:, 0:3] /
        # rows[:, 3:6], C 连续 (n,6) 行的列切片是常规 strided 视图不拷贝),
        # 消 n×2×3 属性链拆包 (取证 633µs/帧, 本函数 60%).
        if row_input is not None and getattr(row_input, 'shape', None) == (n, 6) \
                and row_input.dtype == np.float64:
            ab = row_input[:, 0:3]
            cd = row_input[:, 3:6]
        else:
            ab = np.empty((n, 3))                 # min 角
            cd = np.empty((n, 3))                 # max 角
            for i, (a, b) in enumerate(aabbs):
                ab[i] = (a.x, a.y, a.z)
                cd[i] = (b.x, b.y, b.z)
        corners = np.empty((n * 8, 4), dtype=np.float64)
        xs = np.empty((n, 2)); xs[:, 0] = ab[:, 0]; xs[:, 1] = cd[:, 0]
        ys = np.empty((n, 2)); ys[:, 0] = ab[:, 1]; ys[:, 1] = cd[:, 1]
        zs = np.empty((n, 2)); zs[:, 0] = ab[:, 2]; zs[:, 1] = cd[:, 2]
        corners[:, 0] = np.tile(xs, (1, 4)).ravel()          # x: a,b,a,b,a,b,a,b
        corners[:, 1] = np.tile(np.repeat(ys, 2, axis=1), (1, 2)).ravel()
        corners[:, 2] = np.repeat(zs, 4, axis=1).ravel()     # z: a,a,a,a,b,b,b,b
        corners[:, 3] = 1.0
        if _pr and times is not None:
            # 组8 细拆针 1: 角点填充 (纯 Python 4008 行循环嫌疑)
            times['shadow_cornerfill'] = \
                times.get('shadow_cornerfill', 0.0) + (time.time() - _t0) * 1000.0
            _t0 = time.time()
        w = corners @ view
        mn = w[:, :3].min(axis=0)
        mx = w[:, :3].max(axis=0)
        if _pr and times is not None:
            # 组8 细拆针 2: matmul+minmax (numpy 批量, 应为 µs 级)
            times['shadow_matmul'] = \
                times.get('shadow_matmul', 0.0) + (time.time() - _t0) * 1000.0
        return (mn, mx)

    def _dir_light_vp(self, light, aabbs=None, rows=None):
        """平行光 view-proj (正交): +z_view = 光行进方向, eye = 光源位置.
        full: 正交 XY 覆盖场景 bbox; beam: 正交 XY = 截面 [-size,size]^2, near=0 (射线起点).
        aabbs: 可选预计算 AABB 列表 (避免每帧重复算高面数模型的包围盒).
        rows: 可选与 aabbs 行序一致的 (n,6) f64 直通行表 (2026-09-07, 调用方自证
        配对 —— _compute_light_vps 过滤时同步花式拷贝; 自算路径走实例配对守卫)."""
        D = (light.direction.x, light.direction.y, light.direction.z)
        ln = math.sqrt(D[0] * D[0] + D[1] * D[1] + D[2] * D[2])
        if ln < 1e-6:
            return None
        D = (D[0] / ln, D[1] / ln, D[2] / ln)
        eye = (light.position.x, light.position.y, light.position.z)
        up = (light.up_vector().x, light.up_vector().y, light.up_vector().z)  # M30: roll 倾斜
        view = mat4_view_forward(np, eye, D, up)
        if aabbs is None:
            aabbs = self._model_aabbs_par(self.models, self._frame_world)
            # 直通行直喂 (2026-09-07): 本调用刚算好 aabbs, 行表与它 id 配对时
            # 跳过属性链拆包; 配对守卫挡"表过时/行序错位" (gen=id(out)+n)。
            rows = getattr(self, '_aabb_shadow_rows', None)
            if getattr(self, '_aabb_shadow_gen', None) != (id(aabbs), len(aabbs)):
                rows = None
        bounds = self._scene_light_bounds_par(
            view, aabbs, times=getattr(self, '_stage_times', None), row_input=rows)
        if bounds is None:
            return None
        mn, mx = bounds
        if light.mode == 'beam':
            s = max(light.size, 0.01)
            left, right = -s, s
            bottom, top = -s, s
            near, far = 0.0, max(float(mx[2]) + 2.0, 1.0)
        else:
            pad = 1.5
            left, right = float(mn[0]) - pad, float(mx[0]) + pad
            bottom, top = float(mn[1]) - pad, float(mx[1]) + pad
            near, far = min(0.0, float(mn[2]) - 2.0), max(float(mx[2]) + 2.0, 1.0)
        return view @ mat4_ortho(np, left, right, bottom, top, near, far)

    def _parallel_shadow_and_collision(self, dt, with_events=True):
        """批5 重构: A 类 prep (AABB/光源 VP/碰撞对) 已挪进逻辑帧尾缓存
        (_logic_prep); 渲染帧只做:
          ① 派发逻辑帧检测出的碰撞对 (改脚本状态, 必须主线程, 每逻辑帧一次);
          ② 兜底: 分离未开/编辑态 — 旧串行路径逐位保留.
        ★B2 退役 (2026-10-16): 删 LOOM_NO_PREP 逃生门; 下方旧路径保留
        (服务"分离未开/编辑态"功能边界, 非逃生门)。"""
        if (not getattr(self, '_split_enable', False)
                or not getattr(self, 'is_playing', False)):
            # ---- 旧路径逐位保留 (逃生门/编辑态基线) ----
            pool = self._frame_pool
            models = self.models
            n = len(models)
            need_collision = with_events and pool is not None \
                and n >= self._COLLISION_PAR_THRESHOLD
            need_shadow = any(l.kind == 'directional' and l.shadow and l.mode == 'full'
                              for l in self.lights[:8])
            if (need_collision or need_shadow) and pool is not None and n >= 2:
                aabbs = self._model_aabbs_par(models, self._frame_world, visible_only=False)
                if need_collision:
                    def _shadow():
                        self._profile('shadow_bounds', lambda: self._compute_light_vps(aabbs))
                    def _collide():
                        return self._profile(
                            'collide_pairs',
                            lambda: self._collision_pairs_parallel(aabbs=aabbs))
                    _t = time.time()
                    _r = pool.run_parallel([_shadow, _collide])
                    self._stage_times.setdefault('shadow_jobs', 0.0)
                    if os.environ.get('LOOM_PROFILE') == '1':
                        self._stage_times['shadow_jobs'] += (time.time() - _t) * 1000.0
                    self._profile('dispatch', lambda: self._dispatch_collision_events(_r[1]))
                else:
                    self._compute_light_vps(aabbs)
            else:
                if with_events:
                    self._profile('dispatch', lambda: self._update_collision_events(dt))
                self._compute_light_vps()
            return
        # ---- 批5 路径: 读逻辑帧缓存 ----
        _lgen, _pairs, _lvps = self._logic_snapshot()
        if with_events and self.is_playing:
            # 派发节流: 同一逻辑帧的 pairs 只派发一次 (多渲染帧同逻辑帧)
            if _pairs is not None and self._disp_gen != _lgen:
                self._profile('dispatch',
                              lambda: self._dispatch_collision_events(_pairs))
                self._disp_gen = _lgen
        self._light_vps = _lvps or {}

    def _pipeline_light_vps(self, aabbs, vps):
        """M2a: 走 pipeline.dll 算全部阴影光源 VP; 成功返 True (已填 vps)。

        只在能拿到**全量对齐** AABB 行表时启用 (行表是 DLL 的唯一输入口径);
        任何条件不满足/调用失败 → 返 False, 调用方回退现行 Python 路径。
        ★本方法不改任何数值语义: DLL 侧逐元素运算与 Python 现行实现逐位一致
        (矩阵乘法 ≤1 ULP), 见 tests/_tmp/pipeline_val_check.py 15/15。
        """
        # ★B2 退役 (2026-10-16): 删 LOOM_NO_PIPELINE / pg.disabled() 门。
        import pipeline_glue as pg
        lights = [l for l in self.lights[:8] if l.shadow]
        if not lights:
            return False
        n = len(self.models)
        rows = None
        if aabbs is not None and len(aabbs) == n:
            rows = getattr(self, '_aabb_shadow_rows', None)
            if (rows is None or getattr(rows, 'shape', None) != (n, 6)
                    or getattr(self, '_aabb_shadow_gen', None)
                    != (id(aabbs), len(aabbs))):
                # 行表缺失/配对守卫失败 → 由本方法就地构建 (保持与 aabbs 同序)
                import numpy as _np
                rows = _np.empty((n, 6), dtype=_np.float64)
                for i, (a, b) in enumerate(aabbs):
                    rows[i, 0] = a.x; rows[i, 1] = a.y; rows[i, 2] = a.z
                    rows[i, 3] = b.x; rows[i, 4] = b.y; rows[i, 5] = b.z
        need_bounds = any(l.kind == 'directional' and l.mode == 'full'
                          for l in lights)
        if need_bounds and rows is None:
            if aabbs is None:
                aabbs = self._model_aabbs_par(self.models, self._frame_world)
                rows = getattr(self, '_aabb_shadow_rows', None)
                if (rows is None or getattr(rows, 'shape', None) != (n, 6)
                        or getattr(self, '_aabb_shadow_gen', None)
                        != (id(aabbs), len(aabbs))):
                    import numpy as _np
                    rows = _np.empty((n, 6), dtype=_np.float64)
                    for i, (a, b) in enumerate(aabbs):
                        rows[i, 0] = a.x; rows[i, 1] = a.y; rows[i, 2] = a.z
                        rows[i, 3] = b.x; rows[i, 4] = b.y; rows[i, 5] = b.z
            else:
                return False
        vis_idx = None
        if need_bounds:
            vis_idx = [i for i, m in enumerate(self.models) if m.visible]
        res = pg.light_vps(rows, lights, vis_idx=vis_idx)
        if res is None:
            return False
        out, kinds = res
        for i, light in enumerate(lights):
            k = int(kinds[i])
            if k < 0:
                continue                       # 与 Python 返回 None 等价: 跳过
            if light.kind == 'directional':
                vps[light.guid] = out[i, 0]
            else:
                vps[light.guid] = [out[i, f] for f in range(6)]
        return True

    def _light_vps_cache_sig(self):
        """编辑态阴影VP静止缓存键 (2026-10-14): 世界矩阵对象身份 + 结构/外观代 +
        光源参数指纹。任一变化 -> 签名变 -> 失效重算。"""
        fw = getattr(self, '_frame_world', None)
        lsig = tuple(
            (l.guid, l.kind, bool(getattr(l, 'shadow', False)),
             getattr(l, 'mode', 'full'), getattr(l, 'shape', 'circle'),
             float(getattr(l, 'size', 0.0)),
             ((l.position.x, l.position.y, l.position.z)
              if getattr(l, 'position', None) is not None else None),
             (l.direction.x, l.direction.y, l.direction.z),
             (l.color[0], l.color[1], l.color[2]),
             float(l.intensity))
            for l in self.lights[:8])
        return (id(fw), getattr(self, '_struct_gen', 0),
                GameObject._appearance_gen, lsig)

    def _compute_light_vps(self, aabbs=None):
        """每帧一次: 全部阴影光源的 view-proj (平行光含场景包围, 点光 6 面), 缓存到
        self._light_vps = {guid: vp 或 [vp...]}. shadow pass 与 _upload_lights 都复用,
        消除旧代码"每帧对同一光源算两遍包围盒"的重复开销 (2026-08-15 8 核均摊).
        aabbs: 可选**全量对齐** AABB 列表 (阴影与碰撞共享的那份); 阴影只取可见物体的."""
        vps = {}
        if self.lights:
            # 编辑态静止缓存 (2026-10-14 性能修): 编辑态物体静止是常态, 但阴影VP
            # 每帧全算 (平行光要算全场景包围盒 + matmul, ~0.9ms@1801体)。签名不变
            # 即复用上帧结果。仅编辑态启用 (播放态走逻辑帧 _logic_prep 的 prep
            # 缓存协议, 语义不同不混入)。★B2 退役 (2026-10-16): 删 LOOM_NO_SHADOW_CACHE。
            if not getattr(self, 'is_playing', False):
                sig = self._light_vps_cache_sig()
                if getattr(self, '_light_vps_sig', None) == sig:
                    return self._light_vps or {}
                self._light_vps_sig = sig
            # ---- M2a: pipeline.dll 路径 (C, 无 GIL); 不可用 → 下方 Python 路径 ----
            # ★B2 退役 (2026-10-16): 删 LOOM_NO_PIPELINE 门。
            # 数据边界 (aabbs 行表不可用) 仍 fallback Python 路径。
            if self._pipeline_light_vps(aabbs, vps):
                self._light_vps = vps
                return vps
            # 需要场景 AABB 的只有"阴影+全场景"平行光; 共享时用传入的全量列表并过滤可见
            need_bounds = any(l.kind == 'directional' and l.shadow and l.mode == 'full'
                              for l in self.lights[:8])
            if need_bounds:
                if aabbs is None:
                    aabbs = self._model_aabbs_par(self.models, self._frame_world)
                # 直通行同步过滤 (2026-09-07): 行表与 aabbs id 配对时, 花式索引
                # 一次拷出可见行 (~µs 级), vis_aabbs 行序与行表一致 —— 平行光
                # _dir_light_vp 直喂 _scene_light_bounds_par 消属性链拆包。
                vis_idx = [i for i, m in enumerate(self.models) if m.visible]
                vis_aabbs = [aabbs[i] for i in vis_idx]
                rows = getattr(self, '_aabb_shadow_rows', None)
                if (getattr(self, '_aabb_shadow_gen', None)
                        != (id(aabbs), len(aabbs))) or rows is None:
                    vis_rows = None
                else:
                    vis_rows = rows[vis_idx] if vis_idx else None
            else:
                vis_aabbs = None
                vis_rows = None
            for light in self.lights[:8]:
                if not light.shadow:
                    continue
                if light.kind == 'directional':
                    vp = self._dir_light_vp(light, vis_aabbs, vis_rows)
                    if vp is not None:
                        vps[light.guid] = vp
                else:
                    vps[light.guid] = self._point_light_vp(light)
        self._light_vps = vps
        return vps

    def _point_light_vp(self, light):
        """点光源 6 面 view-proj (90° 透视). 面朝向与 _FRAG_SRC point_shadow 完全对应:
        +X,-X,+Y,-Y,+Z,-Z; ±X/±Z 面 up=(0,1,0), ±Y 面 up=(0,0,1)."""
        pos = (light.position.x, light.position.y, light.position.z)
        proj = mat4_perspective(np, math.radians(90.0), 1.0, 0.05, self._shadow_point_far)
        axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        ups = [(0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0)]
        return [mat4_view_forward(np, pos, a, u) @ proj for a, u in zip(axes, ups)]

