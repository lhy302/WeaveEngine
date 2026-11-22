# -*- coding: utf-8 -*-
"""editor_launch.py — 编辑器入口 --ui × --backend 执行面唯一决策（Q-B7-55-1）。

问题（B7-55 考古，HEAD e2709e8）:
  Loom.py 自 2026-10-18 起把 --ui 解析后**忽略**（注释原话「--ui 已无实际
  效果…编辑器只剩 Qt」）；build_entry.py 仍按 --ui 分支（qt → run_loom_gui；
  default/minimal → EditorApp / VkEditorApp）。同一份 env + argv 在两个入口的
  执行面不同，实测:
    · --ui minimal --backend gl     : Loom.py 起 Qt 窗口 / build_entry 起裸 GL
                                       EditorApp（GLFW 窗口 + MinimalEditorView）
    · --ui minimal --backend vulkan : Loom.py 起 Qt VK 视口（EXIT 0）/
                                      build_entry 可见报错 EXIT 1
  = 四入口「零用户可感知差异」的最后一个执行面分叉。

统一策略（Q-B7-55-1 选择 a —— 保住 --ui 与 guiloader 自定义 GUI 功能）:
  · --ui qt                      -> LoomGUI（Qt 主窗口；视口由 backend 决定
                                    GLViewport / VkViewport）；
  · --ui default/minimal（非 Qt） + gl     -> EditorApp + 注入视图
                                    （MinimalEditorView / guiloader 自定义 GUI）；
  · --ui default/minimal（非 Qt） + vulkan -> **两入口同一条可见报错 + exit 1**：
        VkEditorApp 需要 Qt 宿主注入 wgpu device / present_format（VkViewport），
        非 Qt 视图的叠加层路径直接摸 ctl.ctx.scope（GL 固定功能状态），VK 不支持。
        不静默降级 GL —— 人类口径「失败必须可见」。

  若人类另有裁定（例如改为「两入口都忽略 --ui 恒 Qt」= 方案 b），只需改本函数
  与两个入口的 _editor_execution_plan 转调处；视图装配分支无需再动。

依赖方向：本模块 module 级零 import（纯字符串/纯函数），不依赖引擎与入口。
"""
QT_VIEW = 'qt'
NON_QT_VIEWS = ('default', 'minimal')

# 非 Qt 视图 + vulkan 的统一可见报错（两端打印同一行；%s = 归一后的 --ui 值）。
EDITOR_VK_NON_QT_ERROR = (
    '[错误] --ui %s 是非 Qt 视图，不支持 --backend vulkan：VkEditorApp 需要 Qt 宿主'
    '注入 wgpu device 与 present_format（VkViewport）；非 Qt 视图的叠加层路径直接使用'
    ' ctl.ctx.scope（GL 固定功能状态），VK 不支持。请改用 --ui qt --backend vulkan，'
    '或不带 --backend vulkan。')


def editor_execution_plan(ui, backend, qt_host=False):
    """--ui × --backend -> 编辑器执行面计划（纯函数，无副作用）。

    返回 dict:
      view      : 归一后的视图名（'qt' | 'default' | 'minimal' | 传入值原文小写）
      backend   : 'gl' | 'vulkan'（非 vulkan 一律 gl，与 _editor_backend_choice 同口径）
      engine    : 'LoomGUI' | 'EditorApp' | 'VkEditorApp' | None
      error     : None | 可见报错文案（入口打印后按 exit_code 退出）
      exit_code : 0 | 1

    qt_host=True 仅用于「已注入 Qt 宿主（wgpu device + present_format）」的
    装配场景（当前两个命令行入口都没有这种宿主；保留给宿主装配点，
    也保证 old gate test_entry_backend_parity C2 的 VkEditorApp 装配点可达）。
    """
    view = QT_VIEW if ui in (None, '') else str(ui).strip().lower()
    api = 'vulkan' if str(backend or '').strip().lower() == 'vulkan' else 'gl'
    if view == QT_VIEW:
        return {'view': view, 'backend': api, 'engine': 'LoomGUI',
                'error': None, 'exit_code': 0}
    if api == 'vulkan':
        if qt_host:
            return {'view': view, 'backend': api, 'engine': 'VkEditorApp',
                    'error': None, 'exit_code': 0}
        return {'view': view, 'backend': api, 'engine': None,
                'error': EDITOR_VK_NON_QT_ERROR % view, 'exit_code': 1}
    return {'view': view, 'backend': api, 'engine': 'EditorApp',
            'error': None, 'exit_code': 0}
