# -*- coding: utf-8 -*-
"""loom_model_data.py — 模型 / 材质 / 光源的**数据面**（后端无关，两端同一份）。

2026-11-17（S2-2 门面收敛 / JVM 模型）：`add_model` / `attach_model` / `add_material` /
`find_model_by_guid` 原来长在 GL 侧（`ModelGpuMixin` / `LightingMixin`），
但它们**真正碰 GPU 的只有一行** `self._build_gpu(model)` —— 其余全是数据操作
（建 GameObject、命名、guid、材质库、models 列表、结构失效）。

于是拆成两半：
  · **数据面**（本文件）进内核 → 两端共享同一份；
  · **GPU 上传**留在后端 → 通过钩子 `_backend_upload_model(model)` 调，默认无操作。

为什么 VK 不需要上传：VK 的渲染器（`vk_renderer.draw_frame`）每帧按
`_mesh_key(model)` 从 `model.mesh` 现建/复用实例缓冲，没有「每物体持久 VBO」这个架构。
所以 VK 侧钩子是空操作，**但语义完全一致**（物体出现在 models 里就出现在画面上）。

纪律：本文件**不许**出现 moderngl / wgpu / 着色器 / VBO / VAO / 纹理（门会检查）。
"""

from scene.identity import new_guid   # Q-B7-49-1 P2: guid 唯一真源（uuid4 只许在 identity.py）




class ModelDataMixin:

    # ================ 后端钩子（唯一的 GPU 接触点） ================
    def _backend_upload_model(self, model):
        """后端钩子：GL 建 VBO/VAO 并登记桶资源；VK 无操作（每帧现建）。
        这是「后端差异只允许出现在这一处」的具体形状。"""
        fn = getattr(self, '_build_gpu', None)
        if callable(fn):
            fn(model)

    def _struct_bump(self):
        """结构变更失效（ancestry 缓存 + SoA 快照）。GL 侧是 `_bump_struct`；
        VK 没有这些缓存，调不到就跳过。"""
        fn = getattr(self, '_bump_struct', None)
        if callable(fn):
            fn()

    # ================ 模型 ================
    def add_model(self, mesh, position, rotation, normal_mode='flat',
                  name=None, scale=None, visible=True, color=None, saturation=1.0):
        """添加模型。**数据面**在内核；GPU 上传交给后端钩子。

        normal_mode: 'flat' 面法线（立方体）/ 'vertex' 顶点径向法线（球体）
        name/scale/visible/color: 编辑器扩展属性（color 为 hex 时覆盖为单色材质）
        saturation: 终色饱和度 0..2（0=灰阶, 1=原始, >1=增艳）
        """
        from engine import GameObject            # 惰性：避免 engine ↔ 内核循环导入
        model = GameObject(mesh, position, rotation,
                           name=name, scale=scale, visible=visible,
                           primitive=getattr(mesh, 'primitive', None),
                           params=getattr(mesh, 'params', None),
                           color=color, normal_mode=normal_mode,
                           saturation=saturation)
        if model.name is None:
            prim = model.primitive
            model.name = {None: '物体', 'cube': '立方体', 'sphere': '球体',
                          'plane': '平面'}.get(prim, '物体')
        if model.guid is None:
            model.guid = new_guid()   # Q-B7-49-1 P2: 唯一真源 scene.identity
        self._backend_upload_model(model)        # ← 唯一 GPU 接触点
        self._register_model_material(model)
        self.models.append(model)
        self._struct_bump()
        return model

    def attach_model(self, model, index=None):
        """重新挂载已存在的 GameObject（撤销删除 / Prefab 实例化）。"""
        if getattr(model, 'vbo', None) is None or getattr(model, 'vao', None) is None:
            self._backend_upload_model(model)
        if index is None:
            self.models.append(model)
        else:
            self.models.insert(index, model)
        self._struct_bump()
        return model

    def find_model_by_guid(self, guid):
        """按 guid 找物体，找不到返回 None（相机挂父 / 撤销解析用）。"""
        for m in self.models:
            if m.guid == guid:
                return m
        return None

    # ================ 材质库 ================
    def add_material(self, color=None, saturation=1.0, name=None, guid=None):
        """新建材质并加入材质库（供物体共享引用）。返回 Material。"""
        from loom_material import Material
        mat = Material(color=color, saturation=saturation, name=name, guid=guid)
        self.materials.append(mat)
        return mat

    def _find_material(self, guid):
        """按 guid 在材质库找材质（找不到返回 None）。"""
        if guid:
            for mat in self.materials:
                if mat.guid == guid:
                    return mat
        return None

    def _register_model_material(self, model):
        """把物体自带的材质登记进材质库（未在库中则加入），保证共享可被引用。"""
        mat = model.renderer.material
        if mat is not None and mat not in self.materials:
            self.materials.append(mat)
