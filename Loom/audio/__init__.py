"""audio/ — 音频域（目录重构 B6 批，2026-11-21）。

模块：
  backend.py   双后端适配层 game-audio(miniaudio) / pygame.mixer（原 audio_backend.py）
  system.py    AudioSystem 音频门面（原 loom_components.py 尾部，B6 按域拆出；
               与组件家族零共享状态，唯一实现只有这一份）

刻意不 re-export：audio.backend 单独导入不许拉起组件/引擎图。
"""
