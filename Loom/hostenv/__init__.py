# -*- coding: utf-8 -*-
"""hostenv/ — 平台/宿主环境收口。

目录重构 B1 批（Q-B7-38-1 裁决 20 顶层包，2026-11-21）。
原提案包名 platform/ 与 stdlib platform 冲突 → 定名 hostenv/。成员：
  userpaths         用户可写配置目录唯一收口点（用户配置目录契约 §2）
  crash_reporter    崩溃落盘（dbghelp Minidump + 场景自动备份）
  backend_guard     渲染后端兼容性诊断 + 可见失败

公开 API 重导出（显式列出，不用 import *，可静态分析）。
"""
from hostenv.userpaths import (APP_DIR_NAME, user_root, engine_settings,
                               hub_settings, game_settings, project_settings,
                               log_path, backup_path, ensure_dir, ensure_parent,
                               safe_name, sha1_short, game_id_for, project_id)
from hostenv.crash_reporter import register_scene_backup, write_dump, install
from hostenv.backend_guard import (VK_MIN_API_MAJOR, VK_MIN_API_MINOR,
                                   VkBackendInitError, vulkan_api_version,
                                   vulkan_api_text, adapter_info_dict,
                                   vk_diag_text, adapter_api_version,
                                   adapter_backend, require_vulkan_api,
                                   show_blocking_dialog)

__all__ = [
    'APP_DIR_NAME', 'user_root', 'engine_settings', 'hub_settings',
    'game_settings', 'project_settings', 'log_path', 'backup_path',
    'ensure_dir', 'ensure_parent', 'safe_name', 'sha1_short', 'game_id_for',
    'project_id',
    'register_scene_backup', 'write_dump', 'install',
    'VK_MIN_API_MAJOR', 'VK_MIN_API_MINOR', 'VkBackendInitError',
    'vulkan_api_version', 'vulkan_api_text', 'adapter_info_dict',
    'vk_diag_text', 'adapter_api_version', 'adapter_backend',
    'require_vulkan_api', 'show_blocking_dialog',
]
