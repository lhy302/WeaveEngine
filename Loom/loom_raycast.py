# -*- coding: utf-8 -*-
"""loom_raycast.py — 射线检测子系统 (2026-10-18)

用户决策 C2（物理引擎层，不留技术债）：优先走 Culverin（Jolt）精确 raycast。
降级策略：若物理桥不可用（编辑器静态态 / Culverin 缺失），
          自动退到几何 AABB raycast（复用 editor 同款 slab 法），保证 API 总是可用。
几何 fallback 精度是 AABB 外接盒；物理路径精度是真实碰撞体形状。

三个主 API（决策 D1+D3）:
  raycast(origin, direction, max_dist=1000.0, ignore_model=None, backend='auto')
      -> (model, distance, hit_point_tuple) | None
  raycast_all(origin, direction, max_dist=1000.0, backend='auto')
      -> [(model, distance, hit_point_tuple), ...] 按距离升序
  raycast_screen(px, py, max_dist=1000.0, ignore_model=None, backend='auto')
      -> (model, distance, hit_point_tuple) | None  (从屏幕像素反投影, 一键拾取)

backend 参数:
  'auto'    (默认) 有物理桥走物理, 否则走几何
  'physics' 强制物理 (无桥返回 None + 警告)
  'geometry' 强制几何
"""
import math

import numpy as np

try:
    from loom_types import Point3D
except ImportError:
    Point3D = None


# ======================== 几何 AABB fallback ========================

def _ray_aabb(origin, dirv, mn, mx):
    """slab 法 射线-AABB 相交。返回进入距离 t (>=0) 或 None.

    与 editor._ray_aabb 数学语义一致（未来若 editor 也要复用，可提取到这里）。
    """
    o, d = origin, dirv
    tmin, tmax = 0.0, float('inf')
    for i in range(3):
        if abs(d[i]) < 1e-9:
            if o[i] < mn[i] or o[i] > mx[i]:
                return None
        else:
            t1 = (mn[i] - o[i]) / d[i]
            t2 = (mx[i] - o[i]) / d[i]
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return None
    return tmin if tmin >= 0 else (tmax if tmax >= 0 else None)


class RaycastMixin:
    """GLEngine 的射线检测 mixin.

    使用方式（脚本/命令）:
        hit = engine.raycast((0, 1, 0), (0, -1, 0))
        if hit:
            model, dist, point = hit
            print("命中", model.name, "距离", dist)
    """

    # ---------- 内部: 物理桥句柄反查 ----------
    def _raycast_handle_map(self):
        """从物理桥 _entries 构建 {handle: model} 映射. 无桥返回 {}."""
        bridge = getattr(self, '_phys_bridge', None)
        if bridge is None:
            return {}
        try:
            entries = getattr(bridge, '_entries', None) or []
            return {e['handle']: e['model'] for e in entries
                    if 'handle' in e and 'model' in e}
        except Exception:
            return {}

    def _raycast_phys_available(self):
        bridge = getattr(self, '_phys_bridge', None)
        if bridge is None:
            return False
        if getattr(bridge, '_w', None) is None:
            return False
        try:
            import physics_bridge as pb
            return pb.cv_available
        except Exception:
            return False

    # ---------- 内部: 物理 raycast ----------
    def _raycast_phys(self, origin, direction, max_dist, ignore_handle=0):
        """返回 (handle, distance, hit_point_tuple) 或 None.

        ★重要（2026-10-18 探针确认）：Culverin 的 raycast 返回的 distance 是
        **max_dist 的比例值**（0~1），不是世界单位距离。
          真实距离 = ratio_returned * max_dist
        必须乘回去，否则拿到的距离永远是 0~1 之间的小数（错误）。
        """
        bridge = getattr(self, '_phys_bridge', None)
        if bridge is None or getattr(bridge, '_w', None) is None:
            return None
        try:
            o = (float(origin[0]), float(origin[1]), float(origin[2]))
            d = (float(direction[0]), float(direction[1]), float(direction[2]))
            md = float(max_dist)
            r = bridge._w.raycast(o, d, md, int(ignore_handle))
            if r is None:
                return None
            handle, ratio, normal = r
            # 归一化方向（hit_point 用单位方向 * 真实距离）
            ln = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
            if ln < 1e-12:
                return None
            dn = (d[0] / ln, d[1] / ln, d[2] / ln)
            # ★ Culverin 返回 ratio 需乘 max_dist 才是真实距离
            real_dist = float(ratio) * md
            hp = (o[0] + dn[0] * real_dist,
                  o[1] + dn[1] * real_dist,
                  o[2] + dn[2] * real_dist)
            return (int(handle), real_dist, hp)
        except Exception:
            return None

    # ---------- 内部: 几何 raycast ----------
    def _raycast_geom_all(self, origin, direction, max_dist):
        """几何 AABB raycast 返回 [(model, distance, hit_point), ...] 距离升序."""
        o = (float(origin[0]), float(origin[1]), float(origin[2]))
        d = (float(direction[0]), float(direction[1]), float(direction[2]))
        # 归一化方向（保证 distance 是世界单位）
        ln = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        if ln < 1e-12:
            return []
        dn = (d[0] / ln, d[1] / ln, d[2] / ln)

        models = getattr(self, 'models', None) or []
        if not models:
            return []
        # 复用渲染时的批量 AABB（有则用，无则现算）
        try:
            fw = getattr(self, '_frame_world', None)
            if fw is None or len(fw) != len(models):
                fw = self.compute_world_matrices(models)
            aabbs = self._model_aabbs_par(models, fw)
        except Exception:
            # 保底：逐模型现算
            aabbs = [None] * len(models)
            for i, m in enumerate(models):
                try:
                    from physics_bridge import collider_bounds
                    ab = collider_bounds(m)
                    if ab is not None:
                        aabbs[i] = ab
                except Exception:
                    pass

        results = []
        for i, m in enumerate(models):
            if not m.visible:
                continue
            ab = aabbs[i]
            if ab is None:
                continue
            mn, mx = ab
            t = _ray_aabb(o, dn, (mn.x, mn.y, mn.z), (mx.x, mx.y, mx.z))
            if t is None or t > max_dist or t < 0:
                continue
            hp = (o[0] + dn[0] * t, o[1] + dn[1] * t, o[2] + dn[2] * t)
            results.append((m, float(t), hp))
        results.sort(key=lambda x: x[1])
        return results

    # ---------- 公开 API ----------
    def raycast(self, origin, direction, max_dist=1000.0,
                ignore_model=None, backend='auto'):
        """射线检测: 返回最近命中的物体.

        参数:
          origin: (x, y, z) 起点
          direction: (dx, dy, dz) 方向（不必单位化）
          max_dist: 最大检测距离
          ignore_model: 忽略的模型对象（射线从它内部射出时用）
          backend: 'auto'|'physics'|'geometry'（默认 auto）

        返回: (model, distance, hit_point_tuple) 或 None
        """
        use_phys = (backend == 'physics'
                    or (backend == 'auto' and self._raycast_phys_available()))

        if use_phys:
            ignore_handle = 0
            if ignore_model is not None:
                bridge = getattr(self, '_phys_bridge', None)
                if bridge is not None:
                    for e in getattr(bridge, '_entries', []) or []:
                        if e.get('model') is ignore_model:
                            ignore_handle = int(e.get('handle', 0))
                            break
            r = self._raycast_phys(origin, direction, max_dist, ignore_handle)
            if r is None:
                return None
            handle, dist, hp = r
            hm = self._raycast_handle_map()
            model = hm.get(handle)
            if model is None:
                return None
            return (model, dist, hp)

        # 几何路径
        all_hits = self._raycast_geom_all(origin, direction, max_dist)
        for m, dist, hp in all_hits:
            if m is ignore_model:
                continue
            return (m, dist, hp)
        return None

    def raycast_all(self, origin, direction, max_dist=1000.0, backend='auto'):
        """射线检测: 返回所有命中（按距离升序）.

        返回: [(model, distance, hit_point_tuple), ...]（可能空列表）
        """
        use_phys = (backend == 'physics'
                    or (backend == 'auto' and self._raycast_phys_available()))

        if use_phys:
            hm = self._raycast_handle_map()
            results = []
            ignore = 0
            seen = set()
            # 上限 100 次避免死循环（若 Culverin 返回同一 handle 会死循环）
            for _ in range(100):
                r = self._raycast_phys(origin, direction, max_dist, ignore)
                if r is None:
                    break
                handle, dist, hp = r
                if handle in seen:
                    break
                seen.add(handle)
                model = hm.get(handle)
                if model is not None:
                    results.append((model, dist, hp))
                ignore = handle
            results.sort(key=lambda x: x[1])
            return results

        return self._raycast_geom_all(origin, direction, max_dist)

    def raycast_screen(self, px, py, max_dist=1000.0,
                       ignore_model=None, backend='auto'):
        """从屏幕像素 (px, py) 反投影发射线，返回最近命中.

        返回: (model, distance, hit_point_tuple) 或 None
        """
        ray = self._ray_from_screen(px, py)
        if ray is None:
            return None
        origin, direction = ray
        return self.raycast(origin, direction, max_dist,
                            ignore_model=ignore_model, backend=backend)

    # ---------- 内部: 屏幕坐标反投影 ----------
    def _ray_from_screen(self, px, py):
        """屏幕像素 -> (射线起点, 单位方向). 复用 self._vp.

        无 _vp（首帧前）时返回 None。
        """
        vp = getattr(self, '_vp', None)
        if vp is None:
            return None
        w = getattr(self, 'width', 0)
        h = getattr(self, 'height', 0)
        if w <= 0 or h <= 0:
            return None
        try:
            inv = np.linalg.inv(vp)
        except Exception:
            return None
        # NDC (near z=0, far z=1)
        ndc_near = np.array([2 * px / w - 1, 1 - 2 * py / h, 0.0, 1.0])
        ndc_far = np.array([2 * px / w - 1, 1 - 2 * py / h, 1.0, 1.0])
        near = ndc_near @ inv
        far = ndc_far @ inv
        if abs(near[3]) < 1e-12 or abs(far[3]) < 1e-12:
            return None
        near_w = (near[0] / near[3], near[1] / near[3], near[2] / near[3])
        far_w = (far[0] / far[3], far[1] / far[3], far[2] / far[3])
        d = (far_w[0] - near_w[0],
             far_w[1] - near_w[1],
             far_w[2] - near_w[2])
        ln = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        if ln < 1e-12:
            return None
        return (near_w, (d[0] / ln, d[1] / ln, d[2] / ln))
