# -*- coding: utf-8 -*-
"""
undo.py — 撤销/重做 (M15, 命令模式)

每个可撤销的编辑器操作包装成一个 Command 对象, 带 do()/undo()。
UndoManager 持有双栈 (undo_stack / redo_stack), Ctrl+Z 出 undo 栈、
入 redo 栈, Ctrl+Y 反向。

命令类型:
  - StateCommand    检查器/gizmo 改值: 快照物体字段 before/after
  - AddObjectCommand    添加物体 (redo 时重建, 保 index)
  - DeleteObjectCommand 删除整棵子树 (记录 DFS 顺序/父链/原列表顺序)
  - ReparentCommand     拖拽挂父/脱父
  - LightStateCommand / AddLightCommand / DeleteLightCommand  光源 (M21): 改值/添加/删除

约定:
  - 每个命令 do() 之后才 push 到 undo 栈 (push 即执行)。
  - 命令里不做场景保存, 只改运行时状态; 保存由编辑器显式触发。
  - Point3D 是 namedtuple, 快照一律存 tuple, 应用时重建 Point3D。
"""
from engine import Point3D
import sceneio


# ---------------- 快照工具 ----------------

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
        # M25 组件化: 快照全部脚本组件 (可多个). 元组 (id, vars 副本) 列表.
        'scripts': [(sc.script_id, dict(sc.script_vars)) for sc in m.scripts],
        # M28: 碰撞体 (shape, enabled, friction, restitution) — B1 加接触材质;
        # B1-P1 (2026-08-30) 追加第 5 槽 rolling_friction (旧 2/4 元快照兼容)
        'collider': (m.collider.shape, m.collider.enabled,
                     m.collider.friction, m.collider.restitution,
                     m.collider.rolling_friction),
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
        # M35: 动画 (None 或 (clips, current, loop)); 运行时 time/playing 不还原
        'animator': None if m.animator is None else
        (m.animator.clips, m.animator.current, m.animator.loop),
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
    m.visible = snap['visible']
    m.name = snap['name']
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
        if snap['animator'] is None:
            m.remove_animator()
        elif m.animator is None:
            an = m.add_animator(clips=snap['animator'][0],
                                current=snap['animator'][1],
                                loop=snap['animator'][2])
        else:
            m.animator.clips, m.animator.current, m.animator.loop = snap['animator']
        # 2026-08-30: 运行态清零 (time/playing 不入快照, 还原即"回到未播放")
        if m.animator is not None:
            m.animator.time = 0.0
            m.animator.playing = False


# ---------------- 光源快照 (M21) ----------------

def light_snapshot(l):
    """光源可撤销字段 -> dict (与 apply_light_snapshot 成对; M29 加 mode/shape/size/shadow;
    M30 加平行光方向 3 角度 azimuth/elevation/roll)"""
    return {
        'kind': l.kind,
        'position': (l.position.x, l.position.y, l.position.z),
        'direction': (l.direction.x, l.direction.y, l.direction.z),
        'color': tuple(l.color),
        'intensity': l.intensity,
        'name': l.name,
        'mode': l.mode,
        'shape': l.shape,
        'size': l.size,
        'shadow': l.shadow,
        'azimuth': l.azimuth,
        'elevation': l.elevation,
        'roll': l.roll,
    }


def apply_light_snapshot(l, snap):
    """把快照写回光源 (undo/redo 共用)"""
    l.kind = snap['kind']
    l.position = Point3D(*snap['position'])
    l.color = tuple(snap['color'])
    l.intensity = snap['intensity']
    l.name = snap['name']
    l.mode = snap.get('mode', 'full')
    l.shape = snap.get('shape', 'circle')
    l.size = snap.get('size', 5.0)
    l.shadow = snap.get('shadow', True)
    if 'azimuth' in snap:
        # M30: 平行光方向 3 角度 (直接写角度, 保留 roll)
        l.azimuth = snap['azimuth']
        l.elevation = snap['elevation']
        l.roll = snap.get('roll', 0.0)
    else:
        l.direction = Point3D(*snap['direction'])   # 旧快照回退: 向量反算角度


# ---------------- 摄像机快照 (Unity Camera) ----------------

def camera_snapshot(cam):
    """摄像机可撤销字段 -> dict (与 apply_camera_snapshot 成对).
    M41: 加 roll/俯仰角限制字段. 2026-08-16 相机物体化: 加 parent (父 guid, 稳定)."""
    return {
        'position': (cam.position.x, cam.position.y, cam.position.z),
        'yaw': cam.yaw,
        'pitch': cam.pitch,
        'roll': cam.roll,
        'fov': cam.fov,
        'fov_locked': cam.fov_locked,
        'name': cam.name,
        'pitch_lock': cam.pitch_lock,
        'pitch_min': cam.pitch_min,
        'pitch_max': cam.pitch_max,
        'parent': cam.parent.guid if cam.parent is not None else None,
    }


def apply_camera_snapshot(cam, snap, engine=None):
    """把快照写回摄像机 (undo/redo 共用); .get 兼容旧快照无新字段.
    engine 传则按 parent guid 解析父 (找不到=父被删 -> 脱父), 维护 camera_children."""
    cam.position = Point3D(*snap['position'])
    cam.yaw = snap['yaw']
    cam.pitch = snap['pitch']
    cam.roll = snap.get('roll', 0.0)
    cam.fov = snap['fov']
    cam.fov_locked = snap['fov_locked']
    cam.name = snap['name']
    cam.pitch_lock = snap.get('pitch_lock', False)
    cam.pitch_min = snap.get('pitch_min', -85.0)
    cam.pitch_max = snap.get('pitch_max', 85.0)
    new_parent = None
    pid = snap.get('parent')
    if engine is not None and pid:
        new_parent = engine.find_model_by_guid(pid)
    if cam.parent is not None and cam in cam.parent.camera_children:
        cam.parent.camera_children.remove(cam)
    cam.parent = new_parent
    if new_parent is not None:
        new_parent.camera_children.append(cam)


# ---------------- 命令基类 ----------------

class Command:
    label = "命令"

    def do(self):
        raise NotImplementedError

    def undo(self):
        raise NotImplementedError


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


class LightStateCommand(Command):
    """光源属性改值: before/after 是 light_snapshot (检查器/gizmo 拖光源)."""

    def __init__(self, label, engine, light, before, after):
        self.label = label
        self.engine = engine
        self.light = light
        self.before = before
        self.after = after

    def do(self):
        apply_light_snapshot(self.light, self.after)

    def undo(self):
        apply_light_snapshot(self.light, self.before)


class AddLightCommand(Command):
    """添加光源. do() 首次创建, 撤销移除, 重做重新入列表 (光源无 GPU 资源)."""

    def __init__(self, label, engine, kind, position=None, direction=None,
                 color=(1.0, 1.0, 1.0), intensity=1.0, name=None):
        self.label = label
        self.engine = engine
        self.kind = kind
        self.args = (kind, position, direction, color, intensity, name)
        self.light = None

    def do(self):
        if self.light is None:
            self.light = self.engine.add_light(*self.args)
        else:
            self.engine.lights.append(self.light)
        return self.light

    def undo(self):
        self.engine.remove_light(self.light)


class DeleteLightCommand(Command):
    """删除光源. 光源无 GPU 资源, 撤销直接把对象引用插回原位 (与 DeleteObjectCommand 同风格)."""

    def __init__(self, label, engine, light):
        self.label = label
        self.engine = engine
        self.light = light
        self.index = engine.lights.index(light)

    def do(self):
        self.engine.remove_light(self.light)

    def undo(self):
        if self.light not in self.engine.lights:
            self.engine.lights.insert(min(self.index, len(self.engine.lights)), self.light)


# ---------------- 摄像机命令 (Unity Camera 概念) ----------------

class CameraStateCommand(Command):
    """摄像机属性改值: before/after 是 camera_snapshot (检查器/gizmo 拖摄像机)."""

    def __init__(self, label, engine, cam, before, after):
        self.label = label
        self.engine = engine
        self.cam = cam
        self.before = before
        self.after = after

    def do(self):
        apply_camera_snapshot(self.cam, self.after, self.engine)

    def undo(self):
        apply_camera_snapshot(self.cam, self.before, self.engine)


class AddCameraCommand(Command):
    """添加摄像机. do() 首次创建, 撤销移除, 重做重新入列表 (摄像机无 GPU 资源).
    M41: 参数顺序与 engine.add_camera 一致 (含 roll/俯仰角限制)."""

    def __init__(self, label, engine, position=None, yaw=0.0, pitch=0.0,
                 roll=0.0, fov=60.0, fov_locked=True, name=None,
                 pitch_lock=False, pitch_min=-85.0, pitch_max=85.0):
        self.label = label
        self.engine = engine
        # 2026-08-22: args 与 engine.add_camera 签名逐槽对齐 —— add_camera 在
        # name 后加了 guid=None 槽, 旧 args 无占位 → 位置错位: pitch_min=-85.0
        # 落进 pitch_lock 槽 → 新相机 bool(-85.0)=True 自带"俯仰限制已启用"
        # (diag 实锤, 用户加相机即"已启用"的根因)
        self.args = (position, yaw, pitch, roll, fov, fov_locked, name, None,
                     pitch_lock, pitch_min, pitch_max)
        self.cam = None

    def do(self):
        if self.cam is None:
            self.cam = self.engine.add_camera(*self.args)
        else:
            self.engine.cameras.append(self.cam)
        return self.cam

    def undo(self):
        self.engine.remove_camera(self.cam)


class DeleteCameraCommand(Command):
    """删除摄像机. 撤销插回原位 (active_camera 若指向它已被 remove_camera 清空, 属预期).
    2026-08-16 相机物体化: 记录父 guid, 撤销按 guid 重连父."""

    def __init__(self, label, engine, cam):
        self.label = label
        self.engine = engine
        self.cam = cam
        self.index = engine.cameras.index(cam)
        self.parent_guid = cam.parent.guid if cam.parent is not None else None

    def do(self):
        self.engine.remove_camera(self.cam)

    def undo(self):
        if self.cam not in self.engine.cameras:
            self.engine.cameras.insert(min(self.index, len(self.engine.cameras)), self.cam)
        if self.parent_guid:
            par = self.engine.find_model_by_guid(self.parent_guid)
            if par is not None and self.cam.parent is not par:
                self.cam.parent = par
                par.camera_children.append(self.cam)


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


class ReparentCameraCommand(Command):
    """把摄像机从 old_parent 挂到 new_parent (None=根). 摄像机只可挂 GameObject.
    相机物体化 2026-08-16."""

    def __init__(self, label, engine, cam, old_parent, new_parent):
        self.label = label
        self.engine = engine
        self.cam = cam
        self.old_parent = old_parent
        self.new_parent = new_parent

    def do(self):
        self.engine.set_camera_parent(self.cam, self.new_parent)

    def undo(self):
        self.engine.set_camera_parent(self.cam, self.old_parent)


# ---------------- 撤销管理器 ----------------

class UndoManager:
    def __init__(self, limit=100):
        self.undo_stack = []
        self.redo_stack = []
        self.limit = limit

    def push(self, cmd):
        """执行 cmd 并压入撤销栈, 同时清空重做栈."""
        cmd.do()
        self.undo_stack.append(cmd)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        return cmd

    def undo(self):
        if not self.undo_stack:
            return None
        cmd = self.undo_stack.pop()
        cmd.undo()
        self.redo_stack.append(cmd)
        return cmd

    def redo(self):
        if not self.redo_stack:
            return None
        cmd = self.redo_stack.pop()
        cmd.do()
        self.undo_stack.append(cmd)
        return cmd

    @property
    def can_undo(self):
        return bool(self.undo_stack)

    @property
    def can_redo(self):
        return bool(self.redo_stack)

    def undo_label(self):
        return self.undo_stack[-1].label if self.undo_stack else ""

    def redo_label(self):
        return self.redo_stack[-1].label if self.redo_stack else ""

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
