# -*- coding: utf-8 -*-
"""loom_model_gpu.py — GLEngine 模型/材质 GPU 资源子系统。

从 engine.py 抽出 (作为 ModelGpuMixin 供 GLEngine 继承):
  add_model / add_material / _find_material / _register_model_material
  attach_model / _mesh_key / _flatten_mesh
  _build_gpu / _build_bucket_geo / _grow_bucket_inst / _build_bucket_vaos
  _release_bucket_resources
  remove_model / remove_subtree / clear_scene / load_scene

依赖宿主 GLEngine 运行时提供 (mixin 只通过 self 按需访问, 语义与拆分前逐位一致):
  self.models / self.materials / self.current_model_index
  self.ctx / self.prog / self._shadow_prog / self.view
  self._bucket_geo / self._bucket_inst / self._fw32 / self._render_buckets / self._bb_cache
  self.lights / self.cameras / self.active_camera / self._clock / self._interp
  self._render_world / self._prep_sig / self._prep_pairs / self._disp_gen
  self._bump_struct / self.collect_subtree / self.set_camera_parent
"""
import json
import uuid

import numpy as np

from loom_game_object import GameObject
from loom_material import Material
from loom_color import _hex_rgba


class ModelGpuMixin:
    # ================ GPU 几何构建 ================
    def add_model(self, mesh, position, rotation, normal_mode='flat',
                  name=None, scale=None, visible=True, color=None, saturation=1.0):
        """
        添加模型并一次性上传展平几何到 VBO.
        normal_mode: 'flat' 用面法线 (平直光照, 立方体), 'vertex' 用顶点径向法线 (光滑光照, 球体)
        name/scale/visible/color: 编辑器扩展属性 (color 为 hex 时覆盖网格面色为单色材质)
        saturation: 终色饱和度 0..2 (0=灰阶, 1=原始, >1=增艳)
        """
        model = GameObject(mesh, position, rotation,
                           name=name, scale=scale, visible=visible,
                           primitive=getattr(mesh, 'primitive', None),
                           params=getattr(mesh, 'params', None),
                           color=color, normal_mode=normal_mode,
                           saturation=saturation)
        if model.name is None:
            # 自动命名: 按基元类型 (编辑器场景) / 网格种类 (默认场景)
            prim = model.primitive
            model.name = {None: '物体', 'cube': '立方体', 'sphere': '球体',
                          'plane': '平面'}.get(prim, '物体')
        # 稳定身份 (M16): 每个物体一个 GUID, 场景/Prefab 引用用
        if model.guid is None:
            model.guid = uuid.uuid4().hex
        self._build_gpu(model)
        self._register_model_material(model)   # M23: 材质进库, 供共享引用
        self.models.append(model)
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        return model

    # ================ 材质库管理 (M23) ================
    def add_material(self, color=None, saturation=1.0, name=None, guid=None):
        """新建材质并加入材质库 (供物体共享引用). 返回 Material."""
        mat = Material(color=color, saturation=saturation, name=name, guid=guid)
        self.materials.append(mat)
        return mat

    def _find_material(self, guid):
        """按 guid 在材质库找材质 (找不到返回 None)."""
        if guid:
            for mat in self.materials:
                if mat.guid == guid:
                    return mat
        return None

    def _register_model_material(self, model):
        """把物体自带的材质登记进材质库 (未在库中则加入), 保证共享可被引用."""
        mat = model.renderer.material
        if mat is not None and mat not in self.materials:
            self.materials.append(mat)

    def attach_model(self, model, index=None):
        """重新挂载已存在的 GameObject (撤销删除/Prefab 实例化): 重建 GPU 几何并加入列表."""
        if model.vbo is None or model.vao is None:
            self._build_gpu(model)
        if index is None:
            self.models.append(model)
        else:
            self.models.insert(index, model)
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        return model

    @staticmethod
    def _mesh_key(model):
        """A2 (2026-08-29): GL 桶键 = (基元类型, 参数 json, 法线模式) + M36 贴图 guid.
        与桶几何共享判据; 同键物体共享 vbo/vao/实例缓冲 (50 球 = 1 桶).
        组1 (2026-08-30): 几何键缓存挂 GameObject (_bucket_key, setter 置脏) ——
        每帧 json.dumps(params) 降为创建后一次.
        M36 (2026-10-14): 材质 albedo guid 作为第 4 分量 —— 材质是共享资产, 物体
        缓存感知不到材质变化, 故该分量每帧从 model 现取 (属性链廉价); 贴图变时
        材质 bump _appearance_gen -> 分组缓存失配 -> 重新分组拿到新键."""
        base = getattr(model, '_bucket_key', None)
        if base is None or len(base) != 3:    # 3 元组=GL 几何键 (Vk 键 2 元组, 拒收防串)
            base = (getattr(model, 'primitive', None) or 'obj',
                    json.dumps(getattr(model, 'params', None) or {}, sort_keys=True),
                    getattr(model, 'normal_mode', 'flat'))
            try:
                model._bucket_key = base
            except AttributeError:
                pass                          # __slots__ 桩等不可写场景
        mat = getattr(getattr(model, 'renderer', None), 'material', None)
        tex_guid = getattr(mat, '_tex_guid', '') if mat is not None else ''
        nrm_guid = getattr(mat, '_nrm_guid', '') if mat is not None else ''
        # M36 PBR: 材质级 PBR 参数进桶键 (同桶材质一致; 材质 bump 触发重分组)
        pbr = (round(getattr(mat, '_metallic', 0.0), 4),
               round(getattr(mat, '_roughness', 0.5), 4),
               1 if getattr(mat, '_pbr', False) else 0) if mat is not None else (0.0, 0.5, 0)
        env_guid = getattr(mat, '_env_guid', '') if mat is not None else ''
        return base + (tex_guid, nrm_guid, pbr, env_guid)

    @staticmethod
    def _flatten_mesh(mesh, normal_mode):
        """网格 -> 展平 (3F,12) f4 [pos3+normal3+color4+uv2] + positions-only
        (3F,3) f4 (阴影 VAO 用). 颜色 = 网格原生面色 (材质单色覆盖改走实例属性
        a_col, 桶共享几何必须与物体解耦 —— 与 Vk 桶语义一致)."""
        verts = np.asarray(mesh.vertices, dtype='f4')       # (V,3)
        faces = np.asarray(mesh.faces, dtype=np.int32)      # (F,3)
        tri = verts[faces]                                  # (F,3,3)
        pos = tri.reshape(-1, 3)                            # (3F,3)

        mesh_normals = getattr(mesh, 'normals', None)
        if mesh_normals is not None and len(mesh_normals) == len(verts):
            # 外部网格 (obj 导入) 自带逐顶点法线 (来自 vn 或自动平滑): 直接采用,
            # 不再按 normal_mode 重算 —— Unity 语义: 导入法线优先于 flat/vertex 模式.
            vn_arr = np.asarray(mesh_normals, dtype='f4')   # (V,3)
            norm = vn_arr[faces].reshape(-1, 3)             # (3F,3)
        elif normal_mode == 'vertex':
            # 顶点径向法线: 每顶点归一化 (球心在原点) -> 展平
            ln = np.linalg.norm(verts, axis=1, keepdims=True)
            ln = np.where(ln == 0, 1.0, ln)
            vn = verts / ln
            norm = vn[faces].reshape(-1, 3)                 # (3F,3)
        else:
            # 面法线: 每三角形叉积归一 -> 按 3 顶点重复
            p0, p1, p2 = tri[:, 0], tri[:, 1], tri[:, 2]
            nrm = np.cross(p1 - p0, p2 - p0)                # (F,3)
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            ln = np.where(ln == 0, 1.0, ln)
            nrm = nrm / ln
            norm = np.repeat(nrm, 3, axis=0)                # (3F,3)

        colors = np.zeros((len(face_colors := mesh.face_colors), 4), dtype='f4')
        for i, c in enumerate(face_colors):
            colors[i] = _hex_rgba(c)
        col = np.repeat(colors, 3, axis=0)                  # (3F,4)
        # M36 贴图: UV 展平 (无 uvs -> 全零; 采样恒取纹理原点)
        mesh_uvs = getattr(mesh, 'uvs', None)
        if mesh_uvs is not None and len(mesh_uvs) == len(verts):
            uv_arr = np.asarray(mesh_uvs, dtype='f4')       # (V,2)
            uv = uv_arr[faces].reshape(-1, 2)               # (3F,2)
        else:
            uv = np.zeros((len(pos), 2), dtype='f4')
        packed = np.concatenate([pos, norm, col, uv], axis=1)   # (3F,12)
        return packed.astype('f4'), pos.astype('f4')

    def _build_gpu(self, model):
        """从 model.mesh 绑定桶几何资源 (add_model 与 attach_model 共用).
        A2 (2026-08-29): 几何按 mesh 桶共享 (同键 = 同 vbo/vao/实例缓冲), 物体
        只是"引用"桶资源 —— 删除单物体只解引用, 不释放共享资源 (归属桶, 清场
        统一释放, 见 _release_bucket_resources).
        2026-08-21: Qt 外部模式 UI 回调 (添加物体/导入) 里建 GL 资源前要求
        context current —— QOpenGLWidget 非 paintGL 时机不自动 makeCurrent,
        未激活时 moderngl 资源静默落错 context (VAO 有效但渲染零输出, 用户
        实测"空场景启动后添加物体不显示"). 由视图注入 _gl_guard 钩子."""
        guard = getattr(getattr(self, 'view', None), '_gl_guard', None)
        if guard is not None:
            guard()
        key = self._mesh_key(model)
        ent = self._bucket_geo.get(key)
        if ent is None:
            ent = self._build_bucket_geo(key, model)
        model.vbo = ent['vbo']
        model.vao = ent['vao']
        model._shadow_vbo = ent['sha_vbo']
        model._shadow_vao = ent['sha_vao']
        model.n_vertices = ent['nv']

    def _build_bucket_geo(self, key, model):
        """桶级几何 + 实例缓冲 (初容量 64) + VAO (主 pass 6 属性 / shadow 4 实例属性)."""
        packed, pos = self._flatten_mesh(model.mesh, model.normal_mode)
        vbo = self.ctx.buffer(packed.tobytes())
        sha_vbo = self.ctx.buffer(pos.tobytes())
        ent = {'vbo': vbo, 'sha_vbo': sha_vbo, 'nv': pos.shape[0],
               'vao': None, 'sha_vao': None}
        self._bucket_geo[key] = ent
        self._bucket_inst[key] = {'main': None, 'sha': None, 'n': 0}
        self._grow_bucket_inst(key, 64)
        return ent

    def _grow_bucket_inst(self, key, k):
        """桶级实例缓冲生长: main 96B/实例 (world 16 + sat 4 + color 4), sha 64B
        (world 16). 容量变化 → 重建 VAO (VAO 绑定缓冲对象, 换缓冲必须重建).
        组1: stage (CPU 侧 staging) 一并作废, 下帧按新 cap 重建.
        GC 批: gather 缓冲 (inst['gath']) 一并作废 (与 stage 同寿命)."""
        ent = self._bucket_geo[key]
        inst = self._bucket_inst[key]
        if k <= inst['n'] and inst['main'] is not None:
            return
        cap = max(64, int((k + 15) // 16 * 16))
        inst['main'] = self.ctx.buffer(reserve=cap * 96, dynamic=True)
        inst['sha'] = self.ctx.buffer(reserve=cap * 64, dynamic=True)
        inst['n'] = cap
        inst.pop('stage', None)               # 组1: 旧 staging 作废 (容量已变)
        inst.pop('gath', None)                # GC 批: gather 缓冲一并作废 (容量已变)
        self._build_bucket_vaos(ent, inst)

    def _build_bucket_vaos(self, ent, inst):
        """桶 VAO: 顶点 (位置/法线/颜色) + 实例属性 (格式串尾部 /i = 每实例 divisor;
        moderngl 多属性实例=同一格式串依次排布 offset, 尾部单 /i 整串生效)."""
        ent['vao'] = self.ctx.vertex_array(
            self.prog,
            [(ent['vbo'], '3f 3f 4f 2f', 'in_pos', 'in_normal', 'in_color', 'in_uv'),
             (inst['main'], '4f 4f 4f 4f 4f 4f/i',
              'a_w0', 'a_w1', 'a_w2', 'a_w3', 'a_sat', 'a_col')])
        # M29: 阴影 pass 专用 VAO —— moderngl VAO 与创建程序绑定, 不能复用主 VAO;
        # 阴影程序只有 in_pos, 用独立 positions-only VBO (紧凑 '3f') + 实例 world.
        ent['sha_vao'] = self.ctx.vertex_array(
            self._shadow_prog,
            [(ent['sha_vbo'], '3f', 'in_pos'),
             (inst['sha'], '4f 4f 4f 4f/i',
              'a_w0', 'a_w1', 'a_w2', 'a_w3')])

    def _release_bucket_resources(self):
        """清场/重建时释放全部桶资源 (共享几何+实例缓冲+VAO)."""
        if getattr(self, '_bucket_geo', None) is None:
            return                    # 测试桩 (__new__ 不跑 __init__) 无桶状态
        for ent in self._bucket_geo.values():
            for name in ('vao', 'sha_vao', 'vbo', 'sha_vbo'):
                r = ent.get(name)
                if r is not None:
                    try:
                        r.release()
                    except Exception:
                        pass
            ent['vao'] = ent['sha_vao'] = None
        for inst in self._bucket_inst.values():
            for name in ('main', 'sha'):
                r = inst.get(name)
                if r is not None:
                    try:
                        r.release()
                    except Exception:
                        pass
            inst['main'] = inst['sha'] = None
            inst.pop('stage', None)           # 组1: staging 一并清
            inst.pop('gath', None)            # GC 批: gather 缓冲一并清 (与 stage 同寿命)
        self._bucket_geo.clear()
        self._bucket_inst.clear()
        self._fw32 = None
        self._render_buckets = []

    def remove_model(self, model):
        """删除单个模型: 释放 GPU 资源、解除父链引用并从列表移除.
        2026-08-16 相机物体化: 先脱掉挂在本物体下的摄像机 (世界不跳)."""
        for cam in list(getattr(model, 'camera_children', [])):
            self.set_camera_parent(cam, None, preserve_world=True)
        if model in self.models:
            # C1 (2026-10-16): 物体销毁前派发 on_destroy (obj 仍可读终态;
            # remove_subtree/clear_scene/load_scene 均经本函数, 天然覆盖).
            for sc in model.scripts:
                inst = getattr(sc, '_script', None)
                if inst is not None and not getattr(sc, '_script_broken', False):
                    try:
                        inst.on_destroy()
                    except Exception as e:
                        print("[脚本] %s.on_destroy 出错: %r" % (model.name, e))
            # A2 (2026-08-29): 几何/实例缓冲归 mesh 桶共享 (桶内其他物体还在用),
            # 单物体删除只解除引用; 共享资源由 _release_bucket_resources 统一释放
            # (清场景时). undo.attach_model 依据 vbo is None 重挂会重新解析桶.
            model.vbo = None
            model.vao = None
            model._shadow_vao = None
            model._shadow_vbo = None
            self.models.remove(model)
            self._bump_struct()                # 组3: 结构变更失效 (ancestry+SoA)
        # M23: 材质若不再被任何物体引用 -> 从材质库移除 (避免孤儿堆积)
        mat = model.renderer.material
        if mat is not None and mat in self.materials:
            if not any(other is not model and other.renderer.material is mat
                       for other in self.models):
                self.materials.remove(mat)
        if model.parent is not None:
            if model in model.parent.children:
                model.parent.children.remove(model)
            model.parent = None
        if self.current_model_index >= len(self.models):
            self.current_model_index = max(0, len(self.models) - 1)

    def remove_subtree(self, root):
        """删除 root 及其全部子孙 (M14: 删除物体/撤销 redo 用).
        2026-08-16 相机物体化: 先脱掉整棵子树上挂的摄像机 (父链完整, 世界不跳),
        再逐个删节点."""
        sub = list(self.collect_subtree(root))
        for m in sub:
            for cam in list(getattr(m, 'camera_children', [])):
                self.set_camera_parent(cam, None, preserve_world=True)
        for m in sub:
            self.remove_model(m)

    def clear_scene(self):
        """清空全部模型 (M16: 新建/加载场景用)"""
        for m in list(self.models):
            self.remove_model(m)
        self.models.clear()
        self._bump_struct()                    # 组3: 结构变更失效 (ancestry+SoA)
        self.materials.clear()               # M23: 材质库随场景一起清空
        bb = getattr(self, '_bb_cache', None)
        if bb is not None:
            bb.clear()                       # 网格顶点缓存随场景清空
        self._release_bucket_resources()     # A2: 桶共享几何/实例缓冲统一释放
        self.current_model_index = 0

    def load_scene(self, path):
        """M37/M38: 运行时切换到另一个场景文件 (Unity SceneManager.LoadScene 式).
        清空当前场景 + 加载新场景 (物体/光源/摄像机/材质). 支持明文 JSON 与
        混淆场景 (LOOMSC1, 自动解密). 返回是否成功.
        供脚本/菜单运行时换关卡 (菜单场景 -> 游戏场景)."""
        import sceneio as _sio
        data = _sio.load_scene_data(path)
        if not isinstance(data, dict):
            return False
        self.clear_scene()
        self.lights.clear()
        self.cameras.clear()
        self.active_camera = None
        _sio.scene_from_dict(self, data)
        # 分离批1/2: 换场景边界对齐 (清累积器; 快照重抓加载位姿, 首帧不插值)
        clk = getattr(self, '_clock', None)
        if clk is not None:
            clk.reset()
        it = getattr(self, '_interp', None)
        if it is not None:
            it.advance()      # curr = 加载瞬间位姿
            it.align()        # prev = curr
        if hasattr(self, '_render_world'):
            self._render_world = None       # 强制重算渲染矩阵
        if hasattr(self, '_prep_sig'):
            self._prep_sig = None           # 批5: prep 缓存强制失效
            self._prep_pairs = None         # ★09-07: 换场景清陈旧对缓存
                                            # (旧场景下标派发进新场景 = IndexError)
            self._disp_gen = -1
        return True
