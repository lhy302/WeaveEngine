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

from loom_types import Point3D


class FrameComponentMixin:

    def update_audio(self, dt):
        """M34: 每帧按 AudioSource 组件 playing 状态 play/stop (播放状态变化才操作).
        B2 (2026-08-30): owner=id(组件) —— game-audio 句柄级音量, 同 clip 多组件
        各自独立 (pygame 同 Sound 共享音量, 旧语义下多音量互踩)."""
        for m in self.models:
            a = m.audio_source
            if a is None or not a.clip:
                continue
            key = (a.clip, bool(a.playing))
            if key != a._key:
                if a.playing:
                    self.audio.play(a.clip, a.loop, a.volume, owner=id(a))
                elif a._key is not None:   # 只在曾播放过才 stop (初始/新组件不空停)
                    self.audio.stop(a.clip, owner=id(a))
                a._key = key

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
