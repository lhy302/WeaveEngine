# -*- coding: utf-8 -*-
"""ui/canvas/element.py — UI 元素基类 UIElement (树结构 / 布局 / 命中)

我负责: UI 元素基类 (父子树 / rect-anchor-pivot 钳制 / 屏幕矩形 / 命中测试 /
        通用 pointer 回调派发 / 声明式事件绑定字段容器)。
我不负责: 多 Canvas 容器与输入分发 (manager.py)、具体控件绘制 (widgets_*.py)。
拆分: Q-B7-38-1 第 7 批 (2026-11-26), 原文 Loom/loom_ui.py 118-365 逐字搬入。
"""


class UIElement:
    """UI 元素基类.

    坐标约定: rect=(x, y, w, h) 是相对父容器的偏移与尺寸 (像素, y 向下).
    anchor: 锚点 (0~1), 决定元素「贴父容器哪个位置」;
    pivot:  轴心 (0~1), 决定元素「自身哪个点对齐到锚点」.
    默认 (0,0)+(0,0) = 左上对齐; (1,1)+(1,1) = 右下对齐; (0.5,0.5)+(0.5,0.5) = 居中.
    """

    ctype = 'element'

    def __init__(self, name='element', rect=(0, 0, 100, 30),
                 anchor=(0.0, 0.0), pivot=(0.0, 0.0),
                 visible=True, enabled=True, z_order=0):
        self.name = name
        # 通过 property 赋值, 让 rect/anchor/pivot 的钳制校验生效
        self.rect = rect
        self.anchor = anchor
        self.pivot = pivot
        self.visible = bool(visible)
        self.enabled = bool(enabled)
        self.z_order = int(z_order)
        self.parent = None
        self.children = []
        # 2026-10-18 阶段2: 交互状态 (每帧由 UIManager 分发器更新, 不序列化)
        self._hover = False
        self._pressed = False       # 本元素当前被按下 (按钮/滑条/勾选)
        self._dragging = False      # 本元素正在被拖动 (滑条)
        # 2026-10-18 事件系统: 通用 pointer 回调字段 (与 on_mouse_* 覆写机制并列)
        # 用法: elem.on_pointer_enter = lambda: print('hover 开始')
        # 这些是字段（None 或 callable），子类无需 super() 即可用
        self.on_pointer_enter = None    # ()              鼠标进入
        self.on_pointer_exit = None     # ()              鼠标离开
        self.on_pointer_down = None     # (pos)           左键按下
        self.on_pointer_up = None       # (pos)           左键松开
        self.on_pointer_drag = None     # (pos, delta)    拖动中（仅 dragging 元素）
        # 2026-10-19 P0-5: 声明式事件绑定（可 JSON 序列化，替代 Python callable）。
        # 结构: {'click': {'script': 'sid', 'method': 'on_click', 'owner_guid': None},
        #        'submit': ..., 'change': ...}
        # 派发逻辑在 loom_ui._fire_binding()，由 Button/InputField 等触发点调用。
        self.event_bindings = {}

    # ---- 字段校验 (钳制到合法范围) ----
    @property
    def rect(self):
        return self._rect

    @rect.setter
    def rect(self, v):
        try:
            x, y, w, h = (float(t) for t in v)
        except (TypeError, ValueError):
            return                    # 非法值静默忽略 (保留原值)
        self._rect = (x, y, max(0.0, w), max(0.0, h))

    @property
    def anchor(self):
        return self._anchor

    @anchor.setter
    def anchor(self, v):
        try:
            ax, ay = (float(t) for t in v)
        except (TypeError, ValueError):
            return
        self._anchor = (max(0.0, min(1.0, ax)), max(0.0, min(1.0, ay)))

    @property
    def pivot(self):
        return self._pivot

    @pivot.setter
    def pivot(self, v):
        try:
            px, py = (float(t) for t in v)
        except (TypeError, ValueError):
            return
        self._pivot = (max(0.0, min(1.0, px)), max(0.0, min(1.0, py)))

    # ---- 树操作 ----
    def add_child(self, child):
        """挂子元素 (自动脱原父). 返回 child."""
        if child is self:
            return child
        # 防环: 往上检查 child 不是 self 的祖先
        cur = self
        while cur is not None:
            if cur is child:
                return child
            cur = cur.parent
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        self.children.append(child)
        return child

    def remove_child(self, child):
        """移除子元素 (返回被移除者或 None)."""
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            return child
        return None

    def clear_children(self):
        for c in list(self.children):
            c.parent = None
        self.children.clear()

    def find(self, name):
        """深度优先按 name 查找 (含自身). 找不到返回 None."""
        if self.name == name:
            return self
        for c in self.children:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None

    def find_all(self, name):
        """深度优先找出所有同名元素 (重名允许, 返回列表)."""
        out = []
        if self.name == name:
            out.append(self)
        for c in self.children:
            out.extend(c.find_all(name))
        return out

    def walk(self):
        """深度优先遍历 (含自身), 父先于子, 同级按 children 顺序."""
        yield self
        for c in list(self.children):
            yield from c.walk()

    # ---- 布局计算 ----
    def screen_rect(self, parent_rect):
        """由父屏幕矩形计算本元素的屏幕矩形.

        parent_rect: (px, py, pw, ph) 父容器屏幕矩形 (Canvas 根为 (0,0,W,H)).
        语义: 元素的 pivot 点对齐到父容器的 anchor 点.
        公式 (契约 §4.1):
            x = px + pw * ax - rw * pvx + rx
            y = py + ph * ay - rh * pvy + ry
        """
        px, py, pw, ph = parent_rect
        rx, ry, rw, rh = self._rect
        ax, ay = self._anchor
        pvx, pvy = self._pivot
        x = px + pw * ax - rw * pvx + rx
        y = py + ph * ay - rh * pvy + ry
        return (x, y, rw, rh)

    def screen_rect_recursive(self, parent_rect):
        """返回 {id(element): screen_rect} 全树屏幕矩形映射 (先序, 父先算)."""
        out = {}
        stack = [(self, parent_rect)]
        while stack:
            elem, pr = stack.pop()
            sr = elem.screen_rect(pr)
            out[id(elem)] = sr
            # 逆序压栈, 保证输出顺序与 children 一致 (可选, 便于调试)
            for c in reversed(elem.children):
                stack.append((c, sr))
        return out

    # ---- 命中测试 ----
    @staticmethod
    def _point_in_rect(pos, rect):
        x, y = pos
        rx, ry, rw, rh = rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    def hit_test(self, pos, parent_rect):
        """命中测试 (从最上层往下). 返回命中的 UIElement 或 None.

        规则 (契约 §6.2):
          - 自身不可见/禁用 -> 整个子树跳过
          - 子元素优先于父 (后加的画在上面, 先测后面的)
          - 命中 ScrollView 时, 超出内容区的子元素不参与 (阶段3 实现, 当前跳过)
        """
        if not self.visible:
            return None
        sr = self.screen_rect(parent_rect)
        if not self._point_in_rect(pos, sr):
            return None
        # ScrollView: 子元素带滚动偏移, 且超出可视区不参与命中
        if self.ctype == 'scroll_view' and hasattr(self, 'child_offset'):
            ox, oy = self.child_offset()
            child_parent = (sr[0] + ox, sr[1] + oy, sr[2], sr[3])
            # pos 在可视区域内才能命中子元素 (超出滚动区域不响应)
            if self._point_in_rect(pos, sr):
                for c in reversed(self.children):
                    hit = c.hit_test(pos, child_parent)
                    if hit is not None:
                        # 命中结果的屏幕矩形必须仍在 ScrollView 可视区域内
                        if self._point_in_rect(pos, sr):
                            return hit
            # 落在 ScrollView 空白区 -> 返回自身 (供滚轮转发)
            if not self.enabled:
                return None
            return self
        # 子元素后加的画在上面 -> 逆序测
        for c in reversed(self.children):
            hit = c.hit_test(pos, sr)
            if hit is not None:
                return hit
        if not self.enabled:
            return None
        return self

    # ---- 事件接口 (阶段2, 子类覆写) ----
    def on_mouse_enter(self):
        """鼠标进入 (hover 开始). 子类可覆写."""
        pass

    def on_mouse_leave(self):
        """鼠标离开. 子类可覆写."""
        pass

    def on_mouse_down(self, pos):
        """鼠标左键在本元素上按下. 返回 True = 已消费该事件 (阻止穿透)."""
        return False

    def on_mouse_up(self, pos):
        """鼠标左键松开 (不保证在本元素内). 返回 True = 已消费该事件."""
        return False

    def on_mouse_drag(self, pos):
        """按住时鼠标移动 (仅 _dragging=True 的滑条等). 返回 True = 已消费."""
        return False

    # ---- 2026-10-18 事件系统: 通用 pointer 字段回调派发 ----
    def _emit_pointer(self, kind, *args):
        """派发字段回调（若设置了的话）。kind ∈ enter/exit/down/up/drag.
        异常隔离: 回调抛异常打印后继续（不影响 UIManager 主循环）。"""
        cb = getattr(self, 'on_pointer_' + kind, None)
        if cb is None:
            return
        try:
            cb(*args)
        except Exception as e:
            print('[UI] %s.on_pointer_%s 回调异常: %r'
                  % (getattr(self, 'name', '?'), kind, e))

    # ---- 渲染接口 ----
    def draw(self, engine, screen_rect):
        """绘制自身 (子类覆写). engine 提供 draw_screen_rect / draw_text_quad 等."""
        pass
