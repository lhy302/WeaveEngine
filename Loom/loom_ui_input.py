# -*- coding: utf-8 -*-
"""loom_ui_input.py — UI 输入结算的共享前置（GL 播放器 / VK 播放器 唯一实现）

**我负责什么**：把「本帧滚轮是否被 UI 吃掉」这条判据写成**一份**纯函数，供两端共用 ——
  · GL 侧：runtime.PlayerApp._dispatch_ui_mouse（--run / 打包版 opengl 的唯一派发点）
  · VK 侧：vk_ui.UIInputBridge.begin_frame + vk_player.draw 的帧首结算
两端因此**同源**（docs/guides/开发要求_功能解耦与模块化.md 规则 3：两个功能都依赖同一段
前置时，把前置抽成独立库各自 import，而不是各写一套 —— 本模块就是那段前置）。

**我不负责什么**：不做事件泵、不建窗口、不碰 GPU、不改 UI 状态；只**读** UI 树的命中结果。

## 为什么这条判据必须两端同一份（P-09 裁决 2026-11-07；P3-1 复用 2026-11-18）

滚轮只有「**滚轮本身**被 ScrollView 吃掉」时才不给脚本/相机。
单用「本帧鼠标事件**整体**被消费」（UIManager.dispatch_mouse 的返回值）会把同帧点击的
滚轮一起丢掉 —— 用户可感知：同一帧里「点按钮 + 滚轮」时，滚轮应当仍然给脚本
（镜头缩放 / 切武器），两端必须一样。

判据的实现史（不许再分叉）：
  · 2026-11-07 P-09：判据先写在 vk_player._wheel_taken_by_scrollview，
    vk_ui.UIInputBridge.begin_frame 又写了一份同名同体实现（两份 = 规则 3 反模式）。
  · 2026-11-18 P3-1：GL 播放器补滚轮门控时，把判据**搬到本模块**（唯一实现），
    vk_player / vk_ui / runtime 三处 import 同一份；两端行为零变化，只少了两份拷贝。
"""


def wheel_taken_by_scrollview(ui, pos):
    """本帧滚轮是否真被 UI 的 ScrollView 吃掉（滚轮专属判据）。

    与 UIManager.dispatch_mouse 的滚轮分支同一判据：指针命中的最近 ScrollView 存在且
    可滚动。判不了时保守认为已被消费（历史语义：宁可少给一次滚轮，也不把可能被 UI
    吃掉的滚轮再交给相机/脚本）。

    调用时序：必须在 UIManager.dispatch_mouse **之前**取 —— dispatch 会改
    ScrollView.scroll_pos，取晚了就与 dispatch_mouse 的滚轮分支不同源。
    """
    if ui is None:
        return False
    if not hasattr(ui, '_hit_scroll_view'):
        return True
    try:
        sv = ui._hit_scroll_view(pos)
    except Exception:
        return True
    if sv is None:
        return False
    try:
        return bool(sv.can_scroll())
    except Exception:
        return True


def wheel_consumed_by_ui(wheel, dispatch_consumed, wheel_taken):
    """本帧滚轮是否被 UI 吃掉（**P-09 组合规则**，两端唯一一份）。

    参数:
      wheel            本帧滚轮增量（0 = 本帧没有滚轮）
      dispatch_consumed UIManager.dispatch_mouse 的返回值（本帧鼠标事件**整体**是否被消费）
      wheel_taken      wheel_taken_by_scrollview(...) 的结果（**dispatch 之前**取）

    只有三者同时成立才算「滚轮被 UI 吃掉」：本帧真有滚轮 + UI 确实消费了本帧事件 +
    滚轮落在可滚 ScrollView 上。缺任何一条都要把滚轮交给脚本/相机 —— 尤其
    dispatch_consumed=True 但 wheel_taken=False（同帧「点按钮 + 滚轮」）时，
    滚轮**必须**仍然给脚本。
    """
    return bool(wheel) and bool(dispatch_consumed) and bool(wheel_taken)
