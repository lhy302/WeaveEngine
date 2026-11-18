# -*- coding: utf-8 -*-
r"""loom_ui_resize.py — 「窗口尺寸 -> UI 画布尺寸」同步语义的共享前置（VK 侧唯一实现）

**我负责什么**：把「窗口尺寸变化时，screen Canvas 跟着变」这一件事写成一份纯函数，
供 VK 播放器（`vk_player.draw` 帧首结算）调用；口径与 GL 的
`loom_glfw_window.GlfwWindowMixin._on_resize`（loom_glfw_window.py:251-263）**逐条一致**：

  · 尺寸下限 320x240 + int 截断（GL: `max(320, int(w))` / `max(240, int(h))`）；
  · 只同步 **screen** Canvas，world Canvas 不受窗口尺寸影响（语义在 `UIManager.resize`）；
  · `ui.resize` 抛异常时**不阻断本帧**（GL 也是 `except Exception: pass`）—— 这里保持
    同样的静默，因为多打一行日志本身就是「VK 比 GL 多一条输出」的新差异。

**我不负责什么**：不建窗口、不读 GLFW 回调、不碰 UI 布局算法（anchor/pivot 公式在
`loom_ui.Canvas.resize` / `UIElement.screen_rect` 里，本模块只负责「喂对尺寸」）、
不画东西、不碰相机。

## 为什么必须补（Q-B7-41-1，人类裁决 2026-11-18：「判为缺陷，VK 补 ui.resize」）

GL 在窗口尺寸回调 `_on_resize` 里把窗口尺寸同步给 `ui.resize` 调用点；VK 原先**没有任何**
`ui.resize` 调用点 —— 窗口 resize 后 VK 的 UI 画布仍是构造时的 1280x800，于是
anchor/pivot 布局结果与「画布外」判定跟 GL 分叉（同一份脚本：GL 的按钮贴在窗口右下角，
VK 的还在老位置甚至跑到可见区外）。

## 为什么 GL 没有 import 本模块（留痕，不许当成「又分叉了」）

GL 是本次对拍的**基准**，人类纪律「GL 一行不许动」—— 所以 GL 的 `_on_resize` 保持原样，
本模块只承载 **VK 侧**的同一套口径。防分叉靠**门**而不是靠 import：
`tests/test_ui_hit_parity.py` ⑦ 组把两端窗口 640x400 -> 800x500（再 -> 200x100 触发
320x240 下限钳制）后，逐项比对「UI 画布尺寸 / anchor 布局结果 / 画布外判定」——
任何一端改口径（含 GL 改钳制值）都会当场红。
"""

# 与 GL `_on_resize` 同一对下限（loom_glfw_window.py:252-253，不要各写一份）
UI_MIN_W = 320
UI_MIN_H = 240


def ui_size_for_window(w, h):
    """窗口尺寸 -> UI 画布尺寸（GL _on_resize 同一口径：int 截断 + 下限 320x240）。

    >>> ui_size_for_window(800, 500)
    (800, 500)
    >>> ui_size_for_window(200, 100)
    (320, 240)
    """
    return max(UI_MIN_W, int(w)), max(UI_MIN_H, int(h))


def window_size(win=None, fallback=None):
    """当前窗口尺寸 (w, h)；判不了返回 None。

    与 GL **同源**：GL 的 _on_resize(w, h) 收到的是 GLFW 的**窗口尺寸**（逻辑像素），
    不是 framebuffer 的物理像素。所以这里优先 glfw.get_window_size(win)；拿不到窗口
    句柄时才退回调用方给的 fallback（VK 播放器传 ctx.physical_size）。

    留痕（未核）：非 100% DPI 缩放下 framebuffer 物理像素 != 窗口逻辑像素，此时 fallback
    分支的数值与 GL 不同；本机（100%）两端同值，高 DPI 场景未实测 —— 见交付报告。
    """
    if win is not None:
        try:
            import glfw
            w, h = glfw.get_window_size(win)
            if w and h:
                return int(w), int(h)
        except Exception:
            pass
    if fallback is not None:
        try:
            return int(fallback[0]), int(fallback[1])
        except Exception:
            return None
    return None


def sync_ui_canvas(ui, win=None, fallback_size=None):
    """把 screen Canvas 同步到当前窗口尺寸（GL _on_resize 的同一语义）。

    参数:
      ui            loom_ui.UIManager（None -> 什么都不做，返回 None）
      win           宿主 GLFW 窗口句柄（GL 同源尺寸来源；None 时用 fallback_size）
      fallback_size (w, h) 兜底尺寸（VK 播放器传 ctx.physical_size）

    返回实际应用的 (w, h)；判不了尺寸 / 没有 UI 时返回 None。

    幂等：Canvas.resize 只改根矩形，布局在命中/绘制时按根矩形现算，所以每帧调用
    与 GL「只在窗口尺寸事件里调用」的可观察结果相同（门里逐帧调用即证明这一点）。
    """
    if ui is None:
        return None
    wh = window_size(win, fallback_size)
    if wh is None:
        return None
    w, h = ui_size_for_window(*wh)
    try:
        ui.resize(w, h)
    except Exception:
        # 与 GL 一致：resize 失败不阻断本帧（GL 的 _on_resize 也是 pass，不打印）
        return None
    return (w, h)
