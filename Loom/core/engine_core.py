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
  已从 `GLEngine` 搬进 `scene.query.SceneQueryMixin`（只碰 `self.models`，无 GPU 依赖；B2 原 loom_scene_query.py）。
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

import os
import time

import numpy as np

from components.game_object import GameObject   # S2 阶段2: _model_aabbs_par 的缓存键 (_appearance_gen)
from loom_camera import CameraMixin
from components.frame_components import FrameComponentMixin
from loom_input import InputMixin
from loom_logic_thread import LogicThreadMixin
from components.model_data import ModelDataMixin
from physics.physics import PhysicsMixin
from core.profiler import ProfilerMixin
from components.raycast import RaycastMixin
from scene.entities import LightState   # S4: 光源实体（纯数据, 无 GPU 依赖; B2 原 loom_scene_entities.py 归位）
from scene.query import SceneQueryMixin   # B2: 原 loom_scene_query.py 归位
from components.transform import TransformMixin


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

    # ---- 后端能力契约（Q-B7-53-1，2026-11-22）----
    # grid_in_scene_pass：该后端画编辑器网格时是否**已经带上场景深度**。
    #   False = 网格由共享视图层在 plan 之后叠加绘制（VK 现状：叠加层 flush 挂的是
    #           主 pass 深度视图，深度测试与物体遮挡天然成立）；
    #   True  = 网格由后端自己在**场景 pass 内**画进当前场景目标（GL 现状：深度附件
    #           就是刚写完的场景深度，见 render/gl/render.py::_draw_grid_in_scene），
    #           共享视图层据此**不再**重复画一遍。
    # 纪律：两端都**显式**声明（GL 覆写 True，VK 保持本默认 False）—— 不许用
    # 「属性不存在」表达 False。共享视图层（gui/main_window.py::draw、
    # ui/minimal_editor_view.py::_draw_grid）按本属性分支；若靠 hasattr 隐式分支，
    # 就是「不可见分叉」：将来加第三个后端忘了声明会画两遍网格。
    # 门：tests/test_grid_occlusion_parity.py（两端各一遍真窗口 + B1 断言两端显式有值）。
    grid_in_scene_pass = False

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
            from core.events import EventBus
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
        暂停边界：清 accumulator 余量 + 清墙钟锚点 + 渲染世界缓存失效。

        ★Q-B7-46-1（P6-1，2026-11-19 人类裁决「暂停不得跳变」）：暂停分支**不做**
        `_interp.align()`。align() 的语义是「边界强制对齐」= prev←curr + alpha=0
        = 把画面拉到 curr；而暂停**不改任何位姿**，只停时间 —— 所以那一步是纯粹的
        **画面向前跳**：实测（P6 门 ④/⑥）按 F9 的瞬间 GL 画面 == 「正常推进 1 帧」
        的画面（MAE 2.3e-7），而暂停前最后一帧 == 「正常 0 帧」（MAE 2.96e-4）→
        玩家看到画面向前窜一个逻辑帧。VK 的覆盖版 `SceneDriver.set_logic_paused`
        只 `clk.reset()`（不 align、不清 `_render_world`），画面**就地冻结** ——
        那是正确行为（人类裁定 VK 对），GL 去掉这一句即两端同构。
        副产物修复：去掉 align 后，暂停后第一次 F10 的画面真的前进 1 帧（旧实现
        里那一帧已在暂停瞬间预支，F10 首步画面几乎不动）。

        其它 5 处 `align()` 调用点**仍然正确、一行不动**：加载场景
        （loom_model_gpu:298）/ 进出播放（runtime:189、editor:2184/:2306）/
        VK 加载（scene_driver:901）/ 变换失效重抓（loom_transform:197）——
        那些边界的位姿**本身就跳变**了（换场景/换会话/直接改位姿），必须把 prev
        钉到新位姿，否则首帧会从旧位姿插值过来（「第一帧从原点飞过来」）。
        暂停是唯一「位姿不变、只有时间停」的边界，prev 必须保留。

        `_render_world = None` 保留：`clk.reset()` 把 alpha 归 0，缓存的渲染矩阵是
        暂停前那个 alpha 的产物，必须重算。"""
        self._logic_paused = bool(paused)
        if self._logic_paused:
            clk = self._ensure_logic_clock()
            if clk is not None:
                try:
                    clk.reset()
                except Exception:
                    pass
            self._logic_wall_last = None
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

    def _refresh_play_frame_world(self, models):
        """逻辑位姿矩阵（_frame_world）每逻辑帧刷新 —— P-01 的**唯一实现**（GL/VK 共享）。

        P-01（2026-11-07）：播放态每个逻辑帧都必须走一次 compute_world_matrices ——
        它内部 _fw_cache 在「变换对象未变」时直接返回缓存对象（静止帧 ~0ms），只有
        动态帧才真算；同时 _transform_snapshot 会刷新 _soa_snap 供 interp.advance
        翻页。旧实现只在 None/行数不符时赋值，进播放后 _frame_world 与 _soa_snap
        永久冻结（编辑器画面/阴影/碰撞全停在进播放位姿）。

        ★S5（Q-B7-47-1 五阶段·阶段 5）：本段原是 GLEngine._logic_prep 的内联块；
        VK 的 _logic_prep（只算碰撞对，VK 渲染侧每帧自算 f32 矩阵）此前不刷新
        _frame_world -> **VK 编辑器**播放态的逻辑位姿矩阵冻结在进播放位姿（共享
        编辑器代码与测量面读的是同一个 _frame_world）。按「同源不同步」抽成本方法，
        GL _logic_prep 与 VK _logic_prep 调**同一份**（规则 5.5）；GL 数值逐位不变
        （条件/算式/序一字未改，profile 段标签随实现走，GL 记账口径不变）。
        """
        fw = getattr(self, '_frame_world', None)
        if (getattr(self, 'is_playing', False) or fw is None
                or fw.shape[0] != len(models)):
            self._frame_world = self._profile(
                'world_matrices', lambda: self.compute_world_matrices(models))
            return True
        return False

    # ============ 审核 1/3 P1-1 / P1-2（2026-11-21）：脚本派发与天空盒生效源的唯一实现 ============
    # 审核原文（1/3 号审核，Q-B7-52-1 / Q-B7-52-2）：「『同源』在语义层基本达成……
    # 在实现层只达成 5/8；文档的『全部同源修法』是过度声称，且门把剩下的重复制度化了。」
    # 本段把三处**零后端依赖**的重复收进内核（照 _refresh_play_frame_world 先例）：
    #   · _dispatch_fixed_update / _dispatch_late_update —— 修前 GL render/gl/engine.py 与
    #     VK render/vk/driver.py 各一份（有效行 24 vs 21，16 行逐字相同），只碰
    #     self.models / sc._script / inst.on_*（纯脚本派发、零后端依赖）；
    #   · effective_skybox —— 修前两份且**已分叉**（GL 回落只读 _skybox；VK 回落
    #     skybox→_skybox）：一个字段优先级规则两份代码。后端差异（VK 播放器形状多一个
    #     self.skybox 字段）收进钩子 _backend_scene_skybox()。
    # 纪律：本段不碰任何 GPU 资源；后端差异只经钩子表达（JVM 模型第 2 步）。

    def _dispatch_fixed_update(self, fixed_dt):
        """2026-10-18 阶段1档序10 FixedUpdate（语义对齐 Unity FixedUpdate）—— 两端唯一实现。

        在 _logic_frame 的 _run_scripts 之前调用（用户改速度/位置本步物理生效）。
        零开销：基类空实现跳过（未覆盖 on_fixed_update 的脚本不进热路径）。
        异常隔离：打印 + 标记坏脚本（与 _call_collision_cb 一致）。

        ★审核 1/3 P1-1（2026-11-21）：修前本方法在 GL render/gl/engine.py 与
        VK render/vk/driver.py 各有一份（16 行逐字相同，差异只有 docstring 与
        ImportError 处理位置）；纯脚本派发、零后端依赖，门却断言「恰好两份」把这份
        重复**制度化**。现在两端解析到同一函数对象（GLEngine is SceneDriver）。

        ImportError 处理取 **VK 版**（把 `from script.scripts import Script` 提到循环外、
        失败即 return），理由：① 每次派发只查一次 sys.modules（GL 版每个脚本查一次，
        热路径更省）；② 语义等价 —— _Base 只用于 `type(inst).on_x is _Base.on_x` 的
        基类空实现判据，模块不可导入时 GL 版会对每个脚本各 continue 一次，净效果同样是
        「一个都不派发」（异常隔离边界不变：只吞 ImportError）。
        """
        try:
            from script.scripts import Script as _Base
        except ImportError:
            return
        for m in self.models:
            if not m.scripts:
                continue
            for sc in m.scripts:
                inst = getattr(sc, '_script', None)
                if inst is None or getattr(sc, '_script_broken', False):
                    continue
                if type(inst).on_fixed_update is _Base.on_fixed_update:
                    continue   # 基类空实现：跳过
                try:
                    inst.on_fixed_update(fixed_dt)
                except Exception as e:
                    print("[脚本] %s(%s).on_fixed_update 出错: %r"
                          % (m.name, sc.script_id, e))
                    sc._script_broken = True

    def _dispatch_late_update(self, render_dt):
        """2026-10-18 阶段1档序11 LateUpdate（语义对齐 Unity LateUpdate）—— 两端唯一实现。

        在渲染帧 update 之后、UI 渲染之前调用（相机跟随、HUD 同步用）。
        零开销 + 异常隔离语义同 _dispatch_fixed_update（★审核 1/3 P1-1 同批收口：
        修前两端各一份、16 行逐字相同）。
        """
        try:
            from script.scripts import Script as _Base
        except ImportError:
            return
        for m in self.models:
            if not m.scripts:
                continue
            for sc in m.scripts:
                inst = getattr(sc, '_script', None)
                if inst is None or getattr(sc, '_script_broken', False):
                    continue
                if type(inst).on_late_update is _Base.on_late_update:
                    continue   # 基类空实现：跳过
                try:
                    inst.on_late_update(render_dt)
                except Exception as e:
                    print("[脚本] %s(%s).on_late_update 出错: %r"
                          % (m.name, sc.script_id, e))
                    sc._script_broken = True

    def _backend_scene_skybox(self):
        """钩子（后端差异）：**场景级**天空盒字段 —— 默认 = GL 口径（GL 无独立字段）。

        ★审核 1/3 P1-2（2026-11-21）：VK 播放器形状（SceneDriver.load_from_data 写
        self.skybox）比 GL 多一个场景级字段；修前这条差异靠**第二份 effective_skybox**
        表达，而两份已经分叉（GL 只回落 _skybox，VK 回落 skybox→_skybox）。现在判定
        规则只有一份（effective_skybox），字段差异只在这里（JVM 模型第 2 步）。
        GL 不覆写本钩子（默认返回 None → 回落 _skybox，与修前 GL 逐位相同）。
        """
        return None

    def effective_skybox(self):
        """**生效**天空盒: 相机级 (active_camera.skybox) 优先, 否则场景级 —— 两端唯一实现。

        上层（03 号的命令层 / 场景运行期）把"当前相机的天空盒"写到 CameraState.skybox,
        渲染端只读这里，不再各自实现一套优先级（GL/VK 共用同一判定）。
        返回 Cubemap 实例或 None。

        ★审核 1/3 P1-2（2026-11-21）：修前 GL render/gl/engine.py 与 VK
        render/vk/driver.py 各一份**且已分叉**（GL 回落只读 _skybox；VK 回落
        skybox→_skybox）—— 一个字段优先级规则两份代码，S5 声称的「D2 同源修法」
        不成立。现在回落链 = 钩子 _backend_scene_skybox() → _skybox，两端逐位等价：
          · GL ：钩子返回 None → _skybox（与修前 GL 逐位相同）；
          · VK ：钩子返回 self.skybox → 若 None 再 _skybox（与修前 VK 逐位相同；
            SceneDriver 没有 _skybox 字段 → 播放器回落次序不变）。
        取激活相机失败时的告警口径仍是后端差异（GL 走 _warn_sky_once 只报一次、
        VK 每次打印），沿用 RenderMixin._sky_warn 的既有 getattr 回退写法。
        """
        try:
            cam = self.active_camera_object()
        except Exception as e:
            _ow = getattr(self, '_warn_sky_once', None)
            if callable(_ow):
                try:
                    _ow('effective', '取激活相机失败 (%r)' % (e,))
                except Exception:
                    pass
            else:
                print('[驱动] 取激活相机失败 (%r) -> 天空盒回退场景级' % (e,))
            cam = None
        cube = getattr(cam, 'skybox', None) if cam is not None else None
        if cube is not None:
            return cube
        scene = self._backend_scene_skybox()
        if scene is None:
            scene = getattr(self, '_skybox', None)
        return scene

    # ============ S2（Q-B7-47-1 五阶段·阶段 2）：两个「文件放错」的纯方法归位内核 ============
    # 「B 类」方法 = 文件放在 GL 后端 mixin 里、方法体却一行后端（GL/VK）代码都没有的方法。
    #   · _model_aabbs_par —— 原 loom_lighting.LightingMixin，纯 numpy AABB 批量归约
    #     （阴影 VP / 碰撞 / raycast 共享），一行 GL 都没有；
    #   · _update_fps —— 原 loom_hud.HudMixin，纯计时器。
    # 纯搬家，方法体逐字保留（行为零变化）；宿主字段依赖不变（GL 由 GLEngine.__init__ 建）。
    # 注意：被调方 _aabbs_batched 仍在 loom_lighting（同一份纯 numpy 实现，经 self 解析），
    # 本阶段只搬调研点名的这两个方法（一次提交只做一件事）。

    def _model_aabbs_par(self, models, fw=None, visible_only=True):
        """模型世界 AABB (用当帧矩阵), 与 models 下标对齐 (visible_only=False 全量对齐).
        2026-08-15 8 核均摊: 逐模型 get_bounding_box 是 numpy 重活 (高面数球体 = 几万顶点
        批量变换), 池上分块 -> 释放 GIL 真并行; 结果按序拼接, 与逐模型串行逐位一致.
        visible_only=False: 返回全部模型 (含不可见, 下标与 models 对齐) —— 阴影与碰撞
        共享一次包围盒计算用 (阴影再过滤可见).
        组3层3 (2026-08-31): 逐模型 Python 循环改批量化 _aabbs_batched —— 按顶点数
        分组堆叠, 每组一次批量归约 (消每模型 3 次 numpy 调用开销); 每模型仍是同参数
        matmul (k=4 求和序不变) + min/max 纯比较 -> 与逐模型串行逐位一致 (对拍
        aabb_par_check.py). 池路径 (n>=阈值) 分块内同款批量化.
        ★行级缓存层级修正 (2026-09-06 编译版 9FPS 定案): 行级缓存**只在本层**
        (整 fw 查/写, 池分块路径禁用) —— 旧设计把缓存放进 _aabbs_batched, 池分块
        时每个 worker 拿 fw 切片当"整表"判/写: ①切片行数≠缓存行数恒 miss;
        ②多 worker 写回互相覆盖; ③播放态 fw 每帧新对象雪上加霜 → 编译版
        (numpy 全量慢) 恒 miss 26-37ms/帧 9FPS, 源码 numba 快被掩盖。
        现在本层: 缓存命中 (含 fw 值全等) → 直接返回上帧 out (零计算快路径);
        未命中 → 池分块/串行照旧, 算完写回整缓存。行级变化=值比较 (身份无关)。
        LOOM_PROFILE: 阶段名 'aabbs' (shadow_prep 内部大头, 单独观测)."""
        n = len(models)
        if n == 0:
            return []
        _p = os.environ.get('LOOM_PROFILE') == '1'
        if _p:
            t0 = time.time()
        fw = fw if fw is not None else getattr(self, '_frame_world', None)
        fw_ok = (fw is not None and hasattr(fw, 'ndim') and fw.ndim == 3
                 and fw.shape[1:] == (4, 4) and fw.shape[0] == n)
        stamp3 = (getattr(self, '_struct_gen', 0), GameObject._appearance_gen,
                  bool(visible_only))
        # 2026-11-09 (01 号性能 Q7=B/Q8=A): visible_only=True 的**同帧记忆化**。
        # 现场取证 (beta5_p01_pool_gate.py): visible_only=True 不入行级缓存, 每个
        # 调用点全量重算 —— 504 物体实测 15.3 ms/次 且走 8-worker 池; 灯光的
        # shadow_prep / 每盏灯的 AABB 请求都各自触发一次, 是渲染主线程持 GIL 的
        # 最大单点 (逻辑线程因此被饿到 ~10 次/秒调度)。播放态同一个 _frame_world
        # 会被多个 call site 共享 -> 按 (fw 对象本体, n, stamp3, 可见性序列) 记忆化,
        # 命中直接返回上次的 list 本体: 不重算, 数值与首次逐位相同。
        # ★键里持 fw 强引用 (活对象 id 唯一, 不会与后建数组 id 复用)。
        _vis_key = None
        if visible_only and fw_ok:
            _vis_key = tuple(bool(getattr(m, 'visible', True)) for m in models)
            _vc = getattr(self, '_aabb_vis_cache', None)
            if (_vc is not None and _vc[0] is fw and _vc[1] == n
                    and _vc[2] == stamp3 and _vc[3] == _vis_key):
                if _p:
                    self._stage_calls['aabb_vis_hit'] =                         self._stage_calls.get('aabb_vis_hit', 0) + 1
                return _vc[4]
        cache = getattr(self, '_aabb_row_cache', None)
        if (visible_only is False and fw_ok and cache is not None
                and cache[1] == stamp3 and cache[2] == n
                and cache[3] is not None
                and cache[4] is not None and len(cache[4]) == n):
            # 行级复用仅 visible_only=False (全量下标对齐; 播放态 prep 用)。
            # visible_only=True 时 out 长度=可见数与 fw 行数不对齐, 不入缓存
            # (走下方原路径全算, 语义与旧版逐位一致)。
            # 行级变化判定: 值比较 (对象身份无关 — 播放态 fw 每帧新对象)
            changed = np.any(fw != cache[3], axis=(1, 2))
            c_aabbs = cache[4]
        else:
            changed = None
            c_aabbs = None
        pool = getattr(self, '_frame_pool', None)
        use_pool = pool is not None and n >= self._AABB_POOL_THRESHOLD
        if changed is not None:
            # 行级复用路径: 静止行直接抄上帧, 只把 changed 行 (可见的) 送去算
            out = list(c_aabbs)
            dirty = [i for i in range(n) if changed[i]]
            if _p:
                # ★M3 观测量: 脏行占比 (决定池内实际工作量) —— 计数类, 非耗时
                self._stage_calls['aabb_calls'] = self._stage_calls.get('aabb_calls', 0) + 1
                self._stage_calls['aabb_rows'] = self._stage_calls.get('aabb_rows', 0) + n
                self._stage_calls['aabb_dirty'] = self._stage_calls.get('aabb_dirty', 0) + len(dirty)
            # 直通行发布 (2026-09-07): rows_full 与 out 按下标对齐 (值配对, 身份
            # 无关 —— 上帧表行值=上帧 out 行值, list() 浅拷贝不改行值); prev
            # 形状匹配即复用, 免每帧 501 行 Point3D 回填。
            prev = getattr(self, '_aabb_shadow_rows', None)
            prev_ok = (prev is not None and prev.shape == (n, 6)
                       and prev.dtype == np.float64)
            rows_full = prev if prev_ok else np.empty((n, 6), dtype=np.float64)
            if not dirty:
                self._aabb_shadow_rows = rows_full if prev_ok else None
                self._aabb_shadow_gen = ((id(out), n) if prev_ok else None)
                if _p:
                    # ★M3: 原写 'aabbs' 与外层 _profile('aabbs') 重复计数 → 改名
                    self._stage_times['aabbs_inner'] = \
                        self._stage_times.get('aabbs_inner', 0.0) + (time.time() - t0) * 1000.0
                return out
            sub_models = [models[i] for i in dirty]
            sub_fw = fw[dirty]
            if (use_pool and len(dirty) >= self._AABB_POOL_THRESHOLD
                    and len(dirty) >= self._AABB_DIRTY_POOL_MIN):
                d_segs = []                      # 连续段 [(起,止) in dirty 域]
                s0 = 0
                for q in range(1, len(dirty) + 1):
                    if q == len(dirty) or dirty[q] != dirty[q - 1] + 1:
                        d_segs.append((s0, q)); s0 = q
                def _chunk(idx_iter):
                    idxs = list(idx_iter)
                    # dirty 连续段 -> rows_full **位置切片视图** (map_indexed 恒产
                    # range(a,b) 连续块; 块落在单段内时写回零拷贝)。★勿用
                    # rows_full[dirty[a:b]] —— 列表下标是 fancy indexing 产副本,
                    # 写副本即丢行 (跨段块直接走无行表回退 + 出口按需回填)。
                    a, b = idxs[0], idxs[-1] + 1
                    seg = next((s for s in d_segs if s[0] <= a and b <= s[1]), None)
                    if seg is not None:
                        rc = rows_full[seg[0] + a:seg[0] + b]
                        part = self._aabbs_batched([sub_models[i] for i in idxs],
                                                   sub_fw[idxs],
                                                   False, _row_cache=False,
                                                   out_rows=rc)
                    else:
                        part = self._aabbs_batched([sub_models[i] for i in idxs],
                                                   sub_fw[idxs],
                                                   False, _row_cache=False)
                    return part
                part = pool.map_indexed(len(dirty), _chunk, batches_per_thread=2)
                for i, aabb in zip(dirty, part):
                    out[i] = aabb
                # 段未覆盖 (块跨段) 的行: 从 out 回填 (罕见)
                if not any(s[0] == 0 and s[1] == len(dirty) for s in d_segs):
                    for q, i in enumerate(dirty):
                        mn_, mx_ = out[i]
                        rows_full[i, 0] = mn_.x; rows_full[i, 1] = mn_.y
                        rows_full[i, 2] = mn_.z
                        rows_full[i, 3] = mx_.x; rows_full[i, 4] = mx_.y
                        rows_full[i, 5] = mx_.z
            else:
                rc = np.empty((len(dirty), 6), dtype=np.float64)
                part = self._aabbs_batched(sub_models, sub_fw, False,
                                           _row_cache=False, out_rows=rc)
                for i, aabb in zip(dirty, part):
                    out[i] = aabb
                rows_full[dirty] = rc
            if not prev_ok:
                # 首帧无配对上帧表: 静止行从 out 回填 (首帧 changed≈全量, 罕见)
                for j in range(n):
                    if changed[j]:
                        continue
                    mn_, mx_ = out[j]
                    rows_full[j, 0] = mn_.x; rows_full[j, 1] = mn_.y
                    rows_full[j, 2] = mn_.z
                    rows_full[j, 3] = mx_.x; rows_full[j, 4] = mx_.y
                    rows_full[j, 5] = mx_.z
            self._aabb_shadow_rows = rows_full
            self._aabb_shadow_gen = (id(out), n)
            if _p:
                # ★M3: 同上, 避免与外层 _profile('aabbs') 重复计数
                self._stage_times['aabbs_inner'] = \
                    self._stage_times.get('aabbs_inner', 0.0) + (time.time() - t0) * 1000.0
            return out
        if pool is not None and n >= self._AABB_POOL_THRESHOLD:
            if visible_only is False:
                # 行表只在全量对齐路径分发 (visible_only=True 时 sel=可见子集,
                # 按 sel 下标散写会与 models 下标错位 —— 该路径消费者走属性链回退)。
                rows_full = np.empty((n, 6), dtype=np.float64)
                def _chunk(idx_iter):
                    idxs = list(idx_iter)
                    # map_indexed 恒产连续 range(a,b) (parallel._split_bounds), 行表按
                    # 连续切片视图分发, worker 各写互斥段 (与 out 分块拼接同构)。
                    a, b = idxs[0], idxs[-1] + 1
                    return self._aabbs_batched([models[i] for i in idxs],
                                               [fw[i] for i in idxs] if fw is not None else None,
                                               visible_only, _row_cache=False,
                                               out_rows=rows_full[a:b])
            else:
                rows_full = None
                def _chunk(idx_iter):
                    idxs = list(idx_iter)
                    return self._aabbs_batched([models[i] for i in idxs],
                                               [fw[i] for i in idxs] if fw is not None else None,
                                               visible_only, _row_cache=False)
            out = pool.map_indexed(n, _chunk, batches_per_thread=2)
            self._aabb_shadow_rows = rows_full
            self._aabb_shadow_gen = ((id(out), n) if rows_full is not None else None)
        else:
            if visible_only is False:
                rows_full = np.empty((n, 6), dtype=np.float64)
                out = self._aabbs_batched(models, fw, visible_only,
                                          _row_cache=False, out_rows=rows_full)
                self._aabb_shadow_rows = rows_full
                self._aabb_shadow_gen = (id(out), n)
            else:
                out = self._aabbs_batched(models, fw, visible_only,
                                          _row_cache=False)
                self._aabb_shadow_rows = None
                self._aabb_shadow_gen = None
        if fw_ok and visible_only is False:
            self._aabb_row_cache = (None, stamp3, n, fw, out)
        if _vis_key is not None:
            # 记忆化发布 (与 _aabb_row_cache 同层; 只对 visible_only=True 生效)
            self._aabb_vis_cache = (fw, n, stamp3, _vis_key, out)
        if _p:
            # ★M3: 同上, 避免与外层 _profile('aabbs') 重复计数
            self._stage_times['aabbs_inner'] = self._stage_times.get('aabbs_inner', 0.0) \
                + (time.time() - t0) * 1000.0
        return out

    def _update_fps(self):
        """每秒更新一次 FPS + 帧长滑窗统计 (方案一② 帧长方差观测, 2026-09-05):
        _frame_dt deque(120, maxlen 固定=长寿命不换对象, GC 冻结兼容) 记录
        每渲染帧墙钟; std/max 量化"抖不抖" (Panda3D calc_frame_rate_deviation
        同款 chugginess 指标) — 双峰/限帧器抖动从体感变数字.
        FPS 缓冲预画帧跳过 (不虚计 FPS/不污染帧长窗)."""
        if getattr(self, '_preframing', False):
            return
        self.frame_count += 1
        now = time.perf_counter()   # 高精度单调钟 (帧长滑窗; 与帧 dt 同源)
        # 帧长滑窗: deque 持久 (初始化建, 此处只 append; 窗 120 帧 ≈ 高帧率 1-2s)
        fdt = now - self._last_frame_stamp
        self._last_frame_stamp = now
        if 0.0 < fdt < 0.5:            # 滤掉首帧/窗口拖动冻结的伪长帧
            self._frame_dt.append(fdt)
        if now - self.last_time >= 1.0:
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_time = now

