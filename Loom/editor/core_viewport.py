# -*- coding: utf-8 -*-
"""editor/core_viewport.py — 编辑器视口：6 元布局计算 / 视口内判定 / 无限网格线几何。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：编辑器视口：6 元布局计算 / 视口内判定 / 无限网格线几何。
我不负责：选中框叠加绘制与整帧渲染（core.py：源码文本门锁 _draw_selection_box 的 overlay_scope 行）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""

class EditorViewportMixin(object):
    """编辑器视口：6 元布局计算 / 视口内判定 / 无限网格线几何（纯搬迁）。"""

    def _layout(self):
        """6 元布局 (2026-08-14 晚: 左右/上下分隔条可拖 + 收起).
        面板宽高由 self.panel_* 状态决定, 视图/交互层共读; 保证视口最小宽度."""
        w, h = self.width, self.height
        toolbar = (0, 0, w, 36)
        status = (0, h - 24, w, 24)
        # 左列上下分栏 (M24): 层级在上、资源浏览器在下 (对齐 Unity Project 窗口)
        left_h = h - 60
        max_side = max(24, (w - 120) // 2)   # 每侧最大宽, 保证视口 >= 120
        lw = 24 if self.panel_left_collapsed else max(24, min(max_side, self.panel_left_w))
        rw = 24 if self.panel_right_collapsed else max(24, min(max_side, self.panel_right_w))
        hier_h = int(left_h * self.panel_hier_frac)
        hier_h = max(30, min(left_h - 30, hier_h))
        hierarchy = (0, 36, lw, hier_h)
        resources = (0, 36 + hier_h, lw, left_h - hier_h)
        inspector = (w - rw, 36, rw, left_h)
        viewport = (lw, 36, w - lw - rw, left_h)
        return toolbar, status, hierarchy, inspector, viewport, resources

    def _in_viewport(self, pos):
        vp = self._layout()[4]
        return (vp[0] <= pos[0] < vp[0] + vp[2] and
                vp[1] <= pos[1] < vp[1] + vp[3])

    def grid_geometry(self):
        """无限网格 (2026-08-14): 相机 XZ 为中心 (吸附整数格), 恒定步长, 远处淡出.
        范围只随相机距离 (缩放) 变化, 不随抬头角度; 永不返回 None. 视图层调用."""
        try:
            from ui.grid import build_grid_lines
            return build_grid_lines(
                (self.camera.x, self.camera.y, self.camera.z),
                cam_dist=getattr(self, 'camera_distance', None))
        except Exception:
            return None
