# -*- coding: utf-8 -*-
"""editor/core_selection.py — 拾取与选择态：世界/屏幕投影、射线、AABB 命中、选中读写与下标钳制。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：拾取与选择态：世界/屏幕投影、射线、AABB 命中、选中读写与下标钳制。
我不负责：gizmo 拖拽（core_gizmo）；UI 鼠标派发 _dispatch_ui_mouse（core.py：源码文本门）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
import math
import numpy as np
from engine import (GLEngine, Point3D, LightState, CameraState, wrap_deg,
                    gc_play_enter, gc_play_exit)

class EditorSelectionMixin(object):
    """拾取与选择态：世界/屏幕投影、射线、AABB 命中、选中读写与下标钳制（纯搬迁）。"""

    def _selected(self):
        """当前选中的物体 (选中光源时返回 None)"""
        if self.selected_light_index >= 0:
            return None
        if 0 <= self.selected_index < len(self.models):
            return self.models[self.selected_index]
        return None

    def _select_model(self, index):
        """选中物体 (models 下标): 清掉光源/摄像机选中 —— 三者互斥.
        (2026-08-12 修复: 加光源后再点物体永远选不中, 因 _selected() 优先返回光源;
         2026-08-15 补: 层级对象行松开/添加/复制/挂父/脱父等路径也要走这里, 且清摄像机.)"""
        self.selected_index = index
        self.selected_light_index = -1
        self.selected_camera_index = -1

    def _selected_light(self):
        """当前选中的光源 (未选中光源返回 None)"""
        if 0 <= self.selected_light_index < len(self.lights):
            return self.lights[self.selected_light_index]
        return None

    def _selected_camera(self):
        """当前选中的摄像机 (未选中摄像机返回 None)"""
        if 0 <= self.selected_camera_index < len(self.cameras):
            return self.cameras[self.selected_camera_index]
        return None

    def _select_camera(self, cam):
        """选中某摄像机 (统一清光源/物体选中)"""
        self.selected_camera_index = self.cameras.index(cam)
        self.selected_light_index = -1
        self.selected_index = -1

    # ================ 射线拾取 (M8) ================
    def project_world(self, p):
        """世界点 -> 屏幕像素 (y 向下). 行向量: clip = world @ _vp.
        摄像机背后的点返回 None (2026-08-21 修复, pygame 时期遗留): 背面点
        clip.w<0, 除以负 w 后 NDC 符号翻转 -> 投影到屏幕镜像位置, 表现为
        gizmo 轴帽/光源图标在"背面 180 度"再渲染一遍 (用户实测)."""
        ndc = np.array([p[0], p[1], p[2], 1.0]) @ self._vp
        w = ndc[3]
        if w <= 0:
            return None
        ndc = ndc / w
        return ((ndc[0] + 1) * 0.5 * self.width, (1 - ndc[1]) * 0.5 * self.height)

    def _unproject(self, px, py, ndc_z):
        """屏幕像素 (y 向下) -> 世界点. NDC 深度 [0,1]: z=0 近平面, z=1 远平面."""
        ndc = np.array([2 * px / self.width - 1, 1 - 2 * py / self.height, ndc_z, 1.0])
        world = ndc @ np.linalg.inv(self._vp)      # 行向量: clip @ inv(V·P) = world
        return Point3D(world[0] / world[3], world[1] / world[3], world[2] / world[3])

    def _ray_from_mouse(self, px, py):
        """像素点 -> (射线原点, 单位方向)"""
        near = self._unproject(px, py, 0.0)
        far = self._unproject(px, py, 1.0)
        d = (far.x - near.x, far.y - near.y, far.z - near.z)
        ln = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        if ln < 1e-12:
            return near, (0.0, 0.0, 0.0)
        return near, (d[0] / ln, d[1] / ln, d[2] / ln)

    @staticmethod
    def _ray_aabb(origin, dirv, mn, mx):
        """slab 法 射线-AABB 相交. 返回进入距离 t (>=0) 或 None."""
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
        return tmin

    def _pick(self, px, py):
        """视口点选: 射线 vs 各可见对象 AABB, 取最近命中.
        项B3 (2026-09-02 多物体批): AABB 读当帧批量缓存 (_frame_world 已由
        render 每帧算好, _model_aabbs_par 走 fastpath 批量内核), 不逐模型
        get_bounding_box 现算 (500球逐模型 ~30ms -> 批量 ~1ms). 命中结果与
        旧路径数值同源 (同 get_bounding_box 语义, 批量内核 D6 对拍 1e-7 内)."""
        origin, dirv = self._ray_from_mouse(px, py)
        o = (origin.x, origin.y, origin.z)
        best, best_t = None, float('inf')
        # 当帧世界矩阵: render 已算 (_frame_world); 编辑器冷启动首帧前无缓存时兜底现算
        fw = getattr(self, '_frame_world', None)
        if fw is None or len(fw) != len(self.models):
            fw = self.compute_world_matrices(self.models)
        aabbs = self._model_aabbs_par(self.models, fw)
        for i, m in enumerate(self.models):
            if not m.visible:
                continue
            ab = aabbs[i]
            if ab is None:
                continue
            (mn, mx) = ab
            t = self._ray_aabb(o, dirv, (mn.x, mn.y, mn.z), (mx.x, mx.y, mx.z))
            if t is not None and t < best_t:
                best_t = t
                best = i
        if best is not None:
            self._select_model(best)   # 点选到物体: 清光源选中 (2026-08-12 修复)

    def _reselect(self, guid):
        if guid is not None:
            for i, m in enumerate(self.models):
                if m.guid == guid:
                    self._select_model(i)
                    return
        self._clamp_selection()

    def _clamp_selection(self):
        if self.selected_index >= len(self.models):
            self.selected_index = max(0, len(self.models) - 1)

    def _clamp_light_selection(self):
        """撤销/重做后光源选择越界则清空 (M21)"""
        if self.selected_light_index >= len(self.lights):
            self.selected_light_index = -1
