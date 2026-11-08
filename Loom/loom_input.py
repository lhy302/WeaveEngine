# -*- coding: utf-8 -*-
"""loom_input.py — 按键映射与输入动作层（M30b）。

原属 engine.py（"按键字符 -> pygame 键码" + "输入动作层" + "按键绑定配置" 段）。
零引擎依赖，仅依赖 pygame（用于 K_* 键码常量）。
engine.py 通过 `from loom_input import *` 重导出。
"""

import os

import pygame


# ================ 按键字符 -> pygame 键码 ================
_KEYMAP = {
    'w': pygame.K_w, 's': pygame.K_s, 'a': pygame.K_a, 'd': pygame.K_d,
    'q': pygame.K_q, 'e': pygame.K_e,
    'Left': pygame.K_LEFT, 'Right': pygame.K_RIGHT, 'Up': pygame.K_UP, 'Down': pygame.K_DOWN,
    'i': pygame.K_i, 'k': pygame.K_k, 'j': pygame.K_j, 'l': pygame.K_l,
    'u': pygame.K_u, 'o': pygame.K_o,
    'space': pygame.K_SPACE, 'Tab': pygame.K_TAB,
    'Shift': pygame.K_LSHIFT, 'Ctrl': pygame.K_LCTRL,
    '1': pygame.K_1, '2': pygame.K_2, '3': pygame.K_3,
    '4': pygame.K_4, '5': pygame.K_5, '6': pygame.K_6,
    'a': pygame.K_a,
    'b': pygame.K_b,
    'c': pygame.K_c,
    'd': pygame.K_d,
    'e': pygame.K_e,
    'f': pygame.K_f,
    'g': pygame.K_g,
    'h': pygame.K_h,
    'i': pygame.K_i,
    'j': pygame.K_j,
    'k': pygame.K_k,
    'l': pygame.K_l,
    'm': pygame.K_m,
    'n': pygame.K_n,
    'o': pygame.K_o,
    'p': pygame.K_p,
    'q': pygame.K_q,
    'r': pygame.K_r,
    's': pygame.K_s,
    't': pygame.K_t,
    'u': pygame.K_u,
    'v': pygame.K_v,
    'w': pygame.K_w,
    'x': pygame.K_x,
    'y': pygame.K_y,
    'z': pygame.K_z,
    '0': pygame.K_0,
    '1': pygame.K_1,
    '2': pygame.K_2,
    '3': pygame.K_3,
    '4': pygame.K_4,
    '5': pygame.K_5,
    '6': pygame.K_6,
    '7': pygame.K_7,
    '8': pygame.K_8,
    '9': pygame.K_9,
    'Esc': pygame.K_ESCAPE,
    'Enter': pygame.K_RETURN,
    'Backspace': pygame.K_BACKSPACE,
    'Delete': pygame.K_DELETE,
    'Insert': pygame.K_INSERT,
    'Home': pygame.K_HOME,
    'End': pygame.K_END,
    'PageUp': pygame.K_PAGEUP,
    'PageDown': pygame.K_PAGEDOWN,
    '-': pygame.K_MINUS,
    '=': pygame.K_EQUALS,
    '[': pygame.K_LEFTBRACKET,
    ']': pygame.K_RIGHTBRACKET,
    '\\': pygame.K_BACKSLASH,
    ';': pygame.K_SEMICOLON,
    "'": pygame.K_QUOTE,
    ',': pygame.K_COMMA,
    '.': pygame.K_PERIOD,
    '/': pygame.K_SLASH,
    '`': pygame.K_BACKQUOTE,
    'F1': pygame.K_F1,
    'F2': pygame.K_F2,
    'F3': pygame.K_F3,
    'F4': pygame.K_F4,
    'F5': pygame.K_F5,
    'F6': pygame.K_F6,
    'F7': pygame.K_F7,
    'F8': pygame.K_F8,
    'F9': pygame.K_F9,
    'F10': pygame.K_F10,
    'F11': pygame.K_F11,
    'F12': pygame.K_F12,
}
# 2026-11-07: 键位表补全 (字母/数字/F1-F12/Esc/Enter/编辑键/标点)。
# 旧表只有 30 个键, 玩家把动作改键到 F10/Esc 等会静默失效。

# ================ 输入动作层 (M30b, Unity 输入系统理念) ================
# 动作 = "玩家想做什么" ('向前'/'跳跃'), 绑定到一组键名 (_KEYMAP 字符键).
# 脚本/游戏逻辑用 engine.get_action('动作') 而非 is_key('键') —— 改键不动脚本,
# 像 Unity Input System 的动作层 (Action -> Binding). 键位改在用户层
# (游戏设置.json values.key_bindings), 模板见 输入配置.default.json (只读).
DEFAULT_ACTIONS = {
    # 2026-11-07: 强制存在的"解锁鼠标"动作 (默认 Tab, 可在
    # 游戏设置.json 的 key_bindings 里改键, 游戏开发者可做改键 UI)
    '解锁鼠标': ['Tab'],
    '向前': ['w', 'Up'],
    '向后': ['s', 'Down'],
    '向左': ['a', 'Left'],
    '向右': ['d', 'Right'],
    '跳跃': ['space'],
    '交互': ['e'],
    '加速': ['Shift'],
}
# 2026-11-08 用户配置目录契约 §8: 引擎目录里的键位文件降级为**只读模板**,
# 运行时永不写；玩家/开发者的改键落在用户层 (%LOCALAPPDATA%\Loom\...) 的
# 游戏设置.json -> values.key_bindings。
UNLOCK_ACTION = '解锁鼠标'   # 引擎独占的解锁动作名 (2026-11-08 D6=A)
_ACTION_FILE = "输入配置.default.json"    # 只读模板（随版本更新）
_ACTION_FILE_LEGACY = "输入配置.json"     # 旧名：仍可作模板读（旧安装/开发工作区）


# ================ 按键绑定配置 (可在此处修改) ================
KEY_BINDINGS = {
    # 相机移动控制
    'CAMERA_FORWARD': 'w',
    'CAMERA_BACKWARD': 's',
    'CAMERA_LEFT': 'a',
    'CAMERA_RIGHT': 'd',
    'CAMERA_UP': 'q',
    'CAMERA_DOWN': 'e',

    # 相机视角控制
    'LOOK_LEFT': 'Left',
    'LOOK_RIGHT': 'Right',
    'LOOK_UP': 'Up',
    'LOOK_DOWN': 'Down',

    # 模型选择 (2026-08-28: 删除 'RESET_ALL': 'space' 空格复位 —— 玩具期键位表
    # 遗留, 与输入动作'跳跃'共用空格键, 玩家游戏内按空格(跳跃)被复位回出生点)
    'SELECT_NEXT_MODEL': 'Tab',
}
# ============================================================


# ============ 鼠标锁定: 告警闸门 + Win32 兜底 (2026-11-08 缺陷③) ============
_MOUSE_WARNED = set()


def _mouse_warn_once(tag, msg):
    """同一类问题每进程只告警一次（避免每帧刷屏，又不像 except:pass 那样静默）。"""
    if tag in _MOUSE_WARNED:
        return False
    _MOUSE_WARNED.add(tag)
    print('[鼠标] %s' % (msg,))
    return True


def _win32_clip_cursor(win, locked):
    """Win32 兜底: 锁定 -> 把光标夹在窗口客户区; 解锁 -> ClipCursor(NULL)。

    返回 'clipped' / 'free' / 'n/a'（无窗口或非 Windows） / 'err'（失败，只告警一次）。
    为什么要兜底: 只翻 GLFW CURSOR 模式在部分驱动/Alt+Tab 抢焦点后会失效 ——
    "光标出现但动不了"正是捕获流在 Win32 层残留的表现。
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
    except (AttributeError, ImportError, OSError) as e:
        _mouse_warn_once('win32-import', 'Win32 光标兜底不可用 (%r)' % (e,))
        return 'n/a'
    if not locked:
        try:
            user32.ClipCursor(None)
            return 'free'
        except (AttributeError, OSError) as e:
            _mouse_warn_once('win32-clip-free', 'ClipCursor(NULL) 失败 (%r)' % (e,))
            return 'err'
    if win is None:
        return 'n/a'
    try:
        import glfw
        get_native = getattr(glfw, 'get_win32_window', None)
        if get_native is None:
            return 'n/a'
        hwnd = get_native(win)
        if not hwnd:
            return 'n/a'
        r = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(r)):
            return 'err'
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        rect = wintypes.RECT(pt.x, pt.y, pt.x + r.right, pt.y + r.bottom)
        if not user32.ClipCursor(ctypes.byref(rect)):
            return 'err'
        return 'clipped'
    except (AttributeError, OSError, ValueError) as e:
        _mouse_warn_once('win32-clip-lock', 'ClipCursor(窗口矩形) 失败 (%r)' % (e,))
        return 'err'


def _win32_show_cursor(show):
    """Win32 兜底: ShowCursor(TRUE/FALSE)。返回 True/False；失败 None（告警一次）。"""
    try:
        import ctypes
        ctypes.windll.user32.ShowCursor(1 if show else 0)
        return bool(show)
    except (AttributeError, ImportError, OSError) as e:
        _mouse_warn_once('win32-show', 'ShowCursor 兜底失败 (%r)' % (e,))
        return None


class InputMixin:
    """输入子系统 (从 GLEngine 抽出): 按键快照 / 输入动作层 / 鼠标锁定 / 键位配置.

    依赖宿主 GLEngine 运行时提供:
      self.script_keys / self.actions / self.mouse_locked
      self._external_ctx / self.view / self._ui_capture_mouse /
      self.mouse_unlock_requested
    mixin 只通过 self 按需访问 (语义与拆分前逐位一致)."""

    # 2026-11-08 人类裁决: **默认不锁鼠标**。需要锁的游戏/脚本显式
    # set_mouse_lock_allowed(True)（或 游戏设置.json mouse_lock_allowed=true）。
    mouse_lock_allowed = False
    mouse_locked = False
    mouse_unlock_requested = False
    _ui_capture_mouse = False

    def _key_pressed(self):
        """按键快照 (每帧): 供 _update_camera 等按键查询.
        - 嵌入式模式 (Qt 宿主): 由宿主维护的 key_pressed_array 提供
        - 玩家运行时 (GLFW 窗口): 从 GLFW 键状态构建 dict (按 pygame K_* 索引)
        返回类型是 defaultdict(int)，可按 pygame 键码索引 (0/1)."""
        if getattr(self, '_external_ctx', False):
            view = getattr(self, 'view', None)
            if view is not None and hasattr(view, 'key_pressed_array'):
                return view.key_pressed_array()
            from collections import defaultdict
            return defaultdict(int)   # 特殊键码 (K_LEFT 等) 超 512, 用 dict 防越界
        # 2026-10-18 A2: GLFW 键状态 -> pygame K_* 索引 dict
        from collections import defaultdict
        result = defaultdict(int)
        win = getattr(self, '_glfw_win', None)
        if win is None:
            return result
        try:
            import glfw
            from loom_glfw_window import _GLFW_TO_PG
            for gl_key, pg_key in _GLFW_TO_PG.items():
                if glfw.get_key(win, gl_key) == glfw.PRESS:
                    result[pg_key] = 1
        except Exception:
            pass
        return result

    def is_key(self, name):
        """脚本/游戏输入查询: name 为 _KEYMAP 字符键 ('w'/'space'/'Left'...).
        由 _handle_events 每帧刷新 script_keys; 未刷新过 (无窗口/测试) 返回 False."""
        return bool(self.script_keys.get(name, False))

    def sync_script_keys(self):
        """嵌入式模式 (Qt 宿主) 的脚本键刷新: pygame 路径由 _handle_events 每帧
        刷 script_keys; 外部模式 _handle_events 直接 return (事件由宿主喂), 此前
        script_keys 恒空 = 播放态玩家脚本 is_key/get_action 永远 False (WASD 不
        动/跳跃不跳). 由引擎渲染帧头调用, 与 pygame 路径每帧刷新同语义.
        宿主按键快照经 view.key_pressed_array() (pygame 键码 -> 0/1)."""
        if not getattr(self, '_external_ctx', False):
            return
        _kp = self._key_pressed()
        self.script_keys = {name: bool(_kp[k]) for name, k in _KEYMAP.items()}

    def get_action(self, name):
        """输入动作查询 (Unity 动作层): 动作名 -> 绑定的任意键按下即 True.
        默认动作见 DEFAULT_ACTIONS; 键位可在用户层重映射 (改键不动脚本).
        未绑定动作时回退为同名键查询 (方便脚本直接写 'w')."""
        for k in self.actions.get(name, (name,)):
            if self.script_keys.get(k, False):
                return True
        return False

    # ---- 2026-11-08 (P-01-02 / D6=A): 解锁键归引擎独占 + 键位冲突判定 ----

    def script_occupied_keys(self, exclude_action=None):
        """脚本声明占用的具体键名 -> {键名: [脚本显示名, ...]}。

        声明项展开: 'Tab' 原样; 'action:向前' 用**当前** self.actions 展开。
        exclude_action = 正在改绑的动作名（它自己的旧绑定不算冲突，否则
        "把 向前 再绑回 w" 会被自己拒绝）。
        脚本注册表不可用时出声跳过（不静默通过）。
        """
        occ = {}
        try:
            import scripts
            uses = scripts.script_key_uses()
            disp = scripts.script_display_name
        except Exception as e:
            print('[输入] 脚本键位声明不可用 (%r) -> 本次跳过冲突判定' % (e,))
            return occ
        for sid, decls in uses.items():
            who = disp(sid)
            for d in decls:
                d = str(d)
                if d.startswith(getattr(scripts, 'KEY_ACTION_PREFIX', 'action:')):
                    act = d[len(getattr(scripts, 'KEY_ACTION_PREFIX', 'action:')):]
                    if act == exclude_action:
                        continue
                    keys = self.actions.get(act, (act,))
                else:
                    keys = (d,)
                for k in keys:
                    occ.setdefault(str(k), []).append(who)
        return occ

    def validate_action_binding(self, name, keys):
        """键位冲突校验 -> (ok, reason). 冲突时 reason 可直接展示给玩家。"""
        occ = self.script_occupied_keys(exclude_action=name)
        seen = set()
        hit = []
        for k in (keys or []):
            for who in occ.get(str(k), ()):
                if (k, who) not in seen:
                    seen.add((k, who))
                    hit.append((k, who))
        if hit:
            k0, who0 = hit[0]
            if name == UNLOCK_ACTION:
                return False, ('键位冲突: 解锁键 %s 已被脚本 %s 使用，'
                               '请先定义解锁键（或先改掉该脚本占用的键）'
                               % (k0, who0))
            return False, ('键位冲突: 动作 %s 的键 %s 已被脚本 %s 占用'
                           % (name, k0, who0))
        return True, ''

    def set_mouse_lock_allowed(self, allowed):
        """脚本 API（2026-11-08 裁决 ③①）: 运行期开关"**整个游戏**是否允许锁鼠标"。

        切换后立即按新状态应用（不是等下一帧）:
          · True  -> 按 [特殊场景 | 玩家解锁意图] 重新计算并应用；
          · False -> 清解锁意图 + 立刻释放鼠标（锁不能再被任何脚本强行打开）。

        典型用法（由**游戏开发者**显式决定，引擎不替游戏猜）:
          · FPS/第三人称视角需要转视角: engine.set_mouse_lock_allowed(True)
          · 切到纯 UI 关卡/结算页: engine.set_mouse_lock_allowed(False)
        返回: 切换后的布尔值。
        """
        self.mouse_lock_allowed = bool(allowed)
        if self.mouse_lock_allowed:
            self._apply_mouse_lock()
        else:
            self.mouse_unlock_requested = False
            self.set_mouse_locked(False)
        return self.mouse_lock_allowed

    def set_mouse_locked(self, locked):
        """设置鼠标锁定状态 (True=隐藏+捕获居中, False=显示+释放)。

        2026-11-08 裁决（默认不锁 + 缺陷③）:
          · \`mouse_lock_allowed\` 为 False 时 **锁定请求无效**（每进程告警一次）——
            内置 first/third_person 的 on_start 无条件调用也不会把玩家鼠标锁死；
          · 每次**状态变化**打一行 \`[鼠标] locked=... (glfw_mode=..., clip=..., showing=...)\`；
          · GLFW 设置后**回读校验**，不符/失败都告警（不再 except: pass 静默）；
          · 解锁补 Win32 \`ClipCursor(NULL)\` + \`ShowCursor(TRUE)\`，锁定补
            \`ClipCursor(窗口客户区)\`（ctypes，失败只告警一次）。
        嵌入式模式（Qt 宿主）转给视图实现，不碰 GLFW/Win32 光标。
        返回: True=已应用（或已解锁）; False=因"不允许锁"被拒绝。
        """
        locked = bool(locked)
        if locked and not getattr(self, 'mouse_lock_allowed', False):
            _mouse_warn_once(
                'denied:%s' % type(self).__name__,
                '本游戏不允许锁鼠标 (mouse_lock_allowed=False)，'
                'set_mouse_locked(True) 被忽略；需要锁定请先 '
                'set_mouse_lock_allowed(True) 或在 游戏设置.json 里打开')
            if getattr(self, 'mouse_locked', False):
                self.set_mouse_locked(False)
            return False
        prev = getattr(self, 'mouse_locked', None)
        self.mouse_locked = locked
        mode, clip, showing = 'n/a', 'n/a', 'n/a'
        if self._external_ctx:
            view = getattr(self, 'view', None)
            if view is not None and hasattr(view, 'set_mouse_locked'):
                view.set_mouse_locked(locked)
            mode = 'host'
        else:
            mode, clip, showing = self._apply_cursor_backend(locked)
        if prev is not locked:
            print('[鼠标] locked=%s (glfw_mode=%s, clip=%s, showing=%s)'
                  % (locked, mode, clip, showing))
        return True

    def _apply_cursor_backend(self, locked):
        """真正改光标: GLFW 光标模式 + 回读校验 + Win32 兜底。

        返回 (glfw_mode, clip, showing) 供调用方打证据行:
          glfw_mode: 'disabled' / 'normal' / 'no-window' / 'error'
          clip:      'clipped' / 'free' / 'n/a' / 'err'
          showing:   True / False / None
        """
        mode, clip, showing = 'n/a', 'n/a', 'n/a'
        try:
            import glfw
        except (ImportError, AttributeError) as e:
            _mouse_warn_once('glfw-import', 'GLFW 不可用 (%r)，无法切换光标模式' % (e,))
            glfw = None
        win = getattr(self, '_glfw_win', None)
        if glfw is None:
            return mode, clip, showing
        if win is None:
            return 'no-window', clip, showing
        want = glfw.CURSOR_DISABLED if locked else glfw.CURSOR_NORMAL
        try:
            glfw.set_input_mode(win, glfw.CURSOR, want)
            got = glfw.get_input_mode(win, glfw.CURSOR)      # 缺陷③: 回读校验
            if got == glfw.CURSOR_DISABLED:
                mode = 'disabled'
            elif got == glfw.CURSOR_NORMAL:
                mode = 'normal'
            else:
                mode = 'unknown(%r)' % (got,)
            if got != want:
                _mouse_warn_once('glfw-mode-readback',
                                 'GLFW 光标模式回读不符: 期望 %r 实际 %r (窗口可能已失去焦点)'
                                 % (want, got))
        except (AttributeError, TypeError, RuntimeError) as e:
            _mouse_warn_once('glfw-mode-set',
                             'GLFW 光标模式切换失败 (%r)，改走 Win32 兜底' % (e,))
            mode = 'error'
        clip = _win32_clip_cursor(win, locked)
        showing = _win32_show_cursor(not locked)
        return mode, clip, showing

    def _apply_mouse_lock(self):
        """按 [是否允许锁 | 特殊场景标志 | 玩家解锁意图] 计算实际锁定。

        2026-11-08: allowed=False 时锁恒为关 —— 不允许锁的游戏连"意图"都不保留。
        """
        if not getattr(self, 'mouse_lock_allowed', False):
            self.mouse_unlock_requested = False
            self.set_mouse_locked(False)
            return False
        self.set_mouse_locked(not (self._ui_capture_mouse or self.mouse_unlock_requested))
        return bool(getattr(self, 'mouse_locked', False))

    def toggle_mouse_locked(self):
        """切换玩家解锁意图（非特殊场景；特殊场景下强制置为未解锁并回锁）。

        2026-11-08 裁决: \`mouse_lock_allowed=False\` 时**完全不响应** ——
        不发任何"切换鼠标锁定"日志（玩家按 Tab 不该看到引擎在自说自话）。
        返回: True=有响应; False=因不允许锁而被忽略。
        """
        if not getattr(self, 'mouse_lock_allowed', False):
            return False
        if self._ui_capture_mouse:
            self.mouse_unlock_requested = False     # 特殊场景: 玩家解锁意图强制清零
        else:
            self.mouse_unlock_requested = not self.mouse_unlock_requested
        self._apply_mouse_lock()
        return True

    def set_ui_capture_mouse(self, capture):
        """**开发者显式 API**（2026-11-08 裁决 ②：引擎不做"检测到 UI 就自动解锁"）。

        什么时候该调用（由游戏逻辑自己判断，引擎不猜）:
          · 打开背包/菜单/暂停面板/结算页等**需要玩家点鼠标**的特殊场景 -> True；
          · 这些界面关闭、回到游戏操作 -> False。
        语义: True = 强制显示鼠标 + 清零玩家解锁意图（临时覆盖锁定）；
              False = 回到"按 mouse_lock_allowed + 玩家解锁意图"计算的状态。
        反例提醒（人类裁决原文）: 燕云十六声这类界面有常驻可点 UI 但平时仍锁鼠标，
        因此**不能**用"有 UI 元素"当自动解锁条件 —— 只有游戏自己的状态机知道该不该解锁。
        注意: mouse_lock_allowed=False 时本调用不产生锁定（锁恒为关）。
        """
        self._ui_capture_mouse = bool(capture)
        if capture:
            self.mouse_unlock_requested = False
        self._apply_mouse_lock()

    def _action_bindings_file(self):
        """键位**模板**路径（只读）: 优先 <引擎目录>/输入配置.default.json,
        其次兼容旧名 输入配置.json（旧安装/未迁移的工作区）."""
        d = os.path.dirname(os.path.abspath(__file__))
        p_new = os.path.join(d, _ACTION_FILE)
        if os.path.exists(p_new):
            return p_new
        p_old = os.path.join(d, _ACTION_FILE_LEGACY)
        return p_old if os.path.exists(p_old) else p_new

    def _load_action_bindings(self, path=None):
        """加载动作绑定 = DEFAULT_ACTIONS <- 模板(只读) <- 用户层 key_bindings.

        契约 docs/design/用户配置目录契约_20261108.md §4/§5:
          · 模板坏/缺 -> 用默认，但**出声**（不再静默）；
          · 单条坏条目只影响它自己（审计 P-01-16），其余照常加载；
          · 用户层覆盖由 apply_game_bindings() 收口（审计 P-01-01 的实现点）。
        """
        import json as _json
        p = path or self._action_bindings_file()
        self.actions = dict(DEFAULT_ACTIONS)
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = _json.load(f)
        except FileNotFoundError:
            data = None
        except Exception as e:
            print('[输入] 键位模板读取失败 (%r): %s -> 用默认键位' % (e, p))
            data = None
        acts = data.get('actions') if isinstance(data, dict) else None
        if acts is not None and not isinstance(acts, dict):
            print('[输入] 键位模板 actions 段应为对象 (%s) -> 忽略该段'
                  % (type(acts).__name__,))
            acts = None
        for a, ks in (acts or {}).items():
            try:
                self.actions[str(a)] = list(ks)
            except Exception as e:
                print('[输入] 键位模板条目 %r 非法 (%r) -> 跳过该条' % (a, e))
        self.apply_game_bindings()

    def apply_game_bindings(self):
        """把**用户层** key_bindings 叠加到 self.actions（最高优先级层）.

        契约 §3.4 优先级: 游戏设置.json key_bindings > 引擎模板 > DEFAULT_ACTIONS。
        读失败不抛（启动必须能跑起来），但会打印原因而不是静默跳过。
        """
        try:
            import game_settings
            kb = game_settings.read_key_bindings()
        except Exception as e:
            print('[输入] 读用户键位失败 (%r) -> 沿用模板/默认键位' % (e,))
            return
        for a, ks in (kb or {}).items():
            try:
                self.actions[str(a)] = list(ks)
            except Exception as e:
                print('[输入] 用户键位条目 %r 非法 (%r) -> 跳过' % (a, e))
        self.resolve_unlock_key_conflict()

    def resolve_unlock_key_conflict(self):
        """加载时冲突处置: 用户层已存的解锁键与脚本声明冲突 -> 告警 + 回退默认。

        选择"告警 + 回退默认 Tab"而不是"拒绝启动"的理由: 用户配置目录契约 §5
        要求启动流程必须能跑（配置写错不应把游戏变成打不开）；且内置脚本不再
        占用 Tab 后，默认解锁键天然无冲突，回退是安全的最小动作。
        """
        cur = self.actions.get(UNLOCK_ACTION)
        if not cur:
            return
        ok, reason = self.validate_action_binding(UNLOCK_ACTION, list(cur))
        if ok:
            return
        default = list(DEFAULT_ACTIONS.get(UNLOCK_ACTION, ['Tab']))
        ok2, _r2 = self.validate_action_binding(UNLOCK_ACTION, default)
        if ok2:
            print('[输入] %s -> 已回退默认解锁键 %s' % (reason, default))
            self.actions[UNLOCK_ACTION] = default
        else:
            print('[输入] %s -> 默认解锁键亦被占用，保持当前值（解锁键可能失效）'
                  % (reason,))

    def save_action_bindings(self, path=None):
        """导出/落盘当前动作绑定.

        path 给出 = 写成 {\"actions\": ...} 明文（导出/测试用）；
        path 缺省 = 写**用户层** delta（契约 §7：失败上抛，不再 except: pass）。
        """
        import json as _json
        if path is not None:
            tmp = path + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                _json.dump({"actions": self.actions}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return path
        import game_settings
        return game_settings.write_key_bindings(self.actions)

    def rebind_action(self, name, keys):
        """重映射动作到一组键名 (如 {'跳跃': ['space','j']})。

        2026-11-08（审计 P-01-05）: **只写用户层**（%LOCALAPPDATA%\Loom\… 的
        游戏设置.json values.key_bindings），绝不写引擎目录的只读模板，
        也不写任何受版本控制的文件；写失败上抛，由调用方 (set_action_binding /
        改键 UI) 如实告知玩家（契约 §7）。
        """
        keys = list(keys)
        ok, reason = self.validate_action_binding(name, keys)
        if not ok:
            raise ValueError(reason)          # 冲突即拒绝保存（D6=A 裁决）
        self.actions[name] = keys
        import game_settings
        game_settings.write_key_binding(name, keys)
        return self.actions[name]

    def get_action_bindings(self):
        """当前全部动作绑定 (供改键 UI 展示)。"""
        return {a: list(ks) for a, ks in self.actions.items()}
# ================ 按键绑定配置 (可在此处修改) ================
KEY_BINDINGS = {
    # 相机移动控制
    'CAMERA_FORWARD': 'w',
    'CAMERA_BACKWARD': 's',
    'CAMERA_LEFT': 'a',
    'CAMERA_RIGHT': 'd',
    'CAMERA_UP': 'q',
    'CAMERA_DOWN': 'e',

    # 相机视角控制
    'LOOK_LEFT': 'Left',
    'LOOK_RIGHT': 'Right',
    'LOOK_UP': 'Up',
    'LOOK_DOWN': 'Down',

    # 模型选择 (2026-08-28: 删除 'RESET_ALL': 'space' 空格复位 —— 玩具期键位表
    # 遗留, 与输入动作'跳跃'共用空格键, 玩家游戏内按空格(跳跃)被复位回出生点)
    'SELECT_NEXT_MODEL': 'Tab',
}
# ============================================================

