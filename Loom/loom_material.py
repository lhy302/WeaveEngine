# -*- coding: utf-8 -*-
"""loom_material.py — 材质资产 (M23)。

原属 engine.py（"材质资产 (M23)" 段）。依赖 numpy、loom_color._hex_rgba。
Material._bump_appearance 需 bump GameObject._appearance_gen —— 原靠同一模块
全局命名空间运行期解析；拆出后改为函数内延迟 import engine（同语义，无循环风险）。
engine.py 通过 `from loom_material import Material` 重新导出。
"""
import uuid

import numpy as np

from loom_color import _hex_rgba


# ================ 材质资产 (M23) ================
class Material:
    """材质资产: 颜色 + 饱和度, 可被多个物体共享 (资产即数据的第一步).
    改一个材质 -> 所有引用它的物体一起变, 与 Unity 材质资产语义一致.
    guid 为稳定身份, 场景/Prefab 序列化引用用."""

    def __init__(self, color=None, saturation=1.0, name=None, guid=None, albedo=None,
                 normal_map=None, metallic=0.0, roughness=0.5, pbr=False,
                 env_map=None):
        # 组1: 缓存字段先建 (下方 self.color= 走 property setter 时才有落点)
        self._rgba = None                        # (4,) f32 | None (随 color)
        self._sat_f32 = 0.0
        self._albedo = None                      # M36 贴图: Texture | None
        self._normal_map = None                  # M36 法线贴图: Texture | None
        self._env_map = None                     # M36 环境贴图: Cubemap | None
        self.color = color                       # 单色覆盖 (hex 字符串) 或 None=网格面色
        self.saturation = float(saturation)      # 0=灰阶, 1=原始, >1=增艳
        self.name = name or '材质'
        self.guid = guid or uuid.uuid4().hex
        # M36 PBR (2026-10-14): 金属度/粗糙度/PBR 开关 (对标 Unity Standard Shader)
        self._metallic = 0.0
        self._roughness = 0.5
        self._pbr = False
        self.albedo = albedo                     # M36: 颜色贴图槽 (走 setter bump)
        self.normal_map = normal_map             # M36: 法线贴图槽
        self.env_map = env_map                   # M36: 环境反射贴图槽
        self.metallic = metallic
        self.roughness = roughness
        self.pbr = pbr
        # M36 贴图键: 供渲染分桶用 (材质级, 稳定; 变时 bump 触发重分组)
        self._tex_guid = albedo.guid if albedo is not None else ''
        self._nrm_guid = normal_map.guid if normal_map is not None else ''
        self._env_guid = env_map.guid if env_map is not None else ''
        # 组1 (2026-08-30) 实例数据批: 渲染侧逐帧消费的 f32 缓存 (创建时算一次,
        # setter 置脏) —— 消每帧逐物体 hex 解析/属性链 (_prepare_bucket_frame
        # 与 vk draw_frame 消费). _rgba 复用 _hex_rgba 同源逻辑 (含 tuple 色
        # 灰色回退) 保证与旧路径逐位一致; color=None 时 _rgba=None (写入端留 0).

    @property
    def color(self):
        return self._color
    @color.setter
    def color(self, v):
        self._color = v
        self._rgba = None if v is None else np.asarray(
            _hex_rgba(v), dtype='f4')            # 同源转换, 逐位一致
        self._bump_appearance()

    @property
    def saturation(self):
        return self._sat
    @saturation.setter
    def saturation(self, v):
        self._sat = float(v)
        self._sat_f32 = self._sat
        self._bump_appearance()

    # ---- M36 贴图槽 ----
    @property
    def albedo(self):
        return self._albedo
    @albedo.setter
    def albedo(self, v):
        self._albedo = v
        self._tex_guid = v.guid if v is not None else ''
        self._bump_appearance()                  # 换贴图 -> 分桶/实例失效

    @property
    def normal_map(self):
        return self._normal_map
    @normal_map.setter
    def normal_map(self, v):
        self._normal_map = v
        self._nrm_guid = v.guid if v is not None else ''
        self._bump_appearance()

    @property
    def env_map(self):
        return self._env_map
    @env_map.setter
    def env_map(self, v):
        self._env_map = v
        self._env_guid = v.guid if v is not None else ''
        self._bump_appearance()

    # ---- M36 PBR 参数 (对标 Unity Standard Shader) ----
    @property
    def metallic(self):
        return self._metallic
    @metallic.setter
    def metallic(self, v):
        self._metallic = float(max(0.0, min(1.0, v)))
        self._bump_appearance()

    @property
    def roughness(self):
        return self._roughness
    @roughness.setter
    def roughness(self, v):
        self._roughness = float(max(0.0, min(1.0, v)))
        self._bump_appearance()

    @property
    def pbr(self):
        return self._pbr
    @pbr.setter
    def pbr(self, v):
        self._pbr = bool(v)
        self._bump_appearance()

    @staticmethod
    def _bump_appearance():
        """组6件1 (2026-09-02): 材质内容变化 → bump 桶实例数据代计数器.
        类级 (Material 定义在 GameObject 前, 运行时按名解析无循环依赖);
        引擎 _prepare_bucket_frame 每帧比较代数, 无变化帧整段跳过实例上传.
        多 bump 无害 (只多一次提交)."""
        from engine import GameObject   # 延迟 import：运行时 engine 已加载（原同模块直引，语义不变）
        GameObject._appearance_gen += 1
