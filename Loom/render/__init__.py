# -*- coding: utf-8 -*-
"""render/ — 渲染层包（目录重构 B3 批，2026-11-21）。

三个子包（后端差异在结构上隔离，Q-B7-38-1 目录重构总纲）:
  render/contract/  两端共享描述（FramePlan / 场景 UBO / 着色器源码 / post 链 /
                    帧缓冲记账 / 外观代）—— 零后端依赖（不 import moderngl/wgpu/glfw）
  render/gl/        OpenGL 后端（GLEngine 门面 + 各 Mixin + GLFW 窗口）
  render/vk/        Vulkan 后端（SceneDriver 门面 + VkRenderer + 播放器/窗口）

刻意不在此 re-export 任何子模块（与 scene/ 同纪律）: import render 本身必须保持
零 GPU 依赖；需要谁就显式 "from render.gl import engine" 这样导入。
"""
