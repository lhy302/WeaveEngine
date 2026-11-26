# -*- coding: utf-8 -*-
"""ui/canvas/canvas.py — 单个 UI 画布 Canvas (screen / world)

我负责: 单画布 (尺寸 / 根元素 / resize / find / 全树屏幕矩形)。
我不负责: 元素基类 (element.py)、多画布管理与命中分发 (manager.py)。
拆分: Q-B7-38-1 第 7 批 (2026-11-26), 原文 Loom/loom_ui.py 368-400 逐字搬入。
"""

from .element import UIElement

class Canvas:
    """UI 画布 (契约 §3.2). screen = 屏幕空间; world = 世界空间 (阶段4 实现)."""

    def __init__(self, canvas_type='screen', width=1920, height=1080,
                 target=None, world_scale=0.01, z_order=0, billboard=True):
        self.canvas_type = 'world' if canvas_type == 'world' else 'screen'
        self.width = int(width)
        self.height = int(height)
        self.target = target            # world 模式的宿主 GameObject
        # 2026-10-19 第1档序3阶段4 World Space UI:
        #   world_scale 默认 0.01 = 100px = 1m（Unity 对齐）
        self.world_scale = float(world_scale)
        # billboard=True: 永远面向相机（血条/名字 常用）
        # billboard=False: 跟随 target GameObject 的旋转（告示牌 常用）
        self.billboard = bool(billboard)
        self.z_order = int(z_order)
        # 根元素 (Panel 在阶段1第3步实现; 当前用 UIElement 占位)
        self.root = UIElement(name='root', rect=(0, 0, self.width, self.height))

    def resize(self, width, height):
        """窗口变化时同步 (契约 §4.3: 不自动缩放元素尺寸, 仅更新根矩形)."""
        self.width = int(width)
        self.height = int(height)
        self.root.rect = (0, 0, self.width, self.height)

    def find(self, name):
        return self.root.find(name)

    def screen_rects(self):
        """返回本 Canvas 全树屏幕矩形 {id: (x,y,w,h)}."""
        return self.root.screen_rect_recursive((0.0, 0.0,
                                                float(self.width),
                                                float(self.height)))
