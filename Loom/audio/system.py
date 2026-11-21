# -*- coding: utf-8 -*-
"""audio/system.py — AudioSystem 音频门面（目录重构 B6 批，2026-11-21）。

原属 loom_components.py 尾部（engine.py "组件化 (M25)" 段带来；B6 按域拆出：
音频门面归 audio/ 包）。依赖：
  - audio.backend.AudioBackend（函数内惰性 import，本文件唯一引擎内依赖）

为什么能干净拆出: AudioSystem 与组件家族**零共享状态** —— 对 loom_components
其余部分（组件类/动画快路径）无任何引用，audio_backend 只在 _ensure() 里惰性
import。唯一实现只有这一份；旧调用面 `from loom_components import
AudioSystem` 全部改指本模块（components.components 不 re-export）。
公开 API 语义一字不改：load / play / play_sound / stop / shutdown（2D）
+ set_listener / play_spatial / update_sound_position（3D 纯转发）。
"""


def _delegate_to_backend(name, doc):
    """生成 AudioSystem 的**纯转发**方法：把同名调用转给 audio_backend.AudioBackend。

    P4-1（2026-11-19）：3D 音频三个方法（set_listener / play_spatial /
    update_sound_position）在 audio_backend.py 里早已实现，但 AudioSystem 门面漏了转发。
    用转发器生成而不手写三个 def 的理由：实现只能有一份（解耦规则 3），且门
    test_audio_parity.py 的结构断言要求「def <name> 只有 audio_backend.py 一份实现」。
    语义完全由 AudioBackend 决定（返回值 / 静默降级 / 无设备 no-op 一律原样透传）。
    """
    def _forward(self, *args, **kwargs):
        return getattr(self._ensure(), name)(*args, **kwargs)
    _forward.__name__ = name
    _forward.__qualname__ = 'AudioSystem.' + name
    _forward.__doc__ = doc
    return _forward


class AudioSystem:
    """M34: 音频后端封装 (B2 2026-08-30 换库: 委托 audio_backend.AudioBackend).

    主后端 = game-audio (miniaudio); 兜底 = pygame.mixer (现状语义); 两者皆失败
    → 全静默 no-op (与现状无设备同语义). 公开 API 语义不变: 文件缺失不崩,
    播放失败静默; owner=组件身份 (id 组件) 供同 clip 多组件独立音量.
    ★退出必须 shutdown() (miniaudio 设备线程; 引擎退出链 + atexit 三重兜底).

    公开 API = load / play / play_sound / stop / shutdown（2D）+ set_listener /
    play_spatial / update_sound_position（3D 空间音频，2026-11-19 P4-1 补；**纯委托**
    audio_backend.AudioBackend 的同名方法，本类不另写实现 —— 解耦规则 3）。"""
    def __init__(self):
        self._backend = None   # 惰性 (audio_backend.AudioBackend)
        self._init_done = False

    def _ensure(self):
        if not self._init_done:
            from audio.backend import AudioBackend
            self._backend = AudioBackend()
            self._init_done = True
        return self._backend

    def load(self, path):
        """加载/缓存句柄 (失败 None 缓存, 不崩). 无 owner = 共享句柄 (一次性音效)."""
        b = self._ensure()
        return b.load(path, owner=None)

    def play(self, path, loop=False, volume=1.0, owner=None):
        """播放音效 (loop=True 循环). 文件缺失/后端失败静默跳过."""
        self._ensure().play(path, loop=loop, volume=volume, owner=owner)

    def stop(self, path, owner=None):
        """停止 (幂等; 未播放/未加载静默)."""
        b = self._ensure()
        b.stop(path, owner=owner)

    def play_sound(self, path, volume=1.0):
        """脚本用: 一次性音效 (如跳跃/碰撞)."""
        self.play(path, loop=False, volume=volume)

    # ---- 3D 空间音频（P4-1，2026-11-19）：**纯转发**，实现唯一在 audio_backend.py ----
    # 修前：AudioSystem 只有 load/play/stop/play_sound/shutdown，而
    # loom_frame_components.update_audio（:71）调 play_spatial / update_sound_position、
    # sync_audio_listener（:49）调 set_listener → category=sfx/voice（**默认 sfx**）且
    # playing=True 的 3D 音源一播就 AttributeError（GL/VK 两端同坏 = 3D 音效根本不播）；
    # set_listener 的 AttributeError 被 sync_audio_listener 的 except 吞掉 → 监听器永不生效。
    # 这里**不写三个 def**：实现唯一在 audio_backend.AudioBackend（解耦规则 3「共享前置
    # 抽唯一实现，不许另写一套」），AudioSystem 只做同名转发；门 test_audio_parity.py
    # 的结构断言也正是「def play_spatial / def set_listener / def update_sound_position
    # 只有 audio_backend.py 一份实现（AudioSystem 必须委托它）」。
    set_listener = _delegate_to_backend(
        'set_listener',
        "3D 监听器（相机）位置/前向/上方向同步（契约 §3）。纯委托 AudioBackend；"
        "无 3D 能力的后端（pygame）静默 no-op。")
    play_spatial = _delegate_to_backend(
        'play_spatial',
        "3D 播放（AudioSource category=sfx/voice，契约 §4.1）：位置/距离/衰减/循环/音量。"
        "纯委托 AudioBackend；pygame 后端按 2D 播放（警告一次）。")
    update_sound_position = _delegate_to_backend(
        'update_sound_position',
        "更新已播放 3D 音源的世界位置（物体移动时每帧调，契约 §4.1）。纯委托 AudioBackend。")

    def shutdown(self):
        """关闭音频设备后端 (幂等; 进程退出链 + atexit 兜底)."""
        if self._backend is not None:
            try:
                self._backend.shutdown()
            except Exception:
                pass
