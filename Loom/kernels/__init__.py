# -*- coding: utf-8 -*-
"""kernels/ — C 内核封装（ckernels DLL / 可选加速层）。

目录重构 B1 批（Q-B7-38-1 裁决 20 顶层包，2026-11-21）。成员：
  fastpath         组3 公共静态化模块（C > numba > numpy 三级分派 + 逃生门）
  pipeline_glue    基座 ↔ pipeline.dll 接线层
  parallel         CPU 拓扑 / 亲和性 / 脚本专用线程
  layer_tag        层与标签配置（Layer/Tag 系统）

公开 API 重导出（显式列出，不用 import *，可静态分析）。
"""
from kernels.fastpath import (ckernels_search_dirs, ckernels_candidates,
                              aabbs_minmax, aabbs_minmax_par, collide_extract,
                              collide_extract_local, bucket_pack_available,
                              bucket_pack)
from kernels.pipeline_glue import (LOCK, LoomLight, light_vps, scene_bounds,
                                   aabbs, world_matrices, interp_pose,
                                   interp_world, pack_bucket_instances,
                                   dirty_mask, local_matrices, depths,
                                   ancestry_dfs, shutdown, status)
from kernels.parallel import (detect_topology, mask_of, compute_policy,
                              apply_process_policy, pin_current_thread,
                              current_process_mask, get_parallel, ScriptRunner,
                              FramePool, frame_workers, measure_core_busy,
                              MainThreadCoreScheduler)
from kernels.layer_tag import (MAX_TAGS, MAX_TAG_LEN, MAX_LAYER_NAME_LEN,
                               LAYER_COUNT, DEFAULT_LAYERS, DEFAULT_TAGS,
                               config_path, validate_tag, save, reload,
                               get_layers, get_tags, tag_exists, register_tag,
                               layer_name, layer_id, load)

__all__ = [
    'ckernels_search_dirs', 'ckernels_candidates', 'aabbs_minmax',
    'aabbs_minmax_par', 'collide_extract', 'collide_extract_local',
    'bucket_pack_available', 'bucket_pack',
    'LOCK', 'LoomLight', 'light_vps', 'scene_bounds', 'aabbs',
    'world_matrices', 'interp_pose', 'interp_world', 'pack_bucket_instances',
    'dirty_mask', 'local_matrices', 'depths', 'ancestry_dfs', 'shutdown',
    'status',
    'detect_topology', 'mask_of', 'compute_policy', 'apply_process_policy',
    'pin_current_thread', 'current_process_mask', 'get_parallel',
    'ScriptRunner', 'FramePool', 'frame_workers', 'measure_core_busy',
    'MainThreadCoreScheduler',
    'MAX_TAGS', 'MAX_TAG_LEN', 'MAX_LAYER_NAME_LEN', 'LAYER_COUNT',
    'DEFAULT_LAYERS', 'DEFAULT_TAGS', 'config_path', 'validate_tag', 'save',
    'reload', 'get_layers', 'get_tags', 'tag_exists', 'register_tag',
    'layer_name', 'layer_id', 'load',
]
