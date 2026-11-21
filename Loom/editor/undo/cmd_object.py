# -*- coding: utf-8 -*-
"""
物体域撤销命令（原 Loom/undo.py「快照工具」段 + 物体/材质命令类；
目录重构 B4 批按域拆分，逐行未动）。

成员: 物体/材质快照 (snapshot / apply_snapshot / _material_state /
_apply_material_state) + StateCommand / AddMaterialCommand / AddObjectCommand /
DeleteObjectCommand / DuplicateObjectCommand / PrefabPlaceCommand /
ReparentCommand。
"""
from engine import Point3D
import sceneio

from editor.undo.registry import Command


# ---------------- 快照工具 ----------------

def _material_state(mat):
    """材质内容快照 (2026-11-07): albedo/PBR/env 等修改也要可撤销.

    材质是共享资产: 快照只存字段引用, undo 时写回同一材质对象 (所有引用者
    一起回滚), 与"改一个材质全变"的资产语义一致.
    """
    if mat is None:
        return None
    return {
        'color': mat.color,
        'saturation': mat.saturation,
        'metallic': getattr(mat, 'metallic', 0.0),
        'roughness': getattr(mat, 'roughness', 0.5),
        'pbr': getattr(mat, 'pbr', False),
        'albedo': getattr(mat, 'albedo', None),
        'normal_map': getattr(mat, 'normal_map', None),
        'env_map': getattr(mat, 'env_map', None),
    }

def _apply_material_state(mat, state):
    """把材质内容快照写回 (undo/redo 共用). 旧快照无 material_state -> 跳过."""
    if mat is None or not state:
        return
    if 'color' in state:
        mat.color = state['color']
    if 'saturation' in state:
        mat.saturation = state['saturation']
    if 'metallic' in state:
        mat.metallic = state['metallic']
    if 'roughness' in state:
        mat.roughness = state['roughness']
    if 'pbr' in state:
        mat.pbr = state['pbr']
    if 'albedo' in state:
        mat.albedo = state['albedo']
    if 'normal_map' in state:
        mat.normal_map = state['normal_map']
    if 'env_map' in state:
        mat.env_map = state['env_map']

def snapshot(m):
    """物体可撤销字段 -> dict (不变式: 与 apply 成对)"""
    return {
        'position': (m.position.x, m.position.y, m.position.z),
        'rotation': (m.rotation.x, m.rotation.y, m.rotation.z),
        'scale': tuple(m.scale),
        'color': m.color,
        'saturation': m.saturation,
        'visible': m.visible,
        'name': m.name,
        # Layer/Tag (2026-10-18): 项目级身份元信息 (契约 §4.3 要求进撤销栈);
        # 旧快照无此二键 -> apply_snapshot 跳过 (向后兼容).
        'layer': m.layer,
        'tag': m.tag,
        # M23: 材质引用 (换材质时恢复原材质). 恒存在, 但颜色改动的命令前后同引用.
        'material': m.renderer.material,
        # 2026-11-07 Q5=A: 材质内容 (albedo/PBR/env) 也进快照, 否则检查器改
        # 材质后 undo 只回引用不回内容 (共享材质内容仍是改后的值).
        'material_state': _material_state(m.renderer.material),
        # 2026-11-07 Q5=A: 法线模式/Prefab 归属/LOD 配置 (旧快照无此键 -> apply 跳过)
        'normal_mode': m.normal_mode,
        'prefab_ref': getattr(m, 'prefab_ref', None),
        'lod_levels': (list(m.renderer.lod_levels)
                       if getattr(m.renderer, 'lod_levels', None) else None),
        'lod_screen_levels': (list(m.renderer.lod_screen_levels)
                              if getattr(m.renderer, 'lod_screen_levels', None)
                              else None),
        'lod_bias': getattr(m.renderer, 'lod_bias', 1.0),
        # M25 组件化: 快照全部脚本组件 (可多个). 元组 (id, vars 副本) 列表.
        'scripts': [(sc.script_id, dict(sc.script_vars)) for sc in m.scripts],
        # M28: 碰撞体 (shape, enabled, friction, restitution) — B1 加接触材质;
        # B1-P1 (2026-08-30) 追加第 5 槽 rolling_friction (旧 2/4 元快照兼容)
        # 2026-10-18 Trigger: 第 6 槽 is_trigger (旧 5 元快照兼容, 缺省视为 False)
        'collider': (m.collider.shape, m.collider.enabled,
                     m.collider.friction, m.collider.restitution,
                     m.collider.rolling_friction,
                     bool(getattr(m.collider, 'is_trigger', False))),
        # M31: 刚体 (None 或 (mass, use_gravity, is_kinematic, friction,
        # restitution, rolling_friction)); 运行时速度不序列化. B1 加接触材质+
        # 滚动摩擦 (与 apply_snapshot 成对, 旧 3/5 元快照兼容)
        'rigidbody': None if m.rigidbody is None else
        (m.rigidbody.mass, m.rigidbody.use_gravity, m.rigidbody.is_kinematic,
         m.rigidbody.friction, m.rigidbody.restitution,
         m.rigidbody.rolling_friction),
        # M34: 音频源 (None 或 (clip, loop, volume)); 运行时 playing/_key 不序列化
        # 2026-10-18 3D 音频: 追加 category/min/max/rolloff (旧 3 元快照 apply 时兼容)
        'audio_source': None if m.audio_source is None else
        (m.audio_source.clip, m.audio_source.loop, m.audio_source.volume,
         m.audio_source.category, m.audio_source.min_distance,
         m.audio_source.max_distance, m.audio_source.rolloff),
        # M35: 动画 (None 或 (clips, current, loop, speed)); 运行时 time/playing 不还原
        # beta6 C1: clips **按值拷贝** —— 旧实现按引用存字典, 改快照会污染模型,
        # 关键帧编辑不可撤销 (docs/design/research_beta6_03_animation.md §1.5).
        # 追加第 4 槽 speed; apply_snapshot 兼容旧 3 元快照.
        'animator': None if m.animator is None else
        ({name: clip.copy() for name, clip in m.animator.clips.items()},
         m.animator.current, m.animator.loop,
         float(getattr(m.animator, 'speed', 1.0))),
    }

def apply_snapshot(m, snap):
    """把快照写回物体 (undo/redo 共用)"""
    if 'material' in snap:                 # M23: 先恢复材质引用, 再写颜色/饱和度
        m.renderer.material = snap['material']
    m.position = Point3D(*snap['position'])
    m.rotation = Point3D(*snap['rotation'])
    m.scale = tuple(snap['scale'])
    m.color = snap['color']
    m.saturation = snap['saturation']
    # 2026-11-07 Q5=A: 材质内容 (albedo/PBR/env/金属度/粗糙度) 回写
    if 'material_state' in snap:
        _apply_material_state(m.renderer.material, snap['material_state'])
    m.visible = snap['visible']
    m.name = snap['name']
    # 2026-11-07 Q5=A: 法线模式/Prefab 归属/LOD 配置 (旧快照跳过)
    if 'normal_mode' in snap:
        m.normal_mode = snap['normal_mode']
    if 'prefab_ref' in snap:
        m.prefab_ref = snap['prefab_ref']
    if ('lod_levels' in snap or 'lod_screen_levels' in snap
            or 'lod_bias' in snap):
        m.renderer.lod_levels = (list(snap['lod_levels'])
                                 if snap.get('lod_levels') else None)
        m.renderer.lod_screen_levels = (list(snap['lod_screen_levels'])
                                        if snap.get('lod_screen_levels') else None)
        m.renderer.lod_bias = snap.get('lod_bias', 1.0)
        m.renderer._lod_cur = None       # 强制下帧重新评估 LOD
        m.renderer._lod_radius = None
    if 'layer' in snap:                    # Layer/Tag (2026-10-18; 旧快照跳过)
        m.layer = snap['layer']
    if 'tag' in snap:
        m.tag = snap['tag']
    if 'scripts' in snap:                  # M25: 还原全部脚本组件 (清空重建)
        m.clear_scripts()
        for sid, vars_ in snap['scripts']:
            m.add_script(sid, vars_)
    elif 'script_id' in snap:              # 旧快照 (v3 时期): 单脚本字段 -> 兼容
        m.script_id = snap['script_id']
        m.script_vars = dict(snap['script_vars'])
    if 'collider' in snap:                 # M28: 还原碰撞体 (老快照无此键则跳过)
        col = snap['collider']
        m.collider.shape, m.collider.enabled = col[0], col[1]
        if len(col) >= 4:                  # B1: 旧 2 元快照兼容, 材质回归默认
            m.collider.friction, m.collider.restitution = col[2], col[3]
        if len(col) >= 5:                  # B1-P1: 滚动摩擦 (旧 4 元快照兼容)
            m.collider.rolling_friction = col[4]
        if len(col) >= 6:                  # 2026-10-18 Trigger: is_trigger (旧 5 元兼容)
            m.collider.is_trigger = bool(col[5])
    if 'rigidbody' in snap:                # M31: 还原刚体 (None=无刚体)
        if snap['rigidbody'] is None:
            m.remove_rigidbody()
        elif m.rigidbody is None:
            rb = m.add_rigidbody(*snap['rigidbody'])
            rb.velocity = Point3D(0.0, 0.0, 0.0)
        else:
            rb_snap = snap['rigidbody']
            m.rigidbody.mass, m.rigidbody.use_gravity, m.rigidbody.is_kinematic = \
                rb_snap[0], rb_snap[1], rb_snap[2]
            if len(rb_snap) >= 5:          # B1: 旧 3 元快照兼容, 材质回归默认
                m.rigidbody.friction, m.rigidbody.restitution = rb_snap[3], rb_snap[4]
            if len(rb_snap) >= 6:          # B1-P1: 滚动摩擦 (旧 5 元快照兼容)
                m.rigidbody.rolling_friction = rb_snap[5]
            # 2026-08-30 用户实测: 快照还原 (停止播放/撤销) 属于"回编辑态",
            # 运行时运动状态必须清零 —— 旧版只还原字段, 下落速度残留
            # (用户现象: 播放关闭后速度被储存)。_colliding 同清。
            m.rigidbody.velocity = Point3D(0.0, 0.0, 0.0)
            m.rigidbody._colliding = set()
            m._colliding = set()
    if 'audio_source' in snap:             # M34: 还原音频源 (None=无音频)
        if snap['audio_source'] is None:
            m.remove_audio_source()
        elif m.audio_source is None:
            m.add_audio_source(*snap['audio_source'])
        else:
            au = snap['audio_source']
            m.audio_source.clip = au[0]
            m.audio_source.loop = au[1]
            m.audio_source.volume = au[2]
            if len(au) >= 7:               # 2026-10-18: 3D 字段 (旧 3 元快照兼容)
                m.audio_source.category = au[3]
                m.audio_source.min_distance = au[4]
                m.audio_source.max_distance = au[5]
                m.audio_source.rolloff = au[6]
        # 2026-08-30: 运行态清零 (playing/_key 不入快照; 还原=停播)
        if m.audio_source is not None:
            m.audio_source.playing = False
            m.audio_source._key = None
    if 'animator' in snap:                 # M35: 还原动画 (None=无动画)
        val = snap['animator']
        if val is None:
            m.remove_animator()
        else:
            clips = val[0]
            # beta6 C1: 还原时再拷一份 —— 快照与模型任何一侧后续编辑都不得
            # 影响另一侧 (值隔离是双向的: 存快照时拷、写回模型时也拷).
            clips = {name: clip.copy() for name, clip in clips.items()}
            speed = float(val[3]) if len(val) > 3 else 1.0
            if m.animator is None:
                an = m.add_animator(clips=clips, current=val[1], loop=val[2])
            else:
                an = m.animator
                an.clips = clips
                an.current = val[1]
                an.loop = val[2]
            an.speed = speed
        # 2026-08-30: 运行态清零 (time/playing 不入快照, 还原即"回到未播放")
        if m.animator is not None:
            m.animator.time = 0.0
            m.animator.playing = False

# ---------------- 具体命令 ----------------

class StateCommand(Command):
    """属性改值: before 是操作开始时的快照, after 是结束时的快照."""

    def __init__(self, label, engine, model, before, after):
        self.label = label
        self.engine = engine
        self.model = model
        self.before = before
        self.after = after

    def do(self):
        apply_snapshot(self.model, self.after)

    def undo(self):
        apply_snapshot(self.model, self.before)

class AddMaterialCommand(Command):
    """新建材质资产 (M23). do() 首次创建并进材质库; 可把新建材质挂到指定物体.
    撤销: 物体还原原材质 + 材质移出库. 重做: 重新入库并挂上."""

    def __init__(self, label, engine, color=None, saturation=1.0, name=None,
                 model=None):
        self.label = label
        self.engine = engine
        self.args = (color, saturation, name)
        self.model = model
        self.mat = None
        self.old_mat = None                # 首次 do 记录物体原材质, 供撤销还原

    def do(self):
        if self.mat is None:
            self.mat = self.engine.add_material(*self.args)
            if self.model is not None:
                self.old_mat = self.model.renderer.material
                self.model.renderer.material = self.mat
        else:
            if self.mat not in self.engine.materials:
                self.engine.materials.append(self.mat)
            if self.model is not None:
                self.model.renderer.material = self.mat
        return self.mat

    def undo(self):
        if self.model is not None and self.old_mat is not None:
            self.model.renderer.material = self.old_mat
        if self.mat is not None and self.mat in self.engine.materials:
            self.engine.materials.remove(self.mat)

class AddObjectCommand(Command):
    """添加物体. do() 首次创建, 撤销删除, 重做重新挂载 (GPU 重建)."""

    def __init__(self, label, engine, mesh, position, rotation,
                 normal_mode='flat', name=None, scale=None, visible=True, color=None):
        self.label = label
        self.engine = engine
        self.args = (mesh, position, rotation, normal_mode,
                     name, scale, visible, color)
        self.model = None
        self.index = None

    def do(self):
        if self.model is None:
            self.model = self.engine.add_model(*self.args)
            self.index = len(self.engine.models) - 1
        else:
            # 撤销后再重做: 重挂载, 尽量回原位置
            self.engine.attach_model(self.model, index=self.index)
        return self.model

    def undo(self):
        self.engine.remove_model(self.model)

class DeleteObjectCommand(Command):
    """删除 root 整棵子树. 构造时记录恢复所需全部信息."""

    def __init__(self, label, engine, root):
        self.label = label
        self.engine = engine
        self.root = root
        # 记录: DFS 顺序, 各物体原父, 原平铺列表顺序
        self.order = list(engine.collect_subtree(root))
        self.parent_of = {id(m): m.parent for m in self.order}
        self.models_before = list(engine.models)

    def do(self):
        self.engine.remove_subtree(self.root)

    def undo(self):
        # 1) 恢复平铺列表的原始顺序 (对象引用保持不变)
        self.engine.models = list(self.models_before)
        # 2) 恢复父链: DFS 前序 -> 父先于子处理, 父链天然就位
        for m in self.order:
            par = self.parent_of[id(m)]
            m.parent = par
            if par is not None and m not in par.children:
                par.children.append(m)
        # 3) 重建 GPU 几何
        for m in self.order:
            if m.vbo is None:
                self.engine._build_gpu(m)

class DuplicateObjectCommand(Command):
    """复制物体并挂到原物体父下 (原子: 撤销一并移除)."""

    def __init__(self, label, engine, mesh, src, position, rotation,
                 normal_mode='flat', name=None,
                 scale=None, visible=True, color=None):
        self.label = label
        self.engine = engine
        self.mesh = mesh
        self.src = src
        self.args = (mesh, position, rotation, normal_mode,
                     name, scale, visible, color)
        self.model = None
        self.index = None

    def do(self):
        if self.model is None:
            self.model = self.engine.add_model(*self.args)
            self.index = len(self.engine.models) - 1
        else:
            self.engine.attach_model(self.model, index=self.index)
        if self.src.parent is not None and self.model is not None:
            if self.model.parent is not self.src.parent:
                # 2026-08-16: 复制命令的局部值已按 src 父空间备好 (同位置复制), 不保世界换算
                self.engine.set_parent(self.model, self.src.parent, preserve_world=False)

    def undo(self):
        self.engine.remove_model(self.model)

class PrefabPlaceCommand(Command):
    """放置 Prefab 实例 (M16). do() 首次实例化, 撤销删整棵, 重做重挂."""

    def __init__(self, label, engine, data, offset=(0, 0, 0)):
        self.label = label
        self.engine = engine
        self.data = data
        self.offset = offset
        self.models = []
        self.index = None

    def do(self):
        if not self.models:
            self.models = sceneio.instantiate_prefab(self.engine, self.data,
                                                     self.offset)
            self.index = len(self.engine.models) - 1
        else:
            for m in self.models:
                self.engine.attach_model(m, index=self.index)

    def undo(self):
        for m in list(self.models):
            self.engine.remove_model(m)

class ReparentCommand(Command):
    """把 child 从 old_parent 挂到 new_parent (None=根)."""

    def __init__(self, label, engine, child, old_parent, new_parent):
        self.label = label
        self.engine = engine
        self.child = child
        self.old_parent = old_parent
        self.new_parent = new_parent

    def do(self):
        self.engine.set_parent(self.child, self.new_parent)

    def undo(self):
        self.engine.set_parent(self.child, self.old_parent)
