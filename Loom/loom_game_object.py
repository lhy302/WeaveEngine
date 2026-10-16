# -*- coding: utf-8 -*-
"""loom_game_object.py — 场景物体 GameObject（M25 组件化容器）。

原属 engine.py（"模型状态 (场景物体)" 段）。依赖：
  - loom_types.Point3D
  - loom_components.*（Transform/MeshRenderer/Collider/Script 等）
  - engine.GLEngine（仅 parent setter 运行时按名解析，延迟 import）
engine.py 通过 `from loom_game_object import GameObject` 重导出。
"""

from loom_types import Point3D
from loom_components import (
    TransformComponent, MeshRendererComponent, ScriptComponent,
    ColliderComponent, RigidbodyComponent, AudioSourceComponent,
    AnimatorComponent,
)


# ================ 模型状态 (场景物体) ================
class GameObject:
    """场景物体 (M25 组件化): 容器 + 组件列表.
    组成: TransformComponent + MeshRendererComponent + ScriptComponent[] (可多个).
    便捷属性 (position/color/script_id/...) 委托到组件, 兼容旧代码;
    新代码应直接访问 self.transform / self.renderer / self.scripts."""

    # 组6件1: 材质外观代计数器 (Material.color/saturation setter bump; 见上)
    _appearance_gen = 0

    def __init__(self, mesh, position, rotation,
                 name=None, scale=None, visible=True,
                 primitive=None, params=None, color=None, normal_mode='flat',
                 saturation=1.0):
        self.name = name
        # 稳定身份 (M16): 场景/Prefab 引用用
        self.guid = None
        self.prefab_ref = None
        # —— 组件 (M25) ——
        self.components = []
        self.transform = TransformComponent(position, rotation, scale)
        self.transform.owner = self
        self.renderer = MeshRendererComponent(mesh, color, normal_mode, primitive,
                                              params, saturation, visible)
        self.renderer.owner = self
        self.components += [self.transform, self.renderer]
        self.scripts = []            # ScriptComponent 列表 (可挂多个)
        # 碰撞体 (M28): 球体网格自动用球体碰撞体, 其余用 AABB 盒
        auto_shape = 'sphere' if primitive == 'sphere' else 'box'
        self.collider = ColliderComponent(shape=auto_shape)
        self.collider.owner = self
        self.components += [self.collider]
        self.rigidbody = None        # M31: 刚体组件 (None=无刚体, 不受重力/速度物理)
        self.audio_source = None     # M34: 音频源组件 (None=无音频, 不发声)
        self.animator = None         # M35: 动画组件 (None=无动画)
        self.light = None            # 预留: 物体上可选的光源组件 (本期未用)
        self.camera_children = []    # 2026-08-16 相机物体化: 挂在本物体下的摄像机
                                     # (独立列表, 不进 transform.children —— 后者只装
                                     #  GameObject, 避免 models 的 children 迭代误伤)
        # GPU 几何 (add_model 时构建; 运行态, 不序列化)
        self.vbo = None
        self.vao = None
        self._shadow_vao = None   # M29: 阴影深度 pass 专用 VAO (独立 positions-only VBO)
        self._shadow_vbo = None
        self.n_vertices = 0
        # 组1 (2026-08-30) 桶键缓存: mesh/normal_mode/primitive/params setter
        # 置脏 (None), 帧内 _mesh_key 惰性重建 —— 消每帧 json.dumps(params).
        # 边界: params dict 原地 mutate (不经 setter) 不会失效缓存 —— 全库
        # 无此用法 (mesh.py 创建期/sceneio 读取期均走赋值), 注释备案.
        self._bucket_key = None

    # ================ 变换便捷 (委托 TransformComponent) ================
    @property
    def position(self):
        return self.transform.position
    @position.setter
    def position(self, v):
        self.transform.position = Point3D(*v)
    @property
    def rotation(self):
        return self.transform.rotation
    @rotation.setter
    def rotation(self, v):
        self.transform.rotation = Point3D(*v)
    @property
    def scale(self):
        return self.transform.scale
    @scale.setter
    def scale(self, v):
        self.transform.scale = tuple(v)
    @property
    def parent(self):
        return self.transform.parent
    @parent.setter
    def parent(self, v):
        self.transform.parent = v
        # 组2/组3: 旁路挂父 (脚本/编辑器直写) 也失效引擎侧 ancestry+SoA 缓存.
        # GameObject 无引擎引用 -> 类级弱实例表 (GLEngine.__init__ 注册);
        # 只脏不净 (多算不 错算), 无活实例时静默 (引擎未建则无缓存可脏).
        from engine import GLEngine   # 延迟 import：运行时 engine 已加载（原同模块直引，语义不变）
        for ref in tuple(getattr(GLEngine, '_LIVE_INSTANCES', ())):
            e = ref()
            if e is not None:
                try:
                    e._bump_struct()
                except Exception:
                    pass
    @property
    def children(self):
        return self.transform.children

    # ================ 渲染便捷 (委托 MeshRendererComponent) ================
    @property
    def mesh(self):
        return self.renderer.mesh
    @mesh.setter
    def mesh(self, v):
        self._bucket_key = None               # 组1: 换网格重键 (防御; 键本身不含 mesh)
        self.renderer.mesh = v
        GameObject._appearance_gen += 1       # 组6件1: 换网格=桶归属变 (保守 bump)
    @property
    def color(self):
        return self.renderer.material.color
    @color.setter
    def color(self, v):
        self.renderer.material.color = v
    @property
    def normal_mode(self):
        return self.renderer.normal_mode
    @normal_mode.setter
    def normal_mode(self, v):
        self._bucket_key = None               # 组1: 桶键成分置脏
        self.renderer.normal_mode = v
    @property
    def primitive(self):
        return self.renderer.primitive
    @primitive.setter
    def primitive(self, v):
        self._bucket_key = None               # 组1: 桶键成分置脏
        self.renderer.primitive = v
    @property
    def params(self):
        return self.renderer.params
    @params.setter
    def params(self, v):
        self._bucket_key = None               # 组1: 桶键成分置脏
        self.renderer.params = v
    @property
    def saturation(self):
        return self.renderer.material.saturation
    @saturation.setter
    def saturation(self, v):
        self.renderer.material.saturation = float(v)
    @property
    def visible(self):
        return self.renderer.visible
    @visible.setter
    def visible(self, v):
        self.renderer.visible = bool(v)
        GameObject._appearance_gen += 1       # 组6件1: 可见性=桶过滤变 (保守 bump)

    # ================ 脚本便捷 (操作 scripts[0], 兼容旧单脚本 API) ================
    @property
    def script_id(self):
        return self.scripts[0].script_id if self.scripts else None
    @script_id.setter
    def script_id(self, v):
        if v is None:
            self.clear_scripts()
        elif self.scripts:
            self.scripts[0].script_id = v
        else:
            self.add_script(v)
    @property
    def script_vars(self):
        return self.scripts[0].script_vars if self.scripts else {}
    @script_vars.setter
    def script_vars(self, v):
        if self.scripts:
            self.scripts[0].script_vars = dict(v)
        elif v:
            self.add_script(None, dict(v))
    # 运行态委托 (仅供旧代码; 新代码直接遍历 m.scripts 访问每个 sc)
    @property
    def _script(self):
        return self.scripts[0]._script if self.scripts else None
    @_script.setter
    def _script(self, v):
        if self.scripts:
            self.scripts[0]._script = v
    @property
    def _script_broken(self):
        return self.scripts[0]._script_broken if self.scripts else False
    @_script_broken.setter
    def _script_broken(self, v):
        if self.scripts:
            self.scripts[0]._script_broken = v

    # ================ 脚本管理 (M25: 多脚本) ================
    def add_script(self, script_id, script_vars=None):
        """挂一个脚本组件 (可多个). 返回 ScriptComponent."""
        sc = ScriptComponent(script_id, script_vars)
        sc.owner = self
        self.scripts.append(sc)
        self.components.append(sc)
        return sc

    def remove_script(self, index):
        """移除第 index 个脚本组件 (返回被移除者或 None)."""
        if 0 <= index < len(self.scripts):
            sc = self.scripts.pop(index)
            if sc in self.components:
                self.components.remove(sc)
            return sc
        return None

    def clear_scripts(self):
        """清空全部脚本组件 (撤销还原/退出播放用)."""
        for sc in self.scripts:
            if sc in self.components:
                self.components.remove(sc)
        self.scripts.clear()

    def get_script(self, index):
        """取第 index 个脚本组件 (越界返回 None)."""
        if 0 <= index < len(self.scripts):
            return self.scripts[index]
        return None

    def add_rigidbody(self, mass=1.0, use_gravity=True, is_kinematic=False,
                      friction=0.5, restitution=0.0, rolling_friction=0.1):
        """M31: 给物体加刚体组件 (返回 RigidbodyComponent).
        加刚体后物体由引擎每帧按速度+重力带碰撞移动; 需要碰撞体积请保留 collider.
        B1: friction/restitution/rolling_friction = 动态体接触材质 (桥透传)."""
        rb = RigidbodyComponent(mass=mass, use_gravity=use_gravity,
                                is_kinematic=is_kinematic,
                                friction=friction, restitution=restitution,
                                rolling_friction=rolling_friction)
        rb.owner = self
        self.rigidbody = rb
        self.components.append(rb)
        return rb

    def remove_rigidbody(self):
        """移除刚体组件 (返回被移除者或 None)."""
        rb = self.rigidbody
        if rb is not None:
            self.rigidbody = None
            if rb in self.components:
                self.components.remove(rb)
        return rb

    def add_audio_source(self, clip=None, loop=False, volume=1.0):
        """M34: 给物体加音频源组件 (返回 AudioSourceComponent). 播放状态由 playing 控制."""
        a = AudioSourceComponent(clip=clip, loop=loop, volume=volume)
        a.owner = self
        self.audio_source = a
        self.components.append(a)
        return a

    def remove_audio_source(self):
        """移除音频源组件 (返回被移除者或 None)."""
        a = self.audio_source
        if a is not None:
            self.audio_source = None
            if a in self.components:
                self.components.remove(a)
        return a

    def add_animator(self, clips=None, current=None, loop=True):
        """M35: 给物体加动画组件 (返回 AnimatorComponent). clips={'名': AnimationClip}."""
        an = AnimatorComponent(clips=clips, current=current, loop=loop)
        an.owner = self
        self.animator = an
        self.components.append(an)
        return an

    def remove_animator(self):
        """移除动画组件 (返回被移除者或 None)."""
        an = self.animator
        if an is not None:
            self.animator = None
            if an in self.components:
                self.components.remove(an)
        return an

    # ================ 便捷方法 ================
    def set_scale(self, scale):
        """设置缩放 (tuple (sx,sy,sz))"""
        self.scale = tuple(scale)

    def set_name(self, name):
        """设置显示名称"""
        self.name = name

    def set_visible(self, visible):
        """设置可见性"""
        self.visible = bool(visible)

