# -*- coding: utf-8 -*-
"""editor/vk_app.py — VK 编辑器装配（目录重构 B4 批，2026-11-21）。

VkEditorApp（S4 建的 VK 编辑器装配，VkEditorApp(_EditorCore, SceneDriver)）
与 _VkGlStateShim（editor.render 帧首 GL 状态复位壳）从原 editor.py 尾段按域
归位到 editor/ 包；类体逐行未动（含 S1/S4 同源再绑定三件套）。
"""
import math
import time

from engine import GLEngine   # 仅取 _dispatch_application_quit 同源再绑定
from render.gl.render import RenderMixin      # S4: 同一份 _apply_main_pass_camera
from render.gl.lighting import LightingMixin  # S4: 同一份 _aabbs_batched（S2 留痕未归位）
from render.vk.driver import SceneDriver      # VK 编辑器装配基类

from editor.core import _EditorCore


class VkEditorApp(_EditorCore, SceneDriver):
    """VK 编辑器（Q-B7-47-1 五阶段·阶段 4，S2 占位落地）。

    装配形状（与 GL 侧 EditorApp(_EditorCore, GLEngine) 对称）：

        VkEditorApp -> _EditorCore（编辑器 140 方法的唯一实现）
                   -> SceneDriver（VK 侧装配：VkWindowMixin + VkEditorRenderMixin + EngineCore）
                   -> EngineCore（后端无关内核）

    本类**只做**：
      ① VK 装配（wgpu device / present 格式 / VkRenderer / overlay 线批设备）；
      ② 5 个 B 类钩子的 VK 侧实现（_backend_upload_lights / _backend_prepare_bucket_frame /
         _backend_parallel_shadow_and_collision 为「VK 渲染器帧内自算」的显式 no-op；
         _backend_execute_frame 由 S3 的 VkEditorRenderMixin 提供；_backend_scene_cleared
         由 SceneDriver 提供）—— 不许在 EngineCore 写同名空实现（反模式 2）；
      ③ 编辑器状态装配走 _EditorCore._init_editor_state（GL/VK 同一份，规则 5.5）。
    同源绑定：_apply_main_pass_camera 直接引用 loom_render.RenderMixin 的同一函数对象
    （纯 Python，零 GL 依赖；test_editor_play_parity 结构锁「主 pass 相机策略只有一份」
    因此继续成立 —— VK 不是第二份实现，是同一份的再绑定）。
    """

    # S1（Q-B7-48-1）：主 pass 相机策略唯一实现在 loom_render.RenderMixin ——
    # SceneDriver 不带 RenderMixin，这里按「同一函数对象再绑定」接入（非复制）。
    _apply_main_pass_camera = RenderMixin._apply_main_pass_camera
    # 点选/AABB 路径（_pick -> _model_aabbs_par -> _aabbs_batched）：S2 留痕的「纯 numpy
    # 归位」未做（_aabbs_batched 仍在 GL 的 LightingMixin）；同一函数对象再绑定接入
    # （纯 Python/numpy，零 GL 依赖），GL 侧一行不动。
    _aabbs_batched = LightingMixin._aabbs_batched
    # 应用退出钩子（Qt closeEvent 派发 on_application_quit）：与 GL 同一函数对象再绑定
    # （纯数据/脚本派发，零 GL 依赖；缺了它 LoomGUI 关窗时打印 AttributeError）。
    _dispatch_application_quit = GLEngine._dispatch_application_quit

    def __init__(self, width=1280, height=800, scene_path=None, view=None,
                 device=None, present_format=None):
        # ① VK 装配参数门（报错可见，不许静默降级 GL）
        if device is None or not present_format:
            raise ValueError(
                'VkEditorApp 需要 wgpu device 与 present_format（VkViewport 注入；'
                ' got device=%r, present_format=%r)' % (device, present_format))
        if view is None:
            raise ValueError(
                'VkEditorApp 需要显式注入 Qt 宿主视图（IEditorView）；MinimalEditorView'
                ' 的叠加层路径直接摸 ctl.ctx.scope（GL 固定功能状态），VK 不支持')
        # ② VK 侧引擎装配（SceneDriver.__init__ -> EngineCore.__init__ 内核状态）
        SceneDriver.__init__(self, data=None)
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        # Qt 宿主模式（与 GL 嵌入式 ctx 模式同语义）：事件由宿主喂、帧由宿主驱动、
        # 不进基类 run() 主循环、不做 GLFW swap（editor.render 尾部按本标记跳过）。
        self._external_ctx = True
        # VK 无异步逻辑线程装配（GL 侧 _logic_async 由 GLEngine 按设置建）——
        # S4 编辑态逐帧同步推进；播放态异步化留 S5 对拍收口（留痕）。
        self._logic_async = False
        # editor.render 帧首 self.ctx.scissor = None 是 GL 固定功能状态复位；
        # VK 无此概念 —— 只给一个可赋值的 no-op 壳（诚实留痕，不假装有 ctx）。
        self.ctx = _VkGlStateShim()
        # FramePlan 的 SCREEN 目标格式 = 真实表面格式（VkFrameExecutor 与
        # vk_renderer.draw_frame 双端按同一 plan 缓存键取同一对象）。GL 不设本属性，
        # frame_plan 缺省 rgba8unorm 逐位不变。
        self._plan_screen_format = present_format
        # ③ 5 个 B 类钩子需要的 VK 宿主字段（VkEditorRenderMixin 宿主协议）：
        #    线批设备/格式（overlay_scope / draw_lines / draw_screen_rect 用）；
        #    _vk_renderer_obj（VkFrameExecutor 转 draw_frame）；_vk_ctx 由 VkViewport
        #    在拿到 rendercanvas 上下文后注入（帧提交用）。
        # ④ 编辑器宿主字段（GLEngine.__init__ 建立、_EditorCore 方法消费；SceneDriver
        # 是播放器字段面 —— pressed/released/修饰键/FPS 滑窗等 Qt 编辑器宿主字段不在其中，
        # 这里按 engine.py 原行同值补齐（初值/类型逐位一致，消费方是同一批 _EditorCore 方法）。
        self.fps = 0                                   # engine.py:386
        self.last_time = time.perf_counter()           # engine.py:385
        self.frame_count = 0                           # engine.py:387
        from collections import deque as _dq_deque
        self._frame_dt = _dq_deque(maxlen=120)         # engine.py:391
        self._last_frame_stamp = time.perf_counter()   # engine.py:396
        self.pressed = set()                           # engine.py:436（Qt 宿主事件桥写入）
        self.released = set()                          # engine.py:437
        self.mouse_wheel = 0                           # engine.py:438
        self.mouse_press_pos = {}                      # engine.py:439
        self.buttons = (0, 0, 0)                       # 编辑器鼠标键 (左,中,右) —— 事件桥写
        self._mods = 0                                 # engine.py:440（键盘修饰键）
        self._fov = math.radians(60.0)                 # engine.py:232（轨道相机垂直 FOV）
        self.skybox = None                             # 场景级天空盒（SceneDriver 语义；种子场景无）
        # ⑤ 5 个 B 类钩子需要的 VK 宿主字段（VkEditorRenderMixin 宿主协议）：
        #    线批设备/格式（overlay_scope / draw_lines / draw_screen_rect 用）；
        #    _vk_renderer_obj（VkFrameExecutor 转 draw_frame）；_vk_ctx 由 VkViewport
        #    在拿到 rendercanvas 上下文后注入（帧提交用）。
        from render.vk.renderer import VkRenderer   # 惰性导入：GL 编辑器进程不拉 VK 渲染器
        self._vk_line_device = device
        self._vk_line_format = present_format
        self._vk_renderer_obj = VkRenderer(device, present_format)
        self._vk_ctx = None
        # ④ 编辑器状态装配（GL/VK 同一份唯一实现）
        self._init_editor_state(scene_path=scene_path, view=view)

    # ---------------- B 类钩子（VK）----------------
    def _backend_upload_lights(self):
        """钩子（VK）：光源上传 no-op —— vk_renderer.draw_frame 每帧
        _pack_light_vps + _pack_scene 自带光源上传（Scene UBO 语义在 VK 侧
        由 f32[352] 参数块承担），无 GL 侧的 uniform 数组/阴影贴图绑定动作。"""
        return None

    def _backend_prepare_bucket_frame(self):
        """钩子（VK）：当帧实例数据准备 no-op —— vk_renderer.draw_frame 帧内
        自做桶重排 + 实例缓冲写入（见 vk_renderer.draw_frame「桶实例偏移」段），
        GL 的 _prepare_bucket_frame 产物（_render_buckets/_bucket_inst）VK 无消费方。"""
        return None

    def _backend_parallel_shadow_and_collision(self, delta_time, with_events=True):
        """钩子（VK）：阴影 prep / 碰撞批5 no-op ——
        · 阴影：VK 的光 VP 与阴影贴图都在 draw_frame 帧内自算（_pack_light_vps /
          _exec_shadow_maps），没有 GL 的「渲染帧 prep 缓存」可供给；
        · 碰撞事件：编辑器 VK 侧 advance_logic -> SceneDriver._logic_frame 内联
          派发（与 VK 播放器同一条路径），渲染帧无二次派发动作。"""
        return None

    def _framebuf_prefetch(self, frame_start):
        """钩子（VK）：FPS 预画缓冲 no-op —— GL 的离屏预取（frame_buffer.py）
        消费 moderngl FBO blit；VK 侧 S4 编辑态逐帧直渲，无预取消费方。"""
        return None

    # ---------------- VK 宿主协议 ----------------
    @property
    def _vk_overlay_depth_view(self):
        """叠加层深度附件视图（宿主协议字段）—— 取当前帧主 pass 深度目标。
        vk_renderer.draw_frame 首帧按物理尺寸懒建 self._depth；主 pass 已跑完
        （editor.render 的 plan 执行在 view.draw 之前）所以叠加层 flush 时必已就绪。"""
        r = self._vk_renderer_obj
        d = getattr(r, '_depth', None)
        return d[1] if d is not None else None


class _VkGlStateShim:
    """editor.render 帧首的 GL 状态复位壳（仅 scissor 一个属性可赋值）。

    VK 没有 GL 固定功能状态；给显式 no-op 壳而不是 None，是为了让共享 render()
    的「self.ctx.scissor = None」一行在两端都成立（GL 真复位 / VK 显式 no-op）。
    """

    scissor = None
