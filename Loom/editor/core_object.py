# -*- coding: utf-8 -*-
"""editor/core_object.py — 场景对象增删与层级：基元与 obj 导入、光源/相机增删、复制删除、显隐、新建材质、挂父摘父、层级树、种子场景。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：场景对象增删与层级：基元与 obj 导入、光源/相机增删、复制删除、显隐、新建材质、挂父摘父、层级树、种子场景。
我不负责：属性面板字段命令（core_inspector）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
import math
import os
from engine import (GLEngine, Point3D, LightState, CameraState, wrap_deg,
                    gc_play_enter, gc_play_exit)
from mathlib.mesh import create_cube, create_plane, create_sphere, spec_to_mesh
from editor.undo import (UndoManager, Command, StateCommand, AddObjectCommand,
                  DeleteObjectCommand, ReparentCommand, DuplicateObjectCommand,
                  PrefabPlaceCommand, snapshot as undo_snapshot,
                  apply_snapshot,
                  LightStateCommand, AddLightCommand, DeleteLightCommand,
                  AddMaterialCommand, light_snapshot, apply_light_snapshot,
                  CameraStateCommand, AddCameraCommand, DeleteCameraCommand,
                  ReparentCameraCommand,
                  camera_snapshot, apply_camera_snapshot)
import filedialog

class EditorObjectMixin(object):
    """场景对象增删与层级：基元与 obj 导入、光源/相机增删、复制删除、显隐、新建材质、挂父摘父、层级树、种子场景（纯搬迁）。"""

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
