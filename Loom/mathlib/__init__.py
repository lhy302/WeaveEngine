# -*- coding: utf-8 -*-
"""mathlib/ — 纯数学（零引擎依赖）。

目录重构 B1 批（Q-B7-38-1 裁决 20 顶层包，2026-11-21）。成员：
  matlib          4×4 矩阵数学库（行主序，行向量约定）
  mesh            顶点/索引缓冲 Mesh + cube/sphere/plane/obj 生成器
  line_geometry   「粗线 = 四边形」唯一实现（Q-B7-48-1 裁决 B）
  mathutil        纯数学小工具（wrap_deg，Q-B7-38-1 P1 前置自 loom_scene_entities）

公开 API 重导出（显式列出，不用 import *，可静态分析）。
line_geometry（mathlib.line_geometry）依赖 numpy，不进 __init__ ——
契约模块（loom_scene_contract「零 GPU/零 numpy」门）经
loom_scene_entities → mathlib.mathutil 触发本包初始化时不得被拖入
numpy（test_scene_contract A3 钉住）。
取用：from mathlib.line_geometry import build_line_quads。
"""
from mathlib.matlib import (mat4_identity, mat4_translation, mat4_scale,
                            mat4_rotation, decompose_euler, mat4_perspective,
                            mat4_look_at, mat4_view_yaw_pitch,
                            view_basis_to_angles, mat4_ortho,
                            mat4_view_forward, mat_validate)
from mathlib.mesh import (Mesh, create_cube, create_sphere, create_plane,
                          spec_to_mesh, mesh_validate, load_obj)
from mathlib.mathutil import wrap_deg

__all__ = [
    'mat4_identity', 'mat4_translation', 'mat4_scale', 'mat4_rotation',
    'decompose_euler', 'mat4_perspective', 'mat4_look_at',
    'mat4_view_yaw_pitch', 'view_basis_to_angles', 'mat4_ortho',
    'mat4_view_forward', 'mat_validate',
    'Mesh', 'create_cube', 'create_sphere', 'create_plane', 'spec_to_mesh',
    'mesh_validate', 'load_obj',
    'wrap_deg',
]
