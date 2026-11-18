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

import time

from loom_camera import CameraMixin
from loom_frame_components import FrameComponentMixin
from loom_input import InputMixin
from loom_logic_thread import LogicThreadMixin
from loom_model_data import ModelDataMixin
from loom_physics import PhysicsMixin
from loom_profiler import ProfilerMixin
from loom_raycast import RaycastMixin
from loom_scene_entities import LightState   # S4: 光源实体（纯数据, 无 GPU 依赖）
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
        # 2026-11-18（人类裁决 Q-B7-33-1=B）：UI 派发的**唯一**写者就是这里 ——
        # 所有后端（GL 播放器 / VK 播放器 / 编辑器 / 打包游戏）都把键递到本方法，
        # 宿主不再预喂 UI。旧的「宿主预喂 UI + 内核跳过第③步」双写者标志已删除。
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
    # 2026-11-18（P0-3 **步 2**）：两端都落到这里 —— GL 的 GLFW 泵与 VK 的帧首共用
    # 同一份派生规则（唯一派生实现），_script_keys_dict 负责找到各自的落点。
    def _script_keys_dict(self):
        """拿 script_keys 背后的**稳定 dict**（绝不重新绑定对象）。

        两个后端各有一个落点：
          · GL : script_keys 是普通实例属性（engine.py:417 建立、GLFW 事件泵整表写）；
          · VK : script_keys 是 property（读时派生），真身是 _script_keys。
        先查实例字典里的普通属性（**不走 property**，否则派生会递归），再退回 _script_keys。
        """
        d = self.__dict__.get('script_keys')
        if isinstance(d, dict):
            return d
        d = self.__dict__.get('_script_keys')
        if not isinstance(d, dict):
            d = self.__dict__['_script_keys'] = {}
        return d

    def _write_script_key(self, code, down):
        """把单个键码的按下/松开写进 script_keys（键名->bool）。

        找不到对应键名（不在 _KEYMAP 里的键）就跳过 —— 那些键没有「名字」语义，
        只保留在 key_state（键码）里，供将来 key_pressed 类查询用。

        2026-11-18（P0-3 步 2）：真实键码事件一到，该键名的「直写过渡项」标记立刻失效
        （否则宿主直写的老快照会永远压住物理真相：实测「松开后再按回锁」就是这么坏的）。
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
        sk = self._script_keys_dict()
        direct = self.__dict__.get('_sk_direct')
        if isinstance(direct, set):
            direct.discard(name)
        sk[name] = bool(down)

    def _sync_script_keys_from_state(self):
        """把 key_state 并入 script_keys（返回那个稳定 dict 对象）。

        步 2 的不变量（门 test_input_chain_parity 逐步校验）：

            script_keys ≡ 「key_state 派生结果」∪「键名直写过渡项」

        · 派生结果：key_state 里有的键码，其键名必须同值（key_state 是唯一物理真相）；
        · 直写过渡项：宿主直接 engine.script_keys = {...} 写进来的键名（setter 记进
          _sk_direct）。它们**只在该键没有键码级信息时生效**，且真实键码事件一到就失效
          （见 _write_script_key）—— 老宿主/测试夹具的直写因此仍通到脚本，
          但绝不会盖住物理状态。
        """
        try:
            from loom_input import _KEYMAP
        except Exception:
            return self._script_keys_dict()
        ks = self.__dict__.get('key_state') or {}
        target = self._script_keys_dict()
        direct = self.__dict__.get('_sk_direct')
        if not isinstance(direct, set):
            direct = set()
        for name, code in _KEYMAP.items():
            if code in ks and name not in direct:
                target[name] = bool(ks[code])
        # 过渡兼容：老代码/测试仍会往 key_state 里写**键名**（VK 旧语义）。
        # **仅在该键没有键码级信息时生效** —— 有键码就以键码为准（否则一条陈旧的
        # 键名条目会永远覆盖真实状态：实测「松开后再按回锁」失效就是这个 or 造成的）。
        for name in _KEYMAP:
            if name in ks and _KEYMAP[name] not in ks and name not in direct:
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

    # ==========================================================================
    # S4（2026-11-18）：用户 API —— 两端**同一份实现**，后端差异只经钩子/impl 落地
    # ==========================================================================
    # 人类要求（2026-11-17/18，反复重申）：
    #   「两个后端暴露给用户的 API 都是一样的，选择哪个后端在用户端就是换个配置，
    #     类似于 JVM 虚拟机：不管底层用的什么后端，往上暴露的接口都一样。」
    # 判据不是「差异在缩小」，而是：用户 API 集合两端完全相同，且**是同一个函数对象**
    # （`getattr(GLEngine, n) is getattr(SceneDriver, n)`）。门：tests/test_user_api_parity.py。
    #
    # 分工（写在这里是为了让下一个接手的人不用猜）：
    #   · 公共语义（数据怎么变、什么时候叫后端）→ 本文件，只写一份；
    #   · 后端资源（GL 阴影贴图/桶缓冲；VK 无 GPU 资源）→ `_backend_*` 钩子，**可选**
    #     （后端不定义就跳过，见 _call_backend_hook 的 MRO 说明）；
    #   · 后端装配（场景怎么建、脚本怎么跑）→ `_xxx_impl`，两端各一份。
    #
    # 不许在这里出现 moderngl / wgpu / loom_shaders / loom_shadow / loom_render /
    # loom_hud / loom_model_gpu / loom_lighting / loom_glfw_window（本文件纪律）。

    # ---------------- 光源：数据在两端同一份，资源事交钩子 ----------------
    def add_light(self, kind='directional', position=None, direction=None,
                  color=(1.0, 1.0, 1.0), intensity=1.0, name=None, guid=None,
                  mode='full', shape='circle', size=5.0, shadow=True,
                  azimuth=None, elevation=None, roll=None, range=10.0,
                  spot_inner_angle=30.0, spot_outer_angle=60.0):
        """添加场景光源 (不可见实体, 不渲染网格/不参与拾取). 返回 LightState.
        M29: mode='full'|'beam', shape='circle'|'rect', size=截面尺寸, shadow=是否投射阴影.
        M30: 平行光方向用 azimuth/elevation/roll (度); 旧 direction 向量仍兼容 (自动反算).
        range: 点光影响半径 (对齐 Unity Light.range, 默认 10).
        2026-10-19 序9 聚光灯: kind='spot' 时 spot_inner_angle/outer_angle 生效.

        ★S4（2026-11-18）：**纯数据 + 后端钩子**。建 LightState 与 append 这两步
        两端逐字相同，所以只写在这里；后端要做的资源事走 `_backend_light_added`。
        原 GL 实现（loom_lighting.LightingMixin.add_light）就只有这两步 ——
        语义逐位不变（GL 的阴影贴图是渲染 pass 里惰性建的，add 时无需动作）。
        """
        light = LightState(kind=kind, position=position, direction=direction,
                           color=color, intensity=intensity, name=name, guid=guid,
                           mode=mode, shape=shape, size=size, shadow=shadow,
                           azimuth=azimuth, elevation=elevation, roll=roll,
                           range=range,
                           spot_inner_angle=spot_inner_angle,
                           spot_outer_angle=spot_outer_angle)
        self.lights.append(light)
        self._call_backend_hook('_backend_light_added', light)
        return light

    def remove_light(self, light):
        """从场景移除光源 (释放其阴影贴图).

        ★S4：先给后端一次释放机会（GL 释放该光源的阴影贴图；VK 空操作），再改数据。
        顺序与原 GL 实现逐位一致（先 pop 阴影图，再从 self.lights 摘掉）。
        """
        self._call_backend_hook('_backend_light_removed', light)
        if light in self.lights:
            self.lights.remove(light)

    def _call_backend_hook(self, name, *args):
        """调一个**可选**的 `_backend_*` 钩子；后端没定义就跳过（返回 None）。

        为什么不在 EngineCore 里写"空实现"当默认：GLEngine 的 MRO 是
        `GLEngine → EngineCore → …mixin`，内核里写的同名方法会把 GL mixin 的
        覆盖**遮住**（实测踩过：在核心里加空 _backend_light_removed 之后，
        GL 删光源不再释放阴影贴图 —— 名字都在，功能没了）。所以默认 = 没有这个
        钩子，由后端按需定义（GL 在 loom_lighting / loom_model_gpu，VK 在
        scene_driver）。`_backend_upload_model` 是同一个套路（默认在
        loom_model_data，真实现走 `_build_gpu`）。
        """
        fn = getattr(self, name, None)
        if fn is not None:
            return fn(*args)
        return None

    # ---------------- 场景：数据在两端同一份，资源事交钩子 ----------------
    def remove_model(self, model):
        """删除模型（Q3=A / Unity 语义：仍有子物体 = 连整棵子树一起删）。

        ★S4 收口（2026-11-18）：本方法原只在 GL（loom_model_gpu.remove_model），
        VK 侧有一份**浅删**版本（只从 models 摘除 + 剪 LOD，**不派发 on_destroy**、
        不递归子树）→ 同一份脚本在「清场景 / 换场景 / 删物体」时，GL 收到 on_destroy、
        VK 收不到，而且删父会留下悬空子物体。这是**用户可观察的语义差异**，
        与「两端用户 API 一样」的要求冲突，故收进内核、两端共用一份。
        后端差异只在 `_remove_one_model`（GL 解 GPU 引用 / VK 剪 LOD 候选）。
        """
        if model is None:
            return
        if getattr(model, 'children', None):
            self.remove_subtree(model)
            return
        self._remove_one_model(model)

    def clear_scene(self):
        """清空全部模型 (M16: 新建/加载场景用).

        ★S4：数据面（逐个 remove_model → models/materials/网格顶点缓存清空 →
        current_model_index 归零）两端同一份；后端资源释放走 `_backend_scene_cleared`
        （GL: _release_bucket_resources 释放桶共享 VBO/VAO；VK: 无 GPU 资源）。
        GL 侧原实现逐行照搬到这里，行为零变化。

        ★已知残留差异（本次**不做**，留痕待裁决）：本方法逐模型调 `remove_model`，
        而两端的 remove_model 语义不同 —— GL 版会递归子树并在删节点时派发脚本
        `on_destroy`；VK 版（scene_driver.remove_model）只从 models 摘除 + 剪 LOD
        候选，**不派发 on_destroy**。所以同一份脚本在「清场景/换场景」时，GL 会收到
        on_destroy、VK 不会。要抹平必须改 VK 的 remove_model（既有公共成员，另有
        test_lod_fastpath 等锁着），超出本次「补齐 9 条用户 API」的范围 ——
        已写进交付报告的「未做未核清单」。
        """
        for m in list(self.models):
            self.remove_model(m)
        self.models.clear()
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        self.materials.clear()               # M23: 材质库随场景一起清空
        bb = getattr(self, '_bb_cache', None)
        if bb is not None:
            bb.clear()                       # 网格顶点缓存随场景清空
        self._call_backend_hook('_backend_scene_cleared')   # A2: 后端资源释放
        self.current_model_index = 0

    def remove_subtree(self, root):
        """删除 root 及其全部子孙 (M14: 删除物体/撤销 redo 用).
        2026-08-16 相机物体化: 先脱掉整棵子树上挂的摄像机 (父链完整, 世界不跳),
        再逐个删节点.
        2026-11-07 P-10: 逐节点走 _remove_one_model (不是 remove_model) ——
        避免"父节点再触发一次子树删除"的递归/重复; _remove_one_model 在删父时
        把剩余子物体提升为根, 保证批量/递归矩阵语义一致。

        ★S4：收集子树 / 脱摄像机 / 逐节点删这三段两端完全相同，只写一份；
        逐节点的后端差异（GL 解 GPU 缓冲引用、VK 无 GPU）在各自的
        `_remove_one_model` 里。GL 侧原实现逐行照搬到这里。
        """
        sub = list(self.collect_subtree(root))
        for m in sub:
            for cam in list(getattr(m, 'camera_children', [])):
                self.set_camera_parent(cam, None, preserve_world=True)
        for m in sub:
            self._remove_one_model(m)

    def load_scene(self, path):
        """M37/M38: 运行时切换到另一个场景文件 (Unity SceneManager.LoadScene 式).
        清空当前场景 + 加载新场景 (物体/光源/摄像机/材质). 支持明文 JSON 与
        混淆场景 (LOOMSC1, 自动解密). 返回是否成功.

        ★S4：公共段（读文件 → 判类型 → 交给后端装配）只写一份；装配走
        `_load_scene_data(data, base_dir)`：
          · GL ：sceneio.scene_from_dict（原 load_scene 的现有路径，逐位不变）；
          · VK ：SceneDriver.load_from_data（它已有的装配路径）。
        base_dir = 场景文件目录。**两端都按它解析相对资源**（天空盒六面图 / 材质贴图 /
        资产 guid 的探测根）：VK 走 SceneDriver.load_from_data(base_dir=...)；GL 走
        loom_model_gpu._load_scene_data(data, base_dir) -> sceneio.scene_from_dict(base_dir=...)。
        （B7-16 的 R7 之前 GL 侧故意忽略该参数 —— 从别的 CWD 启动时按 CWD 找图失败、VK 按
        场景目录成功，两端分叉；现在两端一致。门：test_scene_load_parity ⑥-1..11。）
        """
        try:
            import sceneio as _sio
        except Exception as e:
            print('[场景] 场景 IO 不可用 (%r) -> load_scene 失败' % (e,))
            return False
        data = _sio.load_scene_data(path)
        if not isinstance(data, dict):
            return False
        try:
            import os as _os
            base_dir = _os.path.dirname(_os.path.abspath(path))
        except Exception:
            base_dir = None
        return bool(self._load_scene_data(data, base_dir))

    # ---------------- 逻辑时钟观测面（TPS / 体检比值 / 单步） ----------------
    def _tps_sample(self):
        """记一个逻辑帧时间戳 (TPS 实测滑动窗口, 2 秒).

        ★S4：原来只有 GL 的 `_run_scripts` 里内联这几行，VK 侧**从不记** ——
        `get_tps()` 在 VK 上恒 0（等于假实现）。现在收成一份，由公共
        `update_scripts` 在每个逻辑帧记一次（两端同源）。
        """
        # 实例属性守卫：测试桩（__new__ 不跑 __init__）没有 _tps_events 时惰性建
        # （与 _bump_struct / _script_keys_dict 同款）。不写死 self._tps_events 是
        # 因为 update_scripts 是**公共入口**，桩也会直调它（test_scripts /
        # test_add_script_cache 就是这么用的）。
        ev = getattr(self, '_tps_events', None)
        if ev is None:
            ev = self._tps_events = []
        now = time.time()
        ev.append(now)
        cutoff = now - 2.0
        while ev and ev[0] < cutoff:
            # 2026-11-18 实机点验 P0：EngineCore.__init__ 建的是 deque(maxlen=256)，
            # 而 deque.pop() **不接受参数** —— 原来写 ev.pop(0) 会在「窗口超过 2 秒」时
            # 抛 TypeError，把整个渲染循环打挂（VK 播放器跑几百帧必崩）。
            # list / deque 两种容器都要能裁：deque 用 popleft，list 用 pop(0)。
            if hasattr(ev, 'popleft'):
                ev.popleft()
            else:
                ev.pop(0)

    def get_tps(self):
        """实测 TPS (逻辑帧/秒, 2 秒滑动窗口; 状态栏直读). 暂停时 → 0."""
        ev = getattr(self, '_tps_events', None)
        if not ev:
            return 0.0
        now = time.time()
        n = len(ev)
        span = now - ev[0]
        if span <= 0.01:
            return 0.0
        return n / span

    def _logic_ratio_tick(self, render_dt, clk=None, floor=True):
        """记一次逻辑时钟体检样本，返回 (dt_eff, wall_dt)。

        dt_eff = 本次**喂给时钟**的逻辑时间；wall_dt = 本次真实墙钟间隔。
        get_logic_time_ratio() = Σdt_eff / Σwall_dt（1.0 = 时钟没被 dt 口径亏欠）。

        · floor=True （GL 口径，engine._clock_advance 用）：
          dt_eff = max(调用方 dt, 实测墙钟) —— 与旧实现逐位一致；
        · floor=False（VK 口径，SceneDriver.advance_logic 用）：
          VK 喂给时钟的就是宿主给的 render_dt，所以如实记 render_dt
          （比值可能 <1，那正是「宿主 dt 口径比真实帧长小」的信号）。
          VK 这条路径**不动时钟推进语义**，只做体检记账。

        ★S4：这两个字段原先只有 GL 的 _clock_advance 在累加，VK 恒 None。
        """
        now = time.perf_counter()
        last = getattr(self, '_logic_wall_last', None)
        wall_dt = 0.0 if last is None else (now - last)
        if wall_dt < 0.0:
            wall_dt = 0.0
        self._logic_wall_last = now
        if clk is not None:
            # 单帧墙钟按 maximum_logic_delta 截断 (与时钟内部死亡螺旋保险同口径)
            wall_dt = min(wall_dt, clk.maximum_logic_delta)
        if render_dt is None:
            dt_in = wall_dt
        else:
            try:
                dt_in = float(render_dt)
            except (TypeError, ValueError):
                dt_in = wall_dt
        dt_eff = max(dt_in, wall_dt) if floor else dt_in
        self._logic_dt_sum = getattr(self, '_logic_dt_sum', 0.0) + dt_eff
        self._logic_wall_sum = getattr(self, '_logic_wall_sum', 0.0) + wall_dt
        return dt_eff, wall_dt

    def get_logic_time_ratio(self):
        """逻辑时钟拿到的时间 / 真实墙钟 (1.0 = 时钟没被 dt 口径亏欠)。

        2026-11-09 E1 (beta5) 体检口, 配合 get_tps() 用:
          · ratio ≈ 1 且 TPS < 目标 → 瓶颈是**每个逻辑帧本身太贵**
            (看 _stage_times 的 logic_step / pipe_wait);
          · GL 侧 ratio 恒 >= 1（_clock_advance 取 max(调用方 dt, 实测墙钟)，
            ratio<1 结构性不可能）；VK 侧如实记宿主 dt，可能 <1（见
            _logic_ratio_tick 的两种口径）。
        返回 None = 还没采到样本。
        """
        wall = getattr(self, '_logic_wall_sum', 0.0)
        if wall <= 1e-9:
            return None
        return getattr(self, '_logic_dt_sum', 0.0) / wall

    def step_logic_once(self):
        """步进 1 逻辑帧 (F10, MC 同款): 仅暂停态生效 — 置请求标志,
        下一渲染帧 advance_logic 消费 (恰好 1 逻辑帧后继续冻结).

        ★S4：VK 的 advance_logic 现在**真的消费** `_step_requested`
        （暂停分支里走 clk.step_once() = 恰好 1 个逻辑帧）。原来 VK 只认
        logic_paused、根本不看这个标志 —— 同一次 F10 在 VK 上什么都不发生。
        """
        if not self._logic_paused_state():
            return False
        self._step_requested = True
        return True

    # ---------------- 脚本推进入口（薄封装，实现交后端） ----------------
    def update_scripts(self, delta_time):
        """播放期每帧调用: 遍历物体上所有脚本组件 (M25: 可多个), 惰性实例化并 update.

        ★S4：本方法是**薄封装** —— 先记一个 TPS 样本（每个逻辑帧恰好一次，
        两端同源），再交给后端的 `_update_scripts_impl`：
          · GL ：engine.GLEngine._update_scripts_impl（C 批处理 rotate + 通用 update，
                 含解锁键轮询）；
          · VK ：scene_driver.SceneDriver._update_scripts_impl（同语义，纯 Python）。
        这样 `GLEngine.update_scripts is SceneDriver.update_scripts` 成立（同一个
        函数对象），而两端脚本调度的实现差异收在各自的 impl 里。
        """
        self._tps_sample()
        return self._update_scripts_impl(delta_time)
