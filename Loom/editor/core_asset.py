# -*- coding: utf-8 -*-
"""editor/core_asset.py — 项目资产库：项目根与资产上下文定位、导入、扫描、资产数据面、查找、拖放落场景、材质与网格资产落盘、Prefab 保存与实例化。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：项目资产库：项目根与资产上下文定位、导入、扫描、资产数据面、查找、拖放落场景、材质与网格资产落盘、Prefab 保存与实例化。
我不负责：视口布局（core_viewport）；场景文档落盘（core.py/core_scene）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
from editor.core_contract import APP_DIR, _PREFAB_FILTER, unique_default_name
import json
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
import sceneio
import filedialog

class EditorAssetMixin(object):
    """项目资产库：项目根与资产上下文定位、导入、扫描、资产数据面、查找、拖放落场景、材质与网格资产落盘、Prefab 保存与实例化（纯搬迁）。"""

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

    # ================ 资源浏览器 (M24) ================
    # 列出 assets/ 下的网格/材质/Prefab, 点选预览, 拖到视口/物体上复用 (像 Unity Project 窗口).
    # 数据流: _scan_assets 只列文件名 (不逐帧读 JSON); 选中/拖放时 _asset_data 惰性读.
    # 跨文件引用统一走 guid: 材质资产带 guid, 应用时 _find_material 命中即共享复用.
    _BUILTIN_MESHES = (
        ('cube', '立方体', {}),
        ('sphere', '球体', {'radius': 1.0, 'stacks': 14, 'slices': 28}),
        ('plane', '平面', {'width': 8.0, 'depth': 8.0}),
    )
