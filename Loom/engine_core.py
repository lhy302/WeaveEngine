# -*- coding: utf-8 -*-
"""engine_core.py — **后端无关的引擎内核**（S2：门面收敛 / JVM 模型）。

人类裁决（2026-11-17）：
  「两个VK后端的不一致我的要求是如同JAVA或者Python这样的高级编程语言一样不受到后端的影响，
   用户不管用的是VK后端还是GL后端都用的是完全一样的**事件API**，底层的区别由引擎进行屏蔽。」
  → 收敛形状选 **B**：抽中立内核 EngineCore，两个宿主都只做「宿主 + 后端」。

目标形状：

    EngineCore（本文件）          后端无关：场景/脚本/物理/动画/音频/碰撞/时钟/输入状态/
      │                            相机/变换/射线/插桩/生命周期
      ├── GLEngine(EngineCore,     + ShadowMixin / HudMixin / RenderMixin / ModelGpuMixin /
      │            GL 后端与宿主)     LightingMixin / GlfwWindowMixin   ← 只有这里知道 OpenGL
      └── VkEngine(EngineCore,     + VK 后端与宿主（VkRenderer 调度）
                   VK 后端与宿主)

进度（滚动更新）
----------------
- **S2-1（2026-11-17，本次）**：建立 EngineCore 骨架，把后端无关的 mixin 归位到内核（现 10 个），
  GLEngine 改为 `EngineCore + 6 个 GL 后端/宿主 mixin`。**行为零变化**（无 super() 调用、
  唯一跨 mixin 重名的 `_prof_*` 已由 loom_render._mro_prof 做成 MRO 顺序无关）。
- **S2-2（部分完成，2026-11-17）**：11 个纯数据查询方法（Layer/Tag/查找/SendMessage/设置层标签）
  已从 `GLEngine` 搬进 `loom_scene_query.SceneQueryMixin`（只碰 `self.models`，无 GPU 依赖）。
  剩下待做：`add_model`/`add_material`/`add_light` 等的「数据 vs GPU 上传」拆分，
  以及 `GLEngine.__init__` 里后端无关字段搬进 `EngineCore.__init__`。
- **S2-3（完成 2026-11-17）**：`SceneDriver` 已改为继承 EngineCore（`scene_driver.py:458`）。
- S2-4（待做）：`VkEngine(EngineCore, VkBackend)` 装配，`vk_player` 改用它。

判据（**这是 S2 的验收，不是「方法名对齐」**）：
  同一份脚本 + 同一份场景 + 同一串输入 → 两端事件序列与状态序列**逐条相等**。
  见 tests/test_vk_logic_frame_parity.py（已落地）与 S4 用户视角门（待做）。

纪律：
  · 本文件**不许**出现 moderngl / wgpu / loom_shaders / loom_shadow / loom_render /
    loom_hud / loom_model_gpu / loom_lighting / loom_glfw_window（门会检查）；
  · 后端差异只能出现在 GLEngine / VkEngine 这两侧，**不许**渗回内核。
"""

from loom_camera import CameraMixin
from loom_frame_components import FrameComponentMixin
from loom_input import InputMixin
from loom_logic_thread import LogicThreadMixin
from loom_model_data import ModelDataMixin
from loom_physics import PhysicsMixin
from loom_profiler import ProfilerMixin
from loom_raycast import RaycastMixin
from loom_scene_query import SceneQueryMixin
from loom_transform import TransformMixin


class EngineCore(TransformMixin, PhysicsMixin, InputMixin, CameraMixin,
                 FrameComponentMixin, ProfilerMixin, LogicThreadMixin, RaycastMixin,
                 SceneQueryMixin, ModelDataMixin):
    """后端无关的引擎内核（唯一实现）。

    继承顺序 = 原 GLEngine 里这几个 mixin 的相对顺序（保持不变，便于对拍）。
    后端 mixin（Shadow/Hud/Render/ModelGpu/Lighting/GlfwWindow）**不在这里** ——
    它们在 GLEngine 一侧，将来 VkEngine 用 VK 那套。

    当前（S2-1）本类**还没有自己的 __init__**：字段仍由 GLEngine.__init__ 建立。
    S2-2 会把其中后端无关的部分搬进来。
    """

    # ============ S2-2：后端无关的状态与生命周期（两端同一份） ============
    # 2026-11-17（独立审查抓到的一整类问题）：SceneDriver 继承内核后，共享方法里凡是
    # 「硬引用某个字段」的，在 VK 上都会 AttributeError（set_parent 缺 _bump_struct、
    # select_next_model 缺 current_model_index、_prof_add 缺 _stage_times、raycast 缺
    # _model_aabbs_par……）。根因是这些字段原先只在 GLEngine.__init__ 里建。
    # 现在把它们收进内核的 __init__：**谁能继承内核，谁就有这套字段**。
    #
    # 纪律：本 __init__ **不许**碰任何 GPU 资源（VBO/VAO/纹理/上下文）。
    #       GLEngine 自己仍走它原有的 __init__（不调本方法），所以 GL 行为零变化；
    #       SceneDriver 在 __init__ 开头调 `EngineCore.__init__(self)`。

    def __init__(self):
        # ---- 场景数据 ----
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.active_camera = None
        self.current_model_index = 0
        # ---- 结构版本号（ancestry / SoA / 世界矩阵缓存共用失效源） ----
        self._struct_gen = 0
        self._soa_snap = None
        self._soa_snap_gen = -1
        # ---- 插桩（_profile / _prof_add / _prof_count 的宿主字段） ----
        self._stage_times = {}
        self._stage_calls = {}
        self._stage_frames = 0
        # ---- 逻辑时钟观测面 ----
        from collections import deque as _dq
        self._tps_events = _dq(maxlen=256)
        self._logic_wall_sum = 0.0
        self._logic_dt_sum = 0.0
        self._logic_wall_last = None
        self._logic_paused = False
        self._step_requested = False
        self.is_playing = False
        self._render_world = None
        self._interp = None
        self._clock = None
        self.gravity = -9.8
        # ---- 输入状态（两端同一份初值，见 _init_input_state） ----
        self.key_state = {}
        self._init_input_state()
        # ---- 事件总线（loom_events 的用户 API，原先只有 GL 有） ----
        try:
            from loom_events import EventBus
            self.events = EventBus()
        except Exception:
            self.events = None

    def _bump_struct(self):
        """结构变更计数器（SoA 平面快照 + ancestry 缓存 + 世界矩阵缓存共用失效源）。
        原在 GLEngine（engine.py:211），搬进内核后 SceneDriver 也能用 ——
        否则共享的 set_parent / remove_camera 在 VK 上一调就 AttributeError。
        实例属性守卫：测试桩（__new__ 不跑 __init__）无 _struct_gen 时惰性建。"""
        try:
            self._struct_gen += 1
        except AttributeError:
            self._struct_gen = 1

    # ============ S1：宿主事件入口（**唯一**，后端无感） ============
    # 人类裁决：用户不管用 VK 还是 GL，看到的都是**完全一样的事件 API**。
    # 因此宿主（编辑器 GLFW/Qt、GL 播放器、VK 播放器、打包游戏）只调这三个 handle_*；
    # 「谁把事件喂进来」是宿主的事，不是用户 API 的差异。
    #
    # 分工：
    #   handle_*  = 唯一入口，做「顺序编排」（UI 优先 → 钩子 → 状态更新）
    #   on_*      = 可覆写钩子（编辑器用它吞键/拦退出），默认行为在 handle_* 里

    def handle_key_event(self, ev):
        """键盘事件入口（唯一）。顺序与原 GL 回调一致，**但不完全相同**（独立审查 P2-10）：
        旧 GLFW 回调在 F9/F10 分支里有 `print("[逻辑时钟] …")` 日志，本实现没有
        （统一入口不打印，避免 VK 播放器控制台噪音）。除该日志外顺序逐项一致：

          ① F11 全屏（仅 PRESS，且本实例支持）
          ② F9 暂停 / F10 单步逻辑帧（仅 PRESS）
          ③ UI 焦点元素优先消费（仅 PRESS）
          ④ on_key_event 钩子（编辑器可吞键）
          ⑤ key_state 更新 / Tab 选中下一个物体

        返回 True = 已被消费（调用方不再处理）。
        ev = {type: 'KEYDOWN'/'KEYUP', key: <键常量>, mod: <修饰位>, unicode: str}
        """
        try:
            import pygame as _pg
        except Exception:
            _pg = None
        etype = str(getattr(ev, 'type', '') or '')
        is_press = etype.upper().endswith('DOWN')
        k = getattr(ev, 'key', None)
        if k is None:
            return False

        # ① F11 全屏（引擎层，先于 on_key_event 钩子）
        if (is_press and _pg is not None and k == _pg.K_F11
                and getattr(self, 'allow_fullscreen', False)):
            try:
                self._toggle_fullscreen()
            except Exception:
                pass
            return True

        # ② F9 / F10 逻辑时钟（引擎层）
        if is_press and _pg is not None:
            if k == _pg.K_F9:
                try:
                    self.toggle_logic_paused()
                except Exception:
                    pass
                return True
            if k == _pg.K_F10:
                try:
                    self.step_logic_once()
                except Exception:
                    pass
                return True

        # ③ UI 输入框优先接收（焦点元素消费则跳过后续）
        if is_press:
            ui = getattr(self, 'ui', None)
            if ui is not None:
                try:
                    if ui.dispatch_key(k, getattr(ev, 'mod', 0) or 0):
                        return True
                except Exception:
                    pass

        # ④ on_key_event 钩子（编辑器输入框等可吞掉）
        try:
            if self.on_key_event(ev):
                return True
        except Exception:
            pass

        # ⑤ key_state 更新 / Tab 选中下一个
        ks = getattr(self, 'key_state', None)
        if ks is None:
            ks = self.key_state = {}
        # 2026-11-18（P0-3 步 1）：**总是**记录键码，不再要求键已在 ks 里。
        # 旧实现只更新 key_state 已有的键（= 10 个相机键），于是 W/A/S/D 这类脚本键
        # 从来没进过快照。现在 key_state 是「键码 -> bool」的完整物理键快照。
        if is_press:
            if k == getattr(self, '_key', {}).get('SELECT_NEXT_MODEL'):
                try:
                    self.select_next_model()
                except Exception:
                    pass
            ks[k] = True
        else:
            ks[k] = False
        # 2026-11-18（P0-3 步 1）：统一入口同时更新派生视图 `script_keys`（键名->bool）。
        # 这样「同一个事件 → 同一个可观察结果」不再依赖宿主另外刷一次；GL 的 GLFW
        # 事件泵稍后会用物理键快照覆盖同名项（值相同，不冲突）。
        self._write_script_key(k, is_press)
        return False

    def handle_text_input(self, ev):
        """文本输入入口（唯一）。顺序与 GL 原 char 回调逐行一致：
        ① UI 焦点元素优先（IME 中文进 InputField）② on_text_input 钩子。
        返回 True = 已消费。"""
        text = getattr(ev, 'text', '') or ''
        ui = getattr(self, 'ui', None)
        if ui is not None:
            try:
                if ui.dispatch_text(text):
                    return True
            except Exception:
                pass
        try:
            if self.on_text_input(ev):
                return True
        except Exception:
            pass
        return False

    def handle_quit_request(self):
        """关窗请求入口（唯一）。返回 True = 允许退出。
        与 GL 原 _on_window_close_cb 一致：钩子抛异常也按「允许退出」处理
        （否则窗口关不掉 = 卡死，比丢未保存改动更糟）。"""
        try:
            return bool(self.on_quit_request())
        except Exception:
            return True

    # ============ S2-2：暂停语义（两端同一份） ============
    # GL 原来把 `toggle_logic_paused` 写死依赖自己的 `_ensure_split()`；VK 另有
    # `set_logic_paused`。收敛为：内核提供 `set_logic_paused`（GL 侧实现）+ 通用
    # `toggle_logic_paused`；VK 自己的 `set_logic_paused` 覆盖内核版 → 两端都走同一个
    # `toggle_logic_paused`，返回同一语义。

    def _logic_paused_state(self):
        """当前是否暂停。GL 用 `_logic_paused`，VK 用 `logic_paused` —— 两个名字都认。"""
        return bool(getattr(self, '_logic_paused',
                            getattr(self, 'logic_paused', False)))

    def _ensure_logic_clock(self):
        """拿时钟。GL 走 `_ensure_split()`（会按需建）；其它后端直接用 `_clock`。"""
        fn = getattr(self, '_ensure_split', None)
        if callable(fn):
            return fn()
        return getattr(self, '_clock', None)

    def set_logic_paused(self, paused):
        """暂停/恢复逻辑时钟（GL 侧实现；VK 有同名实现会覆盖本方法）。
        暂停边界：清 accumulator 余量 + 清墙钟锚点 + 插值对齐 + 渲染世界缓存失效。"""
        self._logic_paused = bool(paused)
        if self._logic_paused:
            clk = self._ensure_logic_clock()
            if clk is not None:
                try:
                    clk.reset()
                except Exception:
                    pass
            self._logic_wall_last = None
            it = getattr(self, '_interp', None)
            if it is not None:
                try:
                    it.align()
                except Exception:
                    pass
            self._render_world = None
        return self._logic_paused

    def toggle_logic_paused(self):
        """暂停/恢复逻辑时钟（F9，MC 同款暂停世界 TPS）：渲染帧照跑，逻辑帧冻结。
        分离未开（旧绑死模式）= 无暂停语义（返回 False 不生效）。"""
        if not getattr(self, 'is_playing', False):
            return False
        if self._ensure_logic_clock() is None:
            return False
        self.set_logic_paused(not self._logic_paused_state())
        return self._logic_paused_state()

    # ============ S1：与后端无关的输入状态（两端同一份初值） ============
    # 2026-11-17 实测差异（本模块的门 test_host_event_parity 抓到的）：
    #   GL : engine.py:380-386 建立 _key（动作名→键码）+ key_state（相机 10 键 = False）
    #   VK : scene_driver.py:506 只有 self.key_state = {}，**没有 _key**，快照恒空
    #   → 同一串按键事件喂进去，GL 记上了、VK 记不上；VK 下相机键/脚本按键全失效。
    # 这是「受后端影响」的典型：**事件 API 的初值都不一样**。修法是把初值收进内核。

    _CAMERA_KEYS = ('CAMERA_FORWARD', 'CAMERA_BACKWARD', 'CAMERA_LEFT', 'CAMERA_RIGHT',
                    'CAMERA_UP', 'CAMERA_DOWN', 'LOOK_LEFT', 'LOOK_RIGHT',
                    'LOOK_UP', 'LOOK_DOWN')

    def _init_input_state(self):
        """建立后端无关的输入状态：`_key`（动作名→键码）+ `key_state`（相机键快照）。
        **两端都必须调**（GL 原来在 engine.py:380-386 内联做，VK 侧原来没有）。
        幂等：重复调用不会覆盖已有的键位/状态。"""
        try:
            from loom_input import _KEYMAP, KEY_BINDINGS
        except Exception:
            return
        if not getattr(self, '_key', None):
            try:
                self._key = {name: _KEYMAP[ch] for name, ch in KEY_BINDINGS.items()}
            except Exception:
                self._key = {}
        ks = getattr(self, 'key_state', None)
        if ks is None:
            ks = self.key_state = {}
        for name in self._CAMERA_KEYS:
            k = self._key.get(name)
            if k is not None:
                ks.setdefault(k, False)

    # ============ P0-3 步 1：script_keys 派生（只增不覆盖 + 原地改） ============
    # 键空间：key_state = 键码 -> bool（物理键快照，handle_key_event 写）；
    #         script_keys = 键名 -> bool（is_key/get_action 读）。
    #
    # 为什么「只增不覆盖 + 原地改」（2026-11-18 失败留痕的教训）：
    #   · script_keys 有多个写者（GL 的 GLFW 事件泵、editor 帧头、外部 ctx、测试夹具）→
    #     整表重算会把它们的写入**清空**（实测编辑器 WASD 全失效）；
    #   · 重新绑定 dict → 宿主/测试持有旧引用，写入落到旧字典（实测解锁键轮询全失灵）。
    # 所以这里只做「已知键码/键名 -> 覆盖对应项」，绝不删除、绝不换对象。
    #
    # 本方法只被 **VK 侧**调用（GL 的 script_keys 由事件泵自己写，不经过这里）。
    def _write_script_key(self, code, down):
        """把单个键码的按下/松开写进 `script_keys`（键名->bool）。

        找不到对应键名（不在 _KEYMAP 里的键）就跳过 —— 那些键没有「名字」语义，
        只保留在 key_state（键码）里，供将来 key_pressed 类查询用。
        """
        try:
            from loom_input import _KEYMAP
        except Exception:
            return
        name = _KEYMAP.get(code) if hasattr(_KEYMAP, 'get') else None
        if name is None:
            for _n, _c in _KEYMAP.items():
                if _c == code:
                    name = _n
                    break
        if name is None:
            return
        try:
            sk = self.script_keys
        except Exception:
            sk = self.__dict__.get('_script_keys')
        if not isinstance(sk, dict):
            return
        sk[name] = bool(down)

    def _sync_script_keys_from_state(self):
        """把 key_state 并入 script_keys（返回那个稳定 dict 对象）。"""
        try:
            from loom_input import _KEYMAP
        except Exception:
            return self.__dict__.setdefault('_script_keys', {})
        ks = self.__dict__.get('key_state') or {}
        target = self.__dict__.get('_script_keys')
        if not isinstance(target, dict):
            target = self.__dict__['_script_keys'] = {}
        for name, code in _KEYMAP.items():
            if code in ks:
                target[name] = bool(ks[code])
        # 过渡兼容：老代码/测试仍会往 key_state 里写**键名**（VK 旧语义）。
        # **仅在该键没有键码级信息时生效** —— 有键码就以键码为准（否则一条陈旧的
        # 键名条目会永远覆盖真实状态：实测「松开后再按回锁」失效就是这个 `or` 造成的）。
        for name in _KEYMAP:
            if name in ks and _KEYMAP[name] not in ks:
                target[name] = bool(ks[name])
        return target

    # ---- 可覆写钩子（默认行为在 handle_* 里；编辑器/宿主覆写这三个） ----
    def on_key_event(self, ev):
        """键盘钩子。返回 True = 已消费（不再更新 key_state）。默认不消费。"""
        return False

    def on_text_input(self, ev):
        """文本输入钩子。返回 True = 已消费。默认不消费。"""
        return False

    def on_quit_request(self):
        """退出钩子。返回 True = 允许退出。默认允许。"""
        return True
