# -*- coding: utf-8 -*-
"""core/ — 引擎内核（后端无关）。

目录重构 B1 批（Q-B7-38-1 裁决 20 顶层包，2026-11-21）。成员：
  engine_core        EngineCore —— 后端无关引擎内核（JVM 模型门面）
  clock              FixedStepClock —— 逻辑帧/渲染帧分离时钟
  interp             InterpState —— prev/curr 快照 + alpha 插值
  events             EventBus —— 全局事件总线
  profiler           ProfilerMixin —— 性能插桩
  primitives         Point3D —— 基础数据类型（原 loom_types.py，
                     改名 primitives 避免与 stdlib types 撞名）
  color              hex→rgba 转换 + 缓存
  debug              崩溃可见性（LOOM_FAULTHANDLER faulthandler 开关）
  log                启动日志开关（LOOM_QUIET）
  single_instance    编辑器单实例锁

注意：本 __init__ **刻意不** re-export EngineCore（engine_core.py）——
engine_core 拉起整张引擎图（loom_camera/loom_input/...），若在包初始化期
急切导入，任何叶子模块「先 import core.primitives 再被 engine_core 反向
import」都会撞部分初始化环（2026-11-21 实测 ImportError）。
内核入口恒为：from core.engine_core import EngineCore。
其余成员的公开 API 在此重导出（显式列出，不用 import *，可静态分析）。
InterpState（core.interp）依赖 numpy，同样不进 __init__ ——
契约模块（loom_scene_contract 等「零 GPU/零 numpy」门）经
loom_scene_entities → core.primitives 触发本包初始化时不得被拖入
numpy（test_scene_contract A3 / test_plugin_unload_modules 实测钉住）。
取用：from core.interp import InterpState。
"""
from core.clock import FixedStepClock, clock_from_settings, split_enabled
from core.events import EventHandler, EventBus, default_bus
from core.profiler import ProfilerMixin
from core.primitives import Point3D
from core.debug import enable_if_requested
from core.log import is_quiet, verbose, verbose_enabled
from core.single_instance import ensure_editor_single_instance

__all__ = [
    'FixedStepClock', 'clock_from_settings', 'split_enabled',
    'EventHandler', 'EventBus', 'default_bus',
    'ProfilerMixin',
    'Point3D',
    'enable_if_requested',
    'is_quiet', 'verbose', 'verbose_enabled',
    'ensure_editor_single_instance',
]
