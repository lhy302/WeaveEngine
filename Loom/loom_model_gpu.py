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
    # 2026-11-17 (S2-2): add_model / attach_model / add_material / _find_material /
    # _register_model_material 已搬进 loom_model_data.ModelDataMixin（数据面进内核，
    # GPU 上传走 _backend_upload_model 钩子）。本类只剩真正的 GPU 侧实现。

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

    # 2026-11-18（S4）：remove_model 已收进 EngineCore（两端共用一份，含子树递归
    # 与 on_destroy 派发）。本类只保留 _remove_one_model —— 那才是 GL 的后端部分
    # （解 vbo/vao 引用、桶资源共享释放）。

    def _remove_one_model(self, model):
        """删除单个节点 (内部; remove_subtree 逐节点调用).
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
                    # 2026-10-18 协程：物体销毁时显式清理（generator 的 finally 触发）
                    if hasattr(inst, 'stop_all_coroutines'):
                        try:
                            inst.stop_all_coroutines()
                        except Exception as e:
                            print("[脚本] %s.stop_all_coroutines 出错: %r"
                                  % (model.name, e))
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
        # P-10 兜底: 若仍挂着子物体 (父链即将悬空), 提升为根 —— 批量矩阵与
        # model_world_matrix 对"父不在 models"的语义必须一致。remove_model
        # 正常路径已委托 remove_subtree, 这里只服务 remove_subtree 的逐节点
        # 删除 (父先删时子还挂在它下面) 与外部直调 _remove_one_model 的场景。
        for ch in list(getattr(model, 'children', ())):
            if ch is not model and ch in self.models:
                try:
                    self.set_parent(ch, None, preserve_world=False)
                except Exception:
                    ch.transform.parent = None
        if self.current_model_index >= len(self.models):
            self.current_model_index = max(0, len(self.models) - 1)

    # ★S4（2026-11-18）：remove_subtree / clear_scene / load_scene 的**公共面**已搬进
    # engine_core.EngineCore（两端同一份）。本 mixin 只留 GL 后端的两件事：
    #   · _backend_scene_cleared ：清场景时释放桶共享几何/实例缓冲（原 clear_scene 尾段）；
    #   · _load_scene_data       ：sceneio.scene_from_dict 装配（原 load_scene 的装配段）。
    # 逐节点删除的 GL 实现仍在本文件的 _remove_one_model（remove_subtree 调它）。
    def _backend_scene_cleared(self):
        """场景数据清空后调（GL）：释放桶共享几何/实例缓冲（A2）。"""
        self._release_bucket_resources()     # A2: 桶共享几何/实例缓冲统一释放

    def _load_scene_data(self, data, base_dir=None):
        """GL 侧场景装配：**先过场景契约闸门+迁移** → 清场景 → 重置光源/相机 →
        sceneio.scene_from_dict → 时钟对齐。

        逐行照搬原 load_scene 的装配段（行为零变化），只加两处**已证明是缺陷**的修复：
          · B7-16（R5）：prepare() 必须在 clear_scene **之前**。旧顺序是"先清空再让
            scene_from_dict 内部迁移/校验"，于是加载更高版本场景失败时 GL 把当前场景
            清空了、VK 保留 —— 同一个失败两端用户可见结果不同。
          · B7-16（R7）：base_dir 现在**传下去**。旧实现故意忽略它，于是 GL 从别的 CWD
            启动时按 CWD 解析天空盒相对路径（找不到图 -> 回退默认蓝），而 VK 按场景
            目录解析成功。runtime.PlayerApp 初始化那条路本来就传 base_dir，GL 的
            load_scene 不传才是分叉；补传 = 让 GL 的两条路一致，不是新增语义。
        """
        import sceneio as _sio
        # 场景契约唯一入口（闸门 + 迁移）：任何状态变更之前（R5）
        data = _sio.prepare(data)
        self.clear_scene()
        self.lights.clear()
        self.cameras.clear()
        self.active_camera = None
        _sio.scene_from_dict(self, data, base_dir=base_dir)
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
