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
- **S2-1（2026-11-17，本次）**：建立 EngineCore 骨架，把 8 个**后端无关** mixin 归位到内核，
  GLEngine 改为 `EngineCore + 6 个 GL 后端/宿主 mixin`。**行为零变化**（无 super() 调用、
  唯一跨 mixin 重名的 `_prof_*` 已由 loom_render._mro_prof 做成 MRO 顺序无关）。
- **S2-2（部分完成，2026-11-17）**：11 个纯数据查询方法（Layer/Tag/查找/SendMessage/设置层标签）
  已从 `GLEngine` 搬进 `loom_scene_query.SceneQueryMixin`（只碰 `self.models`，无 GPU 依赖）。
  剩下待做：`add_model`/`add_material`/`add_light` 等的「数据 vs GPU 上传」拆分，
  以及 `GLEngine.__init__` 里后端无关字段搬进 `EngineCore.__init__`。
- S2-3（待做）：`SceneDriver` 改为继承 EngineCore，逐个删除 VK 侧重复实现（每删一个跑门）。
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
from loom_physics import PhysicsMixin
from loom_profiler import ProfilerMixin
from loom_raycast import RaycastMixin
from loom_scene_query import SceneQueryMixin
from loom_transform import TransformMixin


class EngineCore(TransformMixin, PhysicsMixin, InputMixin, CameraMixin,
                 FrameComponentMixin, ProfilerMixin, LogicThreadMixin, RaycastMixin,
                 SceneQueryMixin):
    """后端无关的引擎内核（唯一实现）。

    继承顺序 = 原 GLEngine 里这几个 mixin 的相对顺序（保持不变，便于对拍）。
    后端 mixin（Shadow/Hud/Render/ModelGpu/Lighting/GlfwWindow）**不在这里** ——
    它们在 GLEngine 一侧，将来 VkEngine 用 VK 那套。

    当前（S2-1）本类**还没有自己的 __init__**：字段仍由 GLEngine.__init__ 建立。
    S2-2 会把其中后端无关的部分搬进来。
    """

    # ============ S1：宿主事件入口（**唯一**，后端无感） ============
    # 人类裁决：用户不管用 VK 还是 GL，看到的都是**完全一样的事件 API**。
    # 因此宿主（编辑器 GLFW/Qt、GL 播放器、VK 播放器、打包游戏）只调这三个 handle_*；
    # 「谁把事件喂进来」是宿主的事，不是用户 API 的差异。
    #
    # 分工：
    #   handle_*  = 唯一入口，做「顺序编排」（UI 优先 → 钩子 → 状态更新）
    #   on_*      = 可覆写钩子（编辑器用它吞键/拦退出），默认行为在 handle_* 里

    def handle_key_event(self, ev):
        """键盘事件入口（唯一）。顺序与 GL 原 GLFW 回调**逐行一致**：

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
        if is_press:
            if k == getattr(self, '_key', {}).get('SELECT_NEXT_MODEL'):
                try:
                    self.select_next_model()
                except Exception:
                    pass
            elif ks is not None and k in ks:
                ks[k] = True
        elif ks is not None and k in ks:
            ks[k] = False
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
