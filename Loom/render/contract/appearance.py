# -*- coding: utf-8 -*-
"""loom_appearance.py — 外观代计数器（组6件1），不依赖 engine。

为什么单独成模块（2026-11-13 构建器瘦身）:
  材质/贴图的"内容变了"必须让引擎下一帧重新上传实例数据，原实现是
  `from engine import GameObject; GameObject._appearance_gen += 1`。这条**函数内**
  import 会把 engine.py（模块级 import pygame/moderngl）整张依赖图拖进
  build_game 的静态 import 图 —— Nuitka 连函数体内的 import 也会跟随（2026-11-13
  实测：`def f(): import pygame` 从未被调用，pygame 仍进 dist）。构建器因此白背
  pygame 9MB + 整个渲染引擎。

  代计数器本身只是单调整数，和渲染无关，下沉到这里后：
    · 写方: GameObject.mesh/visible setter、Material._bump_appearance、
            Texture.bump_appearance  → loom_appearance.bump()
    · 读方: engine / loom_render / loom_lighting 的 stamp 比较 → loom_appearance.gen()
  语义与原 `GameObject._appearance_gen` 完全一致（同一份单调计数器，进程内首次
  import 时为 0，只增不减；stamp 比较只关心"是否变化"，不关心具体数值）。
"""

_gen = 0


def gen():
    """当前外观代计数（单调递增）。"""
    return _gen


def bump(n=1):
    """外观内容变化 -> 代数 +n（默认 1）。多 bump 无害（只多一次实例上传）。"""
    global _gen
    _gen += int(n)


def set_value(value):
    """绝对赋值 —— 仅供 GameObject 的类属性兼容视图使用（`+=` 的 setter 路径）。"""
    global _gen
    _gen = int(value)
