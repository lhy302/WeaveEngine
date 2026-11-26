# -*- coding: utf-8 -*-
"""ui/canvas/ — Canvas/UI 系统包 (Q-B7-38-1 第 7 批, 2026-11-26)

原位单文件 Loom/loom_ui.py (1728 行 / 15 类) 按域 + 按层拆进本包 (一个功能一个文件):
  element.py         UIElement 基类 (树 / 布局 / 命中)
  canvas.py          Canvas 单画布 (screen / world)
  manager.py         UIManager 多画布容器 + 脚本事件派发子域 + 键码表
  widgets_basic.py   Shape / Panel / Text / Image
  widgets_input.py   Button / Slider / Toggle / InputField / Dropdown
  widgets_layout.py  ScrollView / ProgressBar / GridLayout

对外完全兼容: `import loom_ui` / `from loom_ui import X` 由 Loom/loom_ui.py 薄 shim 转发,
loom_ui is ui.canvas (同一个模块对象, 15 个 class 与拆分前逐字一致, 调用点零改动)。
"""
import math  # noqa: F401  (保持拆分前 loom_ui.math 可见的模块面)

from .element import UIElement
from .canvas import Canvas
from .manager import (UIManager, _fire_binding, _warn_script_host_once,
                      _find_script_instances, _init_key_name_map)
from .widgets_basic import Shape, Panel, Text, Image
from .widgets_input import Button, Slider, Toggle, InputField, Dropdown
from .widgets_layout import ScrollView, ProgressBar, GridLayout

import sys as _sys
import types as _types

# ---- 模块级可变状态转发 (保持拆分前「模块属性赋值即生效」的语义) ----
#
# 拆分前 loom_ui 是单模块, 测试/工具会写 loom_ui._SCRIPT_HOST_WARNED = False 这类
# 模块级可变标志 (tests/test_beta3_batch2_camera_proj.py:404), 且随后要读回内部函数
# 改写后的值; 包化后这些名字的真身在各子模块里, 若只在包命名空间存一份值, 读到的就是
# 陈旧副本。这里照 eai/__init__.py 的 _EaiPackage 先例把读/写转发到真正定义它的子模块
# (写: 只写真身; 读: 未在包命名空间命中时经 __getattr__ 拿真身的活值)。
_PATCH_HOME = {
    '_ACTIVE_ENGINE': _sys.modules[__name__ + '.manager'],
    '_SCRIPT_HOST_WARNED': _sys.modules[__name__ + '.manager'],
    '_KEY_CODE_TO_NAME': _sys.modules[__name__ + '.manager'],
    '_SHAPE_FILL_ERR_REPORTED': _sys.modules[__name__ + '.widgets_basic'],
    '_SHAPE_STROKE_ERR_REPORTED': _sys.modules[__name__ + '.widgets_basic'],
}


class _CanvasPackage(_types.ModuleType):
    """包模块本体: 读/写模块级可变状态时转发到定义该名字的子模块。"""

    def __getattr__(self, name):
        home = _PATCH_HOME.get(name)
        if home is not None:
            return getattr(home, name)
        raise AttributeError('module %r has no attribute %r' % (__name__, name))

    def __setattr__(self, name, value):
        home = _PATCH_HOME.get(name)
        if home is not None:
            setattr(home, name, value)
            return
        _types.ModuleType.__setattr__(self, name, value)


_sys.modules[__name__].__class__ = _CanvasPackage
