# -*- coding: utf-8 -*-
"""ui/canvas/manager.py — 多 Canvas 容器 UIManager + 脚本事件派发子域 + 键码表

我负责: 多 Canvas 容器 (渲染/输入入口: draw_all / hit_test / dispatch_mouse /
        dispatch_key / dispatch_text / focus / resize), 以及脚本事件派发子域
        (_ACTIVE_ENGINE 单点 + _find_script_instances / _fire_binding /
        _warn_script_host_once) 与键码->键名表 (_KEY_CODE_TO_NAME / _init_key_name_map)。

为何事件派发子域与本管理器同文件 (偏离第 7 批原计划把三助手放 element.py):
_ACTIVE_ENGINE 由 UIManager.draw_all 写入、由 _find_script_instances 读取, 二者靠 Python
模块级 global 共享同一格; 拆到两个模块会让 `global _ACTIVE_ENGINE` 写进各自模块命名空间
而互不可见 (UI 声明式事件全断)。为守住「类体逐字不变」, 只能把这对读写与该全局放在同一
模块 —— 即本文件。这是模块级可变状态的技术约束, 不是功能合并。

我不负责: 元素基类 (element.py)、单画布 (canvas.py)、控件绘制 (widgets_*.py)。
拆分: Q-B7-38-1 第 7 批 (2026-11-26), 原文 Loom/loom_ui.py 16-112 + 403-789 + 793-823 逐字搬入。
"""

from .canvas import Canvas

# 2026-10-19 P0-5: 声明式事件绑定的派发基础。
# UIManager.draw_all(engine) 每帧把 engine 写到这里，事件触发时用它找脚本实例。
# 原因：UI 事件（on_mouse_up 等）在输入轮询里触发，不经过 update 循环，
# 需要 module 级引用才能从"某个 UI 元素"反查"引擎里挂了这个脚本的物体"。
_ACTIVE_ENGINE = None
_SCRIPT_HOST_WARNED = False      # 2026-11-08: "宿主不可用"告警每进程只打一次


def _warn_script_host_once(host, engine):
    """宿主缺 .models/.scripts 时告警一次（P-03-09: 不得静默丢事件）。"""
    global _SCRIPT_HOST_WARNED
    if _SCRIPT_HOST_WARNED:
        return
    _SCRIPT_HOST_WARNED = True
    print('[UI 事件] 脚本宿主缺少 .models/.scripts: host=%s draw=%s -> 声明式 UI 事件'
          '将无法派发到脚本；调用方必须传 script_host=(引擎/驱动)，例如'
          ' draw_frame(..., engine=driver)（本提示每进程只打印一次）'
          % (type(host).__name__, type(engine).__name__))


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
            # 2026-11-07 修复: 方法在"运行时脚本实例"上, 不在 ScriptComponent 上。
            # 2026-11-08 批2 (P-03-08): 用**存在性**判断替代真值判断 ——
            # 旧写法 `getattr(sc,'_script',None) or sc` 在运行时实例为"假值"时
            # （脚本类自己定义了 __len__/__bool__，例如容器式脚本）会静默回落成
            # ScriptComponent，随后以"无方法"丢弃事件，玩家看到的就是"点不动"。
            target = getattr(sc, '_script', None)
            if target is None:
                # 未实例化（惰性实例化还没跑到）与"实例缺方法"必须分开报，
                # 否则排查方向会被带错（旧文案把两者都说成"无方法"）。
                print('[UI 事件] 脚本 %r 的运行时实例尚未创建（惰性实例化未运行）'
                      ': event=%r 触发自 %r.%r -> 本次事件丢弃'
                      % (sid, event, getattr(obj, 'name', '?'), elem.name))
                continue
            fn = getattr(target, method, None)
            if fn is None:
                print('[UI 事件] 脚本 %r 缺方法 %r（触发自 %r.%r）'
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

    def _hit_screen(self, pos):
        """多 Canvas 命中 (Q7=C 只吞空白, 2026-11-07 P1-6).

        返回 (canvas, element) 或 (None, None)。

        规则:
          · 从最上层 Canvas 往下测; 命中**子元素**立刻返回 (上层优先不变);
          · 只命中 Canvas 的 root (空白区) 时**继续下探低层 Canvas** ——
            顶层 HUD 铺满全屏, 旧逻辑让它把下层列表/按钮全部吞掉 (下层
            UI 永远点不到);
          · 全部都没命中任何元素时, 返回最上层 Canvas 的 root: 空白点击
            仍算 UI 消费, 不会漏到 3D 拾取/相机 —— 这就是"只吞空白"。
        """
        top = None                     # (canvas, root): 最上层 screen Canvas
        for c in reversed(self.canvases):
            if c.canvas_type != 'screen':
                continue               # world Canvas 命中留到阶段4
            root = c.root
            if top is None:
                top = (c, root)
            hit = root.hit_test(pos, (0.0, 0.0,
                                 float(c.width), float(c.height)))
            if hit is None:            # 该 Canvas 整体没命中 -> 继续下探
                continue
            if hit is not root:        # 命中子元素 -> 上层优先
                return c, hit
            # 只命中 root 空白 -> 记下位置继续下探 (低层子元素仍可能命中)
        if top is not None:
            return top                 # 全都没命中子元素: 顶层 root 吞空白
        return None, None

    def hit_test(self, pos):
        """多 Canvas 命中入口 (Q7=C). 返回 (canvas, root) 表示只吞空白.

        细节见 _hit_screen; 本方法只是稳定入口 (dispatch_mouse /
        update_hover_only / _hit_scroll_view 共用同一条规则)."""
        return self._hit_screen(pos)


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
        # 2026-11-07 P1-6: 与 UIManager.hit_test 共用 Q7=C 规则 (只吞空白;
        # 顶层 Canvas 的空白不再把低层 Canvas 的子元素全吞掉).
        hit_canvas, hovered = self._hit_screen(pos)

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
                # 2026-11-07 修复: 原写法是 "a.b = X if cond else Y" —— 赋值目标
                # 会先求值, _dragging_elem 为 None 时抛 AttributeError (GL editor
                # 在更外层吞掉了异常, 所以一直没被发现; Vk 桥按原语义补清理)。
                if self._dragging_elem is not None:
                    self._dragging_elem._dragging = False
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
        # 2026-11-07 P1-6: 同 hit_test 的 Q7=C 规则 (低层 Canvas 子元素也可 hover)
        _c, hovered = self._hit_screen(pos)
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

    def draw_all(self, engine, script_host=None):
        """渲染所有 screen Canvas 的元素树 (渲染层末尾调用). 父先于子.

        engine      : 绘制目标 (要有 draw_screen_rect 等; GL 是 GLEngine,
                      VK 是 VkUIEngine 门面)。
        script_host : **脚本宿主** (要有 .models/.scripts; 通常是 GLEngine 或
                      SceneDriver)。事件派发 (_fire_binding) 靠它找脚本实例。
        2026-11-07 修复(P0): VK 之前把 VkUIEngine 当成脚本宿主 ->
        _ACTIVE_ENGINE 没有 .models -> 打包版所有 UI 按钮点击无效。
        """
        # 2026-10-19 P0-5: 每帧刷新 _ACTIVE_ENGINE（供 _fire_binding 查脚本实例）
        global _ACTIVE_ENGINE
        host = script_host if script_host is not None else engine
        # 2026-11-08 批2 (P-03-09): 宿主没有 .models/.scripts 时**出声**（每进程一次）。
        # 场景: 调用方忘了把 engine/驱动透传过来（例如 draw_frame(..., engine=None)），
        # 于是 _ACTIVE_ENGINE 变成"绘制门面"，UI 画得全对、事件永远派发不到脚本 ——
        # 旧行为只有点击那一刻往 stdout 打一行，打包版无控制台 = 完全不可见。
        if not hasattr(host, 'models'):
            _warn_script_host_once(host, engine)
        _ACTIVE_ENGINE = host
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
