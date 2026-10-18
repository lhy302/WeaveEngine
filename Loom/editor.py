# -*- coding: utf-8 -*-
"""
editor.py — EditorApp: 3D 游戏引擎编辑器 (Unity/Godot 风格)

布局:
  工具栏(顶部 36px) | 层级面板(左 220px) | 属性检查器(右 280px) | 状态栏(底部 24px) | 视口(中央)
功能 (M7): 布局骨架 + 对象层级点击选中 + 检查器变换编辑 (位置/旋转/缩放)
后续里程碑: M8 射线拾取, M9 平移 gizmo, M10 旋转 gizmo, M11 轨道相机交互, M12 序列化
"""
import math
import os
import json
import time

import numpy as np
import pygame
import moderngl

from engine import (GLEngine, Point3D, LightState, CameraState, wrap_deg,
                    gc_play_enter, gc_play_exit)
from matlib import (mat4_perspective, mat4_rotation, mat4_scale,
                    mat4_translation, mat4_view_yaw_pitch, decompose_euler)
from mesh import create_cube, create_plane, create_sphere, spec_to_mesh
# 2026-10-18 选项1: from gui import GUI 已删（EditorApp 零依赖 MinimalEditorView 兜底路径
# 已随 pygame 窗口剥离一起删除；gui.py 本身保留供 tests 使用）。
# 2026-08-28: 默认视图不再引用 ui.loom_gui (Qt 视图需 QApplication, 由入口
# run_loom_gui 创建后显式注入); EditorApp 默认为零依赖 MinimalEditorView 兜底
from undo import (UndoManager, StateCommand, AddObjectCommand,
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
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SAVE_DIR = os.path.join(APP_DIR, '保存')     # 默认保存文件夹 (未选过目录时)
STATE_FILE = os.path.join(APP_DIR, 'editor_state.json')  # 记忆上次保存目录


def unique_default_name(directory, base, ext):
    """默认文件名冲突时自动加数字: base -> base1 -> base2 ... (ext 含点, 如 '.json').
    返回第一个不存在的文件名 (不含扩展名). base 若自带扩展名会被去掉."""
    base = os.path.splitext((base or '场景').strip())[0] or '场景'
    for i in range(1000):
        name = base if i == 0 else '%s%d' % (base, i)
        if not os.path.exists(os.path.join(directory, name + ext)):
            return name
    return base + '999'


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
    """保存/打开对话框的初始目录: 上次目录优先, 否则默认 '保存' 文件夹."""
    if last_dir and os.path.isdir(last_dir):
        return last_dir
    return DEFAULT_SAVE_DIR


_SCENE_FILTER = "场景文件 (*.json)\0*.json\0所有文件 (*.*)\0*.*\0"
_PREFAB_FILTER = "Prefab 文件 (*.prefab)\0*.prefab\0所有文件 (*.*)\0*.*\0"


class EditorApp(GLEngine):
    def __init__(self, width=1280, height=800, scene_path=None, view=None, ctx=None):
        # ctx 注入 = 嵌入式模式 (Qt 宿主): 见 GLEngine.__init__ 注释 (IME 污染修复)
        super().__init__(width, height, ctx=ctx)
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

        # 打开项目 (--open <scene.json>): 启动即加载指定场景.
        # 由项目管理器"打开项目"调用, 覆盖种子场景进入该项目工作.
        # (2026-08-18) 无场景时的"自动恢复上次场景"由 Qt 入口层 (run_loom_gui)
        # 负责 —— 引擎层保持纯净, 无头测试构造不受影响, pygame 版行为不变.
        if scene_path:
            self._load_scene(scene_path)

    # ================ 种子场景 ================
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

    def _selected(self):
        """当前选中的物体 (选中光源时返回 None)"""
        if self.selected_light_index >= 0:
            return None
        if 0 <= self.selected_index < len(self.models):
            return self.models[self.selected_index]
        return None

    def _select_model(self, index):
        """选中物体 (models 下标): 清掉光源/摄像机选中 —— 三者互斥.
        (2026-08-12 修复: 加光源后再点物体永远选不中, 因 _selected() 优先返回光源;
         2026-08-15 补: 层级对象行松开/添加/复制/挂父/脱父等路径也要走这里, 且清摄像机.)"""
        self.selected_index = index
        self.selected_light_index = -1
        self.selected_camera_index = -1

    def _selected_light(self):
        """当前选中的光源 (未选中光源返回 None)"""
        if 0 <= self.selected_light_index < len(self.lights):
            return self.lights[self.selected_light_index]
        return None

    def _selected_camera(self):
        """当前选中的摄像机 (未选中摄像机返回 None)"""
        if 0 <= self.selected_camera_index < len(self.cameras):
            return self.cameras[self.selected_camera_index]
        return None

    # ================ 射线拾取 (M8) ================
    def project_world(self, p):
        """世界点 -> 屏幕像素 (y 向下). 行向量: clip = world @ _vp.
        摄像机背后的点返回 None (2026-08-21 修复, pygame 时期遗留): 背面点
        clip.w<0, 除以负 w 后 NDC 符号翻转 -> 投影到屏幕镜像位置, 表现为
        gizmo 轴帽/光源图标在"背面 180 度"再渲染一遍 (用户实测)."""
        ndc = np.array([p[0], p[1], p[2], 1.0]) @ self._vp
        w = ndc[3]
        if w <= 0:
            return None
        ndc = ndc / w
        return ((ndc[0] + 1) * 0.5 * self.width, (1 - ndc[1]) * 0.5 * self.height)

    def _unproject(self, px, py, ndc_z):
        """屏幕像素 (y 向下) -> 世界点. NDC 深度 [0,1]: z=0 近平面, z=1 远平面."""
        ndc = np.array([2 * px / self.width - 1, 1 - 2 * py / self.height, ndc_z, 1.0])
        world = ndc @ np.linalg.inv(self._vp)      # 行向量: clip @ inv(V·P) = world
        return Point3D(world[0] / world[3], world[1] / world[3], world[2] / world[3])

    def _ray_from_mouse(self, px, py):
        """像素点 -> (射线原点, 单位方向)"""
        near = self._unproject(px, py, 0.0)
        far = self._unproject(px, py, 1.0)
        d = (far.x - near.x, far.y - near.y, far.z - near.z)
        ln = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        if ln < 1e-12:
            return near, (0.0, 0.0, 0.0)
        return near, (d[0] / ln, d[1] / ln, d[2] / ln)

    @staticmethod
    def _ray_aabb(origin, dirv, mn, mx):
        """slab 法 射线-AABB 相交. 返回进入距离 t (>=0) 或 None."""
        o, d = origin, dirv
        tmin, tmax = 0.0, float('inf')
        for i in range(3):
            if abs(d[i]) < 1e-9:
                if o[i] < mn[i] or o[i] > mx[i]:
                    return None
            else:
                t1 = (mn[i] - o[i]) / d[i]
                t2 = (mx[i] - o[i]) / d[i]
                if t1 > t2:
                    t1, t2 = t2, t1
                tmin = max(tmin, t1)
                tmax = min(tmax, t2)
                if tmin > tmax:
                    return None
        return tmin

    def _pick(self, px, py):
        """视口点选: 射线 vs 各可见对象 AABB, 取最近命中.
        项B3 (2026-09-02 多物体批): AABB 读当帧批量缓存 (_frame_world 已由
        render 每帧算好, _model_aabbs_par 走 fastpath 批量内核), 不逐模型
        get_bounding_box 现算 (500球逐模型 ~30ms -> 批量 ~1ms). 命中结果与
        旧路径数值同源 (同 get_bounding_box 语义, 批量内核 D6 对拍 1e-7 内)."""
        origin, dirv = self._ray_from_mouse(px, py)
        o = (origin.x, origin.y, origin.z)
        best, best_t = None, float('inf')
        # 当帧世界矩阵: render 已算 (_frame_world); 编辑器冷启动首帧前无缓存时兜底现算
        fw = getattr(self, '_frame_world', None)
        if fw is None or len(fw) != len(self.models):
            fw = self.compute_world_matrices(self.models)
        aabbs = self._model_aabbs_par(self.models, fw)
        for i, m in enumerate(self.models):
            if not m.visible:
                continue
            ab = aabbs[i]
            if ab is None:
                continue
            (mn, mx) = ab
            t = self._ray_aabb(o, dirv, (mn.x, mn.y, mn.z), (mx.x, mx.y, mx.z))
            if t is not None and t < best_t:
                best_t = t
                best = i
        if best is not None:
            self._select_model(best)   # 点选到物体: 清光源选中 (2026-08-12 修复)

    # ================ gizmo (M9 平移 / M10 旋转) ================
    _GIZMO_AXES = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}
    _GIZMO_COLORS = {'X': (0.9, 0.2, 0.2), 'Y': (0.2, 0.9, 0.2), 'Z': (0.25, 0.4, 0.9)}
    _GIZMO_LEN = 1.5
    _GIZMO_RAD = 1.5
    _GIZMO_SEGS = 48
    _GIZMO_HIT_PX = 10.0

    def _camera_forward(self):
        """相机前方 (+z_view), 从 target 指向 eye 的反方向"""
        yaw, pitch = self.camera_yaw, self.camera_pitch
        return (math.sin(yaw) * math.cos(pitch),
                math.sin(pitch),
                math.cos(yaw) * math.cos(pitch))

    @staticmethod
    def _seg_dist(p, a, b):
        """点 p 到线段 ab 的距离 (屏幕像素空间)"""
        ax, ay = a; bx, by = b; px, py = p
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _gizmo_basis(self, axis):
        """轴 a 法向平面内的正交基 (u, v): u ⊥ a, v = cross(a, u)"""
        a = np.array(self._GIZMO_AXES[axis])
        ref = np.array((0.0, 0.0, 1.0)) if abs(a[2]) < 0.9 else np.array((1.0, 0.0, 0.0))
        u = np.cross(a, ref)
        u = u / np.linalg.norm(u)
        return u, np.cross(a, u)

    def _gizmo_circle_points(self, o, R, u, v):
        """圆环点列 (世界空间, 轴法向平面内)"""
        pts = []
        for i in range(self._GIZMO_SEGS):
            th = 2 * math.pi * i / self._GIZMO_SEGS
            pts.append((o[0] + R * (math.cos(th) * u[0] + math.sin(th) * v[0]),
                        o[1] + R * (math.cos(th) * u[1] + math.sin(th) * v[1]),
                        o[2] + R * (math.cos(th) * u[2] + math.sin(th) * v[2])))
        return pts

    def _gizmo_hit(self, px, py):
        """屏幕点 -> 命中轴 (平移: 轴线段; 旋转: 圆环段) 或 None.
        M21: 点光源可平移不可旋转; 平行光 gizmo 目标为 None."""
        t = self._gizmo_target()
        if t is None:
            return None
        if self.gizmo_mode == 'rotate' and isinstance(t, (LightState, CameraState)):
            return None
        o = self._target_world_pos(self, t)
        best, best_d = None, self._GIZMO_HIT_PX
        if self.gizmo_mode == 'translate':
            L = self._GIZMO_LEN
            oproj = self.project_world(o)
            if oproj is None:
                return None               # 目标在相机背后: gizmo 不可见, 不命中
            ox, oy = oproj
            for axis, (ax, ay, az) in self._GIZMO_AXES.items():
                eproj = self.project_world((o[0] + L * ax, o[1] + L * ay, o[2] + L * az))
                if eproj is None:
                    continue              # 轴端在相机背后: 该轴帽不可见, 不命中
                ex, ey = eproj
                d = self._seg_dist((px, py), (ox, oy), (ex, ey))
                if d < best_d:
                    best_d = d
                    best = axis
        else:
            R = self._GIZMO_RAD
            for axis in self._GIZMO_AXES:
                u, v = self._gizmo_basis(axis)
                pts = self._gizmo_circle_points(o, R, u, v)
                for i in range(self._GIZMO_SEGS):
                    a = self.project_world(pts[i])
                    b = self.project_world(pts[(i + 1) % self._GIZMO_SEGS])
                    if a is None or b is None:
                        continue          # 圆环段在相机背后: 不命中
                    d = self._seg_dist((px, py), a, b)
                    if d < best_d:
                        best_d = d
                        best = axis
        return best

    def _gizmo_ray_plane_hit(self, axis, o, px, py):
        """射线交过 o、法线 = axis 的平面, 返回命中点向量 (或 None)"""
        a = np.array(self._GIZMO_AXES[axis])
        origin, dirv = self._ray_from_mouse(px, py)
        d = np.array(dirv)
        denom = float(np.dot(a, d))
        if abs(denom) < 1e-8:
            return None
        t = float(np.dot(a, np.array(o) - np.array((origin.x, origin.y, origin.z)))) / denom
        return np.array((origin.x, origin.y, origin.z)) + t * d

    def _local_delta(self, m, world_delta):
        """世界增量 -> 局部增量 (除父级旋转+缩放; 根=恒等). 行向量: local = world @ inv(parent3x3)"""
        par3 = self.parent_world_matrix(m)[:3, :3]
        return np.asarray(world_delta, dtype=np.float64) @ np.linalg.inv(par3)

    def _gizmo_drag_apply(self):
        """拖拽中: 平移=世界轴分量转局部增量; 旋转=世界轴增量合成后转局部欧拉.
        M21: 目标可以是点光源 (平移走自身 position, 无父链; 旋转不支持)."""
        t = self._gizmo_target()
        if t is None:
            return
        if self.gizmo_mode == 'translate':
            axis, start_world, start_local = self.gizmo_drag[:3]
            a = np.array(self._GIZMO_AXES[axis])
            origin, dirv = self._ray_from_mouse(*self.view.input_state()['mouse_pos'])
            oo = np.array((origin.x, origin.y, origin.z))
            d = np.array(dirv)
            # 拖拽平面: 过拖拽起点、法线 = 相机视线 (正对相机, 射线几乎垂直穿过, denom 稳定).
            # 旧实现用 cross(axis, view_forward) 当法线 -> 平面永远包含视线方向, 射线与平面近似平行,
            # denom≈0 -> 交点被浮点噪声放大成巨大位移 (视角与轴越接近越严重) -> 物体拖飞.
            n = np.array(self._camera_forward())
            denom = float(np.dot(n, d))
            if abs(denom) < 1e-8:          # 几乎不可能 (射线与视线夹角极小)
                return
            pp = np.array(start_world)
            dist = float(np.dot(n, pp - oo)) / denom
            hit = oo + dist * d
            # 平面命中点投影到拖拽轴: 轴正对相机(∥视线)时 t_axis≈0 拖不动
            # (该轴在屏幕上无投影, 点也是 gizmo 端点小球, 符合直觉; 不再拖飞)
            t_axis = float(np.dot(hit - pp, a))
            new_world = pp + a * t_axis
            # 世界增量 -> 局部增量 (父旋转/缩放逆变换); 光源无父链 = 恒等;
            # 2026-08-16 相机物体化: 摄像机也走 _local_delta (有父时转父空间局部)
            wd = new_world - pp
            ld = wd if isinstance(t, LightState) else self._local_delta(t, wd)
            t.position = Point3D(float(start_local[0] + ld[0]),
                                 float(start_local[1] + ld[1]),
                                 float(start_local[2] + ld[2]))
        else:
            if isinstance(t, (LightState, CameraState)):
                return                       # 光源/摄像机不可旋转 (gizmo_hit 已挡)
            axis, start_world_R, start_local_euler, start_theta = self.gizmo_drag
            u, v = self._gizmo_basis(axis)
            oo = np.array(self.world_position(t))
            hit = self._gizmo_ray_plane_hit(axis, oo, *self.view.input_state()['mouse_pos'])
            if hit is None:
                return
            rel = hit - oo
            theta = math.atan2(float(np.dot(rel, v)), float(np.dot(rel, u)))
            delta_angle = theta - start_theta
            # 世界轴增量旋转矩阵 (行主序)
            a = np.array(self._GIZMO_AXES[axis])
            R_delta = mat4_rotation(np, a[0] * delta_angle, a[1] * delta_angle,
                                    a[2] * delta_angle)
            # 新世界旋转 = 增量 @ 起始世界旋转 (行向量先乘增量)
            new_world_R = R_delta @ np.asarray(start_world_R)
            # 转回局部: 局部旋转 = 新世界旋转 @ inv(父世界旋转)
            par_R = (self.world_rotation_matrix(t.parent)
                     if t.parent is not None else np.eye(4, dtype=np.float64))
            new_local_R = new_world_R @ np.linalg.inv(par_R)
            alpha, beta, gamma = decompose_euler(new_local_R)
            t.rotation = Point3D(alpha, beta, gamma)

    def _gizmo_start_drag(self, axis, px, py):
        """在按下点启动拖拽, 记起点 (世界基准) + 撤销前快照.
        M21: 点光源只走平移; 平行光 gizmo 目标为 None."""
        t = self._gizmo_target()
        if t is None:
            return
        if self.gizmo_mode == 'rotate' and isinstance(t, (LightState, CameraState)):
            return
        self.gizmo_axis = axis
        if self.gizmo_mode == 'translate':
            w = self._target_world_pos(self, t)
            self.gizmo_drag = (axis, w,
                               (t.position.x, t.position.y, t.position.z))
        else:
            oo = np.array(self.world_position(t))
            u, v = self._gizmo_basis(axis)
            hit = self._gizmo_ray_plane_hit(axis, oo, px, py)
            if hit is None:
                return
            rel = hit - oo
            start_theta = math.atan2(float(np.dot(rel, v)), float(np.dot(rel, u)))
            self.gizmo_drag = (axis, np.array(self.world_rotation_matrix(t)),
                               (t.rotation.x, t.rotation.y, t.rotation.z),
                               start_theta)
        self.gizmo_undo_before = (light_snapshot(t) if isinstance(t, LightState)
                                  else camera_snapshot(t) if isinstance(t, CameraState)
                                  else undo_snapshot(t))

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
        consumed = False
        try:
            consumed = ui.dispatch_mouse(
                getattr(self, 'mouse_pos', (0, 0)),
                set(getattr(self, 'pressed', ())),
                set(getattr(self, 'released', ())))
        except Exception:
            consumed = False
        # hover-only 更新 (按钮悬停效果, 无点击时)
        if not consumed:
            try:
                ui.update_hover_only(getattr(self, 'mouse_pos', (0, 0)))
            except Exception:
                pass
        self.ui_consumed = consumed

    def _update_gizmo(self):
        """视口交互: gizmo 拖拽 > 点选. GUI 未抢点击时处理."""
        # 拖拽中: 每帧重算 (左键松开即结束 -> 压撤销栈)
        if self.gizmo_drag is not None:
            if not self.buttons[0]:
                if self.gizmo_undo_before is not None:
                    t = self._gizmo_target()
                    if t is not None:
                        label = "移动" if self.gizmo_mode == 'translate' else "旋转"
                        if isinstance(t, LightState):
                            after = light_snapshot(t)
                            if after != self.gizmo_undo_before:
                                self.undo.push(LightStateCommand(
                                    label, self, t, self.gizmo_undo_before, after))
                        elif isinstance(t, CameraState):
                            after = camera_snapshot(t)
                            if after != self.gizmo_undo_before:
                                self.undo.push(CameraStateCommand(
                                    label, self, t, self.gizmo_undo_before, after))
                        else:
                            after = undo_snapshot(t)
                            if after != self.gizmo_undo_before:
                                self.undo.push(StateCommand(
                                    label, self, t, self.gizmo_undo_before, after))
                self.gizmo_drag = None
                self.gizmo_axis = None
                self.gizmo_undo_before = None
            else:
                self._gizmo_drag_apply()
            return
        # 无拖拽: 只在左键按下帧处理 (Alt 按下时归相机轨道, 不点选)
        if 1 not in self.pressed or self.view.input_state()['click_captured']:
            return
        if getattr(self, 'ui_consumed', False):    # 2026-10-18: UI 命中则跳过 3D 拾取
            return
        if self._mods & pygame.KMOD_ALT:
            return
        pp = self.mouse_press_pos.get(1)
        if pp is None:
            return
        vp = self._layout()[4]
        if not (vp[0] <= pp[0] < vp[0] + vp[2] and
                vp[1] <= pp[1] < vp[1] + vp[3]):
            return
        # gizmo 命中优先于点选
        axis = self._gizmo_hit(pp[0], pp[1])
        if axis is not None:
            self._gizmo_start_drag(axis, pp[0], pp[1])
        else:
            self._pick(pp[0], pp[1])


    def _layout(self):
        """6 元布局 (2026-08-14 晚: 左右/上下分隔条可拖 + 收起).
        面板宽高由 self.panel_* 状态决定, 视图/交互层共读; 保证视口最小宽度."""
        w, h = self.width, self.height
        toolbar = (0, 0, w, 36)
        status = (0, h - 24, w, 24)
        # 左列上下分栏 (M24): 层级在上、资源浏览器在下 (对齐 Unity Project 窗口)
        left_h = h - 60
        max_side = max(24, (w - 120) // 2)   # 每侧最大宽, 保证视口 >= 120
        lw = 24 if self.panel_left_collapsed else max(24, min(max_side, self.panel_left_w))
        rw = 24 if self.panel_right_collapsed else max(24, min(max_side, self.panel_right_w))
        hier_h = int(left_h * self.panel_hier_frac)
        hier_h = max(30, min(left_h - 30, hier_h))
        hierarchy = (0, 36, lw, hier_h)
        resources = (0, 36 + hier_h, lw, left_h - hier_h)
        inspector = (w - rw, 36, rw, left_h)
        viewport = (lw, 36, w - lw - rw, left_h)
        return toolbar, status, hierarchy, inspector, viewport, resources

    # ================ 工具栏 ================

    def _add_primitive(self, typ):
        """添加基元物体 (可撤销)"""
        if self.is_playing:
            return
        from mesh import create_cube, create_plane, create_sphere
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
            from mesh import load_obj
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
        """添加场景光源 (可撤销). kind: 'directional' | 'point' (兼容 'dir')."""
        if self.is_playing:
            return
        # 归一化: 命令层用 'dir' 简写, LightState 认 'directional' —
        # 不归一化会导致 kind 误判 (名字显示"点光源"但实际按平行光渲染)
        kind = 'directional' if kind in ('dir', 'directional') else 'point'
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

    # ================ gizmo 目标 (物体或光源) ================
    def _gizmo_target(self):
        """gizmo 操作目标: 光源/摄像机选中 -> 光源/摄像机 (可平移定位点, 旋转不支持);
        否则物体. 平行光方向走检查器 (3 角度), 位置走 gizmo 平移/检查器 (2026-08-12).
        M41: 摄像机同样可平移 (位置 gizmo), 旋转不支持."""
        light = self._selected_light()
        if light is not None:
            return light
        cam = self._selected_camera()
        if cam is not None:
            return cam
        return self._selected()

    @staticmethod
    def _target_world_pos(engine, t):
        """目标的世界位置: LightState 用自身 position, CameraState 走父链合成
        (相机物体化), ModelState 走父链合成"""
        if isinstance(t, LightState):
            return (t.position.x, t.position.y, t.position.z)
        if isinstance(t, CameraState):
            return engine.camera_world_position(t)
        return engine.world_position(t)

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
        return {"target": list(self.camera_target),
                "distance": self.camera_distance,
                "yaw": self.camera_yaw,
                "pitch": self.camera_pitch}

    def _camera_depth(self, cam):
        """摄像机挂父链深度 (层级树缩进用, 相机物体化 2026-08-16)."""
        depth = 0
        cur = cam.parent
        while cur is not None:
            depth += 1
            cur = cur.parent
        return depth

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
        data = sceneio.scene_to_dict(self, camera=None)
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

    def _apply_camera(self, cam):
        self.camera_target = tuple(cam.get('target', [0, 0, 0]))
        self.camera_distance = cam.get('distance', 10.0)
        self.camera_yaw = cam.get('yaw', 0.6)
        # 2026-08-18: pitch 恢复时 clamp 到俯视范围 [-1.55, 0] —— 网格是 XZ 平面
        # 线框, 仰视/平视时全部在视锥外 (几何上不可见). 用户上次保存的仰视姿态
        # 恢复后编辑器打开即"无网格", 转动时才闪出 (实测根因之一). 运行时拖动
        # 仍可仰视 (编辑自由度), 仅恢复路径修正.
        self.camera_pitch = max(-1.55, min(0.0, cam.get('pitch', -0.35)))

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
        data = sceneio.scene_to_dict(self, camera=self._camera_dict())
        try:
            sceneio.save_json_atomic(path, data)
            print("[编辑器] 场景已保存到", os.path.abspath(path))
            self.mark_saved()    # 保存成功: 更新"已保存"基线
            return path
        except Exception as e:
            print("[编辑器] 保存失败:", e)
            return None

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
        self._scene_path = path
        save_last_dir(STATE_FILE, path)   # 记住这次打开的目录
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print("[编辑器] 加载失败:", e)
            return
        # 清空现有场景 (不压撤销栈: 加载即整体替换)
        for m in list(self.models):
            self.remove_model(m)
        self.undo.clear()
        cam_out = {}
        sceneio.scene_from_dict(self, data, camera_out=cam_out)
        if cam_out:
            self._apply_camera(cam_out)
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
        self.mark_saved()    # 新空场景视为"已保存"基线

    # ================ 撤销/重做 ================
    def _undo_action(self):
        if self.is_playing:
            return
        sel = self._selected()
        guid = sel.guid if sel is not None else None
        self.undo.undo()
        self._reselect(guid)
        self._clamp_light_selection()

    def _redo_action(self):
        if self.is_playing:
            return
        sel = self._selected()
        guid = sel.guid if sel is not None else None
        self.undo.redo()
        self._reselect(guid)
        self._clamp_light_selection()

    def _reselect(self, guid):
        if guid is not None:
            for i, m in enumerate(self.models):
                if m.guid == guid:
                    self._select_model(i)
                    return
        self._clamp_selection()

    def _clamp_selection(self):
        if self.selected_index >= len(self.models):
            self.selected_index = max(0, len(self.models) - 1)

    def _clamp_light_selection(self):
        """撤销/重做后光源选择越界则清空 (M21)"""
        if self.selected_light_index >= len(self.lights):
            self.selected_light_index = -1

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
        self.undo.push(DeleteObjectCommand("删除", self, m))
        self.selected_index = min(self.selected_index, max(0, len(self.models) - 1))

    # ================ UI 命令层 (2026-08-13: UI 模块化) ================
    # UI (IEditorView) 所有"会改变引擎状态"的写操作都走这里 —— 内部统一处理撤销,
    # 面板不直接 push undo. 三种对象 (物体/光源/摄像机) 各配 edit_*(拖拽)/commit_*(单次)
    # 两个入口 + rename_*(名称失焦提交).

    def set_gizmo_mode(self, mode):
        """切换 gizmo 模式 (translate/rotate)."""
        if self.gizmo_mode != mode:
            self.gizmo_mode = mode
            self.gizmo_drag = None
            self.gizmo_axis = None

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

    def add_script(self, m, sid):
        """挂脚本 + 套默认参数 (可撤销)."""
        before = undo_snapshot(m)
        sc = m.add_script(sid)
        import scripts as _scripts
        for key, _lb, default, *_ in _scripts.get_script(sid).params:
            sc.script_vars[key] = default
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
            return
        self.active_camera = cam.guid

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

    def _select_camera(self, cam):
        """选中某摄像机 (统一清光源/物体选中)"""
        self.selected_camera_index = self.cameras.index(cam)
        self.selected_light_index = -1
        self.selected_index = -1

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
            self.is_playing = True
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
            self._dev_cam_active = False     # 开发者相机接管不跨播放会话
            self._dev_cam_moved = False      # 自由移动盖回保护同复位 (重新回玩家视角)
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
            if self._play_edit_cam is not None:
                self.camera_target, self.camera_distance, self.camera_yaw, \
                    self.camera_pitch, self.camera_roll, self.orbit_mode = self._play_edit_cam
                self.apply_orbit_camera()
            self._play_cameras = self._play_camera_snap = None
            self._play_active_camera = self._play_edit_cam = None
            # 6) 清脚本实例 + 全部运行时状态 (2026-08-30 用户实测铁律:
            # "停止播放清除所有状态(包括运动和下落速度)":
            # apply_snapshot 已清 rb.velocity/_colliding + 动画/音频运行态,
            # 此处对无快照体再兜底清一遍 (断链/防御, 含模型的 _colliding 属性)
            for m in self._play_models:
                for sc in m.scripts:
                    inst = getattr(sc, '_script', None)
                    if inst is not None and not getattr(sc, '_script_broken', False):
                        try:
                            inst.on_disable()   # C1: 停止播放 = 脚本实例禁用
                        except Exception as e:
                            print("[脚本] %s.on_disable 出错: %r" % (m.name, e))
                    sc._script = None
                    sc._script_broken = False
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

    # ================ 渲染 (覆写) ================
    def render(self, delta_time):
        # 防御: 上一帧 GUI 若残留 scissor 裁剪, 会框住本帧的 clear/场景 (残影 bug)
        self.ctx.scissor = None
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
        # 核心任务流水线彻底解耦 (2026-10-01):
        # 仅在 Qt 宿主激活异步线程 (_external_ctx=True) 时由独立逻辑流水线推进;
        # 无头探针/直调测试环境 (_external_ctx=False) 由主线程同步推进 (防无头死锁)。
        is_async_active = getattr(self, '_logic_async', False) and getattr(self, '_external_ctx', False)
        if not is_async_active and not getattr(self, '_advanced_this_frame', False):
            _t = self._prof_t0()
            self.advance_logic(delta_time)
            self._prof_add('mt_render_advance', _t)
        self._advanced_this_frame = False   # 消费本帧标记
        # 编辑态插值失同步修复 (2026-09-06): 物体被直接改位 → 快照对齐
        self._consume_xform_gen()

        # 核心解耦: 播放态与编辑态渲染数据流水线彻底分流
        it = getattr(self, '_interp', None)
        if getattr(self, 'is_playing', False) and it is not None:
            # 播放态流水线: 渲染帧只算插值世界矩阵 (C 原生 interp_world 极速路径直出)
            # 逻辑世界矩阵复用逻辑流水线产物，消除每帧 500 物体的重复双重重算!
            if (getattr(self, '_render_world', None) is not None
                    and it.static_frame()):
                pass
            else:
                self._render_world = self._profile(
                    'interp', lambda: self.compute_render_matrices(self.models))
            if getattr(self, '_frame_world', None) is None:
                self._frame_world = self._render_world
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
        self._profile('shadow_prep', lambda: self._parallel_shadow_and_collision(
            delta_time, with_events=self.is_playing))
        # A2 (2026-08-29): 当帧实例数据准备 (f32 矩阵 + 桶重排 + 桶级实例缓冲),
        # 阴影/主 pass 共享 (逐物体 uniform/upload 循环已取消)
        self._profile('buckets', lambda: self._prepare_bucket_frame())
        # M29: 先画完全部阴影贴图, 主 pass 再采样到物理遮挡
        _t = self._prof_t0()
        self._render_shadow_maps()
        self._prof_add('mt_shadow_maps', _t)

        _t_mp = self._prof_t0()
        _t = _t_mp
        self._screen_fb().use()
        self._clear_main_fbo(0.10, 0.12, 0.16, 1.0)
        self._prof_add('mt_mp_fbo', _t)
        # MVP (轨道相机已由 engine.render 逻辑处理, 但此处复算供 gizmo/拾取用)
        # M41: "用此相机预览"时每帧重应用该摄像机 (含 roll), 拖 gizmo 实时跟
        # ★2026-09-06 相机统一 (用户定案): 播放态 = 编辑态同一轨道相机 —
        # 除"用此相机预览"外全部走 apply_orbit_camera 从
        # (target, yaw, pitch, distance) 合成。旧播放态三分支 (挂父相机盖回/
        # _dev_cam_moved 保护/开发者轨道接管) 随双轨制一并删除 — 玩家脚本
        # 不再写相机, 无双驱动源, WASD/滚轮/右键语义与编辑态完全一致。
        _t = self._prof_t0()
        if self.preview_camera is not None:
            self.apply_camera(self.preview_camera)
        elif self.is_playing or self.orbit_mode:
            self.apply_orbit_camera()
        V = mat4_view_yaw_pitch(np, (self.camera.x, self.camera.y, self.camera.z),
                                self.camera_yaw, self.camera_pitch, self.camera_roll)
        P = mat4_perspective(np, self._fov, self.width / self.height, self.near, self.far)
        self._vp = V @ P
        self._prof_add('mt_mp_camera', _t)
        _t = self._prof_t0()
        self.prog['u_view_proj'].write(np.ascontiguousarray(self._vp, dtype='f4').tobytes())
        self._upload_lights()                     # M21: 多光源 uniform 整块上传
        self.prog['u_view_pos'].value = (self.camera.x, self.camera.y, self.camera.z)
        self._prof_add('mt_mp_uniforms', _t)

        # 场景模型 (A2: 实例化批绘制, 桶已在 _prepare_bucket_frame 备好)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.CULL_FACE)
        _t = self._prof_t0()
        self._draw_main_buckets()
        self._prof_add('mt_mp_draws', _t)
        self._prof_add('mt_main_pass', _t_mp)

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
        if not self._external_ctx:      # 外部模式: 宿主 (QOpenGLWidget) 自动交换缓冲
            # 2026-10-18 A2: GLFW swap（原 pygame.display.flip）
            self._glfw_swap_buffers()
        self._prof_add('mt_render_tail', _t)
        self._prof_add('mt_render_total', _t_render)

    def grid_geometry(self):
        """无限网格 (2026-08-14): 相机 XZ 为中心 (吸附整数格), 恒定步长, 远处淡出.
        范围只随相机距离 (缩放) 变化, 不随抬头角度; 永不返回 None. 视图层调用."""
        try:
            from ui.grid import build_grid_lines
            return build_grid_lines(
                (self.camera.x, self.camera.y, self.camera.z),
                cam_dist=getattr(self, 'camera_distance', None))
        except Exception:
            return None

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
        with self.ctx.scope(framebuffer=self._screen_fb(), enable_only=0):
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
                self._undo_action()
                return True
            if (ev.key == pygame.K_y) and (ev.mod & pygame.KMOD_CTRL):
                self._redo_action()
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

    def _in_viewport(self, pos):
        vp = self._layout()[4]
        return (vp[0] <= pos[0] < vp[0] + vp[2] and
                vp[1] <= pos[1] < vp[1] + vp[3])

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
        # 2026-10-18: UI 鼠标事件分发 (在相机/3D 消费之前). 两条路径 (pygame 主循环
        # 与 Qt loom_gui) 都走本方法, 所以这里是唯一的插入点.
        self._dispatch_ui_mouse()
        if self.preview_camera is not None:
            return
        # UI 命中并消费鼠标 -> 跳过全部鼠标相机控制 (决策3=B, 键盘 WASD 不受影响)
        # 2026-10-18 D1: UI 命中时只锁鼠标 (滚轮/拖拽), 键盘 WASD 不受影响.
        _ui_lock = bool(getattr(self, 'ui_consumed', False))
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
        if (not _ui_lock and self.mouse_wheel
                and self._in_viewport(self.mouse_pos)):
            self.camera_distance = max(0.5, min(200.0,
                self.camera_distance * math.exp(-self.mouse_wheel * 0.1)))

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
            # 转动视角: 右键(激活) 或 Alt+左 / 中键(无 Shift)
            # 上下方向: 向上拖 pitch 增大 (相机上抬看顶, 与方向键一致) —— 2026-08-12 翻正
            elif self._right_drag_view or (left and alt) or (mid and not shift):
                self.camera_yaw += dx * 0.01
                self.camera_pitch = max(-1.55, min(1.55, self.camera_pitch - dy * 0.01))
        elif self._right_drag_view:
            # 右键按下在视口内, 拖出视口仍继续转视角 (Unity 风格)
            self.camera_yaw += dx * 0.01
            self.camera_pitch = max(-1.55, min(1.55, self.camera_pitch - dy * 0.01))

        # 键盘平移 target / 方向键轨道 (输入框失焦时)
        # ★2026-09-06 相机统一 (用户定案): 播放态 = 编辑态同一套轨道相机逻辑
        # — WASD/QE 平移 camera_target, 方向键转视角, apply_orbit_camera 每帧
        # 从 (target, yaw, pitch, distance) 合成位姿。旧"播放态自由相机移
        # camera 本体"双轨制与玩家脚本相机写回互冲 (双驱动源) = 开发者相机
        # 移动 BUG 总根, 已随脚本相机接管一并删除。
        if self.view.input_state()['focus_id'] is None:
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
