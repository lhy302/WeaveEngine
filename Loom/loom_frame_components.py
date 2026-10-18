# -*- coding: utf-8 -*-
"""loom_frame_components.py — GLEngine 每帧组件推进子系统。

从 engine.py 抽出 3 个方法 (作为 FrameComponentMixin 供 GLEngine 继承):
  update_audio            (M34 AudioSource 组件每帧 play/stop)
  update_animations       (M35 Animator 组件每帧推进 + 插值应用)
  _call_collision_cb      (脚本碰撞回调派发, 坏脚本标记不崩帧)

依赖宿主 GLEngine 运行时提供:
  - self.models / self.audio
mixin 只通过 self 按需访问 (语义与拆分前逐位一致)。
"""

import math

from loom_types import Point3D


class FrameComponentMixin:

    def _sync_audio_listener(self):
        """2026-10-18 3D 音频 (契约 §3): 监听器隐式跟随相机 (A1 决策).
        优先当前玩家视角摄像机; 无则用引擎内部相机 (self.camera + yaw/pitch).
        相机看向 -ez (视图空间), 故监听器前向 = -ez, 上方向 = ey."""
        try:
            cam = self.active_camera_object()
            if cam is not None:
                pos = self.camera_world_position(cam)
                _ex, ey, ez = self.camera_world_basis(cam)
            else:
                pos = self.camera
                cy, sy = math.cos(self.camera_yaw), math.sin(self.camera_yaw)
                cp, sp = math.cos(self.camera_pitch), math.sin(self.camera_pitch)
                ey = (-sy * sp, cp, -cy * sp)
                ez = (sy * cp, sp, cy * cp)
            fwd = (-ez[0], -ez[1], -ez[2])
            self.audio.set_listener((pos.x, pos.y, pos.z), fwd, ey)
        except Exception:
            pass          # 监听器同步失败不影响音频播放 (降级为无 3D 参照)

    def update_audio(self, dt):
        """M34: 每帧按 AudioSource 组件 playing 状态 play/stop (播放状态变化才操作).
        B2 (2026-08-30): owner=id(组件) —— game-audio 句柄级音量, 同 clip 多组件
        各自独立 (pygame 同 Sound 共享音量, 旧语义下多音量互踩).
        2026-10-18 3D 音频: category=music 强制 2D; sfx/voice 走 3D (带位置+距离衰减).
        空间化音源移动时每帧更新位置 (容差 1e-4, 未移动零开销)."""
        self._sync_audio_listener()
        for m in self.models:
            a = m.audio_source
            if a is None or not a.clip:
                continue
            spatial = a.is_spatial() if hasattr(a, 'is_spatial') else False
            key = (a.clip, bool(a.playing))
            if key != a._key:
                if a.playing:
                    if spatial:
                        p = self.world_position(m)
                        a._last_pos = (p.x, p.y, p.z)
                        self.audio.play_spatial(
                            a.clip, a._last_pos, loop=a.loop, volume=a.volume,
                            min_distance=a.min_distance,
                            max_distance=a.max_distance,
                            rolloff=a.rolloff, owner=id(a))
                    else:
                        self.audio.play(a.clip, a.loop, a.volume, owner=id(a))
                elif a._key is not None:   # 只在曾播放过才 stop (初始/新组件不空停)
                    self.audio.stop(a.clip, owner=id(a))
                a._key = key
                continue
            if spatial and a.playing:      # 已在播: 仅位置变化时更新
                p = self.world_position(m)
                cur = (p.x, p.y, p.z)
                last = getattr(a, '_last_pos', None)
                if last is None or (abs(cur[0] - last[0]) > 1e-4
                                    or abs(cur[1] - last[1]) > 1e-4
                                    or abs(cur[2] - last[2]) > 1e-4):
                    a._last_pos = cur
                    self.audio.update_sound_position(a.clip, cur, owner=id(a))

    def update_animations(self, dt):
        """M35: 每帧推进动画并插值应用变换 (位置/旋转/缩放)."""
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

    def _call_collision_cb(self, m, hook, other):
        """调物体上所有脚本的碰撞回调 (坏脚本标记不崩帧)."""
        for sc in m.scripts:
            inst = getattr(sc, '_script', None)
            if inst is None or getattr(sc, '_script_broken', False):
                continue
            fn = getattr(inst, hook, None)
            if fn is None:
                continue
            try:
                fn(other)
            except Exception as e:
                print("[脚本] %s(%s) %s 出错: %r" % (m.name, sc.script_id, hook, e))
                sc._script_broken = True
