# -*- coding: utf-8 -*-
"""
scene_driver.py — 播放器中间层 (纯逻辑, 后端无关; 2026-08-29 用户指示"中间层")

SceneDriver = 场景数据 + 每帧步进 (脚本/物理/动画/轨道相机), 不碰任何 GPU API:
  - Vk 播放器 / GL 播放器 (PlayerApp) 共用同一份语义 (engine.update_scripts /
    update_animations 的复刻, 与 engine.py 保持同步注释, 勿分叉公式);
  - 由后端层读 driver.models/lights/vp 画帧 (渲染在别处).
  - B1 (2026-08-30): 补上**物理**缺口 —— 每帧步进含桥三段 (pre/step/post,
    culverin 缺失 -> 无物理 (legacy 语义缺失, 打印提示不崩)); 并补齐脚本
    "引擎 API 最小面" (move_with_collision/get_collisions/collider_hit/
    world_position/输入与相机安全默认), 修 Vk 播放器脚本全体 broken.
"""
import math

import numpy as np

from matlib import mat4_view_yaw_pitch, mat4_perspective
from mesh import spec_to_mesh
from engine import GameObject, Point3D, LightState, DEFAULT_ACTIONS
from scripts import get_script

# B1: 物理桥 (零 GL; 缺失/导入失败 -> physb=None -> 无物理步进)
try:
    import physics_bridge as physb
except Exception:
    physb = None


def build_models(data):
    """场景 dict -> GameObject 列表 (无 GL: 只建组件, 不建 vbo/vao).
    与 engine.sceneio._apply_object 语义对齐 (无 material_id 旧文件路径).
    B1 (2026-08-30): 补 rigidbody/collider (含接触材质 friction/restitution) ——
    旧版缺失 = Vk 播放器物体没有任何刚体, 物理缺口根源之一."""
    models = []
    for obj in data['objects']:
        mesh = spec_to_mesh(obj.get('type', 'cube'), obj.get('params', {}))
        m = GameObject(
            mesh,
            Point3D(*obj.get('position', (0, 0, 0))),
            Point3D(*obj.get('rotation', (0, 0, 0))),
            name=obj.get('name', '物体'),
            scale=obj.get('scale', (1, 1, 1)),
            visible=obj.get('visible', True),
            color=obj.get('color'),
            primitive=obj.get('type', 'cube'),
            params=obj.get('params', {}),
            normal_mode=obj.get('normal_mode', 'flat'),
            saturation=obj.get('saturation', 1.0))
        m.guid = obj.get('id') or obj.get('guid')
        # 碰撞体 (M28 + B1): 文件有 collider 字段则覆盖默认 (缺省=默认, 兼容旧文件)
        col = obj.get('collider')
        if isinstance(col, dict):
            if col.get('shape') in ('box', 'sphere', 'none'):
                m.collider.shape = col['shape']
            m.collider.enabled = bool(col.get('enabled', True))
            m.collider.friction = float(col.get('friction', 0.5))
            m.collider.restitution = float(col.get('restitution', 0.0))
            m.collider.rolling_friction = float(col.get('rolling_friction', 0.1))
        # 刚体 (M31 + B1): 文件有 rigidbody 字段则加刚体 (旧文件无字段=无刚体)
        rb = obj.get('rigidbody')
        if isinstance(rb, dict):
            m.add_rigidbody(mass=rb.get('mass', 1.0),
                            use_gravity=rb.get('use_gravity', True),
                            is_kinematic=rb.get('is_kinematic', False),
                            friction=rb.get('friction', 0.5),
                            restitution=rb.get('restitution', 0.0),
                            rolling_friction=rb.get('rolling_friction', 0.1))
        # 脚本 (M25): 恢复全部脚本组件 (与 engine 语义一致, 惰性实例化见 step)
        scs = obj.get('scripts')
        if scs is None:
            sc = obj.get('script')
            scs = [sc] if isinstance(sc, dict) and sc.get('id') else []
        for s in scs:
            if isinstance(s, dict) and s.get('id'):
                m.add_script(s['id'], s.get('vars') if isinstance(s.get('vars'), dict) else {})
        models.append(m)
    # 父链 (parent_id -> guid 命中)
    by_guid = {m.guid: m for m in models if m.guid}
    for obj, m in zip(data['objects'], models):
        pid = obj.get('parent_id')
        if pid and pid in by_guid:
            m.parent = by_guid[pid]
    return models


def build_lights(data):
    """场景 dict -> LightState 列表 (与 sceneio 同字段语义)."""
    return [LightState(**{k: v for k, v in d.items()
                          if k in ('kind', 'position', 'direction', 'color',
                                   'intensity', 'name', 'guid', 'mode',
                                   'shape', 'size', 'shadow', 'azimuth',
                                   'elevation', 'roll')})
            for d in data.get('lights', [])]


class SceneDriver:
    """播放器中间层: 场景 + 每帧步进 (脚本/物理/动画/轨道相机) + VP 计算.

    帧循环 (后端调用):  vp, cam_pos = world.step(dt)  → 后端画 world.models/world.lights
    """

    def __init__(self, data=None):
        self.models = []
        self.lights = []
        self.target = (0.0, 0.0, 0.0)     # 轨道相机目标 (场景文件恢复)
        self.distance = 10.0
        self.yaw = 0.6
        self.pitch = -0.35
        self.fov = math.radians(45.0)
        self.near = 0.1
        self.far = 100.0
        # B1: 物理桥 (首次 step 惰性建) + 重力 (场景文件覆盖, 默认 -9.8 同引擎)
        self._bridge = None
        self._bridge_disabled = getattr(physb, 'cv_available', False) is not True
        self._bridge_warned = False
        self.gravity = -9.8
        # B1: 脚本 "引擎 API 最小面" 输入/相机安全默认 (无输入=不动; 后端口喂键时
        # 直接写 key_state / actions)
        self.key_state = {}                      # 键名 -> bool (同 engine.script_keys)
        self.actions = dict(DEFAULT_ACTIONS)     # 动作 -> 键名列表 (同 engine.actions)
        self.mouse_rel = (0, 0)
        self.mouse_locked = False
        self.mouse_unlock_requested = False
        self.camera = Point3D(0, 0, -5)          # 脚本接管相机 (first_person 等)
        self.camera_yaw = 0.0
        self.camera_pitch = 0.0
        self.orbit_mode = True                   # 脚本设置 False 表示脚本接管相机
        self.ui = _DriverUI()                    # 运行时 UI 空壳 (e.ui.text 安全 no-op)
        if data is not None:
            self.load_from_data(data)

    # ---------------- 加载 ----------------
    def load_from_data(self, data):
        self.models = build_models(data)
        self.lights = build_lights(data)
        cam = data.get('camera', {})
        self.target = tuple(cam.get('target', (0, 0, 0)))
        self.distance = cam.get('distance', 10.0)
        self.yaw = float(cam.get('yaw', 0.6))
        self.pitch = float(cam.get('pitch', -0.35))
        # B1 (2026-08-30): 场景 'gravity' 字段 (m/s², 负=向下) — 物理桥 R1 用
        self.gravity = float(data.get('gravity', -9.8))

    @property
    def camera_pos(self):
        """轨道相机位置 (与 engine.apply_orbit_camera 同公式).
        B1: 脚本接管相机 (first_person/third_person 设 orbit_mode=False +
        camera/camera_yaw/camera_pitch) -> 返回脚本的相机位置 (视角斜角沿用
        脚本 yaw/pitch 由渲染层从 driver.camera_yaw/camera_pitch 读取)."""
        if not getattr(self, 'orbit_mode', True):
            c = getattr(self, 'camera', None)
            if c is not None:
                return (c.x, c.y, c.z)
        ez = (math.sin(self.yaw) * math.cos(self.pitch),
              math.sin(self.pitch),
              math.cos(self.yaw) * math.cos(self.pitch))
        return (self.target[0] - self.distance * ez[0],
                self.target[1] - self.distance * ez[1],
                self.target[2] - self.distance * ez[2])

    # ---------------- 每帧步进 ----------------
    def step(self, dt, aspect=None):
        """推进脚本 + 物理桥 + 动画 (语义与 engine.update_scripts / update_physics
        (B1 桥路径) / update_animations 同步; 物理桥缺失 -> 无物理, 打印一次提示).
        返回 (vp, camera_pos): 渲染层用."""
        self._update_scripts(dt)
        self._step_physics(dt)
        self._update_animations(dt)
        cam_pos = self.camera_pos
        V = mat4_view_yaw_pitch(np, cam_pos, self.yaw, self.pitch)
        P = mat4_perspective(np, self.fov, aspect or 1.6, self.near, self.far)
        return V @ P, cam_pos

    # ---------------- B1: 物理桥 ----------------
    def _ensure_phys_bridge(self):
        """惰性建桥 (首次 step 直调; culverin 缺失/建体失败 -> None, 此后不重试)."""
        if self._bridge_disabled:
            return None
        if physb is None or not physb.cv_available:
            self._bridge_disabled = True
            if not self._bridge_warned:
                self._bridge_warned = True
                print("[驱动] 物理: culverin 不可导入 -> 无物理步进 (legacy 语义缺失)")
            return None
        try:
            br = physb.PhysicsWorldBridge()
            br.build(self.models)
        except Exception as e:
            print("[驱动] 物理桥建体失败 (%r) -> 无物理步进" % (e,))
            self._bridge_disabled = True
            return None
        self._bridge_disabled = False
        print("[驱动] Jolt (Culverin) 物理桥已建立: %d 体" % br.body_count)
        return br

    def _step_physics(self, dt):
        """物理桥三段 (脚本后/动画前, 同 engine 帧序): ensure_models 差量 ->
        pre_step (脏同步+策略R+手动重力 R1) -> step (释放 GIL) -> post_step 回读."""
        br = self._bridge
        if br is None:
            br = self._bridge = self._ensure_phys_bridge()
        if br is None:
            return
        try:
            br.ensure_models(self.models)
            br.pre_step(dt, self.gravity)
            br.step(dt)
            br.post_step()
        except Exception as e:
            print("[驱动] 物理桥步进异常 (%r) -> 本帧跳过" % (e,))

    def _update_scripts(self, dt):
        """复刻 engine.GLEngine.update_scripts: 惰性实例化 + update (坏脚本标记跳过).
        组2: 引用迭代 (与 engine 同改; 契约: update 不增删本物体脚本组件)."""
        for m in self.models:
            for sc in m.scripts:
                if not sc.script_id:
                    sc._script = None
                    sc._script_broken = False
                    continue
                if sc._script_broken:
                    continue
                s = sc._script
                if s is None:
                    cls = get_script(sc.script_id)
                    if cls is None:
                        continue
                    s = cls()
                    s.obj = m
                    s.engine = self          # 中间层代跑引擎角色 (脚本仅用 models/api)
                    for key, _label, default, *_ in cls.params:
                        if key in sc.script_vars:
                            s.vals[key] = sc.script_vars[key]
                    sc._script = s
                    try:
                        s.on_start()
                    except Exception as e:
                        print("[脚本] %s.on_start 出错: %r" % (m.name, e))
                        sc._script = None
                        sc._script_broken = True
                        continue
                try:
                    s.update(dt)
                except Exception as e:
                    print("[脚本] %s(%s) 出错: %r" % (m.name, sc.script_id, e))
                    sc._script = None
                    sc._script_broken = True

    def _update_animations(self, dt):
        """复刻 engine.GLEngine.update_animations: 推进动画插值应用变换."""
        for m in self.models:
            an = m.animator
            if an is None or not an.playing or not an.current:
                continue
            clip = an.clips.get(an.current)
            if clip is None or not clip.frames:
                continue
            an.time += dt
            s = clip.sample(an.time)
            if 'position' in s:
                m.position = Point3D(*s['position'])
            if 'rotation' in s:
                m.rotation = Point3D(*s['rotation'])
            if 'scale' in s:
                m.set_scale(s['scale'])
            if clip.duration > 0 and an.time >= clip.duration:
                if an.loop:
                    an.time -= clip.duration
                else:
                    an.playing = False

    # ================ B1: 脚本 "引擎 API 最小面" (修 Vk 播放器脚本 broken) ================
    # 与 engine.GLEngine 同签名同语义 (几何走 physics_bridge 静态助手, 公式逐位
    # 一致); 输入/相机按安全默认 (无输入=不动), 后端口可喂 key_state。

    def world_position(self, m):
        """物体中心世界坐标 (含父链) — 与 engine.world_position 同."""
        if physb is None:
            p = m.position
            return Point3D(p.x, p.y, p.z) if p is not None else Point3D(0, 0, 0)
        wp = physb.world_position_vec(m)
        return Point3D(float(wp[0]), float(wp[1]), float(wp[2]))

    def move_with_collision(self, m, dx, dy, dz, bounds=None):
        """带碰撞的位移 (M28 响应) — 与 engine.move_with_collision 逐位一致.
        返回 True = 被挡住/发生碰撞."""
        if physb is None:
            return False
        return physb.move_with_collision(self.models, m, dx, dy, dz, bounds)

    def get_collisions(self, m, fw=None, bounds=None):
        """碰撞查询 — 与 engine.get_collisions 同 (其他物体按 models 顺序)."""
        if physb is None:
            return []
        return physb.get_collisions(self.models, m, bounds)

    def collider_hit(self, a, b):
        """两物体是否碰撞 (同树不算) — 与 engine.collider_hit 同."""
        if physb is None:
            return False
        return physb.collider_hit(a, b)

    # ---- 输入 (安全默认: 无键=不动; 后端口喂数据写 key_state / 改 actions) ----
    def is_key(self, name):
        """按键状态查询 — 同 engine.is_key; 默认全 False (无输入=不动)."""
        return bool(self.key_state.get(name, False))

    def get_action(self, name):
        """输入动作层查询 — 同 engine.get_action; 默认 False."""
        for k in self.actions.get(name, (name,)):
            if self.key_state.get(k, False):
                return True
        return False

    def set_mouse_locked(self, locked):
        self.mouse_locked = bool(locked)

    def toggle_mouse_locked(self):
        self.mouse_locked = not self.mouse_locked

    def player_pitch_limits(self):
        """激活相机俯仰角限制 — 驱动无玩家相机概念 -> None (脚本兜底默认钳位)."""
        return None

    # ---- 相机 (脚本读写; 轨道相机与脚本视角分离) ----
    @property
    def camera_target(self):
        return self.target

    @camera_target.setter
    def camera_target(self, v):
        self.target = (float(v[0]), float(v[1]), float(v[2]))

    @property
    def camera_distance(self):
        return self.distance

    @camera_distance.setter
    def camera_distance(self, v):
        self.distance = float(v)

    def remove_model(self, m):
        """从模型列表移除 (count_touch 等脚本用; 引擎侧含 GPU 释放, 驱动无 GPU)."""
        if m in self.models:
            self.models.remove(m)


class _DriverUI:
    """运行时 UI 空壳 (count_touch 等脚本调用 e.ui.text; 驱动层不支持运行时 UI,
    安全 no-op 保证脚本不 broken)."""

    def __init__(self):
        self._items = []

    def text(self, message, x=0, y=0, size=22, color=None):
        self._items.append(('text', str(message), x, y, size, color))

    def button(self, label, x, y, size=22, callback=None):
        self._items.append(('button', str(label), x, y, size, callback))

    def progress(self, value, x, y, w=100, h=12, label=None):
        self._items.append(('progress', float(value), x, y, w, h, label))

    def draw(self):          # 渲染层自行消费 self._items; 此处只占位
        pass
