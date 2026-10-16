# -*- coding: utf-8 -*-
"""
interp_state.py — 逻辑帧双快照 + 渲染帧 numpy 插值 (分离批2, 2026-09-05)

InterpState = prev/curr 两个 (N,3) 平面快照 (position/rotation_euler/scale):
  - advance(): 逻辑帧翻页 prev<-curr, curr<-_grab() (照抄 engine.
    _transform_snapshot 的 id 钉住三件对象模式, R6);
  - render_pose(alpha): 全 numpy 向量化插值平面 (pos/scl lerp, rot 小角度
    angdiff), 只喂渲染矩阵管道, **不回写 GameObject** (R3);
  - align(): curr=prev 强制对齐 (暂停/加载/toggle_play 边界, alpha=0);
  - 新增物体: prev 缺行用 curr 行填 (首帧不插值);
  - 缓冲 grow-only (R8): 按 2x 容量复用, 扩容只在物体数增长帧。

双端共享: engine.GLEngine 与 scene_driver.SceneDriver 各持一个实例,
  本文件不 import 任何一端 (依赖倒置, 零循环导入)。
"""
import numpy as np


class InterpState:
    """prev/curr 变换快照 + alpha 插值 (numpy 平面, grow-only)."""

    def __init__(self, models):
        self._models_ref = models        # models 列表对象 (id 钉住判据用)
        self._ids = None                 # (N,) int64 上逻辑帧物体 id 序
        self._prev = None                # (cap,3) f64 pos/rot/scl 双缓冲
        self._prev_rot = None
        self._prev_scl = None
        self._curr = None
        self._curr_rot = None
        self._curr_scl = None
        self._out = None                 # 插值输出平面 (持久, R8)
        self._out_rot = None
        self._out_scl = None
        self.alpha = 0.0
        self._n = 0                      # 上逻辑帧物体数
        # ★M3-P1: argsort(known) 缓存 —— known = _ids[:n] 只在逻辑帧翻页时换对象,
        # 渲染帧 90/s 里绝大多数帧可复用 (原每帧 O(n log n) 排序, 实测 0.19 ms/帧级).
        self._order_cache = None         # np.argsort(known) 结果
        self._order_key = None           # (id(self._ids), self._n)
        self._known_sorted = None        # known[order] (searchsorted 输入)
        # ★M3-N4: 整段插值走 pipeline.dll; ★B2 退役 (2026-10-16) 删 LOOM_NO_INTERP_POSE_DLL 门
        self._loc_buf = None             # grow-only int64 行号缓冲 (免每帧分配)
        self._world_buf = None           # grow-only (n,4,4) f64 世界矩阵输出缓冲

    # ---------------- 抓取 (照抄 _transform_snapshot 钉住模式) ----------------
    def _grab(self, models):
        """当前变换 -> (ids, pos, rot, scl) 三个 (N,3) f64 平面.
        R6: ids 记录 id(m) 且把模型列表对象钉在 self._models_ref —— 与
        _transform_snapshot 的对象钉住同构: 钉住的对象不死, id 不可能被
        复用, ids 相等 ⟺ 同一批物体 ⟹ 行对齐成立."""
        n = len(models)
        ids = np.empty(n, dtype=np.int64)
        pos = np.empty((n, 3), dtype=np.float64)
        rot = np.empty((n, 3), dtype=np.float64)
        scl = np.empty((n, 3), dtype=np.float64)
        for i, m in enumerate(models):
            ids[i] = id(m)
            p = m.position; r = m.rotation; s = m.scale
            pos[i, 0] = p.x; pos[i, 1] = p.y; pos[i, 2] = p.z
            rot[i, 0] = r.x; rot[i, 1] = r.y; rot[i, 2] = r.z
            scl[i, 0] = s[0]; scl[i, 1] = s[1]; scl[i, 2] = s[2]
        return ids, pos, rot, scl

    def _fit(self, n):
        """grow-only 扩容 (R8): 只在 n > 当前容量时重分配 (2x 余量).
        重分配保留前 _n 行有效数据 (curr/prev 均按 _ids 行序; 丢数据会让
        扩容帧 prev 变脏内存 — 物体数增长帧插值从垃圾值起步)."""
        keep = self._n
        def fit(buf):
            if buf is None or buf.shape[0] < n:
                cap = max(n, (buf.shape[0] * 2) if buf is not None else 64)
                nb = np.empty((cap, 3), dtype=np.float64)
                if buf is not None and keep:
                    nb[:keep] = buf[:keep]
                return nb
            return buf
        self._curr = fit(self._curr); self._curr_rot = fit(self._curr_rot)
        self._curr_scl = fit(self._curr_scl)
        self._prev = fit(self._prev); self._prev_rot = fit(self._prev_rot)
        self._prev_scl = fit(self._prev_scl)
        self._out = fit(self._out); self._out_rot = fit(self._out_rot)
        self._out_scl = fit(self._out_scl)

    # ---------------- 逻辑帧翻页 ----------------
    def advance(self, planes=None):
        """每逻辑帧末调 (engine._logic_frame / driver 逻辑步尾):
        prev <- curr; curr <- 新抓取.
        优化 (2026-10-01): 支持直接喂入已算好的 SoA 平面 planes=(pos, rot, scl),
        消除每逻辑帧对 500+ 物体的 1500 次 property 读取和重复大数组分配。"""
        models = self._models_ref
        n = len(models)
        if planes is not None and len(planes) == 3 and planes[0].shape[0] == n:
            pos, rot, scl = planes
            if self._ids is None or self._ids.shape[0] != n:
                ids = np.fromiter((id(m) for m in models), dtype=np.int64, count=n)
            else:
                ids = self._ids
        else:
            ids, pos, rot, scl = self._grab(models)
        self._fit(n)
        # prev = curr (同容量平面整块拷; 对齐在 render_pose 按 ids 重建)
        if self._n and self._curr is not None:
            m = min(self._n, n)
            self._prev[:m] = self._curr[:m]
            self._prev_rot[:m] = self._curr_rot[:m]
            self._prev_scl[:m] = self._curr_scl[:m]
        self._curr[:n] = pos
        self._curr_rot[:n] = rot
        self._curr_scl[:n] = scl
        self._ids = ids
        self._n = n

    def align(self):
        """边界强制对齐 (暂停/加载/进出播放): prev=curr, alpha=0 (无插值)."""
        if self._curr is not None and self._n:
            self._prev[:self._n] = self._curr[:self._n]
            self._prev_rot[:self._n] = self._curr_rot[:self._n]
            self._prev_scl[:self._n] = self._curr_scl[:self._n]
        self.alpha = 0.0

    # ---------------- 渲染帧插值 ----------------
    # 方案二 (2026-09-05): 渲染位姿模式 — INTERP_LERP 插值 (落后 curr 半帧内,
    # 默认) / EXTRAP 外推 (领先 curr: a'=1+alpha, SmoothMover/Unity
    # Rigidbody.interpolation=Extrapolate 同款, 输入延迟降半帧;
    # a' 封顶 1.5 防外推跑飞, 弹跳顶点画面超前属已知 trade-off).
    INTERP_LERP = 0
    INTERP_EXTRAP = 1
    _EXTRAP_CAP = 1.5          # 外推系数上限 (调研 §五③: 封顶防抖)

    def render_pose(self, alpha, models, mode=INTERP_LERP):
        """渲染帧调: 产出插值平面 (N,3)x3, 返回 (pos, rot, scl) 只读视图.
        全 numpy 向量化; 不回写 GameObject (R3).
        mode=INTERP_EXTRAP: a' = 1 + alpha (alpha∈[0,1) → a'∈[1,2), 封顶 1.5);
          prev==curr (静止) 时外推=恒等, 零风险.
        行对齐协议: curr/prev 平面按 _ids 行序 (上次 advance 的 models 序);
        输出平面按当前 models 行序 — 每物体经 loc (它在 _ids 里的行号) 取行.
        新增物体 (上逻辑帧后才加入): 无 curr 行 → 停泊到自由行 (≥_n),
        prev/curr 都填现读值 (lerp 恒等当前值 → 首帧不插值);
        消失物体: 行不被任何输出行引用, 自然剔除."""
        self.alpha = float(alpha)
        n = len(models)
        if self._curr is None or n == 0 or not self._n:
            return None, None, None
        # ★M3 诊断: 引擎注入的计时钩子 (仅 LOOM_PROFILE=1 时存在)
        _t0f, _addf = getattr(self, '_prof', (None, None))
        _t = _t0f() if _t0f is not None else 0.0
        cap = self._curr.shape[0]
        cur_ids = np.fromiter((id(m) for m in models), dtype=np.int64, count=n)
        known = self._ids[:self._n]
        # ★M3-P1: order/known_sorted 缓存 (键 = _ids 对象身份 + 行数; advance 换新
        #  数组对象 → 自动失效)。语义与逐帧重算逐位一致 (同数组同算法)。
        _okey = (id(self._ids), self._n)
        if self._order_cache is None or self._order_key != _okey:
            self._order_cache = np.argsort(known)
            self._known_sorted = known[self._order_cache]
            self._order_key = _okey
        order = self._order_cache
        a = self.alpha
        # 外推模式: 渲染时刻在 curr 逻辑帧之后 → a' = 1 + alpha (封顶 1.5)
        if mode == InterpState.INTERP_EXTRAP:
            a = min(1.0 + a, InterpState._EXTRAP_CAP)
        # ★M3-N4 (2026-09-09): 整段 (行映射 + pos/rot/scl lerp) 走 pipeline.dll
        #   (C, nogil)。逐位等价由 tests\_tmp\interp_pose_check.py 对拍。
        # ★B2 退役 (2026-10-16): 删 LOOM_NO_INTERP_POSE_DLL 门 + numpy 回退段
        #   (pipeline 官方件唯一路径)。
        r = self._pose_dll_call(cur_ids, self._known_sorted, order, a, n, models, cap)
        if r is None:
            raise RuntimeError('pipeline.dll interp_pose 返回 None (契约违约)')
        if _t:
            _addf('mt_pose_dll', _t)
        return r

    def render_world(self, models, parent, depth, max_depth, a):
        """★M3-N6: 插值平面 → 世界矩阵**整段**走 C (一次调用)。

        等价于「render_pose 的输出再喂 world_matrices」, 但中间 pos/rot/scl 平面
        留在 C 内, 省掉两次 ctypes 往返 + 6 个平面的编组 (实测 1.28 → ~0.6 ms/帧)。
        返回 (n,4,4) f64 视图; None = 有新物体 → 调用方走旧路径。
        ★B2 退役 (2026-10-16): 删 _pose_dll_off / pg.disabled() 门。
        """
        n = len(models)
        if self._curr is None or n == 0 or not self._n:
            return None
        import pipeline_glue as pg
        cur_ids = np.fromiter((id(m) for m in models), dtype=np.int64, count=n)
        known = self._ids[:self._n]
        _okey = (id(self._ids), self._n)
        if self._order_cache is None or self._order_key != _okey:
            self._order_cache = np.argsort(known)
            self._known_sorted = known[self._order_cache]
            self._order_key = _okey
        order = self._order_cache
        loc = self._loc_buf
        if loc is None or loc.shape[0] < n:
            loc = self._loc_buf = np.empty(max(64, n), dtype=np.int64)
        world = self._world_buf
        if world is None or world.shape[0] < n:
            world = self._world_buf = np.empty((max(64, n), 4, 4),
                                               dtype=np.float64)
        r = pg.interp_world(cur_ids, self._known_sorted, order,
                            self._prev, self._curr,
                            self._prev_rot, self._curr_rot,
                            self._prev_scl, self._curr_scl,
                            parent, depth, int(max_depth), a,
                            loc[:n], world[:n])
        if r is None:
            return None
        if not bool((known[r[0]] == cur_ids).all()):
            return None                      # 有新物体 → 交旧路 (含停泊逻辑)
        return r[1]

    def _pose_dll_call(self, cur_ids, known_sorted, order, a, n, models, cap):
        """★M3-N4: 整段 (行映射 + pos/rot/scl lerp) 走 pipeline.dll。

        与下方 numpy 路径逐位等价 (tests\\_tmp\\interp_pose_check.py 对拍)。
        返回 (pos, rot, scl) 视图; None = 新物体停泊重跑后仍失败 (契约违约)。
        新物体 (known[loc] != cur_ids) 罕见: 停泊到自由行后重跑一次 C。
        ★B2 退役 (2026-10-16): 删 _pose_dll_off / pg.disabled() 门。
        """
        import pipeline_glue as pg
        loc = self._loc_buf
        if loc is None or loc.shape[0] < n:
            loc = self._loc_buf = np.empty(max(64, n), dtype=np.int64)
        loc_v = loc[:n]
        r = pg.interp_pose(cur_ids, known_sorted, order,
                           self._prev, self._curr,
                           self._prev_rot, self._curr_rot,
                           self._prev_scl, self._curr_scl, a,
                           loc_v, self._out[:n], self._out_rot[:n],
                           self._out_scl[:n])
        if r is None:
            return None
        loc2 = r[0]
        known = self._ids[:self._n]
        valid = known[loc2] == cur_ids
        if not valid.all():
            miss = ~valid
            rows_miss = np.nonzero(miss)[0]
            need = self._n + rows_miss.size
            if need > cap:
                self._fit(need)                 # R8: 仅增长帧分配
            for r2, fr in zip(rows_miss, range(self._n, need)):
                m = models[r2]
                self._prev[fr] = (m.position.x, m.position.y, m.position.z)
                self._curr[fr] = self._prev[fr]
                self._prev_rot[fr] = (m.rotation.x, m.rotation.y, m.rotation.z)
                self._curr_rot[fr] = self._prev_rot[fr]
                self._prev_scl[fr] = (m.scale[0], m.scale[1], m.scale[2])
                self._curr_scl[fr] = self._prev_scl[fr]
            loc2[miss] = range(self._n, need)
            r = pg.interp_pose(cur_ids, known_sorted, order,
                               self._prev, self._curr,
                               self._prev_rot, self._curr_rot,
                               self._prev_scl, self._curr_scl, a,
                               loc2, self._out[:n], self._out_rot[:n],
                               self._out_scl[:n])
            if r is None:
                return None
        return r[1], r[2], r[3]

    def interp_position(self, m):
        """单物体渲染帧位置 (脚本相机跟随便捷 API):
        先 render_pose 缓存平面, 再按物体查行. 逻辑状态零读取污染."""
        models = self._models_ref
        pos, _r, _s = self.render_pose(self.alpha, models)
        if pos is None:
            p = m.position
            return (p.x, p.y, p.z)
        try:
            i = models.index(m)          # 相机仅 1 次/帧, O(n) 可接受
        except ValueError:
            p = m.position
            return (p.x, p.y, p.z)
        return (float(pos[i, 0]), float(pos[i, 1]), float(pos[i, 2]))

    def static_frame(self):
        """本渲染帧插值平面是否与上渲染帧逐位相同 (静止判定, 供桶闸跳过):
        prev==curr (上一逻辑帧无位移) 即静止 — 静止行 lerp 输出恒等."""
        if self._curr is None or self._prev is None or not self._n:
            return True
        n = self._n
        return bool((self._curr[:n] == self._prev[:n]).all()
                    and (self._curr_rot[:n] == self._prev_rot[:n]).all()
                    and (self._curr_scl[:n] == self._prev_scl[:n]).all())
