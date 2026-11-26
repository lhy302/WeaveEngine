# -*- coding: utf-8 -*-
"""
editor.py — EditorApp: 3D 游戏引擎编辑器 (Unity/Godot 风格)

布局:
  工具栏(顶部 36px) | 层级面板(左 220px) | 属性检查器(右 280px) | 状态栏(底部 24px) | 视口(中央)
功能 (M7): 布局骨架 + 对象层级点击选中 + 检查器变换编辑 (位置/旋转/缩放)
后续里程碑: M8 射线拾取, M9 平移 gizmo, M10 旋转 gizmo, M11 轨道相机交互, M12 序列化
"""
import math
import json
import os
import time

# 2026-10-19 启动日志开关: 屏蔽 pygame "Hello from the pygame community" 横幅
# 必须在 import pygame 之前设置（pygame 导入时读一次）
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import numpy as np
import pygame
import moderngl

# 2026-11-10 阶段 2A: 与播放器共用同一份 FramePlan 描述（S0-S2）
from render.contract.frame_plan import frame_plan
from render.contract.post import post_enabled   # 2B2: LOOM_POST=0 走旧路径

from engine import (GLEngine, Point3D, LightState, CameraState, wrap_deg,
                    gc_play_enter, gc_play_exit)
from core.engine_core import EngineCore     # S2 阶段2: _EditorCore 的内核底座（后端无关）
# 2026-11-21 B7-28: 滚轮判据与 GL/VK 播放器同源 —— loom_ui_input 是 P3-1 抽出的
# 唯一实现（编辑器不许另写一份判据，开发要求 §5.5「同源不同步」反模式）。
from loom_ui_input import wheel_consumed_by_ui, wheel_taken_by_scrollview
from render.gl.render import RenderMixin  # S4: VkEditorApp 绑定 GL 同一份 _apply_main_pass_camera（同源唯一实现）
from render.gl.lighting import LightingMixin  # S4: VkEditorApp 绑定 GL 同一份 _aabbs_batched（S2 留痕的纯 numpy 归位未做）
from render.vk.driver import SceneDriver # S4: VK 编辑器装配基类（VkEditorApp(_EditorCore, SceneDriver)）
from mathlib.matlib import (mat4_perspective, mat4_ortho, mat4_rotation, mat4_scale,
                    mat4_translation, mat4_view_yaw_pitch, decompose_euler)
from mathlib.mesh import create_cube, create_plane, create_sphere, spec_to_mesh
# 2026-10-18 选项1: from gui import GUI 已删（EditorApp 零依赖 MinimalEditorView 兜底路径
# 已随 pygame 窗口剥离一起删除；gui.py 本身保留供 tests 使用）。
# 2026-08-28: 默认视图不再引用 ui.loom_gui (Qt 视图需 QApplication, 由入口
# run_loom_gui 创建后显式注入); EditorApp 默认为零依赖 MinimalEditorView 兜底
# B4: undo.py -> editor/undo/ 包（Loom/undo.py 门面保仓外旧名）
from editor.undo import (UndoManager, Command, StateCommand, AddObjectCommand,
                  DeleteObjectCommand, ReparentCommand, DuplicateObjectCommand,
                  PrefabPlaceCommand, snapshot as undo_snapshot,
                  apply_snapshot,
                  LightStateCommand, AddLightCommand, DeleteLightCommand,
                  AddMaterialCommand, light_snapshot, apply_light_snapshot,
                  CameraStateCommand, AddCameraCommand, DeleteCameraCommand,
                  ReparentCameraCommand,
                  camera_snapshot, apply_camera_snapshot)
import sceneio
import filedialog

# ================ 文件对话框/默认保存目录 (M19) ================
# Q-B7-38-1 第 9 批：常量/纯工具函数的**唯一真源**拆到 editor/core_contract.py
# （契约/常量单点，规则 1 例外），本文件按名绑定 import —— editor.core.STATE_FILE /
# DEFAULT_SAVE_DIR / _LEGACY_SAVE_DIR / APP_DIR / _SCENE_FILTER 的读与 monkeypatch
# 语义逐位不变（消费点全在本模块的方法/函数里，patch editor.core.X 仍生效）。
from editor.core_contract import (APP_DIR, DEFAULT_SAVE_DIR, _LEGACY_SAVE_DIR,
                                  STATE_FILE, _SCENE_FILTER, _PREFAB_FILTER,
                                  unique_default_name)

def load_last_dir(state_file=None):
    """读上次保存目录 (不存在/失效返回 None). state_file=None 用当前模块
    STATE_FILE (允许测试 patch editor.STATE_FILE 指向临时文件而不污染真实)."""
    if state_file is None:
        state_file = STATE_FILE
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            d = json.load(f)
        p = d.get('last_dir')
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass
    return None

def save_last_dir(state_file, path):
    """记录用户这次保存/打开的目录, 下次默认优先打开这里.
    (2026-08-18) 同时记录 last_scene 完整路径 —— 无 --open 启动时自动恢复上次
    场景 (否则每次都是种子场景, 保存永远弹另存为, 旧文件被避让成 场景1.json)."""
    if not path:
        return
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        return
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump({'last_dir': d, 'last_scene': path}, f, ensure_ascii=False)
    except Exception:
        pass

def load_last_scene(state_file=None):
    """读上次保存/打开的场景完整路径 (不存在/失效返回 None). 旧 state 文件无
    last_scene 字段时返回 None (行为与过去一致: 不自动恢复)."""
    if state_file is None:
        state_file = STATE_FILE
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            d = json.load(f)
        p = d.get('last_scene')
        # 2026-08-20 安全加固 (Qoder 报告提示9): 仅接受 .json 场景文件
        if p and os.path.isfile(p) and p.lower().endswith('.json'):
            return p
    except Exception:
        pass
    return None

def initial_dir(last_dir):
    """保存/打开对话框的初始目录: 上次目录优先, 否则默认 'Projects' 文件夹."""
    if last_dir and os.path.isdir(last_dir):
        return last_dir
    return DEFAULT_SAVE_DIR

# 两个相机撤销命令类（Q-B7-38-1 第 9 批搬到 core_commands.py，此处按名 re-export）
from editor.core_commands import (_CameraProjCommand, _OrbitViewCommand)

def _editor_skybox_provider(engine, cmd):
    """FramePlan 的 skybox 绘制源（编辑器版）：保持迁移前「失败每帧打印一行」的语义。"""
    try:
        engine._draw_skybox()
    except Exception as _e:
        print('[渲染] 天空盒绘制失败: %r' % (_e,))

# ---- 能力域 mixin（Q-B7-38-1 第 9 批；纯搬迁，装配顺序 = 下方基类顺序）----
from editor.core_commands import EditorUndoBridgeMixin
from editor.core_viewport import EditorViewportMixin
from editor.core_selection import EditorSelectionMixin
from editor.core_gizmo import EditorGizmoMixin
from editor.core_camera import EditorCameraMixin

class _EditorCore(EngineCore, EditorUndoBridgeMixin, EditorViewportMixin, EditorSelectionMixin, EditorGizmoMixin, EditorCameraMixin):
    # S5（Q-B7-47-1 五阶段·阶段 5）：编辑器形状标记 —— 渲染帧尾的 LateUpdate 由本类
    # 共享的 editor.render 派发（GL 引擎的 advance_logic 从不派发 LateUpdate）。
    # VK 的 SceneDriver.advance_logic 会在渲染帧尾派发一次（VK 播放器形状没有渲染帧
    # 派发点，必须保持原样）；编辑器形状经本标记让它跳过，否则 VK 编辑器播放态每帧
    # on_late_update **双发**（S5 门 ③ 组修前红：['start','update','late','late']）。
    _render_dispatches_late = True
    # 同族的「编辑器形状」标记：SceneDriver.advance_logic 的编辑态零逻辑门（S5）用它
    # 区分形状 —— 裸 SceneDriver（VK 播放器内核/既有 VK 侧测试直驱）**不看 is_playing、
    # 恒推进逻辑**（生产行为与既有测试契约）；只有编辑器形状（本类）的编辑态
    # （is_playing=False）才零逻辑（与 GL advance_logic 第一分支同语义）。
    _editor_shape = True

    """S2（Q-B7-47-1 五阶段·阶段 2）：编辑器能力的**中间基类**（后端无关）。

    原 EditorApp 类体（除 __init__ 外的全部编辑器方法/类属性）**原样搬入本类，
    一行不改**（纯搬家，行为零变化）—— MRO 探针与 R6 门（test_editor_field_alias.py ④）
    已验证装配形状：

        EditorApp(_EditorCore, GLEngine)      # GL 编辑器（本文件下方，现有入口）
        EditorApp → _EditorCore → GLEngine → EngineCore → …内核 mixin… → …GL mixin…

    本类**无自己的 __init__**：EditorApp.__init__ 的 super().__init__(w,h,ctx=ctx)
    直落 GLEngine.__init__，GL 装配逐位不变。
    （VK 编辑器占位：S4 建 `VkEditorApp(_EditorCore, SceneDriver)`，本阶段不写实现。）
    """
# 本文件（Q-B7-38-1 第 9 批，agent-99）已按能力域拆分：_EditorCore 的方法体
# 分散在 editor/core_<域>.py 的 mixin（selection / gizmo / camera / object / inspector /
# asset / scene / playback / viewport / commands），本文件只保留三件事——
#
#   ① 装配：class _EditorCore(EngineCore, <各域 mixin>) —— EngineCore 必须是**第一个**基类
#      （引擎能力契约 grid_in_scene_pass 等来自它）；各域 mixin 排在其后，两个理由：
#      (a) EngineCore 的能力属性不被任何 mixin 遮蔽（GLEngine 的 MRO 教训）；
#      (b) VkEditorApp / EditorApp 的 MRO 前三位保持不变
#          （VkEditorApp → _EditorCore → SceneDriver / EditorApp → _EditorCore → GLEngine）。
#   ② 模块级常量与工具函数（文件对话框记忆 M19）：APP_DIR / DEFAULT_SAVE_DIR /
#      _LEGACY_SAVE_DIR / STATE_FILE / _SCENE_FILTER / unique_default_name / load_last_dir /
#      save_last_dir / load_last_scene / initial_dir —— 它们是**仓内 monkeypatch 目标**
#      （tests 直接写 editor.core.STATE_FILE / .DEFAULT_SAVE_DIR / .save_last_dir /
#      .apply_snapshot / .frame_plan），消费点必须在**本模块全局**里解析，故定义留在本文件
#      （常量本体唯一真源在 editor/core_contract.py，本文件按名绑定 import）。
#   ③ 测试源码契约锁定的成员（不可迁移；逐条理由见 KEEP 表 / 下方注释）：render /
#      _prepare_main_pass / _after_pass_prof / toggle_play / _save_scene / _load_scene /
#      choose_* / _update_camera / _dispatch_ui_mouse / _draw_selection_box /
#      on_key_event / on_text_input / on_quit_request / _init_editor_state。

    def _seed_scene(self):
        """默认场景: 地面平面 + 立方体 + 球体 (尺寸对齐 Unity 默认: 10/1/0.5)"""
        plane = create_plane(10.0, 10.0); plane.primitive = 'plane'
        self.add_model(plane, Point3D(0, 0, 0), Point3D(0, 0, 0), normal_mode='flat', name='平面',
                       scale=(1, 1, 1))
        cube = create_cube(1.0); cube.primitive = 'cube'
        self.add_model(cube, Point3D(1.2, 0.5, 0.3), Point3D(0, 0, 0), normal_mode='flat', name='立方体',
                       color='#FF5555')
        sphere = create_sphere(0.5, stacks=14, slices=28); sphere.primitive = 'sphere'
        self.add_model(sphere,
                       Point3D(-1.5, 0.5, 0.5), Point3D(0, 0, 0), normal_mode='vertex', name='球体')
        self.selected_index = 1   # 默认选中立方体

    def _dispatch_ui_mouse(self):
        """2026-10-18 阶段2 (决策3=B): UI 鼠标事件分发 + ui_consumed 标记.

        UI 命中并消费的点击, 在 3D 拾取 (_update_gizmo) 与相机控制 (_update_camera)
        中通过 self.ui_consumed 检查而跳过. 每帧开头调一次.
        """
        ui = getattr(self, 'ui', None)
        if ui is None:
            self.ui_consumed = False
            return
        # pressed/released 是「本帧新按下/松开」, 每帧事件处理后被清空
        pos = getattr(self, 'mouse_pos', (0, 0))
        pressed = set(getattr(self, 'pressed', ()))
        released = set(getattr(self, 'released', ()))
        # 2026-11-21 B7-28: 本帧滚轮也要交给 UI（此前漏传, 编辑器里 ScrollView
        # 滚轮滚不动）。Qt 宿主 wheelEvent 给的是 angleDelta/120, 保留浮点不取整,
        # ScrollView 平滑滚动语义不变（GL 播放器 GLFW 事件本就是整数）。
        wheel = getattr(self, 'mouse_wheel', 0) or 0
        # B7-28: 滚轮专属判据必须在 dispatch **之前**取 —— dispatch 会改
        # ScrollView.scroll_pos（与 runtime.P3-1 / vk_ui.begin_frame 同一时序约束）。
        wheel_taken = bool(wheel) and wheel_taken_by_scrollview(ui, pos)
        consumed = False
        try:
            consumed = bool(ui.dispatch_mouse(pos, pressed, released, wheel))
        except Exception:
            consumed = False
        # hover-only 更新 (按钮悬停效果, 无点击时)
        if not consumed:
            try:
                ui.update_hover_only(pos)
            except Exception:
                pass
        # B7-28 (P-09 组合规则, 唯一实现 wheel_consumed_by_ui, 与 GL/VK 播放器同源):
        # 只有「滚轮本身被 ScrollView 吃掉」才清 self.mouse_wheel —— 相机/脚本
        # 不再看到它; 同帧「点按钮 + 滚轮」consumed=True 但 wheel_taken=False,
        # 滚轮照给相机/脚本（不许用整帧 consumed 把滚轮连坐丢掉）。
        if wheel_consumed_by_ui(wheel, consumed, wheel_taken):
            self.mouse_wheel = 0
        self.ui_consumed = consumed

    # ================ 工具栏 ================
    def _add_primitive(self, typ):
        """添加基元物体 (可撤销).

        2026-10-19 P0-3: 返回创建的 model（原来返回 None，导致命令层拿不到 guid，
        只能盲猜 models[-1]，并发/撤销后必错）。
        """
        if self.is_playing:
            return None
        from mathlib.mesh import create_cube, create_plane, create_sphere
        # 基元尺寸对齐 Unity 默认 (2026-10-13): Cube 边长 1 / Sphere 半径 0.5
        # (直径 1) / Plane 10x10 —— 同一操作序列在两引擎得到同尺寸物体。
        mesh = {'cube': create_cube(1.0), 'sphere': create_sphere(0.5),
                'plane': create_plane(10.0, 10.0)}[typ]
        mesh.primitive = typ
        name = {'cube': '立方体', 'sphere': '球体', 'plane': '平面'}[typ]
        color = {'cube': '#55FF55', 'sphere': None, 'plane': '#888888'}[typ]
        n = len(self.models)
        m = self.undo.push(AddObjectCommand(
            "添加%s" % typ, self, mesh, Point3D(0, 1.0, 0), Point3D(0, 0, 0),
            normal_mode='flat' if typ != 'sphere' else 'vertex',
            name="%s%d" % (name, n + 1), color=color)).model
        self._select_model(len(self.models) - 1)   # 2026-08-15: 清光源/摄像机选中
        return m

    def _import_obj(self, path=None):
        """M36: 文件对话框选 .obj -> 加载网格放入场景 (可撤销). obj 文件路径随场景
        序列化 (换机失效时加载兜底立方体).
        path: 直接给路径则跳过文件对话框 —— 命令行 (EAI import_obj) 与自动化
        测试走这条, 与 GUI 共用之后的全部导入逻辑 (2026-08-27)."""
        if self.is_playing:
            return
        if not path:
            path = filedialog.open_file(
                "导入 .obj 模型", filter_str="Wavefront OBJ (*.obj)\0*.obj\0所有文件 (*.*)\0*.*\0")
        if not path:
            return
        try:
            from mathlib.mesh import load_obj
            mesh = load_obj(path)
        except ValueError as e:
            self._notify("导入失败: %s" % e, (235, 90, 90))
            return
        t = self.camera_target
        pos = Point3D(t[0], 0.0, t[1])        # 放视口中心地面
        n = len(self.models)
        # 2026-08-28: rotation_speed 玩具自转链已整体移除 (原 2026-08-21 修复的
        # "误传 (1,1,1) 导入即自转" 问题随机制废除), 新导入静止
        m = self.undo.push(AddObjectCommand(
            "导入模型", self, mesh, pos, Point3D(0, 0, 0),
            normal_mode='flat', name="模型%d" % (n + 1))).model
        # 2026-08-21: 导入后自动适配相机距离 —— 大模型 (>相机距离) 会"贴脸/钻进
        # 模型内部"满屏暗墙, 看起来像"没显示" (用户实测; 保存重进的显示其实是
        # 相机被拖远后的错觉, 保存无副作用). 公式含"目标点到模型中心偏移":
        # 模型放 target 地面但中心可能离 target 很远 (假车库中心偏 ~6.6m).
        import math
        mn = [min(v[i] for v in mesh.vertices) for i in range(3)]
        mx = [max(v[i] for v in mesh.vertices) for i in range(3)]
        dia = max(mx[i] - mn[i] for i in range(3))
        if dia > 0:
            cx = pos.x + (mn[0] + mx[0]) * 0.5
            cy = pos.y + (mn[1] + mx[1]) * 0.5
            cz = pos.z + (mn[2] + mx[2]) * 0.5
            offset = math.sqrt((cx - self.camera_target[0]) ** 2
                               + (cy - self.camera_target[1]) ** 2
                               + (cz - self.camera_target[2]) ** 2)
            fit = offset + dia / (2.0 * math.tan(self._fov / 2.0)) * 1.35
            if fit > self.camera_distance:
                self.camera_distance = fit
        self._select_model(len(self.models) - 1)   # 2026-08-15: 清光源/摄像机选中
        self._notify("已导入 %s" % os.path.basename(path))

    # ================ 光源管理 (M21) ================
    def _add_light(self, kind):
        """添加场景光源 (可撤销). kind: 'directional' | 'point' | 'spot' (兼容 'dir')."""
        if self.is_playing:
            return
        # 归一化: 命令层用 'dir' 简写, LightState 认 'directional' —
        # 不归一化会导致 kind 误判 (名字显示"点光源"但实际按平行光渲染)
        # 2026-10-19 第1档序9: 加 'spot' 聚光灯 (kind 三态 dir/point/spot)
        if kind in ('dir', 'directional'):
            kind = 'directional'
        elif kind == 'spot':
            kind = 'spot'
        else:
            kind = 'point'
        cmd = self.undo.push(AddLightCommand("添加光源", self, kind))
        self.selected_light_index = len(self.lights) - 1
        self.selected_index = -1
        return cmd.light

    def _delete_light(self):
        """删除当前选中的光源 (可撤销)"""
        light = self._selected_light()
        if light is None:
            return
        self.undo.push(DeleteLightCommand("删除光源", self, light))
        self.selected_light_index = min(self.selected_light_index,
                                        max(-1, len(self.lights) - 1))
        if len(self.lights) == 0:
            self.selected_light_index = -1

    # ================ 摄像机管理 (Unity Camera) ================
    def _add_camera(self):
        """添加场景摄像机 (可撤销). 玩家视角 = active_camera."""
        if self.is_playing:
            return
        n = len(self.cameras) + 1
        cmd = self.undo.push(AddCameraCommand(
            "添加摄像机", self, position=(0, 1, -10), name="摄像机%d" % n))
        self.selected_camera_index = len(self.cameras) - 1
        self.selected_light_index = -1
        self.selected_index = -1
        return cmd.cam

    def _delete_camera(self):
        """删除当前选中的摄像机 (可撤销)"""
        cam = self._selected_camera()
        if cam is None:
            return
        self.undo.push(DeleteCameraCommand("删除摄像机", self, cam))
        self.selected_camera_index = min(self.selected_camera_index,
                                         max(-1, len(self.cameras) - 1))
        if len(self.cameras) == 0:
            self.selected_camera_index = -1

    # ================ 层级面板 (树形 + 拖拽挂父, M14) ================
    def _hierarchy_rows(self):
        """场景树扁平化: [(depth, model), ...] DFS 前序, 只从根开始"""
        rows = []
        def walk(m, depth):
            rows.append((depth, m))
            for c in m.children:
                walk(c, depth + 1)
        for m in self.models:
            if m.parent is None:
                walk(m, 0)
        return rows

    def _camera_dict(self):
        """当前场景相机（写场景文件用）。

        2026-11-08 批2 (D7=A): ortho / ortho_size / fov 是**场景相机属性**，随场景
        一起保存；这里显式取值，不再依赖 sceneio 的 setdefault 兜底。
        yaw/pitch 存弧度（与 _apply_camera 读回同单位），fov 存**度**。
        """
        d = {"target": list(self.camera_target),
             "distance": self.camera_distance,
             "yaw": self.camera_yaw,
             "pitch": self.camera_pitch}
        d.update(self._camera_proj_state())
        return d

    # ---- 天空盒（beta5 Q1=A 默认蓝 / Q3=A 相机级优先 / Q5=A 失败可见） ----
    def _scene_dir(self):
        """当前场景文件目录（skybox 相对路径的基准；无对应文件时用 CWD）。"""
        p = getattr(self, '_scene_path', None)
        return os.path.dirname(os.path.abspath(p)) if p else os.getcwd()

    # ---- beta6 B1: 项目资产库（<项目根>/Assets/assets.json） ----
    def _project_root(self):
        """场景目录向上找项目根（以 Assets/assets.json 为唯一判据）；没有返回 None。"""
        try:
            import assets.assets as loom_assets
            return loom_assets.find_project_root(self._scene_dir())
        except Exception:
            return None

    def _asset_context(self, create=False):
        """当前项目的资产上下文；无项目资产库返回 None（旧路径模式）。

        F-02: create=True 时**必须**有场景文件 —— 未保存场景的 _scene_dir() 是
        CWD，直接建库会在仓库根/程序目录写出 Assets/assets.json。
        """
        if create and not getattr(self, '_scene_path', None):
            return None
        try:
            import assets.assets as loom_assets
            return loom_assets.AssetContext.for_dir(self._scene_dir(), create=create)
        except Exception:
            return None

    def asset_import(self, path=None, kind='texture', name=None, paths=None,
                     import_settings=None):
        """导入资产到项目 Assets/ -> (guid|None, created, reason).

        项目根 = 场景目录（要求场景已保存到文件；否则拒绝，避免把 Assets/ 建到
        引擎目录/CWD 污染仓库）。
        """
        import assets.assets as loom_assets
        if not getattr(self, '_scene_path', None):
            return None, False, '请先保存场景：项目根 = 场景文件所在目录'
        ctx = loom_assets.AssetContext.for_dir(self._scene_dir(), create=True)
        if ctx is None:
            return None, False, '无法创建项目资产库: %s' % (self._scene_dir(),)
        kind = (kind or 'texture').lower()
        if kind == 'texture':
            return ctx.import_texture(path, name=name,
                                      import_settings=import_settings)
        if kind == 'cubemap':
            return ctx.import_cubemap(paths, name=name)
        if kind == 'material':
            m = self._selected()
            mat = getattr(getattr(m, 'renderer', None), 'material', None) if m else None
            if mat is None:
                return None, False, '没有选中的材质'
            return ctx.import_material(mat)
        return None, False, '未知资产类型: %r (texture|cubemap|material)' % (kind,)

    def _effective_skybox(self):
        """Q3=A: 生效天空盒 —— **委托** GLEngine.effective_skybox()（GL/VK 同一判定）。

        2026-11-09 收尾: 优先级判定已上收到引擎（相机级优先 → 场景级），本方法只做兼容别名，
        避免编辑器/渲染端各写一套（那正是 Q3 要消灭的分叉）。
        """
        fn = getattr(self, 'effective_skybox', None)
        if callable(fn):
            return fn()
        cam = self.active_camera_object()      # 极旧桩兜底
        cb = getattr(cam, 'skybox', None) if cam is not None else None
        return cb if cb is not None else getattr(self, '_scene_skybox', None)

    def _refresh_effective_skybox(self):
        """生效天空盒换了对象 -> 复位渲染端 sky 状态（02 号 reset_sky_state, 幂等）。

        为什么需要: 旧实现 `_sky_prog = False` 是永久哨兵，一次编译失败后换场景也永不重试
        （天空盒静默消失）。这里与渲染端的"对象变了自动复位"形成双保险。
        返回当前生效的 Cubemap（或 None）。
        """
        # P1-1（回归修复）: 先把**场景级**写回渲染面 engine._skybox ——
        # engine.effective_skybox() 的回落值就是 self._skybox；旧实现只返回不写回，
        # 于是 skybox_set 之后 _skybox 恒 None -> editor.render 门 / loom_render 绘制门
        # 双双早退，"设完天空盒当场不生效（要重载或新建才生效）"。
        self._skybox = getattr(self, '_scene_skybox', None)
        eff = self._effective_skybox()
        if eff is not getattr(self, '_sky_eff_last', None):
            self._sky_eff_last = eff
            rs = getattr(self, 'reset_sky_state', None)
            if callable(rs):
                rs()
            else:                              # 极旧桩兜底
                for attr in ('_sky_prog', '_sky_vao', '_sky_vbo'):
                    setattr(self, attr, None)
        return eff

    # ================ 场景改动跟踪 (2026-08-13 修复: 新建前询问是否保存) ================
    def _scene_digest(self):
        """当前场景内容摘要 (不含编辑器轨道相机) —— 判定"自上次保存/加载后有改动".
        camera 固定传 None: 编辑器转视角/移动相机不算场景内容改动.
        数值规范化: int/float 统一为 float —— render 的 m.update 会把 int 0 变成
        float 0.0, json 视为不同, 导致"没改场景却判脏" (2026-08-13 用户实测 A01)."""
        def _norm(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict):
                return {k: _norm(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [_norm(x) for x in v]
            return v
        data = sceneio.scene_to_dict(self, camera=None, base_dir=self._scene_dir())
        # 2026-11-08 批2 (D7=A): 轨道相机**视角**(target/distance/yaw/pitch) 仍属
        # 编辑器视图状态, 不计入场景内容; 但投影三件套是**场景相机属性** -> 必须进
        # 脏判定, 否则 EAI camera_proj 改完直接关窗口 = 静默丢失（P-03-05 同源）。
        data['_camera_proj'] = self._camera_proj_state()
        try:
            return json.dumps(_norm(data), ensure_ascii=False, sort_keys=True)
        except Exception:
            return repr(data)

    def mark_saved(self):
        """记录当前场景为"已保存"基线 (保存/加载/新建后调用)."""
        self._saved_digest = self._scene_digest()

    def scene_is_dirty(self):
        """当前场景相对上次保存/加载/新建有无改动 (不含编辑器相机视角)."""
        return self._scene_digest() != getattr(self, '_saved_digest', None)

    def save_scene(self):
        """工具栏"保存"按钮 (独立命令, 2026-08-13): 场景有对应文件 (_scene_path)
        直接保存到该文件 (覆盖, 不弹框); 没有对应文件 (从未保存过) 与另存为一致
        (弹保存对话框). 返回 True = 保存成功 / False = 取消或失败."""
        if self._scene_path:
            return self._save_scene(self._scene_path) is not None
        return self._save_scene() is not None   # path=None -> 弹保存对话框

    def save_scene_as(self):
        """工具栏"另存为"按钮 (独立命令, 2026-08-13): 总是弹保存对话框选位置/文件名."""
        return self._save_scene() is not None

    def save_current_scene(self):
        """防丢保存 (新建/加载/退出前调用): 有对应文件直接存, 无文件弹另存为框.
        返回 True = 已保存 (可继续); False = 取消或失败 (应中止, 不覆盖当前场景)."""
        return self.save_scene()

    # ================ 防丢统一入口 (逻辑全在 controller; UI 只发指令) ================
    def _confirm_unsaved(self):
        """新建/加载/退出共用: 场景有未保存改动时询问是否保存.
        询问框由 UI 注入 (self._confirm_callback -> 'save'|'discard'|'cancel';
        兼容旧 bool: True=save / False=discard, 无回调默认保存).
        返回 True = 可继续执行指令; False = 用户取消 (中止当前指令, 不退出).
        保存 -> 成功继续 (取消失败中止); 不保存 -> 丢弃当前工作继续;
        取消 -> 中止 (回到编辑器继续编辑, 弹框 X/Esc 视同取消).
        2026-08-22: 三态化 —— 旧两态 (bool) 下弹框右上角 X 被归为"否"→
        不保存退出 (用户实测 A01); closeEvent/加载/新建 复用本函数."""
        if not self.scene_is_dirty():
            return True
        ask = getattr(self, '_confirm_callback', None)
        choice = ask() if ask is not None else None
        if choice is None:
            choice = 'save'
        if choice is True:
            choice = 'save'
        elif choice is False:
            choice = 'discard'
        if choice == 'cancel':
            return False
        if choice == 'discard':
            return True        # 点"不保存": 丢弃当前工作, 继续执行指令
        return self.save_current_scene()   # 点"保存": 成功继续, 取消失败中止

    def new_scene_cmd(self):
        """UI 指令: 新建场景 (有未保存改动先询问是否保存)."""
        if self.is_playing:
            return
        if not self._confirm_unsaved():
            return
        self._new_scene()

    def load_scene_cmd(self):
        """UI 指令: 加载场景 (有未保存改动先询问是否保存)."""
        if self.is_playing:
            return
        if not self._confirm_unsaved():
            return
        self._load_scene()

    def _save_scene(self, path=None):
        """保存场景. path 为 None 时弹系统文件对话框 (M19). 返回保存路径, 取消返回 None."""
        if self.is_playing:
            return None
        if path is None:
            path = self._choose_scene_path()
            if path is None:
                return None
        self._scene_path = path
        base = os.path.splitext(os.path.basename(path))[0]
        if base:
            self.scene_name = base        # 名称框同步为文件名 (去扩展名)
        save_last_dir(STATE_FILE, path)   # 记住这次保存的目录
        data = sceneio.scene_to_dict(self, camera=self._camera_dict(),
                                    base_dir=self._scene_dir())
        _mats_migrated = int(getattr(self, '_materials_migrated', 0) or 0)
        try:
            sceneio.save_json_atomic(path, data)
            print("[编辑器] 场景已保存到", os.path.abspath(path))
            # Q-B1-3=A: 内联材质已抽到资产库（场景只写引用）—— 明确告知用户
            if _mats_migrated:
                _notify = getattr(self, '_notify', None)
                if callable(_notify):
                    _notify('已保存：%d 个材质已迁移到资产库（场景只保留引用）'
                            % (_mats_migrated,), (150, 200, 235))
            # P2-⑥ + Q-B1-1=A: 保存后若仍有失效引用，明确告知"已原样保留"
            _notice = sceneio.asset_issue_notice(self, '保存')
            if _notice:
                _notify = getattr(self, '_notify', None)
                if callable(_notify):
                    _notify('已保存（' + _notice + '）', (235, 180, 90))
            self.mark_saved()    # 保存成功: 更新"已保存"基线
            return path
        except Exception as e:
            print("[编辑器] 保存失败:", e)
            return None

    # ---- 文件对话框输入采集 (公开; Q-B7-56-1 裁定①, 2026-11-22) ----
    # 裁定①: GUI 文件类点击的对话框只是"人类输入采集", 保存/加载/导入的**写本体**
    # 必须翻译成 EAI 命令 (scene_save/scene_load/import_obj)。三个公开方法只选
    # 路径、不写任何编辑器状态, 与原先内嵌在 _save_scene/_load_scene/_import_obj
    # 里的对话框逐参一致 (GUI 路径行为不变); 命令行/远程仍走免对话框的命令语义。
    def choose_scene_save_path(self):
        """弹"保存场景"对话框, 返回所选路径 (取消 None). GUI 输入采集专用."""
        return self._choose_scene_path()

    def choose_scene_to_open(self):
        """弹"加载场景"对话框 (与 _load_scene 的对话框逐参一致). 取消 None."""
        path = filedialog.open_file("加载场景", initial_dir(self.last_dir),
                                    _SCENE_FILTER)
        self.view.reset_interaction()
        return path

    def choose_obj_to_import(self):
        """弹"导入 .obj 模型"对话框 (与 _import_obj 的对话框逐参一致). 取消 None."""
        return filedialog.open_file(
            "导入 .obj 模型",
            filter_str="Wavefront OBJ (*.obj)\0*.obj\0所有文件 (*.*)\0*.*\0")

    def _choose_scene_path(self):
        """弹保存对话框: 初始目录=上次目录或'保存', 默认文件名自动避让重名."""
        directory = initial_dir(self.last_dir)
        base = os.path.splitext(self.scene_name.strip())[0] or '场景'
        default_name = unique_default_name(directory, base, '.json')
        path = filedialog.save_file("保存场景", directory, default_name,
                                    _SCENE_FILTER, "json")
        self.view.reset_interaction()     # 系统对话框返回后清空 UI 交互状态 (防卡死)
        if path is None:
            return None
        if not path.lower().endswith('.json'):
            path += '.json'
        return path

    def _load_scene(self, path=None):
        """加载场景. path 为 None 时弹系统文件对话框 (M19)."""
        if self.is_playing:
            return
        if path is None:
            path = filedialog.open_file("加载场景", initial_dir(self.last_dir),
                                        _SCENE_FILTER)
            self.view.reset_interaction()
            if path is None:
                return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print("[编辑器] 加载失败:", e)
            self._notify("加载失败: %s" % e, (235, 90, 90))
            return
        # 2026-11-07 F7 收口: 父链成环等对象图错误必须在**清空旧场景之前**拒绝。
        # 旧顺序是先 remove_model 全部 + undo.clear 再 scene_from_dict, 而
        # scene_from_dict 内部才校验 -> 加载非法场景时用户先丢了当前工作。
        if not isinstance(data, dict):
            self._notify("加载失败: 场景文件格式非法 (顶层不是对象)", (235, 90, 90))
            return
        # beta6 C1/D7 + B7-16: 场景契约唯一入口 prepare()（版本闸门 + 数据迁移）——
        # 必须在**清空旧场景之前**跑：场景要求更高引擎版本时拒绝加载并保留当前场景
        # （旧引擎加载新字段会静默丢弃，所以宁可拒绝；先 clear 再校验会把用户工作清掉）。
        # 迁移也在这里做完：v8 老场景的相机弧度->度不再依赖下游 scene_from_dict 内部那一步，
        # 编辑器 / GL 播放器 / VK 播放器 / 打包游戏 / 游戏包 / EAI 命令走同一份实现。
        try:
            data = sceneio.prepare(data)
        except sceneio.SceneVersionError as e:
            print("[编辑器] 场景版本不兼容, 保留当前场景:", e)
            self._notify("加载失败: %s" % e, (235, 90, 90))
            return
        _objs = data.get('objects', [])
        if not isinstance(_objs, list):
            _objs = []
        try:
            sceneio._validate_object_graph(_objs)
        except sceneio.SceneCycleError as e:
            print("[编辑器] 场景对象图非法, 保留当前场景:", e)
            self._notify("加载失败: %s" % e, (235, 90, 90))
            return
        # 校验通过后才记录"上次打开" —— 失败加载不得污染 _scene_path/state 文件
        self._scene_path = path
        save_last_dir(STATE_FILE, path)   # 记住这次打开的目录
        # 清空现有场景 (不压撤销栈: 加载即整体替换)
        for m in list(self.models):
            self.remove_model(m)
        self.undo.clear()
        cam_out = {}
        # Q6=A: 天空盒六面图相对路径按**场景目录**解析（不再相对 CWD/引擎目录）
        sceneio.scene_from_dict(self, data, camera_out=cam_out,
                                base_dir=os.path.dirname(os.path.abspath(path)))
        if cam_out:
            self._apply_camera(cam_out)          # 含投影三件套 (D7=A)
        else:
            # 2026-11-08 批2 (P-03-05): 场景**没有 camera 段**（v1 老存档 /
            # mcp_procedural_arena 之类）时, 旧实现什么都不做 -> 上一个场景的
            # ortho/ortho_size/fov 与 _scene_cam 会残留: 旧场景被按正交打开,
            # 而且随后保存会把残留值写进这份旧文件; 更糟的是点播放会强制套用
            # 上一个场景的相机。这里显式回到引擎默认投影并清空场景相机快照。
            self._scene_cam = None
            self._apply_camera_proj({'ortho': False,
                                     'ortho_size': sceneio.ORTHO_SIZE_DEFAULT,
                                     'fov': sceneio.FOV_DEFAULT_DEG})
        # Q3=A: scene_from_dict 已同时写 engine._scene_skybox / engine._skybox（都是场景级）；
        # 这里只做"换场景 -> 复位渲染端 sky 状态"（02 号 reset_sky_state, 幂等）：
        # 覆盖"上一次编译失败(_sky_prog=False 永久哨兵) 后换场景仍不出图"的病灶。
        self._scene_skybox = getattr(self, '_skybox', self._scene_skybox)
        self._sky_eff_last = None
        self._refresh_effective_skybox()
        # beta6 轮5 P2-⑥: 资产问题必须对 GUI 用户可见（此前只有 print）。
        # Q-B1-1=A: 同时说明"引用已保留，保存不会改写"，避免用户以为已丢失。
        _notice = sceneio.asset_issue_notice(self, '打开')
        if _notice:
            _notify = getattr(self, '_notify', None)
            if callable(_notify):
                _notify(_notice, (235, 180, 90))
            print('[编辑器] ' + _notice)
        base = os.path.splitext(os.path.basename(path))[0]
        if base:
            self.scene_name = base
        self.selected_index = min(0, len(self.models) - 1)
        self.mark_saved()    # 加载成功: 更新"已保存"基线
        print("[编辑器] 已加载", len(self.models), "个对象")

    def _new_scene(self):
        if self.is_playing:
            return
        for m in list(self.models):
            self.remove_model(m)
        self.lights.clear()                 # M21: 新建场景无默认光源
        self.cameras.clear()                # Unity Camera: 新建场景无摄像机
        self.active_camera = None
        # 2026-10-19 P0-4: 新建场景必须清 UI/材质/天空盒（防场景互相污染）
        # 之前只清 models/lights/cameras，A 场景的 HUD/材质会漏进 B，场景隔离被破坏。
        # 清 UI 后重建一个空默认 Canvas，否则 ui_add 会因 ui.canvases 为空而报"找不到 Canvas"。
        if getattr(self, 'ui', None) is not None:
            try:
                self.ui.clear()
                from loom_ui import Canvas as _Canvas
                self.ui.add_canvas(_Canvas(
                    canvas_type='screen',
                    width=getattr(self, 'width', 1280),
                    height=getattr(self, 'height', 800),
                    z_order=0))
            except Exception:
                pass
        if getattr(self, 'materials', None):
            self.materials.clear()
        # 2026-11-09 beta5 Q1=A: 新建场景 = **默认纯色蓝天**（白盒契约;
        # 颜色单点在 sceneio.DEFAULT_SKYBOX_COLOR, 这里不写字面量）
        self._scene_skybox = sceneio.default_skybox()
        self._skybox = self._scene_skybox   # 场景级（engine 侧字段保持"场景默认"语义）
        # beta6 轮6 D-01: 新建场景 = 换场景，必须与 scene_from_dict 同口径重置资产状态。
        # 否则上一场景的 _skybox_ref（失效引用）会在保存时被 scene_to_dict 写回新场景，
        # 并把上一场景的资产问题谎报成新场景的（跨场景污染）。
        self._skybox_valid = True
        self._skybox_error = None
        self._skybox_ref = None
        sceneio.reset_asset_errors(self)
        self._sky_eff_last = None           # 强制下一次 refresh 走"变更"分支
        self._refresh_effective_skybox()    # -> reset_sky_state()（幂等）
        self.undo.clear()
        self.selected_index = 0
        self.selected_light_index = -1
        self.selected_camera_index = -1
        self.scene_name = '场景'
        self._scene_path = None
        self.camera_target = (0, 0, 0)
        self.camera_distance = 10.0
        self.camera_yaw = 0.6
        self.camera_pitch = -0.35
        # 2026-11-08 批2 (D7=A): 新空场景 = 默认透视投影; 场景相机快照清空
        self._scene_cam = None
        self._apply_camera_proj({'ortho': False,
                                 'ortho_size': sceneio.ORTHO_SIZE_DEFAULT,
                                 'fov': sceneio.FOV_DEFAULT_DEG})
        self.mark_saved()    # 新空场景视为"已保存"基线

    # ================ Prefab (M16) ================
    def _save_prefab(self, path=None):
        """把选中物体(含子树)存为 Prefab. path 为 None 时弹系统对话框 (默认 assets 目录)."""
        if self.is_playing:
            return
        m = self._selected()
        if m is None:
            print("[编辑器] 请先选中要存为 Prefab 的物体")
            return
        if path is None:
            assets_dir = os.path.join(APP_DIR, 'assets')
            os.makedirs(assets_dir, exist_ok=True)
            base = (self.prefab_name.strip() or m.name or 'prefab').strip()
            default_name = unique_default_name(assets_dir, base, '.prefab')
            path = filedialog.save_file("保存 Prefab 模板", assets_dir, default_name,
                                        _PREFAB_FILTER, "prefab")
            self.view.reset_interaction()
            if path is None:
                return
            if not path.lower().endswith('.prefab'):
                path += '.prefab'
        self.prefab_name = os.path.splitext(os.path.basename(path))[0]
        try:
            sceneio.save_prefab(path, m)
            print("[编辑器] Prefab 已保存:", os.path.abspath(path))
        except Exception as e:
            print("[编辑器] 保存 Prefab 失败:", e)

    def _instantiate_prefab(self, path=None, offset=(0.0, 1.0, 0.0)):
        """从 .prefab 放一个实例 (可撤销), 根整体平移 offset 避免重叠.
        path 为 None 时弹系统对话框."""
        if self.is_playing:
            return
        if path is None:
            assets_dir = os.path.join(APP_DIR, 'assets')
            path = filedialog.open_file("放置 Prefab 实例", assets_dir, _PREFAB_FILTER)
            self.view.reset_interaction()
            if path is None:
                return
        if not os.path.exists(path):
            print("[编辑器] Prefab 不存在:", path)
            return
        try:
            data = sceneio.load_prefab(path)
        except sceneio.SceneVersionError as e:
            # R5-02 P-04: 版本不兼容要说人话 (不能只落 stdout)
            print("[编辑器] Prefab 版本不兼容:", e)
            self._notify("放置失败: %s" % e, (235, 90, 90))
            return
        except Exception as e:
            print("[编辑器] 读取 Prefab 失败:", e)
            return
        cmd = self.undo.push(PrefabPlaceCommand(
            "放Prefab", self, data, offset))
        self.prefab_count += 1
        if cmd.models:
            self._select_model(self.models.index(cmd.models[0]))

    # ================ 资源浏览器 (M24) ================
    # 列出 assets/ 下的网格/材质/Prefab, 点选预览, 拖到视口/物体上复用 (像 Unity Project 窗口).
    # 数据流: _scan_assets 只列文件名 (不逐帧读 JSON); 选中/拖放时 _asset_data 惰性读.
    # 跨文件引用统一走 guid: 材质资产带 guid, 应用时 _find_material 命中即共享复用.
    _BUILTIN_MESHES = (
        ('cube', '立方体', {}),
        ('sphere', '球体', {'radius': 1.0, 'stacks': 14, 'slices': 28}),
        ('plane', '平面', {'width': 8.0, 'depth': 8.0}),
    )

    def _scan_assets(self, assets_dir=None):
        """扫描资产目录 -> 资产项列表 [{type,key,name,path,builtin,spec}].
        assets_dir 供测试注入临时目录 (默认 APP_DIR/assets). 只列文件名不读内容."""
        base = assets_dir or os.path.join(APP_DIR, 'assets')
        items = []
        # 内置网格恒在 (assets/ 为空时面板也有用), spec 现成
        for prim, name, params in self._BUILTIN_MESHES:
            items.append({'type': 'mesh', 'key': 'builtin.' + prim,
                          'name': name, 'path': None, 'builtin': True,
                          'spec': {'type': prim, 'params': params}})
        # 网格/材质资产文件: assets/meshes|materials/*.json
        for sub, type_ in (('meshes', 'mesh'), ('materials', 'material')):
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.lower().endswith('.json'):
                        p = os.path.join(d, fn)
                        items.append({'type': type_, 'key': type_ + '.' + fn,
                                      'name': os.path.splitext(fn)[0], 'path': p,
                                      'builtin': False, 'spec': None})
        # Prefab 资产: assets/*.prefab (M16 已存格式)
        if os.path.isdir(base):
            for fn in sorted(os.listdir(base)):
                if fn.lower().endswith('.prefab'):
                    p = os.path.join(base, fn)
                    items.append({'type': 'prefab', 'key': 'prefab.' + fn,
                                  'name': os.path.splitext(fn)[0], 'path': p,
                                  'builtin': False, 'spec': None})
        # beta6 B1: 项目资产库（Assets/assets.json）里的贴图/六面图/材质，按 guid 列出
        try:
            ctx = self._asset_context()
            if ctx is not None:
                for gid, e in sorted(ctx.entries().items()):
                    t = e.get('type')
                    if t not in ('texture', 'cubemap', 'material'):
                        continue
                    items.append({'type': t, 'key': '%s.%s' % (t, gid),
                                  'name': e.get('name') or gid, 'path': None,
                                  'builtin': False, 'spec': None, 'guid': gid})
        except Exception:
            pass
        return items

    def _asset_data(self, it):
        """惰性读取资产文件数据 (材质/网格资产; 内置网格与 Prefab 返回 None)."""
        try:
            if it['type'] == 'material' and it['path']:
                return sceneio.load_material_asset(it['path'])
            if it['type'] == 'mesh' and not it.get('builtin') and it['path']:
                return sceneio.load_mesh_asset(it['path'])
        except Exception:
            return None
        return None

    def _find_asset(self, key):
        """按 (type, key) 在扫描结果里找回资产项 (选中态跨帧用键匹配, 不依赖对象身份)."""
        for it in self._scan_assets():
            if (it['type'], it['key']) == key:
                return it
        return None

    def _mouse_to_ground(self, px, py):
        """鼠标像素 -> 射线与地面 (y=0) 交点. 射线平行地面时回退原点."""
        origin, d = self._ray_from_mouse(px, py)
        if abs(d[1]) < 1e-9:
            return (0.0, 0.0, 0.0)
        t = -origin.y / d[1]
        return (origin.x + d[0] * t, 0.0, origin.z + d[2] * t)

    def _asset_drop_to_scene(self, it, mouse_pos):
        """资产拖进视口: 网格 -> 落点加物体; Prefab -> 落点实例化; 材质 -> 应用到选中.
        gpos 只在 mesh/prefab 分支计算 (材质不需要射线落地, 也便于无头测试)."""
        if self.is_playing:
            return
        if it['type'] == 'mesh':
            gpos = self._mouse_to_ground(mouse_pos[0], mouse_pos[1])
            spec = it.get('spec')
            if spec is None:
                data = self._asset_data(it)
                spec = {'type': data['type'], 'params': data.get('params', {})}
            mesh = spec_to_mesh(spec['type'], spec['params'])
            name = {'cube': '立方体', 'sphere': '球体', 'plane': '平面'}.get(
                spec['type'], spec['type'])
            n = len(self.models)
            self.undo.push(AddObjectCommand(
                "放%s" % name, self, mesh, Point3D(*gpos),
                Point3D(0, 0, 0),
                normal_mode='flat' if spec['type'] != 'sphere' else 'vertex',
                name="%s%d" % (name, n + 1)))
            self._select_model(len(self.models) - 1)   # 2026-08-15: 清光源/摄像机选中
        elif it['type'] == 'prefab':
            gpos = self._mouse_to_ground(mouse_pos[0], mouse_pos[1])
            try:
                data = sceneio.load_prefab(it['path'])
            except Exception as e:
                print("[编辑器] 读取 Prefab 失败:", e)
                return
            root_y = 0.0
            objs = data.get('objects', [])
            if objs:
                root_y = objs[0].get('position', [0, 0, 0])[1]
            cmd = self.undo.push(PrefabPlaceCommand(
                "放Prefab", self, data, (gpos[0], -root_y, gpos[2])))  # 根贴地
            self.prefab_count += 1
            if cmd.models:
                self._select_model(self.models.index(cmd.models[0]))
        elif it['type'] == 'material':
            m = self._selected()
            if m is not None:
                self._apply_material_asset(it, m)

    def _apply_material_asset(self, it, m):
        """把材质资产按 guid 应用到物体 (库中已有则共享复用, 否则按 guid 自建). 可撤销."""
        if self.is_playing:
            return
        data = self._asset_data(it)
        if not data:
            print("[编辑器] 材质资产损坏:", it['path'])
            return
        mat = self._find_material(data['id'])
        if mat is None:
            mat = self.add_material(color=data.get('color'),
                                    saturation=data.get('saturation', 1.0),
                                    name=data.get('name', '材质'),
                                    guid=data['id'])
        if m.renderer.material is not mat:
            before = undo_snapshot(m)
            m.renderer.material = mat
            self.undo.push(StateCommand("应用材质", self, m, before,
                                        undo_snapshot(m)))

    def _hex_to_rgb(c):
        """'#RRGGBB' -> (r,g,b) 0..1 供 GUI 色块. 非法返回 None."""
        try:
            if not c or len(c) != 7 or c[0] != '#':
                return None
            return (int(c[1:3], 16) / 255.0,
                    int(c[3:5], 16) / 255.0,
                    int(c[5:7], 16) / 255.0)
        except ValueError:
            return None

    def _asset_file_by_guid(self, directory, guid, ext):
        """在目录下找含指定 guid 的资产文件 (同 guid 再存=覆盖更新). 找不到返回 None."""
        if not os.path.isdir(directory):
            return None
        for fn in os.listdir(directory):
            if not fn.lower().endswith(ext):
                continue
            p = os.path.join(directory, fn)
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get('id') == guid:
                    return p
            except Exception:
                continue
        return None

    def _save_material_asset(self, path=None):
        """把选中物体的材质存为独立资产 (assets/materials/*.json).
        已存在同 guid 的资产文件则覆盖更新 (再存=更新), 否则 unique_default_name 新建."""
        if self.is_playing:
            return
        m = self._selected()
        if m is None or m.renderer.material is None:
            print("[编辑器] 请先选中一个带材质的物体")
            return
        mat = m.renderer.material
        mats_dir = os.path.join(APP_DIR, 'assets', 'materials')
        os.makedirs(mats_dir, exist_ok=True)
        target = path or self._asset_file_by_guid(mats_dir, mat.guid, '.json')
        if target is None:
            base = (mat.name or m.name or '材质').strip() or '材质'
            target = os.path.join(mats_dir,
                                  unique_default_name(mats_dir, base, '.json') + '.json')
        try:
            sceneio.save_material_asset(target, mat)
            print("[编辑器] 材质资产已保存:", os.path.abspath(target))
        except Exception as e:
            print("[编辑器] 保存材质资产失败:", e)

    def _save_mesh_asset(self, path=None):
        """把选中物体的网格 spec 存为独立资产 (assets/meshes/*.json)."""
        if self.is_playing:
            return
        m = self._selected()
        if m is None:
            print("[编辑器] 请先选中物体")
            return
        meshes_dir = os.path.join(APP_DIR, 'assets', 'meshes')
        os.makedirs(meshes_dir, exist_ok=True)
        target = path
        if target is None:
            base = (m.name or '网格').strip() or '网格'
            target = os.path.join(meshes_dir,
                                  unique_default_name(meshes_dir, base, '.json') + '.json')
        try:
            sceneio.save_mesh_asset(target, m.primitive or 'cube',
                                    dict(m.params) if m.params else {})
            print("[编辑器] 网格资产已保存:", os.path.abspath(target))
        except Exception as e:
            print("[编辑器] 保存网格资产失败:", e)

    # ================ 复制/删除 ================

    # ================ 复制/删除 ================
    def duplicate_object(self):
        if self.is_playing:
            return
        m = self._selected()
        if m is None:
            return
        mesh = spec_to_mesh(m.primitive or 'cube', m.params or {'size': 1.0})
        if m.color:
            mesh.face_colors = list(mesh.face_colors)
        newm = self.undo.push(DuplicateObjectCommand(
            "复制", self, mesh, m,
            Point3D(m.position.x + 0.8, m.position.y, m.position.z),
            Point3D(m.rotation.x, m.rotation.y, m.rotation.z),
            normal_mode=m.normal_mode,
            name=m.name + "_副本", scale=m.scale, color=m.color,
            visible=m.visible)).model
        self._select_model(len(self.models) - 1)   # 2026-08-15: 清光源/摄像机选中
        return newm

    def delete_object(self):
        """删除选中的物体或光源 (M21: 光源走 DeleteLightCommand)"""
        if self.is_playing:
            return
        if self._selected_camera() is not None:
            self._delete_camera()
            return
        if self._selected_light() is not None:
            self._delete_light()
            return
        m = self._selected()
        if m is None:
            return
        # Q3=A (2026-11-07): 删除入口统一走 DeleteObjectCommand (内部 remove_subtree),
        # 删父 = 连子树删。删除前若 N>0 个子物体, 由 UI 注入的回调弹确认框显示 N;
        # 无回调 (无头/最小视图) 保持旧行为直接删。
        n_children = len(self.collect_subtree(m)) - 1
        if n_children > 0:
            ask = getattr(self, '_confirm_delete_callback', None)
            if ask is not None:
                try:
                    ok = ask(m, n_children)
                except TypeError:
                    ok = ask(n_children)
                if not ok:
                    return
        self.undo.push(DeleteObjectCommand("删除", self, m))
        self.selected_index = min(self.selected_index, max(0, len(self.models) - 1))

    def toggle_visible(self, m):
        """切换物体可见性 (可撤销)."""
        if m is None:
            return
        before = undo_snapshot(m)
        m.set_visible(not m.visible)
        self.undo.push(StateCommand("显隐", self, m, before, undo_snapshot(m)))

    def new_material(self, m):
        """用当前物体颜色/饱和度新建材质并挂上 (AddMaterialCommand 可撤销)."""
        self.undo.push(AddMaterialCommand(
            "新建材质", self, color=m.color, saturation=m.saturation,
            name="材质%d" % (len(self.materials) + 1), model=m))

    def reparent(self, m, target):
        """把 m 挂到 target 下 (可撤销)."""
        self.undo.push(ReparentCommand("挂父", self, m, m.parent, target))
        self._select_model(self.models.index(m))   # 2026-08-15: 清光源/摄像机选中

    def detach(self, m):
        """把 m 脱父到根 (可撤销)."""
        self.undo.push(ReparentCommand("脱父", self, m, m.parent, None))
        self._select_model(self.models.index(m))   # 2026-08-15: 清光源/摄像机选中

    def reparent_camera(self, cam, target):
        """把摄像机挂到 target (GameObject) 下 (可撤销). 相机物体化 2026-08-16."""
        self.undo.push(ReparentCameraCommand("摄像机挂父", self, cam, cam.parent, target))
        self._select_camera(cam)

    def detach_camera(self, cam):
        """把摄像机脱父到根 (可撤销)."""
        self.undo.push(ReparentCameraCommand("摄像机脱父", self, cam, cam.parent, None))
        self._select_camera(cam)

    # ---- 物体字段命令 (undo_snapshot + StateCommand) ----
    def edit_model(self, m, label, active, key, apply_fn):
        """拖拽式字段命令: active 期间每次调 apply_fn, 结束按快照差异压撤销."""
        if active and key not in self._insp_undo_start:
            self._insp_undo_start[key] = undo_snapshot(m)
        apply_fn()
        if not active and key in self._insp_undo_start:
            before = self._insp_undo_start.pop(key)
            after = undo_snapshot(m)
            if after != before:
                self.undo.push(StateCommand(label, self, m, before, after))

    def commit_model(self, m, label, apply_fn, before=None):
        """单次字段命令: 取 before 快照(可覆盖) -> apply_fn -> 压撤销."""
        before = before if before is not None else undo_snapshot(m)
        apply_fn()
        after = undo_snapshot(m)
        if after != before:
            self.undo.push(StateCommand(label, self, m, before, after))

    def _notify(self, msg, color=(220, 222, 228)):
        """状态栏提示 (toast, 约 4s 后自动消失). 命名校验/导入结果/设置项共用.
        (2026-08-17: 命名合法性提示统一走这里, 由 旧版GUI._draw_toast 渲染到屏幕)"""
        self.msg = msg
        self.msg_color = color
        self._msg_until = time.time() + 4.0

    def _validate_object_name(self, new_name, exclude):
        """命名合法性 (2026-08-17): 所有物体(模型/光源/摄像机)共用一个名字池.
        规则: ① 空名(去空白后)非法; ② 与其他任意物体重名(按去空白比较)非法.
        exclude 为被改名对象本体 (按 is 排除自身, 允许"重命名为自己的当前名字").
        返回 None 表示合法, 否则返回错误提示字符串 (交给 _notify 显示)."""
        stripped = new_name.strip()
        if not stripped:
            return "名称不能为空"
        for obj in list(self.models) + list(self.lights) + list(self.cameras):
            if obj is exclude:
                continue
            if getattr(obj, 'name', '').strip() == stripped:
                return "名称已存在: %s" % stripped
        return None

    def rename(self, m, new_name, old_name):
        err = self._validate_object_name(new_name, exclude=m)
        if err:
            self._notify(err, (235, 90, 90))
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        before = undo_snapshot(m)
        before['name'] = old_name
        m.name = new_name
        self.undo.push(StateCommand("改名", self, m, before, undo_snapshot(m)))

    # ---- 光源字段命令 (light_snapshot + LightStateCommand) ----
    def edit_light(self, light, label, active, key, apply_fn):
        if active and key not in self._light_undo_start:
            self._light_undo_start[key] = light_snapshot(light)
        apply_fn()
        if not active and key in self._light_undo_start:
            before = self._light_undo_start.pop(key)
            after = light_snapshot(light)
            if after != before:
                self.undo.push(LightStateCommand(label, self, light, before, after))

    def commit_light(self, light, label, apply_fn, before=None):
        before = before if before is not None else light_snapshot(light)
        apply_fn()
        after = light_snapshot(light)
        if after != before:
            self.undo.push(LightStateCommand(label, self, light, before, after))

    def rename_light(self, light, new_name, old_name):
        err = self._validate_object_name(new_name, exclude=light)
        if err:
            self._notify(err, (235, 90, 90))
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        before = light_snapshot(light)
        before['name'] = old_name
        light.name = new_name
        self.undo.push(LightStateCommand("光源改名", self, light, before,
                                         light_snapshot(light)))

    # ---- 摄像机字段命令 (camera_snapshot + CameraStateCommand) ----
    def edit_camera(self, cam, label, active, key, apply_fn):
        if active and key not in self._cam_undo_start:
            self._cam_undo_start[key] = camera_snapshot(cam)
        apply_fn()
        if not active and key in self._cam_undo_start:
            before = self._cam_undo_start.pop(key)
            after = camera_snapshot(cam)
            if after != before:
                self.undo.push(CameraStateCommand(label, self, cam, before, after))

    def commit_camera(self, cam, label, apply_fn, before=None):
        before = before if before is not None else camera_snapshot(cam)
        apply_fn()
        after = camera_snapshot(cam)
        if after != before:
            self.undo.push(CameraStateCommand(label, self, cam, before, after))

    def rename_camera(self, cam, new_name, old_name):
        err = self._validate_object_name(new_name, exclude=cam)
        if err:
            self._notify(err, (235, 90, 90))
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        before = camera_snapshot(cam)
        before['name'] = old_name
        cam.name = new_name
        self.undo.push(CameraStateCommand("摄像机改名", self, cam, before,
                                          camera_snapshot(cam)))

    # ---- 组件/动作命令 (单次, 自动撤销) ----
    def toggle_collider(self, m):
        self.commit_model(m, "碰撞体开关",
                          lambda: setattr(m.collider, 'enabled', not m.collider.enabled))

    def toggle_trigger(self, m):
        """2026-10-18 阶段1档序17 Trigger: 切换 collider.is_trigger。
        is_trigger=True 时物理层建 sensor 体（可重叠穿过），事件走 on_trigger_*。"""
        self.commit_model(m, "触发器开关",
                          lambda: setattr(m.collider, 'is_trigger',
                                          not m.collider.is_trigger))

    def add_rigidbody(self, m):
        self.commit_model(m, "加刚体", m.add_rigidbody)

    def remove_rigidbody(self, m):
        self.commit_model(m, "移除刚体", m.remove_rigidbody)

    def toggle_rigidbody_gravity(self, m):
        self.commit_model(m, "刚体重力",
                          lambda: setattr(m.rigidbody, 'use_gravity',
                                          not m.rigidbody.use_gravity))

    def add_audio_source(self, m):
        self.commit_model(m, "加音频源", m.add_audio_source)

    def remove_audio_source(self, m):
        self.commit_model(m, "移除音频", m.remove_audio_source)

    def toggle_audio_playing(self, m):
        if m.audio_source is not None:
            m.audio_source.playing = not m.audio_source.playing

    def toggle_audio_loop(self, m):
        self.commit_model(m, "音频循环",
                          lambda: setattr(m.audio_source, 'loop', not m.audio_source.loop))

    def set_audio_clip(self, m, clip, old_clip):
        """音频文件路径失焦提交 (可撤销)."""
        if clip == old_clip:
            return
        # 2026-08-27 修复: undo_snapshot 的 audio_source 是**元组**
        # (clip, loop, volume), 旧代码 dict(元组) 直接 TypeError —— 检查器
        # 音频路径框每次失焦提交都炸 (异常被 Qt 信号层吞掉, 表现为改不动).
        snap = undo_snapshot(m)
        au = snap.get('audio_source')
        if au is None:
            return                       # 没有音频组件, 无从设置
        before = {**snap, 'audio_source': (old_clip, au[1], au[2])}
        m.audio_source.clip = clip
        self.undo.push(StateCommand("音频文件", self, m, before, undo_snapshot(m)))

    def add_animator(self, m):
        self.commit_model(m, "加动画", m.add_animator)

    def remove_animator(self, m):
        self.commit_model(m, "移除动画", m.remove_animator)

    def play_anim(self, m, name):
        if m.animator is not None:
            m.animator.play(name, restart=True)

    def toggle_anim_playing(self, m):
        if m.animator is not None:
            m.animator.playing = not m.animator.playing

    def toggle_anim_loop(self, m):
        self.commit_model(m, "动画循环",
                          lambda: setattr(m.animator, 'loop', not m.animator.loop))

    # ---- beta6 C1: 每片段循环模式 / 播放速率 (命令层 + 检查器共用, 可撤销) ----
    def set_anim_loop_mode(self, m, clip_name, mode):
        """设置某片段的循环模式 ('once'/'loop'/'pingpong'/'inherit'). 可撤销."""
        clip = m.animator.clips.get(clip_name) if m.animator is not None else None
        if clip is None:
            raise ValueError('片段不存在: %r (可用: %s)'
                             % (clip_name, list(m.animator.clips or [])
                                if m.animator is not None else []))
        mode = str(mode if mode is not None else '').strip().lower()
        if mode in ('inherit', 'none', 'default', ''):
            mode = None
        elif mode not in ('once', 'loop', 'pingpong'):
            raise ValueError('loop_mode 只能 once|loop|pingpong|inherit, 收到 %r'
                             % (mode,))
        self.commit_model(m, "动画循环模式",
                          lambda: setattr(clip, 'loop_mode', mode))
        return mode

    def set_anim_speed(self, m, speed):
        """设置播放速率 (写入场景, 可撤销). 非法值抛 ValueError 且模型不变."""
        if m.animator is None:
            raise ValueError('没有动画组件')
        before = undo_snapshot(m)
        m.animator.set_speed(speed)      # set_speed 先校验后写: 失败时模型不变
        after = undo_snapshot(m)
        if after != before:
            self.undo.push(StateCommand("动画变速", self, m, before, after))
        return m.animator.speed

    def add_script(self, m, sid, extra_vars=None):
        """挂脚本 + 套默认参数 (可撤销).

        2026-10-19 P0-2 修复: 先校验 sid 是否注册，再动模型 —— 旧顺序是先
        m.add_script(sid) 把组件加进去，再 get_script(sid).params，sid 不存在时
        .params 抛 AttributeError，但坏组件已入模型且未回滚，场景被污染。
        修复后：未注册时直接抛 ValueError，模型不变。

        extra_vars: 挂载时覆盖默认参数（对齐 P1-1 script_vars 透传）。
        """
        import script.scripts as _scripts
        cls = _scripts.get_script(sid)
        if cls is None:
            raise ValueError(
                "脚本不存在: %r（先 script_reload 热重载，或用 scripts 查看已注册列表）"
                % sid)
        before = undo_snapshot(m)
        sc = m.add_script(sid)
        for key, _lb, default, *_ in cls.params:
            sc.script_vars[key] = default
        if extra_vars and isinstance(extra_vars, dict):
            for k, v in extra_vars.items():
                # 只接受已声明参数，避免污染 script_vars
                if any(p[0] == k for p in cls.params):
                    sc.script_vars[k] = v
        self.undo.push(StateCommand("挂脚本", self, m, before, undo_snapshot(m)))

    def remove_script(self, m, i):
        self.commit_model(m, "卸脚本", lambda: m.remove_script(i))

    def set_script_var(self, m, i, key, value, active, kkey):
        """脚本参数拖拽 (edit_ 式撤销)."""
        if active and kkey not in self._insp_undo_start:
            self._insp_undo_start[kkey] = undo_snapshot(m)
        m.scripts[i].script_vars[key] = value
        if not active and kkey in self._insp_undo_start:
            before = self._insp_undo_start.pop(kkey)
            after = undo_snapshot(m)
            if after != before:
                self.undo.push(StateCommand("脚本参数", self, m, before, after))

    def unlink_prefab(self, m):
        self.commit_model(m, "断开Prefab", lambda: setattr(m, 'prefab_ref', None))

    def toggle_cam_fov_locked(self, cam):
        self.commit_camera(cam, "摄像机视角可调",
                           lambda: setattr(cam, 'fov_locked', not cam.fov_locked))

    def set_active_camera(self, cam):
        """把某摄像机设为场景激活相机 (播放时视角走它; 随场景序列化).
        传 None = 取消激活 (active_camera=None, 播放时用编辑器轨道视角/脚本视角)."""
        if cam is None:
            self.active_camera = None
            self._refresh_effective_skybox()
            return
        self.active_camera = cam.guid
        # Q3=A: 换了激活相机 -> 相机级天空盒优先级随之变化
        self._refresh_effective_skybox()

    # ---- 摄像机"用此相机预览" (M41: 编辑器视口切到某摄像机视角) ----
    def toggle_camera_preview(self, cam):
        if cam is None:
            return
        if self.preview_camera is cam:
            self.exit_camera_preview()
            return
        # 首次进入才捕获轨道视角 (切到第二个相机不覆盖)
        if self._preview_orbit is None:
            self._preview_orbit = (self.camera_target, self.camera_distance,
                                   self.camera_yaw, self.camera_pitch)
        self.preview_camera = cam
        self._select_camera(cam)

    def exit_camera_preview(self):
        """退出预览, 还原进入前轨道视角. 开发者轨道相机恒直立 (roll 归零,
        预览过带倾斜的相机会把 camera_roll 带歪, 必须清掉)."""
        if self.preview_camera is None:
            return
        self.preview_camera = None
        if self._preview_orbit is not None:
            t, d, y, p = self._preview_orbit
            self.camera_target, self.camera_distance = t, d
            self.camera_yaw, self.camera_pitch = y, p
            self._preview_orbit = None
        self.camera_roll = 0.0       # 修复: 预览倾斜相机退出后开发者视角不再歪
        self.orbit_mode = True
        self.apply_orbit_camera()

    # ---- 摄像机俯仰角限制 (M41): 拖条会话结束校验 [pitch_min, pitch_max] 非空 ----
    def edit_camera_pitch_bound(self, cam, key, field, active, value):
        """pitch_min/pitch_max 拖拽: 会话结束 (active 由真->假) 校验范围交集非空
        (pitch_min <= pitch_max), 非法则回滚会话前快照 + 提示 (不压撤销)."""
        if active and key not in self._cam_undo_start:
            self._cam_undo_start[key] = camera_snapshot(cam)
        setattr(cam, field, value)               # 拖拽中实时 / 会话末应用最终值
        if not active and key in self._cam_undo_start:
            before = self._cam_undo_start.pop(key)
            if cam.pitch_min <= cam.pitch_max:
                after = camera_snapshot(cam)
                if after != before:
                    self.undo.push(CameraStateCommand(
                        "摄像机俯仰角限制", self, cam, before, after))
            else:
                apply_camera_snapshot(cam, before, self)   # 交集为空: 回滚合法会话前快照
                gui = getattr(self.view, 'gui', None)
                if gui is not None:
                    gui.notice = "俯仰角范围无效: 最低俯角不能高于最高仰角"

    # ================ 播放模式 (M26: 编辑/播放分离) ================
    def toggle_play(self):
        """进入/退出播放模式. 进入: 快照编辑态场景、清撤销、跑脚本;
        退出: 丢弃播放期所有运行时改动, 还原编辑态场景 (所见即所得)."""
        # 播放切换是模式边界: 清残留交互状态 (挂脚本/拖参数等操作后检查器布局变化,
        # 可能残留 active_id/_focus -> 进入播放后检查器不画编辑控件, 残留必卡死 UI).
        # gui.end_frame 已治本(消失控件自动清), 这里双保险. 无头桩无 gui 时跳过.
        if getattr(self, 'view', None) is not None:
            self.view.reset_interaction()
        if not self.is_playing:
            # —— 进入播放 ——
            # R6 F-03: 新会话从空名单开始 (上一场停止若异常未清, 这里兜底)
            if hasattr(self, '_clear_anim_fallback'):
                self._clear_anim_fallback()
            self.exit_camera_preview()   # M41: 先退出"用此相机预览", 播放视角走 active_camera
            self.undo.clear()          # 播放期改动不可撤销 (跨边界撤销易错)
            self._play_models = list(self.models)
            self._play_lights = list(self.lights)
            self._play_snap = {id(m): undo_snapshot(m) for m in self.models}
            self._play_light_snap = {id(l): light_snapshot(l) for l in self.lights}
            self._play_parents = {id(m): m.parent for m in self.models}
            self._play_cameras = list(self.cameras)
            self._play_camera_snap = {id(c): camera_snapshot(c) for c in self.cameras}
            self._play_active_camera = self.active_camera
            self._play_edit_cam = (self.camera_target, self.camera_distance,
                                   self.camera_yaw, self.camera_pitch,
                                   self.camera_roll, self.orbit_mode)   # 编辑器轨道视角, 退出恢复
            # 2026-11-08 批2 (D7=A "播放前后恒等"): 投影三件套也必须快照 ——
            # 播放会用场景相机覆盖 ortho/ortho_size/fov，退出播放若不还原，
            # 编辑态投影就被播放态污染（旧实现只还原视角，漏了投影）。
            self._play_edit_proj = self._camera_proj_state()
            self.is_playing = True
            # 2026-11-07: 播放强制相机 —— 编辑态滑到哪都不影响, 一律回到场景相机
            try:
                _sc = getattr(self, '_scene_cam', None)
                if isinstance(_sc, dict) and _sc:
                    self._apply_camera(_sc)
            except Exception:
                pass
            # 2026-11-07 可玩性修复: 点"播放"按钮后键盘焦点在工具栏按钮上，
            # 视口收不到 WASD（key_state 为空）-> 脚本 is_key/get_action 恒 False，
            # 表现为"播放了但角色不动"。进播放即把焦点交还视口。
            try:
                _vp = getattr(getattr(self, 'view', None), 'viewport', None)
                if _vp is not None:
                    _vp.setFocus()
            except Exception:
                pass
            # B1: 进入播放建 Culverin (Jolt) 物理桥 (库缺失/建体失败 -> 返回 None,
            # update_physics 回退 legacy; 测试桩 __new__ 无 _phys_bridge_auto -> 不建桥,
            # 契约测试路径保持不变). 退出时 _destroy_phys_bridge (见下方退出分支).
            self._ensure_phys_bridge()
            for m in self.models:      # 播放期脚本实例由 update_scripts 惰性重建
                for sc in m.scripts:
                    sc._script = None
                    sc._script_broken = False
            # GC 生命周期 (2026-09-01 流畅度批): 冻结编辑态场景 (模型大 list 永久代化)
            # + 放宽播放阈值 —— 播放期 GC 只扫增量 churn (1% low 帧尖刺治理).
            # 上面刚清空的旧脚本实例会被 enter 内的 collect 先行回收, 不被冻进去.
            gc_play_enter()
            # 分离批5: 进播放清暂停态 (F9 暂停不跨播放会话; 按钮文字由 GUI 复位)
            self._logic_paused = False
            self._step_requested = False
            self._request_exit_play = False   # 脚本可置 True 请求退出播放 (通关UI的"退出游戏")
            # 分离批2: 播放边界对齐 (快照首抓 = 当前编辑态位姿, 首帧不插值)
            clk = getattr(self, '_clock', None)
            if clk is not None:
                clk.reset()
            if getattr(self, '_interp', None) is not None:
                self._interp.advance()      # curr = 进播放瞬间位姿
                self._interp.align()        # prev = curr (首帧不插值)
            self._render_world = None       # 强制重算渲染矩阵
            self._prep_sig = None           # 批5: prep 缓存强制失效
            self._prep_pairs = None         # ★09-07: 陈旧对缓存同清 (旧场景/旧
                                            # 会话下标派发进新场景 = IndexError/
                                            # 虚假 on_collision_start, 对拍探针实证)
            self._disp_gen = -1             # 派发节流复位 (新播放首帧必派发)
            # 玩家视角 = 场景 active_camera (Unity Camera); 无则保持编辑器轨道视角
            cam = self.active_camera_object()
            if cam is not None:
                self.apply_camera(cam)
            # Q3=A: 播放态天空盒 = active camera 覆盖 ? 场景级（相机优先）
            self._refresh_effective_skybox()
        else:
            # —— 退出播放: 还原编辑态场景 ——
            self.is_playing = False
            # 1) 移除播放期间新增的物体/光源 (脚本 v1 不生成, 但防御)
            for m in list(self.models):
                if m not in self._play_models:
                    self.remove_model(m)
            for l in list(self.lights):
                if l not in self._play_lights:
                    self.remove_light(l)
            # 1.5) 派发 on_disable (Q-B7-48-2 修复, 2026-11-20): 停止播放 = 脚本实例
            #      禁用 (C1 契约)。★必须在第 2 步 apply_snapshot **之前** ——
            #      apply_snapshot (undo.py:164-167) 会 clear_scripts()+add_script()
            #      **重建**全部脚本组件, 旧组件 (持有播放期脚本实例) 被丢弃; 旧版把
            #      本循环放在第 6 步, 遍历到的已是 _script=None 的新组件 -> on_disable
            #      从未触发 (scripts.py 的 on_disable 契约成死代码, Lua VM 的停止
            #      释放同断链, 只剩 script_glue 的 __del__ 兜底)。本循环 = 全仓唯一
            #      一份 on_disable 派发实现, 只挪位置不改派发语义 (on_disable ->
            #      stop_all_coroutines -> 清实例); 时序仍在第 1 步 on_destroy (播放
            #      期新增物体) 之后, 与原意图一致; 且脚本此刻仍持播放期终态
            #      (obj 可读终态, 与 on_destroy 同口径)。
            for m in self._play_models:
                for sc in m.scripts:
                    inst = getattr(sc, '_script', None)
                    if inst is not None and not getattr(sc, '_script_broken', False):
                        try:
                            inst.on_disable()   # C1: 停止播放 = 脚本实例禁用
                        except Exception as e:
                            print("[脚本] %s.on_disable 出错: %r" % (m.name, e))
                        # 2026-10-18 协程：on_disable 后显式清理（generator 里的
                        # try/finally 在此触发，避免停止播放时泄漏资源）
                        if hasattr(inst, 'stop_all_coroutines'):
                            try:
                                inst.stop_all_coroutines()
                            except Exception as e:
                                print("[脚本] %s.stop_all_coroutines 出错: %r"
                                      % (m.name, e))
                    sc._script = None
                    sc._script_broken = False
            # 2) 还原原物体: 字段快照 + 挂回列表 (若被删) + 重建 GPU
            for m in self._play_models:
                if m not in self.models:
                    self.attach_model(m)
                apply_snapshot(m, self._play_snap[id(m)])
            # 3) 还原父链 (children 列表由 set_parent 重建)
            #    2026-08-16: preserve_world=False —— 第 2 步 apply_snapshot 已还原局部
            #    值, 父也还原为播放前 -> 世界即精确回到播放前; 保世界换算会节外生枝
            for m in self._play_models:
                self.set_parent(m, self._play_parents[id(m)], preserve_world=False)
            # 4) 列表顺序还原到播放前 (DFS 前序)
            order = {id(m): i for i, m in enumerate(self._play_models)}
            self.models.sort(key=lambda mm: order.get(id(mm), len(order) + 1))
            # 5) 光源顺序 + 快照还原
            for l in self._play_lights:
                if l not in self.lights:
                    self.lights.append(l)
                apply_light_snapshot(l, self._play_light_snap[id(l)])
            # 5.5) 摄像机还原: 播放期新增删除 + 字段快照 + active + 恢复编辑器轨道视角
            for c in list(self.cameras):
                if c not in self._play_cameras:
                    self.cameras.remove(c)
            for c in self._play_cameras:
                if c not in self.cameras:
                    self.cameras.append(c)
                apply_camera_snapshot(c, self._play_camera_snap[id(c)], self)
            self.active_camera = self._play_active_camera
            # Q3=A: 退出播放后按恢复的 active_camera 重算"生效的那一个"（播放前后恒等）
            self._refresh_effective_skybox()
            if self._play_edit_cam is not None:
                self.camera_target, self.camera_distance, self.camera_yaw, \
                    self.camera_pitch, self.camera_roll, self.orbit_mode = self._play_edit_cam
                self.apply_orbit_camera()
            # 2026-11-08 批2 (D7=A): 还原编辑态投影（播放期可能套用了场景正交/fov）
            _pep = getattr(self, '_play_edit_proj', None)
            if _pep:
                self._apply_camera_proj(_pep)
            self._play_cameras = self._play_camera_snap = None
            self._play_active_camera = self._play_edit_cam = None
            self._play_edit_proj = None
            # 6) 清全部运行时状态 (2026-08-30 用户实测铁律:
            # "停止播放清除所有状态(包括运动和下落速度)":
            # apply_snapshot 已清 rb.velocity/_colliding + 动画/音频运行态,
            # 此处对无快照体再兜底清一遍 (断链/防御, 含模型的 _colliding 属性)。
            # 脚本 on_disable 派发 + 清实例已前移到第 1.5 步 (Q-B7-48-2, 2026-11-20):
            # 必须发生在 apply_snapshot 重建脚本组件**之前** —— 旧版放在这里,
            # 遍历到的恒是 _script=None 的新组件 (死代码缺陷; 修前红/修后绿留痕
            # 见 tests/_tmp/qb7482_disable_probe.py 与 test_editor_play_parity.py ⑦)。
            for m in self._play_models:
                rb = getattr(m, 'rigidbody', None)
                if rb is not None:
                    rb.velocity = Point3D(0.0, 0.0, 0.0)
                    rb._colliding = set()
                m._colliding = set()
                an = getattr(m, 'animator', None)
                if an is not None:
                    an.playing = False
                    an.time = 0.0
                au = getattr(m, 'audio_source', None)
                if au is not None:
                    au.playing = False
                    au._key = None
            # R6 F-03: 停止播放清空"动画回退驱动"名单 —— 否则它会对已删除/
            # 已还原的模型保留强引用 (WeakSet 只解决删除后滞留, 会话结束仍要清)
            if hasattr(self, '_clear_anim_fallback'):
                self._clear_anim_fallback()
            self._play_models = self._play_lights = None
            self._play_snap = self._play_light_snap = self._play_parents = None
            # B1: 退出播放销毁物理桥 (**在全部 apply_snapshot 还原完成之后**:
            # 桥回读写回的运行时位形必须在还原前被丢弃; destroy 后 ensure_models
            # 在 _destroy/重建前均禁用)。幂等; 未建桥 (legacy/测试桩) 时 no-op.
            self._destroy_phys_bridge()
            self._clamp_selection()
            self._clamp_light_selection()
            # M39: 停止播放释放鼠标 (回编辑器; 播放期玩家控制器锁定了鼠标)
            try:
                self.set_mouse_locked(False)
            except Exception:
                pass
            # GC 生命周期 (2026-09-01 流畅度批): 解冻 (冻结对象回普通代, 播放期
            # 垃圾与 remove_model 型脚本环可回收) + full collect + 阈值还原
            # 进入前实测值 (gc.get_threshold 快照, 非硬编码)
            gc_play_exit()
            # 分离批2: 退出播放 → 场景已还原编辑态, 快照对齐新位姿
            if getattr(self, '_interp', None) is not None:
                self._interp.advance()
                self._interp.align()
            self._render_world = None
            self._prep_sig = None           # 批5: prep 缓存强制失效
            self._prep_pairs = None         # ★09-07: 陈旧对缓存同清 (同上)
            self._disp_gen = -1
            clk = getattr(self, '_clock', None)
            if clk is not None:
                clk.reset()

    def _refresh_play_matrices(self, it):
        """播放态渲染帧矩阵刷新 (P-01, 2026-11-07).

        渲染矩阵 (_render_world) 走插值；逻辑矩阵 (_frame_world) **只**由逻辑帧
        _logic_prep 维护。旧实现在这里写 `if _frame_world is None:
        _frame_world = _render_world`，一旦进播放 _frame_world 非空就再没人刷新
        → 逻辑矩阵/SoA 快照/阴影 VP/碰撞 AABB 全部冻结在进播放位姿。
        首帧 (逻辑帧尚未跑) 才用当前位形补一次，且必须走 compute_world_matrices
        (它同时刷新 _soa_snap)，绝不拿插值矩阵冒充逻辑位姿。"""
        if (getattr(self, '_render_world', None) is not None
                and it.static_frame()):
            pass
        else:
            self._render_world = self._profile(
                'interp', lambda: self.compute_render_matrices(self.models))
        if getattr(self, '_frame_world', None) is None:
            self._frame_world = self._profile(
                'world_matrices',
                lambda: self.compute_world_matrices(self.models))

    # ================ 退出播放的原子化 (2026-11-08 批4 · 审计 U-01 / 裁决 A) ========
    def _exit_play_atomic(self):
        """退出播放: 要么完整成功, 要么**回滚到"仍在播放"**并明确告警 (不留中间态).

        背景: 旧实现 `render` 帧末用裸 `except Exception: pass` 包住 `toggle_play()`,
        而退出播放是"整场景还原"的复合操作 (移除播放期新物体 / apply_snapshot /
        父链 / 光源 / 相机 / 物理桥销毁 / GC 解冻) —— 半途失败会留下半还原场景,
        调用方却什么都看不到, 下一次进播放就以这个坏状态为新基线。

        做法: 先快照播放记录的**引用**(模型/光源/相机/快照表/编辑态相机与投影),
        失败时整体还原并把 `is_playing` 置回 True。还原路径对已还原项是幂等的
        (apply_snapshot 写绝对值; remove_model/attach_model 都有存在性判断),
        所以用户再点一次"停止播放"会从同一基线重跑整条路径。

        告警策略 (共性问题): 不捕 BaseException (SystemExit/KeyboardInterrupt 上抛);
        失败**首次**打日志+traceback+用户可见提示, 之后的失败只累加计数不再刷屏。

        返回 True=已退出播放; False=失败并已回滚到播放态。
        """
        if not getattr(self, 'is_playing', False):
            return True
        keep = {}
        for name in ('_play_models', '_play_lights', '_play_snap',
                     '_play_light_snap', '_play_parents', '_play_cameras',
                     '_play_camera_snap', '_play_active_camera',
                     '_play_edit_cam', '_play_edit_proj'):
            keep[name] = getattr(self, name, None)
        try:
            self.toggle_play()
        except Exception as e:
            for name, val in keep.items():
                setattr(self, name, val)
            self.is_playing = True
            self._play_exit_fail_count = int(
                getattr(self, '_play_exit_fail_count', 0)) + 1
            self._play_exit_error = '%s: %s' % (type(e).__name__, e)
            if not getattr(self, '_play_exit_warned', False):
                self._play_exit_warned = True        # 只告警一次, 之后只计数
                print('[播放] 退出播放失败, 已回滚到播放态 (可再次停止播放重试): %s'
                      % self._play_exit_error)
                try:
                    import traceback
                    traceback.print_exc()
                except Exception as _e:
                    print('[播放] 打印退出播放异常栈失败: %r' % (_e,))
                try:
                    self._notify('退出播放失败, 已留在播放态 (可重试): %s'
                                 % self._play_exit_error, (235, 90, 90))
                except Exception as _e:
                    print('[播放] 退出播放失败提示未能上屏: %r' % (_e,))
            return False
        self._play_exit_error = None
        self._play_exit_warned = False               # 成功退出 -> 下次失败重新告警
        return True

    # ================ 渲染 (覆写) ================
    def _after_pass_prof(self, spec):
        """2B1: 阴影段收口，并把「主 pass 计时起点」定在阴影之后（与迁移前一致）。"""
        if spec.id == 'shadow_maps':
            self._prof_add('mt_shadow_maps', getattr(self, '_t_shadow', 0))
            self._t_mp = self._prof_t0()

    def _prepare_main_pass(self):
        """编辑器主 pass 的 CPU 侧准备（相机 / VP / uniform），由 FramePlan 执行器调用。

        迁移前这段在 render() 里手写；现在编辑器与播放器共用同一份 FramePlan。
        ★审核 1/3 P1-3（2026-11-21）：VP 计算**不再在本类内联** —— 与播放器同调
        loom_render.RenderMixin._compute_view_proj（唯一实现；VkEditorApp 经
        editor/vk_app.py 同一函数对象再绑定接入）。本方法只保留**编辑器独有**的两件事：
        preview_camera 分支 + prof 记账（mt_mp_camera / mt_mp_uniforms）。
        """
        self._prof_add('mt_mp_fbo', getattr(self, '_t_mp', 0))
        _t = self._prof_t0()
        # MVP (轨道相机已由 engine.render 逻辑处理, 但此处复算供 gizmo/拾取用)
        # M41: "用此相机预览"时每帧重应用该摄像机 (含 roll), 拖 gizmo 实时跟
        # ★S1 (Q-B7-48-1, 人类 2026-11-19 裁决「播放组件完全可以两边用一样的代码,
        # 只要两边一直同源就不会出现差别」): 播放态相机策略与播放器**同源** ——
        # 共用 loom_render.RenderMixin._apply_main_pass_camera (orbit_mode 才合成)。
        # 旧「★2026-09-06 相机统一: 播放态=编辑态同一轨道相机」裁决已被 beta7
        # 「编辑器试播放的表现也要和播放器同步」裁决推翻; 旧拷贝在
        # elif 分支里多了 is_playing 半个条件, 让播放态每帧被陈旧轨道参数
        # 覆盖并抹掉 roll (对拍门修前红 3/3 例), 已删。
        if self.preview_camera is not None:
            self.apply_camera(self.preview_camera)
        else:
            self._apply_main_pass_camera()
        # ★审核 1/3 P1-3：VP 计算唯一实现（与播放器同一份，不再内联复制 15 行）
        self._compute_view_proj()
        self._prof_add('mt_mp_camera', _t)
        _t = self._prof_t0()
        # T3c-1: mvp/cam/灯光 全部由 _upload_lights() 一次性写 Scene UBO
        self._backend_upload_lights()
        self._prof_add('mt_mp_uniforms', _t)
        self._t_mp_draws = self._prof_t0()

    def render(self, delta_time):
        # 防御: 上一帧 GUI 若残留 scissor 裁剪, 会框住本帧的 clear/场景 (残影 bug)
        self.ctx.scissor = None
        # 2026-11-07 C: 相机聚焦插值 (180ms 线性; 播放态不推进, 不动播放相机)
        if not self.is_playing:
            self._advance_focus_anim()
        # 状态栏提示 (toast) 到期清空 (2026-08-17: _notify 定时消失)
        if self.msg and time.time() > self._msg_until:
            self.msg = ""
        # M32: 鼠标相对移动 (玩家控制器转向; 渲染帧实时采集 — Unity 同款:
        # 输入即时, 逻辑帧消费)
        # 2026-10-18 A2: EditorApp 只在 _external_ctx=True 下运行 (Qt 宿主),
        # mouse_rel 由宿主 GLViewport 喂；此处不再需要 pygame.mouse.get_rel()。
        # 保留 mouse_rel 上次值（不重置），防宿主喂流中断时突跳。
        pass
        # 嵌入式模式 (Qt 宿主): 刷新脚本键快照 (pygame 路径在 _handle_events
        # 每帧刷; 外部模式事件由宿主喂, script_keys 此前恒空 = 玩家脚本
        # is_key/get_action 永远 False). 每渲染帧刷新, 与 pygame 同语义.
        self.sync_script_keys()
        # TPS 缓冲: 帧首打点 (与 engine.render 同款)
        self._frame_start = time.perf_counter()
        # ★M3 插桩: 帧计数 + render() 总耗时 (EditorApp 覆写了基类 render, 必须在此插)
        self._stage_frames = getattr(self, '_stage_frames', 0) + 1
        _t_render = self._prof_t0()
        # 2026-08-16 相机物体化 (S1 补齐, Q-B7-48-1): 挂父激活相机每帧重应用 ——
        # 与 loom_render.render 同序同源 (共享 loom_camera.CameraMixin.
        # _reapply_parent_camera, 不复制三行)。仅播放态生效 (编辑态轨道视角不受
        # 影响); "用此相机预览"由 _prepare_main_pass 每帧 apply_camera 覆盖
        # (含父链), 不在此重复。修前编辑器无此调用 -> 播放态相机不随父移动
        # (对拍门用例 C 修前红)。
        if self.is_playing and self.preview_camera is None:
            self._reapply_parent_camera()
        # 核心任务流水线彻底解耦 (2026-10-01):
        # 仅在 Qt 宿主激活异步线程 (_external_ctx=True) 时由独立逻辑流水线推进;
        # 无头探针/直调测试环境 (_external_ctx=False) 由主线程同步推进 (防无头死锁)。
        is_async_active = getattr(self, '_logic_async', False) and getattr(self, '_external_ctx', False)
        if not is_async_active and not getattr(self, '_advanced_this_frame', False):
            _t = self._prof_t0()
            self.advance_logic(delta_time)
            self._prof_add('mt_render_advance', _t)
        self._advanced_this_frame = False   # 消费本帧标记
        # 2026-10-18 阶段1档序11 LateUpdate (S1 补齐, Q-B7-48-1): 与
        # loom_render.render 同序 —— 逻辑帧跑完后、世界矩阵重算前派发;
        # 共享 mixin 方法 _dispatch_late_update (engine.py) 即播放器同一条实现。
        # 修前编辑器 0 处调用, 脚本 on_late_update 在编辑器播放态死掉。
        self._dispatch_late_update(delta_time)
        # 编辑态插值失同步修复 (2026-09-06): 物体被直接改位 → 快照对齐
        self._consume_xform_gen()

        # 核心解耦: 播放态与编辑态渲染数据流水线彻底分流
        it = getattr(self, '_interp', None)
        if getattr(self, 'is_playing', False) and it is not None:
            # 播放态流水线: 渲染帧只算插值世界矩阵 (C 原生 interp_world 极速路径直出);
            # 逻辑世界矩阵由逻辑帧 _logic_prep 维护 (P-01: 这里只做首帧兜底,
            # 不再把插值矩阵写进 _frame_world —— 旧写法会让逻辑矩阵永久冻结).
            self._refresh_play_matrices(it)
        else:
            # 编辑态流水线: 常规世界矩阵计算
            self._frame_world = self._profile(
                'world_matrices', lambda: self.compute_world_matrices(self.models))
            self._render_world = self._frame_world
        # M36 LOD: 按相机距离切换网格精度 (无 LOD 物体零开销)。
        # EditorApp 覆写 render, 故此处也要调 (基类 render 的调用不生效)。
        self._profile('lod', lambda: self._update_lod())
        # 批5: 阴影/碰撞 prep 逻辑帧缓存; 编辑态走旧路径分支 (逃生门内)
        # 2026-08-15 8 核均摊: 阴影 VP (只读) 与碰撞检测 (只读, 仅播放期) 池上并行;
        # 编辑期只算阴影缓存 (不跑碰撞事件)
        self._profile('shadow_prep', lambda: self._backend_parallel_shadow_and_collision(
            delta_time, with_events=self.is_playing))
        # A2 (2026-08-29): 当帧实例数据准备 (f32 矩阵 + 桶重排 + 桶级实例缓冲),
        # 阴影/主 pass 共享 (逐物体 uniform/upload 循环已取消)
        self._profile('buckets', lambda: self._backend_prepare_bucket_frame())
        # 2026-11-10 阶段 2B1（S3）: 阴影也进 FramePlan（GL 侧是真深度目标；
        # 逐光源/逐面 FBO 仍归 loom_shadow，描述里标 owned_by_provider）。
        self._t_shadow = self._prof_t0()
        # 2026-11-13 T2-D05: 编辑器路径也要画 world Canvas。播放路径
        # (loom_render.py:1217) 早已 include_world_canvas=True；编辑器此前漏传，
        # 导致编辑态看不到 world 空间 UI、播放态看得到，本身不一致。
        # 判据只看 canvas_type=='world'：ui.canvases 始终含一个默认 screen Canvas
        # （engine.py:400 / editor._new_scene），不能用"非空"判定，否则 25 个没有
        # world Canvas 的场景都会多挂一个空 pass。无 world Canvas -> False，
        # 现有场景的 plan/像素完全不变。
        _ui = getattr(self, 'ui', None)
        _has_world_canvas = any(
            getattr(c, 'canvas_type', 'screen') == 'world'
            for c in (getattr(_ui, 'canvases', None) or ()))
        # S1 (Q-B7-48-1): Canvas 游戏 UI 走 FramePlan 的 screen_ui pass —— 与播放器
        # (loom_render.render 的 include_ui=...) 同一条绘制路径 (同源)。此前编辑器
        # 不传 include_ui、改在 view.draw 里自画 (同一函数、不同状态上下文) ——
        # 视图层自画已删 (ui/loom_gui.py 与 ui/minimal_editor_view.py)。编辑态不画
        # (is_playing 门控, 与旧行为一致: 游戏 HUD 不盖编辑视图)。
        plan = frame_plan(include_shadow=bool(self.lights),
                          include_sky=(self.effective_skybox() is not None),
                          include_world_canvas=_has_world_canvas,
                          include_ui=(getattr(self, 'ui', None) is not None
                                      and self.is_playing),
                          include_post=post_enabled(),
                          # S4: SCREEN 目标格式 = 真实表面格式（VK 真窗口 bgra8unorm；
                          # GL 不设 _plan_screen_format，缺省 rgba8unorm 逐位不变）。
                          screen_format=getattr(self, '_plan_screen_format',
                                                'rgba8unorm'))
        self._backend_execute_frame(plan, prepare=self._prepare_main_pass,
                                    after_pass=self._after_pass_prof)
        # 相机策略见 _prepare_main_pass (S1: 播放态与播放器同源 —— 走
        # _apply_main_pass_camera; 挂父相机跟随在 render 早段 _reapply_parent_camera。
        # 旧「★2026-09-06 播放态=编辑态同一轨道相机」注释已随裁决更新, 见上)。
        # 相机/VP/uniform/绘制/天空/Canvas UI 全部由 FramePlan 执行（见
        # _prepare_main_pass 与 loom_pass_gl 的绘制源）。这里只补记迁移前同名的阶段耗时。
        self._prof_add('mt_mp_draws', getattr(self, '_t_mp_draws', 0))
        self._prof_add('mt_main_pass', getattr(self, '_t_mp', 0))

        # UI 层 (IEditorView): 视口叠加 + 全部面板 + 播放期游戏 HUD. 播放期不画编辑辅助
        _t = self._prof_t0()
        self.view.draw(self, delta_time)

        # 视口交互: gizmo 拖拽 > 点选 (UI 未抢走点击时). 播放期不编辑
        if not self.is_playing:
            self._update_gizmo()
        self._prof_add('mt_editor_view', _t)

        _t = self._prof_t0()
        self._update_fps()
        # TPS 缓冲 (2026-09-06): 渲染帧尾富余时段预取下一逻辑帧 (成品缓存,
        # 下帧 advance 消费). FPS 预画帧不预取/不计数; 关闭时零开销.
        if not getattr(self, '_preframing', False):
            self._framebuf_prefetch(getattr(self, '_frame_start', time.perf_counter()))
        # 2026-11-07 通关 UI 的"退出游戏": 脚本置 _request_exit_play,
        # 帧末再退出播放 (不能在脚本迭代中还原场景)
        if getattr(self, '_request_exit_play', False):
            self._request_exit_play = False
            # 2026-11-08 批4 (U-01 / 裁决 A): 原子化退出 —— 失败会回滚到播放态并
            # 告警一次 (旧实现是裸 except: pass, 失败=半还原场景 + 无人知情)。
            self._exit_play_atomic()
        if not self._external_ctx:      # 外部模式: 宿主 (QOpenGLWidget) 自动交换缓冲
            # 2026-10-18 A2: GLFW swap（原 pygame.display.flip）
            self._glfw_swap_buffers()
        self._prof_add('mt_render_tail', _t)
        self._prof_add('mt_render_total', _t_render)

    def _draw_selection_box(self):
        """选中对象 AABB 12 条棱 (亮黄), 关深度恒可见"""
        m = self._selected()
        if m is None or not m.visible:
            return
        mn, mx = self.get_bounding_box(m)
        corners = [(mn.x, mn.y, mn.z), (mx.x, mn.y, mn.z), (mx.x, mx.y, mn.z), (mn.x, mx.y, mn.z),
                   (mn.x, mn.y, mx.z), (mx.x, mn.y, mx.z), (mx.x, mx.y, mx.z), (mn.x, mx.y, mx.z)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0),
                 (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        lines = []
        for a, b in edges:
            lines.append(corners[a]); lines.append(corners[b])
        col = (1.0, 0.85, 0.2)
        with self.overlay_scope(framebuffer=self._screen_fb(), enable_only=0):
            self.draw_lines(lines, [col] * len(lines))

    # ================ 主循环 ================
    # 2026-10-18 选项1: EditorApp 不再覆写 run()。原 pygame 编辑器路径（--ui default/minimal）
    # 已随 pygame 窗口剥离删除，Qt 编辑器由宿主 paintGL 驱动，从不进入基类 loom_render.run()。
    # 若未来有人直接调 EditorApp().run()，走基类：因 _external_ctx=True 立即 return（行为一致）。
    def on_key_event(self, ev):
        """吞掉 GUI 输入框按键 + 旧引擎快捷键 (编辑器模式). 返回 True = 已消费."""
        if ev.type in (pygame.KEYDOWN, pygame.KEYUP):
            if self.view.handle_key_event(ev):
                return True
        if ev.type == pygame.KEYDOWN:
            # 分离批5: F9 暂停逻辑时钟 / F10 步进 1 逻辑帧 (MC 同款, 播放态生效)
            if ev.key == pygame.K_F9:
                new_state = self.toggle_logic_paused()
                if new_state is not None:
                    self._notify("逻辑时钟 %s" % (
                        "已暂停 (F10 步进)" if new_state else "已恢复"),
                        (240, 200, 90))
                return True
            if ev.key == pygame.K_F10:
                if self.step_logic_once():
                    self._notify("步进 1 逻辑帧", (240, 200, 90))
                return True
            if (ev.key == pygame.K_z) and (ev.mod & pygame.KMOD_CTRL):
                _r = self._undo_action()
                if isinstance(_r, dict) and (_r.get('blocked') or _r.get('error')):
                    self._notify(_r.get('blocked') or _r.get('error'), (240, 200, 90))
                return True
            if (ev.key == pygame.K_y) and (ev.mod & pygame.KMOD_CTRL):
                _r = self._redo_action()
                if isinstance(_r, dict) and (_r.get('blocked') or _r.get('error')):
                    self._notify(_r.get('blocked') or _r.get('error'), (240, 200, 90))
                return True
            if ev.key == pygame.K_TAB and self.models:
                self.selected_index = (self.selected_index + 1) % len(self.models)
                return True
            if ev.key == pygame.K_0:              # 重置相机姿态 (2026-08-28: 从
                # 空格迁移 —— 空格极易误触且与玩家'跳跃'动作共用; 0=归零语义)
                self.camera_target = (0, 0, 0)
                self.camera_distance = 10.0
                self.camera_yaw = 0.6
                self.camera_pitch = -0.35
                return True
            if ev.key == pygame.K_ESCAPE and self.preview_camera is not None:
                self.exit_camera_preview()        # M41: Esc 退出"用此相机预览"
                return True
        return True    # 编辑器模式: 全部吞掉 (WASD 由 _update_camera 直接读键处理)

    def on_text_input(self, ev):
        """IME 合成文本 (pygame.TEXTINPUT) -> 视图输入框.
        (2026-08-17: 命名框开启中文输入法后, 中文字符经 TEXTINPUT 事件送达而非
        KEYDOWN.unicode; 引擎 _handle_events 捕获 TEXTINPUT 后经此转发给视图/gui)"""
        return self.view.handle_key_event(ev)

    def on_quit_request(self):
        """窗口右上角关闭拦截: 有未保存改动先询问是否保存 (防丢, 逻辑在 controller).
        返回 True = 允许退出; False = 中止退出 (保存取消或失败)."""
        return self._confirm_unsaved()

    def _update_camera(self, delta_time=None):
        # 2026-10-18: UI 鼠标事件分发 (在相机/3D 消费之前). 两条路径 (pygame 主循环
        # 与 Qt loom_gui) 都走本方法, 所以这里是唯一的插入点.
        """轨道相机交互: 右键=转动视角(Unity 场景视图风格), Alt+左/中键=轨道,
        中键+Shift/Alt=平移 target, 滚轮=缩放.
        WASD/QE/方向键在输入框失焦时移动 target. 全部限视口内.
        M41: "用此相机预览"时禁用轨道操作 (视口固定在该摄像机视角).
        2026-08-19: 移动/转向全部按 delta_time 缩放 (帧率恒定) —— 原每帧固定
        步长导致 30帧(2.4单位/秒) 与无上限 245帧(19.6单位/秒) 移速差 8 倍.
        2026-10-18: UI 鼠标分发置于本方法开头 (两条路径共用入口)."""
        # 2026-11-07 C: 推进聚焦插值 (render 之外的第二推进点; 播放态不动相机)
        if not getattr(self, 'is_playing', False):
            self._advance_focus_anim()
        # 2026-10-18: UI 鼠标事件分发 (在相机/3D 消费之前). 两条路径 (pygame 主循环
        # 与 Qt loom_gui) 都走本方法, 所以这里是唯一的插入点.
        self._dispatch_ui_mouse()
        # 2026-11-07 2D 视角锁定: 播放态下相机朝向/缩放/平移全部冻结
        # (右键转视角、Alt+左键轨道、中键平移、滚轮缩放都不再生效)，
        # 只保留 UI 分发（HUD 按钮仍可点）。玩家 WASD 走脚本，不动相机。
        if getattr(self, 'is_playing', False):
            self._cam_prev_mouse = self.mouse_pos
            return
        # UI 命中并消费鼠标 -> 跳过全部鼠标相机控制 (决策3=B, 键盘 WASD 不受影响)
        # 2026-10-18 D1: UI 命中时只锁鼠标 (滚轮/拖拽), 键盘 WASD 不受影响.
        _ui_lock = bool(getattr(self, 'ui_consumed', False))
        # P-22/F3 (2026-11-07): 本拍左键按下 → 记代际点击给 paintGL 的
        # _update_gizmo 消费 (Qt 在 _on_tick 末尾清 pressed)。UI 已消费则不记,
        # 保证"UI 命中时不进 gizmo"。
        if not _ui_lock and 1 in getattr(self, 'pressed', ()):
            _pp = self.mouse_press_pos.get(1)
            if (_pp is not None
                    and _pp is not getattr(self, '_gizmo_consumed_press', None)):
                self._gizmo_click_gen = getattr(self, '_gizmo_click_gen', 0) + 1
                self._gizmo_click_pos = _pp
        if self.preview_camera is not None:
            return
        if _ui_lock:
            self._cam_prev_mouse = self.mouse_pos    # 保持 prev 同步, 防消费结束后突跳
        if delta_time is None:
            # ★2026-09-07 相机卡顿修复①: dt 时钟 time.time()->perf_counter。
            # time.time() 走系统定时器 (本机 1ms 粒度; 无 timeBeginPeriod 的机器
            # 15.6ms 粒度) — 6ms 轻帧下 dt 量化 ±1ms = 相机速率逐帧 ±15% 抖动
            # (微观卡顿); 15.6ms 粒度机器上更会 0/15.6/31 台阶。perf_counter
            # 100ns 精度, 每渲染帧位移精确 ∝ 真实帧间隔 (速率恒定)。
            # 语义零变化: 同为"上一帧到本帧墙钟", 只是时钟源换高精度单调钟。
            now_pc = time.perf_counter()
            delta_time = min(now_pc - getattr(self, '_cam_dt_last', now_pc), 0.1)
            self._cam_dt_last = now_pc
        # 摄像机移速倍率 (引擎设置项 cam_speed, 0.5-2.0, 默认 1.0 = 120帧原移速;
        # 缓存到 self._cam_speed, 设置面板修改时同步更新)
        if not hasattr(self, '_cam_speed'):
            try:
                import guiloader
                self._cam_speed = float(guiloader.load_settings('loom').get('cam_speed', 1.0))
            except Exception:
                self._cam_speed = 1.0
        mods = self._mods
        alt = bool(mods & pygame.KMOD_ALT)
        shift = bool(mods & pygame.KMOD_SHIFT)
        left = bool(self.buttons[0])    # pygame.get_pressed() -> (左, 中, 右)
        mid = bool(self.buttons[1])
        right = bool(self.buttons[2])   # 右键: 按住拖动 = 转动视角 (与 Unity 一致)

        px, py = self.mouse_pos
        dx = px - self._cam_prev_mouse[0]
        dy = py - self._cam_prev_mouse[1]

        # 滚轮缩放 (视口内): 往上推 = 放大/拉近, 往下滑 = 拉远 (2026-08-12 用户确认标准方向)
        # 2026-09-06 相机统一: 播放/编辑同一轨道几何 — 滚轮一律推拉
        # camera_distance (旧"播放态推拉相机本体"自由相机分支删除)。
        # 2026-11-21 B7-28 (P-09 裁决): 滚轮不再被 _ui_lock (整帧鼠标事件被消费)
        # 连坐 —— 只有「滚轮本身被 ScrollView 吃掉」才不给相机; 被吃掉的滚轮已在
        # _dispatch_ui_mouse 里清 0, 这里只看 self.mouse_wheel 是否还有值。
        # 同帧「点按钮 + 滚轮」: 按钮消费点击, 滚轮仍归相机/脚本。
        if (self.mouse_wheel
                and self._in_viewport(self.mouse_pos)):
            # 2026-10-20 视距提升：相机滚动上限 200→1000（匹配 far=1000）
            self.camera_distance = max(0.5, min(1000.0,
                self.camera_distance * math.exp(-self.mouse_wheel * 0.1)))
            self._cancel_focus_anim()      # 用户滚轮 -> 放弃聚焦插值

        # 2026-08-12: 右键转视角 = 视口内按下即激活, 拖动过程(即使拖出视口)持续, 松开停
        # (Unity 风格: 大范围拖动更合理; 检查器/面板上右键仍走拖条数值输入)
        if not _ui_lock and right and self._in_viewport(self.mouse_pos):
            self._right_drag_view = True
        if not right or _ui_lock:
            self._right_drag_view = False

        in_vp = self._in_viewport(self.mouse_pos) and not _ui_lock
        if in_vp:
            # 平移 target: 中键 + (Shift/Alt)
            if mid and (shift or alt):
                # 屏幕像素 -> 世界 (target 深度处), 拖拽右移 -> target 左移
                k = 2.0 * self.camera_distance * math.tan(self._fov / 2) / self.height
                yaw, pitch = self.camera_yaw, self.camera_pitch
                r = (math.cos(yaw), 0.0, -math.sin(yaw))       # 相机右
                u = (math.sin(yaw) * math.sin(pitch),
                     math.cos(pitch),
                     math.cos(yaw) * math.sin(pitch))          # 相机上
                t = self.camera_target
                self.camera_target = (t[0] - r[0] * dx * k - u[0] * dy * k,
                                      t[1] - r[1] * dx * k - u[1] * dy * k,
                                      t[2] - r[2] * dx * k - u[2] * dy * k)
                self._cancel_focus_anim()      # 用户平移 -> 放弃聚焦插值
            # 转动视角: 右键(激活) 或 Alt+左 / 中键(无 Shift)
            # 上下方向: 向上拖 pitch 增大 (相机上抬看顶, 与方向键一致) —— 2026-08-12 翻正
            elif self._right_drag_view or (left and alt) or (mid and not shift):
                self.camera_yaw += dx * 0.01
                self.camera_pitch = max(-1.55, min(1.55, self.camera_pitch - dy * 0.01))
                self._cancel_focus_anim()      # 用户转视角 -> 放弃聚焦插值
        elif self._right_drag_view:
            # 右键按下在视口内, 拖出视口仍继续转视角 (Unity 风格)
            self.camera_yaw += dx * 0.01
            self.camera_pitch = max(-1.55, min(1.55, self.camera_pitch - dy * 0.01))
            self._cancel_focus_anim()

        # 键盘平移 target / 方向键轨道 (输入框失焦时)
        # ★2026-09-06 相机统一 (用户定案): 播放态 = 编辑态同一套轨道相机逻辑
        # — WASD/QE 平移 camera_target, 方向键转视角, apply_orbit_camera 每帧
        # 从 (target, yaw, pitch, distance) 合成位姿。旧"播放态自由相机移
        # camera 本体"双轨制与玩家脚本相机写回互冲 (双驱动源) = 开发者相机
        # 移动 BUG 总根, 已随脚本相机接管一并删除。
        # 2026-11-07 视角锁定: 播放态下 WASD/方向键归玩家脚本，
        # 不再平移/旋转编辑器轨道相机（否则按 W 玩家和相机一起动 = "视角没锁"）。
        if (not getattr(self, 'is_playing', False)
                and self.view.input_state()['focus_id'] is None):
            ks = self._key_pressed()    # 嵌入式模式 (Qt) 由宿主提供按键快照
            yaw, pitch = self.camera_yaw, self.camera_pitch
            # 2026-08-19 修复: 水平移动方向只由 yaw 决定 —— 之前乘 cos(pitch),
            # 视角抬到 ±90° 时 cos→0, W/A/S/D 移动速度递减到 0 (无法前进).
            # pitch 只影响视角高低 (view 矩阵), 不该缩放水平移动速度.
            f = (math.sin(yaw), 0.0, math.cos(yaw))
            # 帧率恒定: 0.08*120 = 9.6 单位/秒 (保持原 120帧 移速), 乘 delta_time
            # 与 cam_speed 倍率 (0.5-2.0, 默认 1.0).
            # ★2026-09-06 修复: 相机统一重构误删本行 (speed 定义) —— 下方 WASD/QE
            # 段引用 speed 直抛 NameError, _on_tick 每拍中断 (viewport.update()
            # 永不执行) = 播放态按键即全场冻结. 与稳定备份区 2087 行逐字一致.
            speed = 0.08 * delta_time * 120.0 * self._cam_speed
            t = self.camera_target
            if ks[pygame.K_w]:
                t = (t[0] + f[0] * speed, t[1], t[2] + f[2] * speed)
            if ks[pygame.K_s]:
                t = (t[0] - f[0] * speed, t[1], t[2] - f[2] * speed)
            if ks[pygame.K_a]:
                t = (t[0] - f[2] * speed, t[1], t[2] + f[0] * speed)
            if ks[pygame.K_d]:
                t = (t[0] + f[2] * speed, t[1], t[2] - f[0] * speed)
            if ks[pygame.K_q]:
                t = (t[0], t[1] + speed, t[2])
            if ks[pygame.K_e]:
                t = (t[0], t[1] - speed, t[2])
            self.camera_target = t
            # 方向键转视角: 同样按 delta_time 缩放 (帧率恒定, 默认行为不变)
            rot = 0.02 * delta_time * 120.0
            if ks[pygame.K_LEFT]:
                self.camera_yaw -= rot
            if ks[pygame.K_RIGHT]:
                self.camera_yaw += rot
            if ks[pygame.K_UP]:
                self.camera_pitch = min(1.55, self.camera_pitch + rot)
            if ks[pygame.K_DOWN]:
                self.camera_pitch = max(-1.55, self.camera_pitch - rot)

        self._cam_prev_mouse = (px, py)

    # ================= S4（Q-B7-47-1 阶段 4）：编辑器状态装配（GL/VK 同一份） =================
    # 原 EditorApp.__init__ 里「super().__init__ 之后的全部编辑器状态」原样搬入本方法
    # （逐行未改，规则 5.5 同源不同步：EditorApp 与 VkEditorApp 都只调这一份装配）。
    # 前置：宿主引擎的 __init__ 已跑完（GL=GLEngine.__init__ / VK=SceneDriver.__init__），
    # width/height/_external_ctx 等宿主字段由各装配点先行置好。
    def _init_editor_state(self, scene_path=None, view=None):
        """编辑器状态装配（后端无关唯一实现；GL/VK 共用，见上方段注释）。"""
        self.allow_fullscreen = False   # 编辑器禁 F11 全屏 (只留最大化+自由缩放; 2026-08-17)
        global DEFAULT_SAVE_DIR   # 设置面板改"保存目录"时覆盖模块默认值
        # ================ 编辑器状态 ================
        # UI 层 (IEditorView, 见 ui/editor_ui.py) 可注入: 官方 GUI = LoomGUI
        # (ui/loom_gui.py, Qt 原生, 由入口 run_loom_gui 创建后注入); 换 UI 只需
        # 传另一个实现 —— 引擎/逻辑零改动. 未注入时的兜底 = MinimalEditorView
        # (零 Qt/pygame 依赖, 2026-08-28 起; 旧默认 pygame 即时 GUI 已删除).
        # 注意: self.ui 是引擎 Canvas UI (loom_ui.UIManager), 编辑器视图用 self.view 区分.
        if view is None:
            from ui.minimal_editor_view import MinimalEditorView
            view = MinimalEditorView()
        self.view = view
        self.view.attach(self)
        self.selected_index = 0
        self.selected_light_index = -1    # 选中光源 (>=0 时优先于 selected_index)
        self.selected_camera_index = -1   # 选中摄像机 (Unity Camera, 优先于光源/物体)
        self.gizmo_mode = 'translate'     # 'translate' | 'rotate'
        self.gizmo_axis = None            # 当前拖拽/高亮的轴 ('X'/'Y'/'Z' 或 None)
        self.gizmo_drag = None            # 拖拽状态 (axis, start_pos) 或 None
        self.gizmo_undo_before = None     # 拖拽开始的快照 (结束时压撤销栈)
        self.scene_name = '场景'          # 场景名 (保存对话框的默认文件名)
        self._scene_path = None
        # 状态栏提示 (toast): 命名非法/导入结果/设置项待重启生效等. _msg_until 到期清空.
        self.msg = ""
        self.msg_color = (220, 222, 228)
        self._msg_until = 0.0
        self.last_dir = load_last_dir()   # 上次保存/打开的目录 (M19)
        # Q3=A (2026-11-07): 删除仍有子物体的父对象 = 连整棵子树一起删 (Unity 语义).
        # UI 层可注入 self._confirm_delete_callback(model, n_children) -> bool,
        # 在删除前弹确认框显示子物体数量; 无注入 (无头测试/最小视图) 直接删.
        self._confirm_delete_callback = None
        # 2026-10-19 B2: 旧"保存/"自动迁移为"Projects/"（仅首次，rename 原子操作）
        try:
            # 2026-11-06: 迁移前加显式开关。这是**破坏性**操作 (rename 掉受
            # 版本控制的目录), 测试/CI/批量工具应设 LOOM_NO_SAVE_MIGRATE=1
            # 关掉, 而不是各自重定向常量 (复核 A 实测: 未重定向的 EditorApp
            # 一实例化就会把 保存/ 改名成 Projects/)。
            if (os.environ.get("LOOM_NO_SAVE_MIGRATE") != "1"
                    and os.path.isdir(_LEGACY_SAVE_DIR)
                    and not os.path.isdir(DEFAULT_SAVE_DIR)):
                os.rename(_LEGACY_SAVE_DIR, DEFAULT_SAVE_DIR)
                print("[编辑器] 项目目录已迁移: 保存/ -> Projects/")
        except OSError as _e:
            print("[编辑器] 项目目录迁移失败 (忽略，继续用 保存/): %r" % (_e,))
        os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)
        # 设置面板里改的"保存目录"覆盖默认保存目录 (启动器设置, 2026-08-14)
        try:
            import guiloader
            _sd = guiloader.load_settings('loom').get('save_dir')
            if _sd:
                DEFAULT_SAVE_DIR = _sd
                os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)
        except Exception:
            pass
        self.prefab_name = 'prefab'       # 存/放 Prefab 用的文件名
        self.prefab_count = 0             # 实例计数 (每次放置递增避免重叠)

        # 撤销/重做 (M15)
        self.undo = UndoManager()

        # 检查器拖拽撤销: field_key -> 拖拽开始快照 (M15)
        self._insp_undo_start = {}
        self._name_was_focused = False
        self._name_before = None
        # 光源检查器撤销 (M21): 光源属性拖拽/名称失焦
        self._light_undo_start = {}
        self._li_name_was_focused = False
        self._li_name_before = None
        # 摄像机检查器撤销 (Unity Camera): 摄像机属性拖拽/名称失焦
        self._cam_undo_start = {}
        self._cam_name_was_focused = False
        self._cam_name_before = None
        # 摄像机"用此相机预览" (M41): 编辑器视口切到某摄像机视角; _preview_orbit 记录进入前轨道
        self.preview_camera = None
        self._preview_orbit = None

        # 层级拖拽挂父 (M14): (被拖模型) 或 None
        self._hier_drag = None

        # 资源浏览器 (M24): 选中的资产键 (type, key) 或 None; 拖拽源资产项或 None
        self._res_selected = None
        self._res_drag = None
        self._hier_row_targets = []      # 层级行 (rect, model) 命中表, 资源材质可拖到行上应用

        # 播放模式 (M26): 编辑/播放分离. 播放时快照场景跑脚本, 退出丢弃改动还原.
        self.is_playing = False
        self._play_models = None       # 播放开始时模型引用列表 (还原/清理用)
        self._play_lights = None
        self._play_snap = None         # {id(m): undo_snapshot} 播放开始时的编辑态快照
        self._play_light_snap = None
        self._play_parents = None      # {id(m): parent}
        self._play_cameras = None      # 播放开始时的摄像机引用列表
        self._play_camera_snap = None  # {id(c): camera_snapshot}
        self._play_active_camera = None  # 播放开始时的 active_camera
        self._play_edit_cam = None     # 播放开始时的编辑器视角 (退出恢复轨道相机)

        # 轨道相机初始姿态
        self.orbit_mode = True
        self.camera_target = (0.0, 0.0, 0.0)
        self.camera_distance = 10.0
        self.camera_yaw = 0.6
        self.camera_pitch = -0.35
        # 2026-11-07 2D: 主相机正交投影 (ortho=True 时用 ortho_size 作为可见高度)
        self.ortho = False
        self.ortho_size = 12.0
        # 2026-11-07 C: Agent 自动聚焦/相机聚焦插值状态 (None = 无动画)
        self._focus_anim = None
        self.apply_orbit_camera()
        self._cam_prev_mouse = (0, 0)   # 相机拖拽的上帧鼠标
        self._right_drag_view = False   # 2026-08-12: 视口内按下右键即激活视角拖动, 拖出视口仍持续到松开 (Unity 风格)

        # 面板布局状态 (2026-08-14 晚: 分隔条拖动 + 收起, 显示层/交互层共读)
        self.panel_left_w = 220         # 左列宽 (层级+资源)
        self.panel_right_w = 280        # 右列宽 (检查器)
        self.panel_hier_frac = 0.55     # 左列上层级占比
        self.hier_list_h = None         # 层级面板内"列表"高 (px, 固定; 拖列表/操作横线才改,
                                        # 2026-08-15 独立于层级面板缩放, 不因拖 hdiv 级联移动)
        self.panel_left_collapsed = False   # 左列收起 (薄条, 舞台视野更大)
        self.panel_right_collapsed = False  # 右列收起

        # 清掉 GLEngine 默认场景, 换成编辑器种子场景
        for m in list(self.models):
            self.remove_model(m)
        self._seed_scene()
        self.mark_saved()        # 种子场景视为"已保存"基线 (未改动时新建不询问)

        # S5（Q-B7-47-1 五阶段·阶段 5）：插值平面（分离批2）。GL 引擎在
        # GLEngine.__init__ 建 _interp（split 开启时）；VK 编辑器经 SceneDriver
        # 裸装配没有它，播放态 _refresh_play_matrices 会落到编辑态管线（渲染矩阵 =
        # 逻辑位姿、无插值），与 GL 编辑器播放态差 1 个逻辑帧的观感（S5 门修前红：
        # rw 逐帧不等、暂停/单步像素差 1 帧）。GL 已有 -> 本分支不触发，一行不变。
        # models 列表对象是 EngineCore.__init__ 建的稳定引用（只 clear 不换），
        # 与 GL 同一构造式。
        if getattr(self, '_interp', None) is None and getattr(self, '_split_enable', False):
            from core.interp import InterpState
            self._interp = InterpState(self.models)

        # 打开项目 (--open <scene.json>): 启动即加载指定场景.
        # 由项目管理器"打开项目"调用, 覆盖种子场景进入该项目工作.
        # (2026-08-18) 无场景时的"自动恢复上次场景"由 Qt 入口层 (run_loom_gui)
        # 负责 —— 引擎层保持纯净, 无头测试构造不受影响, pygame 版行为不变.
        if scene_path:
            self._load_scene(scene_path)
