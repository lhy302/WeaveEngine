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

