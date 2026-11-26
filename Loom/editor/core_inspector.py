# -*- coding: utf-8 -*-
"""editor/core_inspector.py — 属性面板字段命令：变换/光源/相机字段、改名校验与通知、碰撞与触发、刚体、音频、动画、脚本、Prefab 解链、相机预览与 FOV 锁、俯仰角限制。

Q-B7-38-1 第 9 批（agent-99）：editor/core.py 按能力域拆分的**纯搬迁**产物 ——
类体成员从 editor/core.py 的 _EditorCore 逐字搬入本 mixin（方法体一行未改）；
装配见 editor/core.py 的 _EditorCore(EngineCore, <各域 mixin> ...)。

我负责：属性面板字段命令：变换/光源/相机字段、改名校验与通知、碰撞与触发、刚体、音频、动画、脚本、Prefab 解链、相机预览与 FOV 锁、俯仰角限制。
我不负责：场景对象增删（core_object）。
mixin 之间只经 self 互调（装配后同一个实例），互不 import。
"""
import time
from editor.undo import (UndoManager, Command, StateCommand, AddObjectCommand,
                  DeleteObjectCommand, ReparentCommand, DuplicateObjectCommand,
                  PrefabPlaceCommand, snapshot as undo_snapshot,
                  apply_snapshot,
                  LightStateCommand, AddLightCommand, DeleteLightCommand,
                  AddMaterialCommand, light_snapshot, apply_light_snapshot,
                  CameraStateCommand, AddCameraCommand, DeleteCameraCommand,
                  ReparentCameraCommand,
                  camera_snapshot, apply_camera_snapshot)

class EditorInspectorMixin(object):
    """属性面板字段命令：变换/光源/相机字段、改名校验与通知、碰撞与触发、刚体、音频、动画、脚本、Prefab 解链、相机预览与 FOV 锁、俯仰角限制（纯搬迁）。"""

    def _notify(self, msg, color=(220, 222, 228)):
        """状态栏提示 (toast, 约 4s 后自动消失). 命名校验/导入结果/设置项共用.
        (2026-08-17: 命名合法性提示统一走这里, 由 旧版GUI._draw_toast 渲染到屏幕)"""
        self.msg = msg
        self.msg_color = color
        self._msg_until = time.time() + 4.0

    def _validate_object_name(self, new_name, exclude):
        """命名合法性 (2026-08-17): 所有物体(模型/光源/摄像机)共用一个名字池.
        规则: ① 空名(去空白后)非法; ② 与其他任意物体重名(按去空白比较)非法.
        exclude 为被改名对象本体 (按 is 排除自身, 允许"重命名为自己的当前名字").
        返回 None 表示合法, 否则返回错误提示字符串 (交给 _notify 显示)."""
        stripped = new_name.strip()
        if not stripped:
            return "名称不能为空"
        for obj in list(self.models) + list(self.lights) + list(self.cameras):
            if obj is exclude:
                continue
            if getattr(obj, 'name', '').strip() == stripped:
                return "名称已存在: %s" % stripped
        return None

    def rename(self, m, new_name, old_name):
        err = self._validate_object_name(new_name, exclude=m)
        if err:
            self._notify(err, (235, 90, 90))
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        before = undo_snapshot(m)
        before['name'] = old_name
        m.name = new_name
        self.undo.push(StateCommand("改名", self, m, before, undo_snapshot(m)))

    # ---- 物体字段命令 (undo_snapshot + StateCommand) ----
    def edit_model(self, m, label, active, key, apply_fn):
        """拖拽式字段命令: active 期间每次调 apply_fn, 结束按快照差异压撤销."""
        if active and key not in self._insp_undo_start:
            self._insp_undo_start[key] = undo_snapshot(m)
        apply_fn()
        if not active and key in self._insp_undo_start:
            before = self._insp_undo_start.pop(key)
            after = undo_snapshot(m)
            if after != before:
                self.undo.push(StateCommand(label, self, m, before, after))

    def commit_model(self, m, label, apply_fn, before=None):
        """单次字段命令: 取 before 快照(可覆盖) -> apply_fn -> 压撤销."""
        before = before if before is not None else undo_snapshot(m)
        apply_fn()
        after = undo_snapshot(m)
        if after != before:
            self.undo.push(StateCommand(label, self, m, before, after))

    # ---- 光源字段命令 (light_snapshot + LightStateCommand) ----
    def edit_light(self, light, label, active, key, apply_fn):
        if active and key not in self._light_undo_start:
            self._light_undo_start[key] = light_snapshot(light)
        apply_fn()
        if not active and key in self._light_undo_start:
            before = self._light_undo_start.pop(key)
            after = light_snapshot(light)
            if after != before:
                self.undo.push(LightStateCommand(label, self, light, before, after))

    def commit_light(self, light, label, apply_fn, before=None):
        before = before if before is not None else light_snapshot(light)
        apply_fn()
        after = light_snapshot(light)
        if after != before:
            self.undo.push(LightStateCommand(label, self, light, before, after))

    def rename_light(self, light, new_name, old_name):
        err = self._validate_object_name(new_name, exclude=light)
        if err:
            self._notify(err, (235, 90, 90))
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        before = light_snapshot(light)
        before['name'] = old_name
        light.name = new_name
        self.undo.push(LightStateCommand("光源改名", self, light, before,
                                         light_snapshot(light)))

    # ---- 摄像机字段命令 (camera_snapshot + CameraStateCommand) ----
    def edit_camera(self, cam, label, active, key, apply_fn):
        if active and key not in self._cam_undo_start:
            self._cam_undo_start[key] = camera_snapshot(cam)
        apply_fn()
        if not active and key in self._cam_undo_start:
            before = self._cam_undo_start.pop(key)
            after = camera_snapshot(cam)
            if after != before:
                self.undo.push(CameraStateCommand(label, self, cam, before, after))

    def commit_camera(self, cam, label, apply_fn, before=None):
        before = before if before is not None else camera_snapshot(cam)
        apply_fn()
        after = camera_snapshot(cam)
        if after != before:
            self.undo.push(CameraStateCommand(label, self, cam, before, after))

    def rename_camera(self, cam, new_name, old_name):
        err = self._validate_object_name(new_name, exclude=cam)
        if err:
            self._notify(err, (235, 90, 90))
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        before = camera_snapshot(cam)
        before['name'] = old_name
        cam.name = new_name
        self.undo.push(CameraStateCommand("摄像机改名", self, cam, before,
                                          camera_snapshot(cam)))

    # ---- 组件/动作命令 (单次, 自动撤销) ----
    def toggle_collider(self, m):
        self.commit_model(m, "碰撞体开关",
                          lambda: setattr(m.collider, 'enabled', not m.collider.enabled))

    def toggle_trigger(self, m):
        """2026-10-18 阶段1档序17 Trigger: 切换 collider.is_trigger。
        is_trigger=True 时物理层建 sensor 体（可重叠穿过），事件走 on_trigger_*。"""
        self.commit_model(m, "触发器开关",
                          lambda: setattr(m.collider, 'is_trigger',
                                          not m.collider.is_trigger))

    def add_rigidbody(self, m):
        self.commit_model(m, "加刚体", m.add_rigidbody)

    def remove_rigidbody(self, m):
        self.commit_model(m, "移除刚体", m.remove_rigidbody)

    def toggle_rigidbody_gravity(self, m):
        self.commit_model(m, "刚体重力",
                          lambda: setattr(m.rigidbody, 'use_gravity',
                                          not m.rigidbody.use_gravity))

    def add_audio_source(self, m):
        self.commit_model(m, "加音频源", m.add_audio_source)

    def remove_audio_source(self, m):
        self.commit_model(m, "移除音频", m.remove_audio_source)

    def toggle_audio_playing(self, m):
        if m.audio_source is not None:
            m.audio_source.playing = not m.audio_source.playing

    def toggle_audio_loop(self, m):
        self.commit_model(m, "音频循环",
                          lambda: setattr(m.audio_source, 'loop', not m.audio_source.loop))

    def set_audio_clip(self, m, clip, old_clip):
        """音频文件路径失焦提交 (可撤销)."""
        if clip == old_clip:
            return
        # 2026-08-27 修复: undo_snapshot 的 audio_source 是**元组**
        # (clip, loop, volume), 旧代码 dict(元组) 直接 TypeError —— 检查器
        # 音频路径框每次失焦提交都炸 (异常被 Qt 信号层吞掉, 表现为改不动).
        snap = undo_snapshot(m)
        au = snap.get('audio_source')
        if au is None:
            return                       # 没有音频组件, 无从设置
        before = {**snap, 'audio_source': (old_clip, au[1], au[2])}
        m.audio_source.clip = clip
        self.undo.push(StateCommand("音频文件", self, m, before, undo_snapshot(m)))

    def add_animator(self, m):
        self.commit_model(m, "加动画", m.add_animator)

    def remove_animator(self, m):
        self.commit_model(m, "移除动画", m.remove_animator)

    def play_anim(self, m, name):
        if m.animator is not None:
            m.animator.play(name, restart=True)

    def toggle_anim_playing(self, m):
        if m.animator is not None:
            m.animator.playing = not m.animator.playing

    def toggle_anim_loop(self, m):
        self.commit_model(m, "动画循环",
                          lambda: setattr(m.animator, 'loop', not m.animator.loop))

    # ---- beta6 C1: 每片段循环模式 / 播放速率 (命令层 + 检查器共用, 可撤销) ----
    def set_anim_loop_mode(self, m, clip_name, mode):
        """设置某片段的循环模式 ('once'/'loop'/'pingpong'/'inherit'). 可撤销."""
        clip = m.animator.clips.get(clip_name) if m.animator is not None else None
        if clip is None:
            raise ValueError('片段不存在: %r (可用: %s)'
                             % (clip_name, list(m.animator.clips or [])
                                if m.animator is not None else []))
        mode = str(mode if mode is not None else '').strip().lower()
        if mode in ('inherit', 'none', 'default', ''):
            mode = None
        elif mode not in ('once', 'loop', 'pingpong'):
            raise ValueError('loop_mode 只能 once|loop|pingpong|inherit, 收到 %r'
                             % (mode,))
        self.commit_model(m, "动画循环模式",
                          lambda: setattr(clip, 'loop_mode', mode))
        return mode

    def set_anim_speed(self, m, speed):
        """设置播放速率 (写入场景, 可撤销). 非法值抛 ValueError 且模型不变."""
        if m.animator is None:
            raise ValueError('没有动画组件')
        before = undo_snapshot(m)
        m.animator.set_speed(speed)      # set_speed 先校验后写: 失败时模型不变
        after = undo_snapshot(m)
        if after != before:
            self.undo.push(StateCommand("动画变速", self, m, before, after))
        return m.animator.speed

    def add_script(self, m, sid, extra_vars=None):
        """挂脚本 + 套默认参数 (可撤销).

        2026-10-19 P0-2 修复: 先校验 sid 是否注册，再动模型 —— 旧顺序是先
        m.add_script(sid) 把组件加进去，再 get_script(sid).params，sid 不存在时
        .params 抛 AttributeError，但坏组件已入模型且未回滚，场景被污染。
        修复后：未注册时直接抛 ValueError，模型不变。

        extra_vars: 挂载时覆盖默认参数（对齐 P1-1 script_vars 透传）。
        """
        import script.scripts as _scripts
        cls = _scripts.get_script(sid)
        if cls is None:
            raise ValueError(
                "脚本不存在: %r（先 script_reload 热重载，或用 scripts 查看已注册列表）"
                % sid)
        before = undo_snapshot(m)
        sc = m.add_script(sid)
        for key, _lb, default, *_ in cls.params:
            sc.script_vars[key] = default
        if extra_vars and isinstance(extra_vars, dict):
            for k, v in extra_vars.items():
                # 只接受已声明参数，避免污染 script_vars
                if any(p[0] == k for p in cls.params):
                    sc.script_vars[k] = v
        self.undo.push(StateCommand("挂脚本", self, m, before, undo_snapshot(m)))

    def remove_script(self, m, i):
        self.commit_model(m, "卸脚本", lambda: m.remove_script(i))

    def set_script_var(self, m, i, key, value, active, kkey):
        """脚本参数拖拽 (edit_ 式撤销)."""
        if active and kkey not in self._insp_undo_start:
            self._insp_undo_start[kkey] = undo_snapshot(m)
        m.scripts[i].script_vars[key] = value
        if not active and kkey in self._insp_undo_start:
            before = self._insp_undo_start.pop(kkey)
            after = undo_snapshot(m)
            if after != before:
                self.undo.push(StateCommand("脚本参数", self, m, before, after))

    def unlink_prefab(self, m):
        self.commit_model(m, "断开Prefab", lambda: setattr(m, 'prefab_ref', None))

    def toggle_cam_fov_locked(self, cam):
        self.commit_camera(cam, "摄像机视角可调",
                           lambda: setattr(cam, 'fov_locked', not cam.fov_locked))

    def set_active_camera(self, cam):
        """把某摄像机设为场景激活相机 (播放时视角走它; 随场景序列化).
        传 None = 取消激活 (active_camera=None, 播放时用编辑器轨道视角/脚本视角)."""
        if cam is None:
            self.active_camera = None
            self._refresh_effective_skybox()
            return
        self.active_camera = cam.guid
        # Q3=A: 换了激活相机 -> 相机级天空盒优先级随之变化
        self._refresh_effective_skybox()

    # ---- 摄像机"用此相机预览" (M41: 编辑器视口切到某摄像机视角) ----
    def toggle_camera_preview(self, cam):
        if cam is None:
            return
        if self.preview_camera is cam:
            self.exit_camera_preview()
            return
        # 首次进入才捕获轨道视角 (切到第二个相机不覆盖)
        if self._preview_orbit is None:
            self._preview_orbit = (self.camera_target, self.camera_distance,
                                   self.camera_yaw, self.camera_pitch)
        self.preview_camera = cam
        self._select_camera(cam)

    def exit_camera_preview(self):
        """退出预览, 还原进入前轨道视角. 开发者轨道相机恒直立 (roll 归零,
        预览过带倾斜的相机会把 camera_roll 带歪, 必须清掉)."""
        if self.preview_camera is None:
            return
        self.preview_camera = None
        if self._preview_orbit is not None:
            t, d, y, p = self._preview_orbit
            self.camera_target, self.camera_distance = t, d
            self.camera_yaw, self.camera_pitch = y, p
            self._preview_orbit = None
        self.camera_roll = 0.0       # 修复: 预览倾斜相机退出后开发者视角不再歪
        self.orbit_mode = True
        self.apply_orbit_camera()

    # ---- 摄像机俯仰角限制 (M41): 拖条会话结束校验 [pitch_min, pitch_max] 非空 ----
    def edit_camera_pitch_bound(self, cam, key, field, active, value):
        """pitch_min/pitch_max 拖拽: 会话结束 (active 由真->假) 校验范围交集非空
        (pitch_min <= pitch_max), 非法则回滚会话前快照 + 提示 (不压撤销)."""
        if active and key not in self._cam_undo_start:
            self._cam_undo_start[key] = camera_snapshot(cam)
        setattr(cam, field, value)               # 拖拽中实时 / 会话末应用最终值
        if not active and key in self._cam_undo_start:
            before = self._cam_undo_start.pop(key)
            if cam.pitch_min <= cam.pitch_max:
                after = camera_snapshot(cam)
                if after != before:
                    self.undo.push(CameraStateCommand(
                        "摄像机俯仰角限制", self, cam, before, after))
            else:
                apply_camera_snapshot(cam, before, self)   # 交集为空: 回滚合法会话前快照
                gui = getattr(self.view, 'gui', None)
                if gui is not None:
                    gui.notice = "俯仰角范围无效: 最低俯角不能高于最高仰角"
