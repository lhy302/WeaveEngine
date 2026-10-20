# -*- coding: utf-8 -*-
"""loom_ui.py — Canvas/UI 系统数据模型与布局 (2026-10-18)

契约: docs/design/CanvasUI系统契约_20261018.md
本文件只做「数据模型 + 布局计算 + 树操作 + 查找」, 不依赖 moderngl/pygame,
便于无头单测。渲染由 loom_ui_render.py (阶段1第4步) 接; 输入由阶段2 接。

层次:
  UIManager  多 Canvas 容器 (渲染/命中入口)
  Canvas     单个 UI 画布 (screen / world)
  UIElement  UI 元素基类 (Panel/Text/Button... 的父类)
"""
import math


# 2026-10-19 P0-5: 声明式事件绑定的派发基础。
# UIManager.draw_all(engine) 每帧把 engine 写到这里，事件触发时用它找脚本实例。
# 原因：UI 事件（on_mouse_up 等）在输入轮询里触发，不经过 update 循环，
# 需要 module 级引用才能从"某个 UI 元素"反查"引擎里挂了这个脚本的物体"。
_ACTIVE_ENGINE = None


def _find_script_instances(script_id, owner_guid=None):
    """从 _ACTIVE_ENGINE 的所有物体里找挂指定 script_id 的脚本实例列表。

    owner_guid 非空时只返回该 guid 物体的脚本实例。
    返回 [(obj, script_instance), ...]
    """
    if _ACTIVE_ENGINE is None:
        return []
    out = []
    try:
        for m in getattr(_ACTIVE_ENGINE, 'models', []):
            if owner_guid and getattr(m, 'guid', None) != owner_guid:
                continue
            for sc in getattr(m, 'scripts', []):
                if getattr(sc, 'script_id', None) == script_id:
                    out.append((m, sc))
    except Exception:
        pass
    return out


def _fire_binding(elem, event, *args):
    """派发声明式事件绑定 (2026-10-19 P0-5).

    elem.event_bindings[event] = {'script': sid, 'method': name, 'owner_guid'?}
    在 _ACTIVE_ENGINE 里找挂 sid 的脚本实例，调用 instance.method(*args)。
    返回 是否触发成功（找到并调用）。
    异常不向上抛（防 UI 元素拖崩整帧），但会打印到 stdout 供排查。
    """
    try:
        bindings = getattr(elem, 'event_bindings', None)
        if not bindings:
            return False
        cfg = bindings.get(event)
        if not cfg:
            return False
        sid = cfg.get('script')
        method = cfg.get('method') or ('on_' + event)
        owner_guid = cfg.get('owner_guid')
        if not sid:
            return False
        insts = _find_script_instances(sid, owner_guid)
        if not insts:
            print('[UI 事件] 找不到脚本实例: sid=%r owner_guid=%r event=%r'
                  % (sid, owner_guid, event))
            return False
        fired = False
        for obj, sc in insts:
            fn = getattr(sc, method, None)
            if fn is None:
                print('[UI 事件] 脚本 %r 无方法 %r（触发自 %r.%r）'
                      % (sid, method, getattr(obj, 'name', '?'), elem.name))
                continue
            try:
                fn(*args)
                fired = True
            except Exception as e:
                print('[UI 事件] 调用 %r.%r 异常: %r' % (sid, method, e))
        return fired
    except Exception as e:
        print('[UI 事件] _fire_binding 兜底异常: %r' % (e,))
        return False


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


class UIManager:
    """多 Canvas 容器 (渲染/命中入口)."""

    def __init__(self):
        self.canvases = []
        # 2026-10-18 阶段2: 交互状态 (每帧由 dispatch_mouse 更新)
        self._hovered = None        # 当前鼠标悬停的元素
        self._pressed_elem = None   # 当前被按下且消费了事件的元素
        self._dragging_elem = None  # 当前拖动中的元素 (滑条)
        # 2026-10-18 事件系统: 记录"最后按下的元素"用于 pointer up 派发
        # 与 _pressed_elem 的区别: _pressed_elem 只有 on_mouse_down 返回 True 才设,
        # _last_pointer_down 无论是否消费都记录（用于通用 pointer 回调）
        self._last_pointer_down = None
        # 2026-10-18 阶段3: 焦点管理 (契约 §6.4, 同一时刻最多一个)
        self._focused = None        # 当前持有键盘焦点的元素 (InputField 等)

    def add_canvas(self, canvas):
        if canvas not in self.canvases:
            self.canvases.append(canvas)
            self.canvases.sort(key=lambda c: c.z_order)
        return canvas

    def remove_canvas(self, canvas):
        if canvas in self.canvases:
            self.canvases.remove(canvas)
            return canvas
        return None

    def clear(self):
        self.canvases.clear()

    def find(self, name):
        """跨 Canvas 查找 (按 z_order 从小到大找, 返回第一个命中)."""
        for c in self.canvases:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None

    def resize(self, width, height):
        """窗口 resize: screen Canvas 全同步; world Canvas 不受影响."""
        for c in self.canvases:
            if c.canvas_type == 'screen':
                c.resize(width, height)

    def hit_test(self, pos):
        """从最上层 Canvas 往下测, 返回 (canvas, element) 或 (None, None)."""
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue          # world Canvas 命中留到阶段4
            hit = c.root.hit_test(pos, (0.0, 0.0,
                                        float(c.width), float(c.height)))
            if hit is not None:
                return c, hit
        return None, None


    # ---- 焦点管理 (阶段3, 契约 §6.4) ----
    def focus_element(self, elem):
        """设置焦点元素. 原焦点元素先失焦. elem 为 None 时等效 blur_focused()."""
        if self._focused is elem:
            return
        if self._focused is not None:
            try:
                self._focused.on_blur()
            except Exception:
                pass
        self._focused = elem
        if elem is not None:
            try:
                elem.on_focus()
            except Exception:
                pass

    def blur_focused(self):
        """清空焦点."""
        self.focus_element(None)

    def focused(self):
        """返回当前焦点元素 (无则 None)."""
        return self._focused

    def dispatch_key(self, pg_key, mods=0):
        """键盘事件 -> 焦点元素. 返回 True = 消费.
        pg_key 是 pygame 键码 (与 loom_input._KEYMAP 一致).
        键名转译: pg_key -> 'Backspace'/'Delete'/'Left'/'Right'/'Home'/'End'/'Return'/'Escape'.
        普通字符不经此处 (走 dispatch_text, 由 IME/GLFW char_callback 提供).
        """
        if self._focused is None:
            return False
        name = _KEY_CODE_TO_NAME.get(pg_key)
        if name is None:
            return False
        try:
            return bool(self._focused.on_key_down(name))
        except Exception:
            return False

    def dispatch_text(self, text):
        """文本输入 (IME 提交的最终文本或 ASCII) -> 焦点元素. 返回 True = 消费."""
        if self._focused is None or not text:
            return False
        try:
            return bool(self._focused.on_text_input(text))
        except Exception:
            return False


    # ---- 鼠标事件分发 (阶段2) ----
    def dispatch_mouse(self, pos, pressed, released, wheel=0):
        """每帧分发鼠标事件到 UI 树. 返回 True = 本帧点击被 UI 消费.

        pressed / released 是「本帧新按下/松开」的键码集合 (engine 语义).
        只处理左键 (键码 1). 见契约 §6.
        wheel: 滚轮增量 (>0 向上, <0 向下). 2026-10-18: ScrollView 消费.
        """
        left_down = 1 in pressed
        left_up = 1 in released

        # 滚轮事件 -> 命中 ScrollView 时转发
        if wheel:
            wheel_hit = self._hit_scroll_view(pos)
            if wheel_hit is not None:
                try:
                    if wheel_hit.on_mouse_wheel(wheel):
                        return True
                except Exception:
                    pass

        # 1) 命中测试 (只测 screen Canvas, 从最上层 Canvas 开始)
        hovered = None
        hit_canvas = None
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue
            hit = c.root.hit_test(pos, (0.0, 0.0,
                                        float(c.width), float(c.height)))
            if hit is not None:
                hovered = hit
                hit_canvas = c
                break

        # 2) hover 变化通知
        if hovered is not self._hovered:
            if self._hovered is not None:
                try:
                    self._hovered.on_mouse_leave()
                except Exception:
                    pass
                self._hovered._emit_pointer('exit')
            if hovered is not None:
                try:
                    hovered.on_mouse_enter()
                except Exception:
                    pass
                hovered._emit_pointer('enter')
            self._hovered = hovered

        consumed = False

        # 2.5) 展开的 Dropdown 优先处理点击 (列表在树外, hit_test 测不到)
        if left_down:
            exp_dd = self._find_expanded_dropdown()
            if exp_dd is not None:
                # 计算该 Dropdown 的 screen_rect (从所属 Canvas)
                sr = self._screen_rect_of(exp_dd)
                if sr is not None:
                    try:
                        if exp_dd.handle_expanded_click(pos, sr):
                            return True
                    except Exception:
                        pass

        # 2.6) 焦点切换 (阶段3, 契约 §6.4): 点击 InputField 获焦, 点击别处失焦
        if left_down:
            if hovered is not None and hovered.ctype == 'input_field':
                self.focus_element(hovered)
            elif self._focused is not None:
                # 点击任何非 InputField 元素 / 空白 -> 原焦点失焦
                self.blur_focused()

        # 3) 按下
        if left_down and hovered is not None:
            hovered._emit_pointer('down', pos)
            self._last_pointer_down = hovered
            try:
                if hovered.on_mouse_down(pos):
                    self._pressed_elem = hovered
                    consumed = True
            except Exception:
                pass

        # 4) 拖动 (滑条等)
        if self._dragging_elem is not None and hit_canvas is not None:
            try:
                sr = self._dragging_elem.screen_rect(
                    (0.0, 0.0, float(hit_canvas.width), float(hit_canvas.height)))
                if hasattr(self._dragging_elem, 'drag_to'):
                    self._dragging_elem.drag_to(pos, sr)
                    consumed = True
                # 通用 pointer drag 回调（pos 已在 screen 坐标）
                self._dragging_elem._emit_pointer('drag', pos)
            except Exception:
                pass
        # 若当前 hover 的是 Slider 且已按下, 开始拖动
        if (self._pressed_elem is not None
                and self._pressed_elem.ctype == 'slider'
                and self._dragging_elem is None):
            self._pressed_elem._dragging = True
            self._dragging_elem = self._pressed_elem

        # 5) 松开
        if left_up:
            # 通用 pointer up: 派发给"最后按下的元素"（不依赖 _pressed_elem，
            # 因为基类 on_mouse_down 返回 False 时 _pressed_elem 未被设置）
            if self._last_pointer_down is not None:
                self._last_pointer_down._emit_pointer('up', pos)
                self._last_pointer_down = None
            if self._pressed_elem is not None:
                try:
                    if self._pressed_elem.on_mouse_up(pos):
                        consumed = True
                except Exception:
                    pass
                self._pressed_elem._pressed = False
                self._dragging_elem._dragging = False                     if self._dragging_elem is not None else None
                self._pressed_elem = None
                self._dragging_elem = None

        return consumed

    def _find_expanded_dropdown(self):
        """扫描所有 Canvas 找展开中的 Dropdown (无则 None)."""
        for c in self.canvases:
            if c.canvas_type != 'screen':
                continue
            for elem in c.root.walk():
                if elem.ctype == 'dropdown' and getattr(elem, '_expanded', False):
                    return elem
        return None

    def _screen_rect_of(self, target):
        """计算目标元素在所属 Canvas 上的屏幕矩形 (无则 None)."""
        for c in self.canvases:
            if c.canvas_type != 'screen':
                continue
            # 沿父链找根, 自顶向下计算
            chain = []
            cur = target
            while cur is not None:
                chain.append(cur)
                cur = cur.parent
            chain.reverse()
            if not chain or chain[0] is not c.root:
                continue
            parent_rect = (0.0, 0.0, float(c.width), float(c.height))
            for elem in chain:
                sr = elem.screen_rect(parent_rect)
                parent_rect = sr
            return parent_rect
        return None

    def _hit_scroll_view(self, pos):
        """命中测试 + 沿父链找最近的 ScrollView (若自身就是则返回自身)."""
        c, elem = self.hit_test(pos)
        if elem is None:
            return None
        cur = elem
        while cur is not None:
            if cur.ctype == 'scroll_view':
                return cur
            cur = cur.parent
        return None

    def update_hover_only(self, pos):
        """仅更新 hover 状态 (无点击时每帧调, 用于按钮悬停效果)."""
        hovered = None
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue
            hit = c.root.hit_test(pos, (0.0, 0.0,
                                        float(c.width), float(c.height)))
            if hit is not None:
                hovered = hit
                break
        if hovered is not self._hovered:
            if self._hovered is not None:
                try:
                    self._hovered.on_mouse_leave()
                except Exception:
                    pass
                self._hovered._emit_pointer('exit')
            if hovered is not None:
                try:
                    hovered.on_mouse_enter()
                except Exception:
                    pass
                hovered._emit_pointer('enter')
            self._hovered = hovered

    def draw_all(self, engine):
        """渲染所有 screen Canvas 的元素树 (渲染层末尾调用). 父先于子."""
        # 2026-10-19 P0-5: 每帧刷新 _ACTIVE_ENGINE（供 _fire_binding 查脚本实例）
        global _ACTIVE_ENGINE
        _ACTIVE_ENGINE = engine
        # 1) 主树渲染 (Dropdown 展开时其列表暂不画, 留到第 2 轮)
        expanded_dd = self._find_expanded_dropdown()
        for c in self.canvases:
            if c.canvas_type != 'screen':
                continue
            self._draw_elem(c.root, engine,
                            (0.0, 0.0, float(c.width), float(c.height)))
        # 2) 展开的 Dropdown 列表画在最上层
        if expanded_dd is not None:
            sr = self._screen_rect_of(expanded_dd)
            if sr is not None:
                try:
                    expanded_dd._draw_expanded_list(engine, sr)
                except Exception:
                    pass

    @staticmethod
    def _draw_elem(elem, engine, parent_rect):
        if not elem.visible:
            return
        sr = elem.screen_rect(parent_rect)
        elem.draw(engine, sr)
        # ScrollView: 开启 scissor 裁剪 + 子元素叠加滚动偏移
        if elem.ctype == 'scroll_view' and hasattr(engine, 'push_scissor'):
            try:
                engine.push_scissor((sr[0], sr[1], sr[2], sr[3]))
            except Exception:
                pass
            ox, oy = elem.child_offset()
            child_parent_rect = (sr[0] + ox, sr[1] + oy, sr[2], sr[3])
            for child in list(elem.children):
                UIManager._draw_elem(child, engine, child_parent_rect)
            try:
                engine.pop_scissor()
            except Exception:
                pass
            return
        # 普通元素: 递归绘制子元素
        for child in list(elem.children):
            UIManager._draw_elem(child, engine, sr)

    def default_canvas(self):
        """返回第一个 screen Canvas (无则创建 1920x1080). 脚本便捷入口."""
        for c in self.canvases:
            if c.canvas_type == 'screen':
                return c
        c = Canvas(canvas_type='screen', width=1920, height=1080)
        self.add_canvas(c)
        return c



# ======================== 键码 -> 键名映射 (阶段3) ========================
# InputField 用字符串名识别按键 (loom_ui.py 不 import pygame)
_KEY_CODE_TO_NAME = None    # 惰性初始化 (避免 loom_ui 硬依赖 pygame)


def _init_key_name_map():
    """惰性构建 pygame 键码 -> 键名字符串映射 (模块首次调用时)."""
    global _KEY_CODE_TO_NAME
    if _KEY_CODE_TO_NAME is not None:
        return _KEY_CODE_TO_NAME
    try:
        import pygame
        _KEY_CODE_TO_NAME = {
            pygame.K_BACKSPACE: 'Backspace',
            pygame.K_DELETE: 'Delete',
            pygame.K_LEFT: 'Left',
            pygame.K_RIGHT: 'Right',
            pygame.K_HOME: 'Home',
            pygame.K_END: 'End',
            pygame.K_RETURN: 'Return',
            pygame.K_KP_ENTER: 'Return',
            pygame.K_ESCAPE: 'Escape',
            pygame.K_TAB: 'Tab',
        }
    except Exception:
        _KEY_CODE_TO_NAME = {}
    return _KEY_CODE_TO_NAME


# 惰性初始化 (模块导入时先建，避免每次 dispatch_key 都判空)
_init_key_name_map()


# =================== 阶段1 元素: Panel / Text (2026-10-18) ===================

class Shape(UIElement):
    """2D 图形元素 (2026-10-20 沙盘支持).

    支持 4 种形状，用 shape_type 区分：
      - 'line'     两点直线段
      - 'polyline' 折线（不闭合）
      - 'polygon'  多边形（自动闭合，可填充）
      - 'circle'   圆（近似 32 段）

    坐标约定:
      - points 是元素内相对坐标 [(px, py), ...]，需转成绝对像素后绘制。
      - circle 只用 rect 的边界（填满矩形），radius > 0 时按 radius 覆盖 rect 中心。
      - polygon 的填充用三角形扇（从第 0 点扇出），对凸多边形精确；凹多边形会有瑕疵。

    颜色: (r, g, b) 或 (r, g, b, a) 0~255。
    线宽: stroke_width 像素（>=1）。
    """

    ctype = 'shape'

    def __init__(self, name='shape', rect=(0, 0, 100, 100),
                 shape_type='line', points=None, radius=0.0,
                 stroke_color=(255, 255, 255, 255), stroke_width=2,
                 fill_color=None, segments=32, close=False, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.shape_type = str(shape_type)
        if self.shape_type not in ('line', 'polyline', 'polygon', 'circle'):
            self.shape_type = 'line'
        self.points = list(points or [])
        self.radius = float(radius)
        self.stroke_color = tuple(stroke_color) if stroke_color else None
        self.stroke_width = max(1, int(stroke_width))
        self.fill_color = tuple(fill_color) if fill_color else None
        self.segments = max(8, int(segments))
        # close: 是否在 polyline 上自动闭合（polygon 恒闭合，不需此字段）
        self.close = bool(close)

    def _resolve_points_px(self):
        """返回绝对像素坐标列表（元素内坐标 + 屏幕位置）。"""
        x, y, w, h = self._screen_rect_cached
        if self.shape_type == 'circle':
            import math
            r = self.radius if self.radius > 0 else min(w, h) / 2.0
            cx, cy = x + w / 2.0, y + h / 2.0
            out = []
            for i in range(self.segments + 1):
                a = 2 * math.pi * i / self.segments
                out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            return out
        # 其它形状：points 是元素内坐标 (0..w, 0..h)
        return [(x + float(px), y + float(py)) for (px, py) in self.points]

    def draw(self, engine, screen_rect):
        # 保存屏幕 rect（供 _resolve_points_px 用）
        self._screen_rect_cached = screen_rect
        pts_px = self._resolve_points_px()
        if not pts_px:
            return
        # 填充（polygon / circle 支持）
        if self.fill_color and len(pts_px) >= 3:
            try:
                engine.draw_screen_polygon(pts_px, self.fill_color)
            except Exception:
                pass
        # 描边
        if self.stroke_color and len(pts_px) >= 2:
            close = (self.shape_type == 'polygon' or
                     self.shape_type == 'circle' or
                     self.close)
            try:
                engine.draw_screen_lines(pts_px, self.stroke_color,
                                         width=self.stroke_width,
                                         close=close)
            except Exception:
                pass


class Panel(UIElement):
    """纯色矩形 (契约 §3.3). bg_color=(r,g,b) 或 (r,g,b,a) 0~255."""

    ctype = 'panel'

    def __init__(self, name='panel', rect=(0, 0, 100, 30),
                 bg_color=(0, 0, 0, 128), **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.bg_color = tuple(bg_color)

    def draw(self, engine, screen_rect):
        engine.draw_screen_rect(screen_rect, self.bg_color)


class Text(UIElement):
    """文字元素 (契约 §3.3). 支持自动换行 (wrap_width > 0) 与 UTF-8 全字符集
    (走 engine.draw_text_quad -> loom_font.FontChain 多字体回退)."""

    ctype = 'text'

    def __init__(self, name='text', rect=(0, 0, 200, 30), text='',
                 font_size=16, color=(255, 255, 255),
                 align='left', wrap_width=0, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.text = str(text)
        self.font_size = int(font_size)
        self.color = tuple(color)
        self.align = align if align in ('left', 'center', 'right') else 'left'
        self.wrap_width = max(0, int(wrap_width))

    def _wrap_lines(self, engine):
        """自动换行: 按测量宽度累计切行 (中英混排/emoji 安全)."""
        if not self.text:
            return []
        if self.wrap_width <= 0:
            return self.text.split('\n')
        lines = []
        cur = []
        cur_w = 0
        for ch in self.text:
            if ch == '\n':
                lines.append(''.join(cur))
                cur, cur_w = [], 0
                continue
            w = engine._measure_text(ch, self.font_size)[0]
            if cur_w + w > self.wrap_width and cur:
                lines.append(''.join(cur))
                cur, cur_w = [ch], w
            else:
                cur.append(ch)
                cur_w += w
        if cur:
            lines.append(''.join(cur))
        return lines

    def draw(self, engine, screen_rect):
        if not self.text:
            return
        x, y, w, h = screen_rect
        lines = self._wrap_lines(engine)
        line_h = engine._measure_text('Mg', self.font_size)[1] or self.font_size
        for i, line in enumerate(lines):
            if not line:
                continue
            lw = engine._measure_text(line, self.font_size)[0]
            if self.align == 'center':
                tx = x + (w - lw) / 2
            elif self.align == 'right':
                tx = x + w - lw
            else:
                tx = x
            engine.draw_text_quad(line, int(tx), int(y + i * line_h),
                                  self.color, self.font_size)


class Image(UIElement):
    """图片元素 (契约 §3.3). fit: stretch 拉伸 / contain 等比装入 / cover 等比填满."""

    ctype = 'image'

    def __init__(self, name='image', rect=(0, 0, 100, 100),
                 texture_path='', tint=(255, 255, 255, 255),
                 fit='stretch', **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.texture_path = str(texture_path or '')
        self.tint = tuple(tint) + ((255,) if len(tint) == 3 else ())
        self.fit = fit if fit in ('stretch', 'contain', 'cover') else 'stretch'
        self._tex = None
        self._tex_size = (0, 0)
        self._tex_loaded = False

    def _load(self, engine):
        """惰性加载图片 -> moderngl 纹理. 失败时 _tex 保持 None (画占位灰底)."""
        if self._tex_loaded:
            return
        self._tex_loaded = True
        if not self.texture_path:
            return
        try:
            import pygame
            # 不用 convert_alpha(): 它要求 display 已初始化, 无头环境会抛异常;
            # PNG 载入后本身带 SRCALPHA, _surf_to_tex 走 array_alpha 可正常处理
            # (与 draw_text_quad 里 font.render(True, color) 的表面同款).
            surf = pygame.image.load(self.texture_path)
            self._tex = engine._surf_to_tex(surf)
            self._tex_size = surf.get_size()
        except Exception:
            self._tex = None

    def _fit_rect(self, rect):
        """按 fit 策略计算实际绘制矩形 (相对于 screen_rect)."""
        x, y, w, h = rect
        tw, th = self._tex_size
        if tw <= 0 or th <= 0:
            return rect
        if self.fit == 'stretch':
            return (x, y, w, h)
        if self.fit == 'contain':
            s = min(w / tw, h / th)
        else:               # cover
            s = max(w / tw, h / th)
        dw, dh = tw * s, th * s
        return (x + (w - dw) / 2, y + (h - dh) / 2, dw, dh)

    def draw(self, engine, screen_rect):
        self._load(engine)
        if self._tex is None:
            engine.draw_screen_rect(screen_rect, (80, 80, 80, 255))
            return
        engine.draw_texture_quad(self._tex, self._fit_rect(screen_rect), self.tint)


# =================== 阶段2 元素: Button / Slider / Toggle / ProgressBar ===================

class Button(UIElement):
    """按钮 (契约 §3.3). 按下+松开在同一元素内才触发 on_click (用户决策 1=B)."""

    ctype = 'button'

    def __init__(self, name='button', rect=(0, 0, 120, 36), text='',
                 font_size=16, text_color=(255, 255, 255),
                 normal_color=(70, 80, 100, 255),
                 hover_color=(90, 100, 125, 255),
                 pressed_color=(50, 60, 80, 255),
                 on_click=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.text = str(text)
        self.font_size = int(font_size)
        self.text_color = tuple(text_color)
        self.normal_color = tuple(normal_color)
        self.hover_color = tuple(hover_color)
        self.pressed_color = tuple(pressed_color)
        self.on_click = on_click

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False
        # 鼠标移出时清按下态 (移出再移回不触发)
        self._pressed = False

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        self._pressed = True
        return True

    def on_mouse_up(self, pos):
        if not self.enabled:
            return False
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed:
            # 2026-10-19 P0-5: Python callable 与声明式绑定并存
            if self.on_click is not None:
                try:
                    self.on_click()
                except Exception:
                    pass
            _fire_binding(self, 'click')
            return True
        return was_pressed

    def draw(self, engine, screen_rect):
        if self._pressed and self._hover:
            bg = self.pressed_color
        elif self._hover:
            bg = self.hover_color
        else:
            bg = self.normal_color
        engine.draw_screen_rect(screen_rect, bg)
        if self.text:
            lw = engine._measure_text(self.text, self.font_size)[0]
            lh = engine._measure_text('Mg', self.font_size)[1] or self.font_size
            x, y, w, h = screen_rect
            tx = int(x + (w - lw) / 2)
            ty = int(y + (h - lh) / 2)
            engine.draw_text_quad(self.text, tx, ty, self.text_color, self.font_size)


class Slider(UIElement):
    """滑条 (契约 §3.3). 拖拽锁定 + 边界钳制 (用户决策 2=C)."""

    ctype = 'slider'

    def __init__(self, name='slider', rect=(0, 0, 200, 24),
                 min_value=0.0, max_value=1.0, value=0.0,
                 direction='h',
                 track_color=(50, 55, 70, 255),
                 fill_color=(80, 140, 220, 255),
                 handle_color=(220, 225, 235, 255),
                 on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        self.direction = 'v' if direction == 'v' else 'h'
        self._value = self._clamp(float(value))
        self.track_color = tuple(track_color)
        self.fill_color = tuple(fill_color)
        self.handle_color = tuple(handle_color)
        self.on_change = on_change

    def _clamp(self, v):
        return max(self.min_value, min(self.max_value, v))

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._set_value(float(v), notify=False)

    def _set_value(self, v, notify=True):
        v = self._clamp(v)
        changed = (v != self._value)
        self._value = v
        if changed and notify and self.on_change is not None:
            try:
                self.on_change(v)
            except Exception:
                pass

    def _ratio(self):
        span = self.max_value - self.min_value
        return (self._value - self.min_value) / span if span > 0 else 0.0

    def _pos_to_value(self, pos, screen_rect):
        x, y, w, h = screen_rect
        if self.direction == 'h':
            t = (pos[0] - x) / w if w > 0 else 0.0
        else:
            t = (y + h - pos[1]) / h if h > 0 else 0.0
        t = max(0.0, min(1.0, t))
        return self.min_value + t * (self.max_value - self.min_value)

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        self._pressed = True
        self._dragging = True
        return True

    def on_mouse_up(self, pos):
        self._pressed = False
        self._dragging = False
        return False

    def on_mouse_drag(self, pos):
        # 阶段2 UIElement 签名是 on_mouse_drag(pos), 但滑条需 screen_rect 才能算值,
        # 由 UIManager 分发时额外传 screen_rect (见 UIManager.dispatch_mouse).
        return True

    def drag_to(self, pos, screen_rect):
        """UIManager 分发时调用: 用鼠标位置更新值 (边界钳制)."""
        if not self._dragging:
            return
        v = self._pos_to_value(pos, screen_rect)
        self._set_value(v, notify=True)

    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        engine.draw_screen_rect(screen_rect, self.track_color)
        ratio = self._ratio()
        if self.direction == 'h':
            fw = int(w * ratio)
            if fw > 0:
                engine.draw_screen_rect((x, y, fw, h), self.fill_color)
            hx = int(x + w * ratio) - 4
            engine.draw_screen_rect((hx, y - 2, 8, h + 4), self.handle_color)
        else:
            fh = int(h * ratio)
            if fh > 0:
                engine.draw_screen_rect((x, y + h - fh, w, fh), self.fill_color)
            hy = int(y + h - h * ratio) - 4
            engine.draw_screen_rect((x - 2, hy, w + 4, 8), self.handle_color)


class Toggle(UIElement):
    """勾选框 (契约 §3.3). 点击切换 is_on."""

    ctype = 'toggle'

    def __init__(self, name='toggle', rect=(0, 0, 160, 24),
                 is_on=False, label='',
                 box_color=(70, 80, 100, 255),
                 check_color=(80, 200, 120, 255),
                 label_color=(230, 230, 230),
                 label_size=16,
                 on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.is_on = bool(is_on)
        self.label = str(label)
        self.box_color = tuple(box_color)
        self.check_color = tuple(check_color)
        self.label_color = tuple(label_color)
        self.label_size = int(label_size)
        self.on_change = on_change

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False
        self._pressed = False

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        self._pressed = True
        return True

    def on_mouse_up(self, pos):
        was_pressed = self._pressed
        self._pressed = False
        if was_pressed and self.enabled:
            self.is_on = not self.is_on
            if self.on_change is not None:
                try:
                    self.on_change(self.is_on)
                except Exception:
                    pass
            return True
        return was_pressed

    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        box = min(h, 20)
        engine.draw_screen_rect((x, y, box, box), self.box_color)
        if self.is_on:
            pad = 3
            engine.draw_screen_rect((x + pad, y + pad,
                                     box - 2 * pad, box - 2 * pad),
                                    self.check_color)
        if self.label:
            engine.draw_text_quad(self.label, x + box + 8, y, self.label_color,
                                  self.label_size)


class ProgressBar(UIElement):
    """只读进度条 (契约 §3.3). value: 0~1."""

    ctype = 'progress_bar'

    def __init__(self, name='progress', rect=(0, 0, 200, 18),
                 value=0.0,
                 bg_color=(40, 44, 54, 255),
                 fill_color=(80, 220, 120, 255), **kw):
        super().__init__(name=name, rect=rect, **kw)
        self._value = max(0.0, min(1.0, float(value)))
        self.bg_color = tuple(bg_color)
        self.fill_color = tuple(fill_color)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = max(0.0, min(1.0, float(v)))

    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        engine.draw_screen_rect(screen_rect, self.bg_color)
        fw = int(w * self._value)
        if fw > 0:
            engine.draw_screen_rect((x, y, fw, h), self.fill_color)



class ScrollView(UIElement):
    """可滚动容器 (契约 §3.3). 超出内容区的子元素被裁剪, 右侧滚动条可选."""

    ctype = 'scroll_view'

    def __init__(self, name='scroll', rect=(0, 0, 300, 200),
                 content_size=(300, 800),
                 bg_color=(30, 34, 44, 255),
                 bar_color=(120, 130, 150, 255),
                 bar_width=8,
                 show_bar=True,
                 scroll_step=30,
                 **kw):
        super().__init__(name=name, rect=rect, **kw)
        self._content_size = (max(0.0, float(content_size[0])),
                              max(0.0, float(content_size[1])))
        self.scroll_pos = (0.0, 0.0)   # (x, y), y 为负时向上滚 (看下方内容)
        self.bg_color = tuple(bg_color)
        self.bar_color = tuple(bar_color)
        self.bar_width = int(bar_width)
        self.show_bar = bool(show_bar)
        self.scroll_step = int(scroll_step)

    @property
    def content_size(self):
        return self._content_size

    @content_size.setter
    def content_size(self, v):
        try:
            w, h = (float(t) for t in v)
        except (TypeError, ValueError):
            return
        self._content_size = (max(0.0, w), max(0.0, h))
        self._clamp_scroll()

    def _clamp_scroll(self):
        """滚动范围钳制: scroll_x ∈ [-(cw-w), 0], scroll_y ∈ [-(ch-h), 0]."""
        x, y, w, h = self.rect
        cw, ch = self._content_size
        max_sx = max(0.0, cw - w)
        max_sy = max(0.0, ch - h)
        sx = max(-max_sx, min(0.0, self.scroll_pos[0]))
        sy = max(-max_sy, min(0.0, self.scroll_pos[1]))
        self.scroll_pos = (sx, sy)

    def can_scroll(self):
        x, y, w, h = self.rect
        cw, ch = self._content_size
        return cw > w or ch > h

    def scroll_by(self, dx, dy):
        sx, sy = self.scroll_pos
        self.scroll_pos = (sx + dx, sy + dy)
        self._clamp_scroll()

    def on_mouse_wheel(self, delta):
        """滚轮事件: delta > 0 向上滚 (看更上面), delta < 0 向下滚 (看更下面).

        scroll_pos.y 语义: 0 = 内容顶部, 负值 = 向下滚.
        向上滚 -> y 趋向 0; 向下滚 -> y 趋向 -(content_h - view_h).
        """
        if not self.can_scroll():
            return False
        self.scroll_by(0, delta * self.scroll_step)
        return True

    def child_offset(self):
        """子元素绘制/命中时的坐标偏移 (叠加 scroll_pos)."""
        return self.scroll_pos

    def draw(self, engine, screen_rect):
        engine.draw_screen_rect(screen_rect, self.bg_color)
        x, y, w, h = screen_rect
        cw, ch = self._content_size
        if self.show_bar and ch > h:
            bar_x = x + w - self.bar_width
            engine.draw_screen_rect((bar_x, y, self.bar_width, h),
                                    (self.bar_color[0], self.bar_color[1],
                                     self.bar_color[2], 60))
            frac = h / ch
            block_h = max(20, int(h * frac))
            max_sy = max(1.0, ch - h)
            ratio = -self.scroll_pos[1] / max_sy
            block_y = int(y + (h - block_h) * ratio)
            engine.draw_screen_rect((bar_x, block_y, self.bar_width, block_h),
                                    self.bar_color)






class InputField(UIElement):
    """单行文本输入框 (契约 §3.3). 键盘焦点 + IME 支持（B1：不显示拼音中间态）.

    焦点由 UIManager 统一管理：点击本元素 -> UIManager.focused = self；
    点击其他元素 -> UIManager.focused = None。
    """

    ctype = 'input_field'

    def __init__(self, name='input', rect=(0, 0, 200, 32),
                 text='', placeholder='',
                 max_length=200,
                 bg_color=(50, 55, 70, 255),
                 focus_bg_color=(60, 70, 90, 255),
                 text_color=(255, 255, 255),
                 placeholder_color=(140, 140, 150),
                 cursor_color=(220, 220, 230),
                 font_size=16,
                 on_submit=None, on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.text = str(text)
        self.placeholder = str(placeholder)
        self.max_length = max(0, int(max_length))
        self.bg_color = tuple(bg_color)
        self.focus_bg_color = tuple(focus_bg_color)
        self.text_color = tuple(text_color)
        self.placeholder_color = tuple(placeholder_color)
        self.cursor_color = tuple(cursor_color)
        self.font_size = int(font_size)
        self.on_submit = on_submit
        self.on_change = on_change
        # 2026-10-18 阶段3: 光标位置 (字符索引, 0..len(text))
        # _focused 由 UIManager 设置 (不在此初始化, 避免与焦点系统竞态)
        self._cursor = len(self.text)
        self._focused = False

    # ---- 焦点回调 (UIManager 调) ----
    def on_focus(self):
        self._focused = True
        self._cursor = min(self._cursor, len(self.text))

    def on_blur(self):
        self._focused = False

    # ---- 文本编辑 ----
    def _set_text(self, new_text, notify=True):
        old = self.text
        if self.max_length > 0:
            new_text = new_text[:self.max_length]
        self.text = new_text
        self._cursor = max(0, min(self._cursor, len(self.text)))
        if notify and new_text != old:
            # 2026-10-19 P0-5: Python callable 与声明式绑定并存
            if self.on_change is not None:
                try:
                    self.on_change(new_text)
                except Exception:
                    pass
            _fire_binding(self, 'change', new_text)

    def _insert(self, s):
        """在光标处插入字符串 (支持多字符)"""
        if not s:
            return
        cur = self._cursor
        new = self.text[:cur] + s + self.text[cur:]
        self._set_text(new)
        self._cursor = min(cur + len(s), len(self.text))

    def _backspace(self):
        if self._cursor > 0:
            cur = self._cursor
            new = self.text[:cur - 1] + self.text[cur:]
            self._set_text(new)
            self._cursor = cur - 1

    def _delete(self):
        if self._cursor < len(self.text):
            cur = self._cursor
            new = self.text[:cur] + self.text[cur + 1:]
            self._set_text(new)
            # 光标不动

    def _submit(self):
        # 2026-10-19 P0-5: Python callable 与声明式绑定并存
        if self.on_submit is not None:
            try:
                self.on_submit(self.text)
            except Exception:
                pass
        _fire_binding(self, 'submit', self.text)

    # ---- 键盘事件 (UIManager 分发, 只在 focused=True 时) ----
    def on_key_down(self, key_name):
        """接收按键名 ('Backspace'/'Delete'/'Left'/'Right'/'Home'/'End'/'Return').

        返回 True = 消费按键; False = 未处理（UIManager 转给其他逻辑）。
        普通字符走 on_text_input, 不走这里。
        """
        if key_name == 'Backspace':
            self._backspace()
            return True
        if key_name == 'Delete':
            self._delete()
            return True
        if key_name == 'Left':
            if self._cursor > 0:
                self._cursor -= 1
            return True
        if key_name == 'Right':
            if self._cursor < len(self.text):
                self._cursor += 1
            return True
        if key_name == 'Home':
            self._cursor = 0
            return True
        if key_name == 'End':
            self._cursor = len(self.text)
            return True
        if key_name == 'Return':
            self._submit()
            return True
        if key_name == 'Escape':
            # ESC 在输入框内不消费，让上层处理（UIManager 会转给引擎）
            return False
        return False

    def on_text_input(self, text):
        """IME 提交的文本 (含中文/emoji/普通字母). 由 UIManager 分发."""
        if not text:
            return False
        self._insert(text)
        return True

    # ---- 鼠标交互 ----
    def on_mouse_down(self, pos):
        """返回 True = 请求焦点 (UIManager 处理后设置焦点 + 清空 pressed)."""
        if not self.enabled:
            return False
        # 简化: 点击任意位置把光标放到末尾（不做字符位置点击定位）
        self._cursor = len(self.text)
        return True

    def on_mouse_up(self, pos):
        return True    # 消费点击 (防止穿透到 3D)

    # ---- 绘制 ----
    def draw(self, engine, screen_rect):
        x, y, w, h = screen_rect
        bg = self.focus_bg_color if self._focused else self.bg_color
        engine.draw_screen_rect(screen_rect, bg)
        # 文字 (空时显示 placeholder)
        pad = 6
        ty = int(y + (h - self.font_size * 1.2) / 2)
        if self.text:
            engine.draw_text_quad(self.text, x + pad, ty,
                                  self.text_color, self.font_size)
        elif self.placeholder:
            engine.draw_text_quad(self.placeholder, x + pad, ty,
                                  self.placeholder_color, self.font_size)
        # 光标 (只在有焦点时画，绘制在 _cursor 字符位置的 x)
        if self._focused:
            # 光标前的文本宽度
            prefix = self.text[:self._cursor]
            prefix_w = engine._measure_text(prefix, self.font_size)[0] if prefix else 0
            cx = x + pad + prefix_w
            engine.draw_screen_rect((cx, y + 4, 2, h - 8), self.cursor_color)



class Dropdown(UIElement):
    """下拉菜单 (契约 §3.3). 点击展开 -> 列表显示在框下方; 选中项后收起.

    展开列表始终在 draw 时直接画出 (不依赖子元素树, 保证画在最上层).
    """

    ctype = 'dropdown'

    def __init__(self, name='dropdown', rect=(0, 0, 200, 32),
                 options=None, selected_index=0,
                 bg_color=(70, 80, 100, 255),
                 hover_color=(90, 100, 125, 255),
                 list_bg=(50, 55, 70, 255),
                 list_hover=(80, 140, 220, 255),
                 text_color=(255, 255, 255),
                 font_size=14,
                 item_height=28,
                 on_change=None, **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.options = list(options or [])
        self.selected_index = (max(0, min(len(self.options) - 1,
                                          int(selected_index)))
                               if self.options else -1)
        self.bg_color = tuple(bg_color)
        self.hover_color = tuple(hover_color)
        self.list_bg = tuple(list_bg)
        self.list_hover = tuple(list_hover)
        self.text_color = tuple(text_color)
        self.font_size = int(font_size)
        self.item_height = int(item_height)
        self.on_change = on_change
        self._expanded = False
        self._hover_item = -1

    def _list_rect(self, screen_rect):
        x, y, w, h = screen_rect
        return (x, y + h, w, self.item_height * len(self.options))

    def on_mouse_enter(self):
        self._hover = True

    def on_mouse_leave(self):
        self._hover = False
        self._hover_item = -1

    def on_mouse_down(self, pos):
        if not self.enabled:
            return False
        if self._expanded:
            # 展开态: 点击由 UIManager 转发给 handle_expanded_click
            return True
        self._expanded = True
        return True

    def on_mouse_up(self, pos):
        return self._expanded

    def handle_expanded_click(self, pos, screen_rect):
        """展开时 UIManager 调: 判断点击的是哪一项. 返回 True=消费."""
        lx, ly, lw, lh = self._list_rect(screen_rect)
        if lx <= pos[0] < lx + lw and ly <= pos[1] < ly + lh:
            idx = int((pos[1] - ly) // self.item_height)
            if 0 <= idx < len(self.options):
                self.selected_index = idx
                self._expanded = False
                if self.on_change is not None:
                    try:
                        self.on_change(self.options[idx])
                    except Exception:
                        pass
                return True
        # 点击列表外 -> 收起
        self._expanded = False
        return True

    @property
    def selected_value(self):
        if 0 <= self.selected_index < len(self.options):
            return self.options[self.selected_index]
        return ''

    def draw(self, engine, screen_rect):
        """画 box 本身 + 选中值. 展开列表由 _draw_expanded_list 单独绘制
        (UIManager.draw_all 第 2 轮调, 保证列表画在所有元素之上)."""
        x, y, w, h = screen_rect
        bg = self.hover_color if self._hover else self.bg_color
        engine.draw_screen_rect(screen_rect, bg)
        txt = self.selected_value
        if txt:
            lh = engine._measure_text('Mg', self.font_size)[1] or self.font_size
            ty = int(y + (h - lh) / 2)
            engine.draw_text_quad(txt, x + 8, ty, self.text_color, self.font_size)

    def _draw_expanded_list(self, engine, screen_rect):
        """展开列表绘制 (单独入口: UIManager.draw_all 在所有元素之后调)."""
        if not self._expanded or not self.options:
            return
        lx, ly, lw, lh = self._list_rect(screen_rect)
        engine.draw_screen_rect((lx, ly, lw, lh), self.list_bg)
        for i, opt in enumerate(self.options):
            iy = ly + i * self.item_height
            if i == self._hover_item:
                engine.draw_screen_rect((lx, iy, lw, self.item_height),
                                        self.list_hover)
            lh2 = engine._measure_text('Mg', self.font_size)[1] or self.font_size
            ty = int(iy + (self.item_height - lh2) / 2)
            engine.draw_text_quad(opt, lx + 8, ty, self.text_color, self.font_size)


class GridLayout(UIElement):
    """网格布局 (契约 §3.3). 按 columns/cell_size/spacing 自动排列子元素.

    自身仅绘制背景 (可选); 子元素 rect 由 _reflow 自动计算.
    """

    ctype = 'grid_layout'

    def __init__(self, name='grid', rect=(0, 0, 400, 300),
                 cell_size=(64, 64), spacing=(8, 8), columns=4,
                 bg_color=(0, 0, 0, 0), **kw):
        super().__init__(name=name, rect=rect, **kw)
        self.cell_w, self.cell_h = cell_size
        self.spacing_x, self.spacing_y = spacing
        self.columns = max(1, int(columns))
        self.bg_color = tuple(bg_color)

    def add_child(self, child):
        super().add_child(child)
        self._reflow()
        return child

    def remove_child(self, child):
        r = super().remove_child(child)
        self._reflow()
        return r

    def _reflow(self):
        for i, c in enumerate(self.children):
            row = i // self.columns
            col = i % self.columns
            cx = col * (self.cell_w + self.spacing_x)
            cy = row * (self.cell_h + self.spacing_y)
            c.rect = (cx, cy, self.cell_w, self.cell_h)

    def content_height(self):
        rows = (len(self.children) + self.columns - 1) // self.columns
        return rows * self.cell_h + max(0, rows - 1) * self.spacing_y

    def draw(self, engine, screen_rect):
        if len(self.bg_color) > 3 and self.bg_color[3] == 0:
            return
        engine.draw_screen_rect(screen_rect, self.bg_color)





