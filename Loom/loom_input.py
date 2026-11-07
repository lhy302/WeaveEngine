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
# 像 Unity Input System 的动作层 (Action -> Binding). 键位可在 输入配置.json 重映射.
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
_ACTION_FILE = "输入配置.json"   # 键位重映射配置文件 (放引擎目录, 缺失用默认)


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


class InputMixin:
    """输入子系统 (从 GLEngine 抽出): 按键快照 / 输入动作层 / 鼠标锁定 / 键位配置.

    依赖宿主 GLEngine 运行时提供:
      self.script_keys / self.actions / self.mouse_locked
      self._external_ctx / self.view / self._ui_capture_mouse /
      self.mouse_unlock_requested
    mixin 只通过 self 按需访问 (语义与拆分前逐位一致)."""

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
        默认动作见 DEFAULT_ACTIONS; 键位可在 输入配置.json 重映射 (改键不动脚本).
        未绑定动作时回退为同名键查询 (方便脚本直接写 'w')."""
        for k in self.actions.get(name, (name,)):
            if self.script_keys.get(k, False):
                return True
        return False

    def set_mouse_locked(self, locked):
        """M39 底层: 直接设鼠标锁定状态 (True=隐藏+捕获居中, False=显示+释放).
        嵌入式模式 (Qt 宿主) 转给视图实现 (QOpenGLWidget 光标/捕获), 不碰 pygame."""
        self.mouse_locked = bool(locked)
        if self._external_ctx:
            view = getattr(self, 'view', None)
            if view is not None and hasattr(view, 'set_mouse_locked'):
                view.set_mouse_locked(locked)
            return
        # 2026-10-18 A2: GLFW 光标模式（原 pygame.event.set_grab + mouse.set_visible）
        # CURSOR_DISABLED = 锁定 + 隐藏（玩家控制器转视角用）
        # CURSOR_NORMAL   = 正常显示（解锁）
        try:
            import glfw
            win = getattr(self, '_glfw_win', None)
            if win is not None:
                mode = glfw.CURSOR_DISABLED if locked else glfw.CURSOR_NORMAL
                glfw.set_input_mode(win, glfw.CURSOR, mode)
        except Exception:
            pass

    def _apply_mouse_lock(self):
        """M39: 按 [特殊场景标志 | 玩家解锁意图] 计算实际鼠标锁定.
        locked = not (ui_capture_mouse or unlock_requested)."""
        self.set_mouse_locked(not (self._ui_capture_mouse or self.mouse_unlock_requested))

    def toggle_mouse_locked(self):
        """M39: Tab 切换玩家解锁意图 (非特殊场景). 特殊场景下强制置为未解锁."""
        if self._ui_capture_mouse:
            self.mouse_unlock_requested = False     # 特殊场景: 玩家解锁意图强制清零
        else:
            self.mouse_unlock_requested = not self.mouse_unlock_requested
        self._apply_mouse_lock()

    def set_ui_capture_mouse(self, capture):
        """M39: 特殊场景 (UI 菜单/暂停等需要鼠标操作) 强制显示鼠标, 并清玩家解锁意图.
        退出特殊场景时解锁意图仍为"未解锁" -> 鼠标正常回锁 (FPS 通用解锁回锁机制):
        非特殊场景解锁 -> 进特殊场景强制回锁 -> 退出特殊场景鼠标回锁, 需再按 Tab 才解锁."""
        self._ui_capture_mouse = bool(capture)
        if capture:
            self.mouse_unlock_requested = False
        self._apply_mouse_lock()

    def _action_bindings_file(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), _ACTION_FILE)

    def _load_action_bindings(self, path=None):
        """从 输入配置.json 加载动作绑定 (坏文件回退默认)."""
        import json as _json
        p = path or self._action_bindings_file()
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, dict) and data.get('actions'):
                self.actions = {a: list(ks) for a, ks in data['actions'].items()}
                # 补新动作 (旧配置缺的新动作用默认)
                for a, ks in DEFAULT_ACTIONS.items():
                    self.actions.setdefault(a, list(ks))
        except Exception:
            self.actions = dict(DEFAULT_ACTIONS)
        # 2026-11-07: 叠加本游戏键位覆盖 (游戏设置.json key_bindings 优先)
        self.apply_game_bindings()

    def save_action_bindings(self, path=None):
        """保存当前动作绑定到 输入配置.json (供改键 UI 调用)."""
        import json as _json
        p = path or self._action_bindings_file()
        tmp = p + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            _json.dump({"actions": self.actions}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    def rebind_action(self, name, keys):
        """重映射动作到一组键名 (如 {'跳跃': ['space','j']})。

        2026-11-07: **同时写进本游戏的 游戏设置.json key_bindings** ——
        打包游戏的玩家改键只影响这个游戏, 不污染引擎 输入配置.json;
        开发环境另存一份到引擎配置便于复用。
        """
        keys = list(keys)
        self.actions[name] = keys
        try:
            import game_settings
            game_settings.write_key_binding(name, keys)
        except Exception as e:
            print('[输入] 写游戏键位失败 (忽略): %r' % (e,))
        try:
            self.save_action_bindings()
        except Exception:
            pass
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

