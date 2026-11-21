# -*- coding: utf-8 -*-
"""render/contract/ — 两端共享的渲染描述层（零后端依赖）。

纪律（与 scene/contract 同口径）: 本包**不许** import moderngl / wgpu / glfw / pygame /
engine / scene_driver —— 只放纯数据/纯文本装配（FramePlan、std140 打包、GLSL 单源拼装、
post 链参数、TPS 缓冲记账、外观代计数）。
"""
