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
import weakref

from components.components import evaluate_animations, physics_disabled_by_env


# ============ 2026-11-17 (B7-26): 音频段与碰撞回调的**共享实现**（两端同一份） ============
# 原来这两个方法只长在 FrameComponentMixin 上，VK 的 SceneDriver 一个都没有 —— 于是 VK 下
# AudioSource 的 play/stop 永不发生、脚本碰撞回调永不触发。抽成模块级函数后 GL/VK 都调同一份。


def sync_audio_listener(host):
    """监听器隐式跟随相机（契约 §3 / A1 决策）：优先当前玩家视角摄像机，
    无则用引擎内部相机（GL 的 `camera + camera_yaw/pitch`，VK 的 `current_camera_position + yaw/pitch`）。
    相机看向 -ez，故监听器前向 = -ez，上方向 = ey。失败静默（降级为无 3D 参照）。"""
    try:
        cam = host.active_camera_object()
        if cam is not None:
            pos = host.camera_world_position(cam)
            _ex, ey, ez = host.camera_world_basis(cam)
        else:
            pos = getattr(host, 'camera', None)
            if pos is None:
                pos = host.current_camera_position
            yaw = getattr(host, 'camera_yaw', None)
            if yaw is None:
                yaw = getattr(host, 'yaw', 0.0)
            pitch = getattr(host, 'camera_pitch', None)
            if pitch is None:
                pitch = getattr(host, 'pitch', 0.0)
            cy, sy = math.cos(yaw), math.sin(yaw)
            cp, sp = math.cos(pitch), math.sin(pitch)
            ey = (-sy * sp, cp, -cy * sp)
            ez = (sy * cp, sp, cy * cp)
        fwd = (-ez[0], -ez[1], -ez[2])
        host.audio.set_listener((pos.x, pos.y, pos.z), fwd, ey)
    except Exception:
        pass          # 监听器同步失败不影响音频播放（降级为无 3D 参照）


def update_audio(host, dt):
    """M34: 每帧按 AudioSource 组件 playing 状态 play/stop（播放状态变化才操作）。
    逐行照抄原 FrameComponentMixin.update_audio（行为不变），宿主只需提供
    `models / audio / world_position / active_camera_object / camera_world_position /
    camera_world_basis` 与 `camera 或 current_camera_position`。"""
    sync_audio_listener(host)
    for m in host.models:
        a = m.audio_source
        if a is None or not a.clip:
            continue
        spatial = a.is_spatial() if hasattr(a, 'is_spatial') else False
        key = (a.clip, bool(a.playing))
        if key != a._key:
            if a.playing:
                if spatial:
                    p = host.world_position(m)
                    a._last_pos = (p.x, p.y, p.z)
                    host.audio.play_spatial(
                        a.clip, a._last_pos, loop=a.loop, volume=a.volume,
                        min_distance=a.min_distance,
                        max_distance=a.max_distance,
                        rolloff=a.rolloff, owner=id(a))
                else:
                    host.audio.play(a.clip, a.loop, a.volume, owner=id(a))
            elif a._key is not None:   # 只在曾播放过才 stop（初始/新组件不空停）
                host.audio.stop(a.clip, owner=id(a))
            a._key = key
            continue
        if spatial and a.playing:      # 已在播：仅位置变化时更新
            p = host.world_position(m)
            cur = (p.x, p.y, p.z)
            last = getattr(a, '_last_pos', None)
            if last is None or (abs(cur[0] - last[0]) > 1e-4
                                or abs(cur[1] - last[1]) > 1e-4
                                or abs(cur[2] - last[2]) > 1e-4):
                a._last_pos = cur
                host.audio.update_sound_position(a.clip, cur, owner=id(a))


def call_collision_cb(m, hook, other):
    """调物体上所有脚本的碰撞回调（坏脚本标记不崩帧）。实现已收敛到 loom_collision。"""
    return _lc.call_cb(m, hook, other)


import components.collision as _lc   # noqa: E402  (模块级共享：碰撞回调)

class FrameComponentMixin:

    def _sync_audio_listener(self):
        """监听器隐式跟随相机。2026-11-17 (B7-26): 实现搬进模块级 sync_audio_listener ——
        VK 侧 SceneDriver 调的是**同一个函数**。"""
        return sync_audio_listener(self)
    def update_audio(self, dt):
        """M34: 每帧按 AudioSource 组件 playing 状态 play/stop。

        2026-11-17 (B7-26): 实现搬进模块级 update_audio —— VK 侧调同一份，
        两端 AudioSource 语义不可能再分叉。行为逐位不变。"""
        return update_audio(self, dt)
    def update_animations(self, dt):
        """推进动画并应用变换 (位置/旋转/缩放).

        beta6 C1: 实现已收敛到 loom_components.evaluate_animations ——
        与 scene_driver.SceneDriver._update_animations **同一份**内核
        (批量 SoA + once 末帧 + 跨周期规范化 + D6 写者优先级)。
        旧实现在此逐物体 sample, 500 物体 12.7ms/逻辑帧。

        R5-02 P-06: 把"物理后端是否真的在驱动刚体"传下去 —— 桥缺失/被禁时
        动态刚体改由动画驱动 (否则位姿永久冻结)。判定取保守面: 桥已建 -> 可用;
        未建但引擎声明会惰性建桥 (_phys_bridge_auto) -> 仍按可用处理 (首帧
        物理会接管, 避免"第 1 帧动画驱动、第 2 帧物理接管"的位姿跳变)。
        """
        pb = getattr(self, '_phys_bridge', None)
        phys_ok = (pb is not None) or bool(
            getattr(self, '_phys_bridge_auto', False))
        if getattr(self, '_phys_bridge_disabled', False):
            phys_ok = False
        if physics_disabled_by_env():        # R6 V-10: LOOM_NO_PHYSICS=1 真开关
            phys_ok = False
        stats = evaluate_animations(self.models, dt, physics_available=phys_ok)
        # R6 V-08: 回退驱动的这批物体要在**同一帧**的物理步里被排除,
        # 否则动画位姿 + legacy 物理位姿叠加 (偏移每帧线性增长)。
        # R6 F-03: 用 WeakSet 而非 list —— 播放中删掉的模型不会因为这张名单
        # 被强引用而滞留 (物理侧 set(weakset) 只取仍存活的对象)。
        self._anim_fallback_models = weakref.WeakSet(
            stats.get('fallback_models') or ())
        return stats

    def _clear_anim_fallback(self):
        """清空"动画回退驱动"名单 (F-03: 播放开始/停止时调用, 不留跨会话引用)."""
        self._anim_fallback_models = ()

    def _call_collision_cb(self, m, hook, other):
        """调物体上所有脚本的碰撞回调（坏脚本标记不崩帧）。

        2026-11-17 (B7-26): 实现已收敛到 loom_collision.call_cb（VK 侧同一份）。"""
        return call_collision_cb(m, hook, other)