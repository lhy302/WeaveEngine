# -*- coding: utf-8 -*-
"""editor_launch.py — 编辑器入口「后端决策 + --ui × --backend 执行面」唯一实现。

唯一实现（规则 5.5，两个入口只做薄转调）:
  · editor_backend_choice(argv)  —— Q-B7-60-1 编辑器**后端决策**（显式 --backend >
    配置 render_api > 默认；与播放器同一事实源 run_player）；
  · editor_execution_plan(ui, backend) —— Q-B7-55-1 --ui × --backend **执行面**计划。
2026-11-25 终审 P1-1/P1-2 追加三个（同一份「编辑器渲染后端」语义的读写/策略面）:
  · effective_render_api()                        —— 读**生效值**（面板显示值 = 生效值）；
  · write_render_api_choice(api, invoke=None)     —— **唯一写盘路径**（面板 + VK 失败回退）；
  · should_rewrite_config_on_vk_failure(...)      —— VK 失败是否改写配置的唯一判据。

---- 以下为 Q-B7-55-1 执行面部分的历史留痕 ----

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


def editor_backend_choice(argv):
    """编辑器视口后端决策（纯函数，无副作用）: 显式 --backend > 配置 render_api > 默认。

    Q-B7-60-1（人类 2026-11-23 裁决）: 「编辑器里的后端只取决于文件里的后端是啥」
    + 「一个键全局消费」+「--backend 命令行仍是显式最高优先级」+「重启编辑器生效」。
    修前 Loom.py / build_entry.py 各有一份逐位重复的同名函数，只认**显式
    --backend vulkan**，配置里的 render_api 对编辑器视口完全无效 —— 同一个键在
    编辑器里只是「替播放器设的」，与播放器里「我自己用的」语义不对称。本函数把
    编辑器拉回与播放器**同一条解析链**（一个键全局消费，不是两条链）:

      · 显式 --backend <值>（argv 里有且后面跟了值）:
            vulkan / auto -> vulkan；opengl -> gl
        （--backend 后没跟值 = 视为没给，与 run_player.parse_backend_arg 同口径）
      · 无显式: 读配置 —— 直接转调 run_player.resolve_backend(None)，即播放器
        那条 **--backend > 游戏设置.json > 引擎 设置.json > 默认 vulkan** 的
        解析链（本函数**不自己读 json**，唯一事实源在 run_player）:
            vulkan / auto -> vulkan；opengl -> gl

    **auto 在编辑器侧与播放器同义（2026-11-25 终审 P1-2 修）**:
      两端都是「先试 VK，失败回退 GL，且不改写配置」。
        · 播放器: run_player._run_backend_impl(api='auto') 先 _run_vulkan，VkInitError
          -> 同进程走 GL，且 _handle_vk_init_failure 明确**不写配置**（Q1/Q7=A：
          auto 没有偏好可持久化）。
        · 编辑器: 本函数把 auto 映射成 vulkan（先试 VK）；装配失败由启动期的
          gui/main_window._handle_vk_init_failure 当场回退 GL 视口 + 可见提示，失败
          策略同样**不改写配置**（唯一判据 should_rewrite_config_on_vk_failure）。
      与裁决①「重启编辑器生效、不做视口热切换」不冲突: 启动期一次性选择不是热切换。
      修前把 auto 归成保底 gl 的理由（「编辑器不做回退，所以 auto 只能当 gl」）已随
      启动期回退机制就位而失效 —— 现在两端对同一个 auto 值行为一致。

    返回 vulkan | gl（与 editor_execution_plan 的 backend 口径一致）。
    依赖方向：module 级仍零 import（run_player 在函数内 import，不依赖入口模块）。
    """
    import run_player
    cli = run_player.parse_backend_arg(list(argv or ()))
    # cli=None -> resolve_backend 走配置解析链（与播放器同一事实源，不自己读 json）
    api = run_player.resolve_backend(cli)
    # 2026-11-25 终审 P1-2 修：auto 在编辑器侧与播放器**同义** = 先试 VK，失败回退 GL
    # （不改写配置）。修前这里把 auto 归成保底 gl —— 同一个 auto 在播放器里是「先试 VK」、
    # 在编辑器里却是「直接 GL」，用户看到的两端行为不同义。现在编辑器启动期回退机制
    # （gui/main_window._handle_vk_init_failure + vk_viewport.probe_vk_ready）就位，
    # auto 可以放心映射成 vulkan：VK 装不上就当场回退 GL 视口并给可见提示。
    return 'vulkan' if api in ('vulkan', 'auto') else 'gl'


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


# ======================================================================
# 渲染后端「读生效值 / 写盘 / 失败策略」—— 编辑器侧三个唯一实现（P1-1 / P1-2）
# ======================================================================

def effective_render_api():
    """编辑器与播放器**共同**的生效后端 = run_player.resolve_backend(None)。

    唯一解析链（--backend > 游戏设置.json > 引擎 设置.json > 默认 vulkan）在 run_player，
    本函数只做转调，**不自己读 json**（否则就是第二条链，P1-1 的根因形态）。
    设置面板用它决定下拉框选中项（P1-1 修法: 显示**生效值**，不是引擎层单层值）。

    返回 (api, source): api ∈ {'vulkan','opengl','auto'}；source ∈
    {'cli','game','engine','default'}（来源层，供面板标注「当前生效值来自哪一层」）。
    """
    import run_player
    api = run_player.resolve_backend(None)
    return api, getattr(run_player, '_LAST_SOURCE', 'engine')


def should_rewrite_config_on_vk_failure(explicit, requested_api):
    """VK 装配失败时是否把配置里的 render_api 改写成 opengl —— **唯一判据**。

    人类 2026-11-24 指令「加编辑器启动时 VK 失败 → 自动改写配置为 opengl + 提示」；
    两条既有裁决收窄它的适用范围:
      · explicit=True（argv 里显式给了 --backend 值）-> **不改写**（Q6 先例: 显式选择
        不动用户配置，只本次降级 + 可见提示）；
      · requested_api == 'auto' -> **不改写**（Q1/Q7=A: auto 本身就是「先试 VK 再 GL」，
        没有偏好可持久化；播放器侧同一裁决，见 run_player._handle_vk_init_failure）；
      · 其余（配置/默认来的 vulkan）-> 改写为 opengl。
    requested_api 为 None（读配置失败）= 按默认 vulkan 处理（默认就是 vulkan，能走到
    VK 装配说明请求来自默认/配置）。
    """
    if explicit:
        return False
    a = str(requested_api or 'vulkan').strip().lower()
    return a == 'vulkan'


def write_render_api_choice(api, invoke=None):
    """编辑器侧渲染后端**唯一写盘路径**（设置面板 / VK 装配失败自动回退 共用）。

    为什么必须只有一条（P1-1 终审实测）: 修前设置面板写**引擎层** 设置.json、脚本 API
    （render/gl/engine.py::set_render_api / render/vk/driver.py::set_render_api）写**游戏层**
    游戏设置.json，而解析链优先级是 游戏层 > 引擎层 —— 于是面板显示引擎层的值、真正生效的
    却是游戏层的值（「面板显示 X、生效 Y」）；播放器 VK 失败回退把游戏层写成 opengl 之后，
    面板永久显示 vulkan 且改回无效。

    两层由**一条**函数收口（不许另起第三处写盘）:
      ① 引擎层 设置.json 的 render_api = api —— 走 settings_set 命令壳（Q-B7-56-2 裁定①:
         面板写盘翻译成命令；GUI 侧把 _invoke_cmd 作为 invoke 传进来 = 与面板同一入口，
         缺省 invoke=None 时直调同一命令体 agent_commands.cmd_settings_set(None, ...)）；
      ② 清掉**更高优先级**的游戏层覆盖键（游戏设置.json 的 render_api）—— 否则用户改了
         面板、解析链仍被游戏层压住 = 改了无效。只删这一个键，其它键与其它层一字不动
         （引擎层仍是「编辑器/开发环境的默认」，打包游戏/播放器照旧读它 = 一个键全局消费）；
      ③ 复核: 解析链下次启动（resolve_backend(None)）必须真的读到 api，否则 ok=False 如实
         报错（契约 §7 禁止假成功）。

    返回 dict(ok, saved, effective, source, cleared_game_layer, error)。
    """
    a = str(api or '').strip().lower()
    if a not in ('vulkan', 'opengl', 'auto'):
        return {'ok': False, 'saved': None, 'effective': None, 'source': None,
                'cleared_game_layer': False,
                'error': 'render_api 必须是 vulkan / opengl / auto'}
    err = None
    try:
        if invoke is not None:
            res = invoke('settings_set', {'key': 'render_api', 'value': a})
        else:
            import agent_commands as ac
            res = ac.cmd_settings_set(None, {'key': 'render_api', 'value': a})
    except Exception as e:
        res, err = None, repr(e)
    if err is None and isinstance(res, dict) and res.get('error'):
        err = str(res.get('error'))
    cleared = False
    if err is None:
        try:
            import run_player
            ok_c, err_c = run_player.clear_game_layer_render_api()
            cleared = bool(ok_c)
            if not ok_c:
                err = err_c or '清游戏层覆盖键失败'
        except Exception as e:
            err = repr(e)
    effective, source = None, None
    try:
        effective, source = effective_render_api()
    except Exception as e:
        if err is None:
            err = repr(e)
    ok = (err is None) and (effective == a)
    if (not ok) and err is None:
        err = '写盘后复核失败: 解析链生效值仍为 %r' % (effective,)
    return {'ok': ok, 'saved': a, 'effective': effective, 'source': source,
            'cleared_game_layer': cleared, 'error': err}
