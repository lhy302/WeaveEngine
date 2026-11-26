# -*- coding: utf-8 -*-
"""_editor_vk_fallback_child.py — 父门 tests/test_editor_vk_fallback_panel.py 的真窗口子探针。

任务（Q-B7-60-1 终审 P0-1 + 人类 2026-11-24 指令「加编辑器启动时 VK 失败 → 自动改写
配置为 opengl + 提示」）:

  A 组（mode=a，backend 来自配置）：模拟 VK 装配失败 → 真建 LoomGUI →
    ① 设置面板仍能创建对话框（P0-1 另一半：面板可达）；
    ② 引擎层 render_api 已被改写为 opengl（且走唯一写盘路径 write_render_api_choice）；
    ③ self.viewport 是 GLViewport（本次回退成功，且真建出 GL 编辑器 = 真可用）；
    ④ 可见提示被发出（show_blocking_dialog 被调用 + 文案含原因/已改写/已回退）。
  B 组（mode=b，显式 --backend vulkan）：配置不变（仍 vulkan），但仍有提示 + 回退 GL。
  C 组（mode=c，配置 auto，P1-2 两端同义）：先试 VK 失败 -> 回退 GL，但配置**不变**
    （仍 auto；与播放器 run_player 对 auto 的 Q1/Q7=A 裁决同义），提示里说明「未改写」。

VK 不可用的模拟方式（**不打桩被测代码**）: 把 hostenv.backend_guard.vulkan_api_version
改成返回 (1, 0, 0) —— 即「显卡驱动只支持 Vulkan 1.0，低于 wgpu-native 的 1.1 地板」，
生产判据 require_vulkan_api 会**真的**抛 VkBackendInitError（本机适配器探测能过、
地板判据必然红 = 与「VK 不可用机器」等价）。

隔离: LOOM_USER_ROOT 指向临时目录（引擎层 设置.json 与游戏层 游戏设置.json 都落那里，
不污染 %LOCALAPPDATA% 也不在仓库里留文件）；LOOM_NO_DIALOG=1。

为什么是子进程: 真窗口 + GL 上下文在进程收尾会非确定性卡在驱动 teardown（进程变僵尸
数分钟，本机实测），父门只认 verdict 文件 —— 与 test_vk_editor_smoke /
test_grid_occlusion_parity 同一条隔离纪律。
"""
import json
import os
import sys
import tempfile
import time

MODE = (sys.argv[1] if len(sys.argv) > 1 else 'a').strip().lower()
_VERDICT_PATH = (sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'editor_vk_fallback_verdict.json'))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 子进程住在 tests/，引擎根 = Loom/
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_DIALOG', '1')
os.environ['LOOM_USER_ROOT'] = tempfile.mkdtemp(prefix='loom_vkfallback_')   # 强制覆盖：绝不写共享 root（2026-11-26 污染修复）
os.environ.setdefault('LOOM_NO_PARALLEL', '1')
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

_fails = []
_pass_n = 0


def check(name, cond, detail=''):
    global _pass_n
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


def _write_verdict():
    data = {'ok': not _fails, 'fails': list(_fails), 'pass_count': _pass_n,
            'mode': MODE}
    try:
        with open(_VERDICT_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print('FAIL verdict 落盘失败: %r' % (e,))


def main():
    import guiloader
    import run_player
    import hostenv.backend_guard as bg
    import hostenv.editor_launch as el

    # 起点配置：a/b = vulkan（配置来的 / 显式 --backend），c = auto（P1-2 两端同义）。
    _START_API = 'auto' if MODE == 'c' else 'vulkan'
    print('=== mode=%s 起点: 引擎层 render_api=%s（%s） ==='
          % (MODE, _START_API,
             {'a': '来自配置文件', 'b': '显式 --backend vulkan',
              'c': '配置 auto: 先试 VK 失败回退 GL'}[MODE]))
    guiloader.save_settings('loom', dict(guiloader.load_settings('loom'),
                                        render_api=_START_API))
    print('[child] 起点配置 render_api=%r' % (guiloader.load_settings('loom').get('render_api'),))

    # ---- 模拟 VK 装配失败：驱动只到 Vulkan 1.0（低于 wgpu-native 1.1 地板）----
    bg.vulkan_api_version = lambda: (1, 0, 0)

    # ---- 截获可见提示（LOOM_NO_DIALOG=1 语义下生产实现只打印，这里同时记账）----
    dialogs = []

    def _spy_dialog(title, text):
        dialogs.append((title, text))
        return False                 # 与 LOOM_NO_DIALOG=1 时 show_blocking_dialog 同语义
    bg.show_blocking_dialog = _spy_dialog

    # ---- 截获「唯一写盘路径」调用（断言回退与设置面板是同一份实现）----
    writes = []
    _real_write = getattr(el, 'write_render_api_choice', None)
    if callable(_real_write):
        def _spy_write(api, invoke=None):
            writes.append(str(api))
            return _real_write(api, invoke=invoke)
        el.write_render_api_choice = _spy_write

    from PySide6.QtWidgets import QApplication
    from gui.main_window import LoomGUI
    from gui.gl_viewport import GLViewport
    try:
        from editor.viewport.vk_viewport import VkViewport
    except Exception as e:
        VkViewport = None
        print('[child] VkViewport 不可导入 (%r)' % (e,))

    app = QApplication.instance() or QApplication(['editor-vk-fallback-%s' % MODE])
    explicit = (MODE == 'b')
    # 修前态兼容：LoomGUI 还没有 explicit 参数时按 explicit=False 装配，好让本组四条
    # 断言仍能跑出**真红**（面板 0 次 / 配置未改写 / viewport 仍是 VkViewport），
    # 而不是在构造处 TypeError 直接崩（那样拿不到逐条证据）。
    try:
        win = LoomGUI(scene_path=None, width=900, height=640,
                      backend='vulkan', explicit=explicit)
        explicit_ok = True
    except TypeError:
        win = LoomGUI(scene_path=None, width=900, height=640, backend='vulkan')
        explicit_ok = False
        print('[child] LoomGUI 尚无 explicit 参数（修前态）-> 按 explicit=False 装配')
    check('A0 LoomGUI 接受 explicit 参数（本次 backend 是否来自显式 --backend 可知）',
          explicit_ok, 'explicit=%r' % (explicit,))

    # ---- ③ 本次回退：viewport 必须是 GLViewport（不是 VkViewport）----
    check('A1 本次回退：self.viewport 是 GLViewport（不是 VkViewport）',
          isinstance(win.viewport, GLViewport)
          and not (VkViewport is not None and isinstance(win.viewport, VkViewport)),
          type(win.viewport).__name__)

    cfg = guiloader.load_settings('loom').get('render_api')
    try:
        eff = run_player.resolve_backend(None)
        eff_err = None
    except Exception as e:
        eff, eff_err = None, repr(e)
    if MODE == 'a':
        # ---- ② 配置已自动改写为 opengl（走唯一写盘路径）----
        check('A2 引擎层 render_api 已自动改写为 opengl（配置来的 vulkan）',
              cfg == 'opengl', 'render_api=%r' % (cfg,))
        check('A3 重启后生效值（resolve_backend(None)）= opengl',
              eff == 'opengl', 'eff=%r err=%s' % (eff, eff_err))
        check('A4 改写走的是唯一写盘路径（editor_launch.write_render_api_choice）',
              writes == ['opengl'], 'writes=%r（面板/回退同一份实现）' % (writes,))
    elif MODE == 'b':
        check('B2 显式 --backend vulkan：配置不变（仍 vulkan，Q6 先例）',
              cfg == 'vulkan', 'render_api=%r' % (cfg,))
        check('B3 显式不改写 -> 生效值仍 vulkan',
              eff == 'vulkan', 'eff=%r err=%s' % (eff, eff_err))
        check('B4 显式不改写：未调用写盘路径', writes == [], 'writes=%r' % (writes,))
    else:
        # P1-2（auto 两端同义）: 先试 VK 失败 -> 回退 GL 但**不改写配置**
        # （与播放器 run_player._handle_vk_init_failure 对 auto 的 Q1/Q7=A 裁决同义）
        check('C2 配置 auto：失败后配置不变（仍 auto，与播放器同义）',
              cfg == 'auto', 'render_api=%r' % (cfg,))
        check('C3 配置 auto：生效值仍 auto（下次启动继续先试 VK）',
              eff == 'auto', 'eff=%r err=%s' % (eff, eff_err))
        check('C4 配置 auto：未调用写盘路径（auto 没有偏好可持久化）',
              writes == [], 'writes=%r' % (writes,))

    # ---- ④ 可见提示 ----
    check('A5 发出可见提示（show_blocking_dialog 被调用恰 1 次）',
          len(dialogs) == 1, 'n=%d' % len(dialogs))
    text = dialogs[0][1] if dialogs else ''
    title = dialogs[0][0] if dialogs else ''
    check('A6 提示含 VK 初始化失败原因摘要',
          ('[VK]' in text) and ('Vulkan' in text) and ('失败原因' in text),
          'title=%r text=%r' % (title, text[:160]))
    check('A7 提示含「本次已回退到 OpenGL 视口可继续使用」',
          '回退到 OpenGL' in text and '继续使用' in text, text[:200])
    if MODE == 'a':
        check('A8 提示含「已把配置改为 opengl」',
              '已把配置' in text and 'opengl' in text, text[:200])
    elif MODE == 'b':
        check('B5 提示含「未改写配置」（显式选择被尊重）',
              '未改写' in text and '显式' in text, text[:200])
    else:
        check('C5 提示含「auto 未改写配置」（与播放器同义，用户看得见）',
              '未改写' in text and 'auto' in text, text[:200])
    printed = text.strip()
    check('A8b 提示文案同时打印到 stdout（Loom.exe 无控制台时靠弹窗，控制台靠这行）',
          bool(printed), 'len=%d' % len(printed))

    # ---- ① 设置面板仍可达（P0-1 另一半）----
    import gui.main_window as mw
    # Q-B7-38-1 第 8 批（2026-11-26）：设置面板段已按面板域纯搬迁到
    # gui/panels/settings_mixin.py（LoomGUI mixin 装配）。对话框类名在该模块内自带
    # import 绑定，故 QDialog 打桩需**同时**打到实际解析模块；断言判据
    # 一字不动（仍要求「创建 1 次 + exec 1 次」）。
    import gui.panels.settings_mixin as _set_mixin

    class _RecDialog(mw.QDialog):
        made = []
        exec_calls = [0]

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            _RecDialog.made.append(self)

        def exec(self):
            _RecDialog.exec_calls[0] += 1
            return 0

    _orig_dialog = mw.QDialog
    _orig_dialog_set = _set_mixin.QDialog
    mw.QDialog = _RecDialog
    _set_mixin.QDialog = _RecDialog      # 设置面板本尊所在模块（见上方路径跟随说明）
    try:
        win._cmd_settings()
        dlg_err = None
    except Exception as e:
        dlg_err = repr(e)
    finally:
        mw.QDialog = _orig_dialog
        _set_mixin.QDialog = _orig_dialog_set
    check('A9 视口装配失败（editor is None）时设置面板仍能创建对话框',
          len(_RecDialog.made) == 1 and _RecDialog.exec_calls[0] == 1,
          'made=%d exec=%d err=%s editor=%r'
          % (len(_RecDialog.made), _RecDialog.exec_calls[0], dlg_err, win.editor))
    combo = getattr(win, '_render_api_combo', None)
    # 选中项 = **生效值**：A 组（配置被改写）是 opengl；B 组（显式不改写）仍是 vulkan。
    _exp_combo = {'a': 'opengl', 'b': 'vulkan', 'c': 'auto'}[MODE]
    check('A10 面板渲染后端下拉无条件渲染，选中项 = 生效值（%s）' % _exp_combo,
          combo is not None and str(combo.currentData()) == _exp_combo,
          'currentData=%r' % (None if combo is None else combo.currentData(),))

    # A10b: editor 为 None 时**真的能改后端**（逃生门可用，不只是「渲染出来」）
    _target = 'vulkan' if str(None if combo is None else combo.currentData()) == 'opengl' \
        else 'opengl'
    try:
        _idx = -1
        for _i in range(combo.count() if combo is not None else 0):
            if str(combo.itemData(_i)) == _target:
                _idx = _i
        combo.setCurrentIndex(_idx)      # 触发 currentIndexChanged -> _cmd_set_render_api
        changed_err = None if _idx >= 0 else '下拉里没有 %r' % (_target,)
    except Exception as e:
        changed_err = repr(e)
    cfg2 = guiloader.load_settings('loom').get('render_api')
    check('A10b editor 为 None 时面板改渲染后端真的落盘（逃生门可用，不是只有个壳）',
          changed_err is None and cfg2 == _target,
          'render_api=%r target=%r err=%s' % (cfg2, _target, changed_err))

    # ---- 真建一次确认可用（回退后的 GL 视口）----
    win.show()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 90 and getattr(win.viewport, 'editor', None) is None:
        app.processEvents()
        time.sleep(0.01)
    vp = win.viewport
    check('A11 回退后的 GL 视口真建成功（GL 上下文 + EditorApp 就绪 = 编辑器可用）',
          getattr(vp, 'editor', None) is not None
          and getattr(vp, 'init_error', None) is None,
          'editor=%r init_error=%r 耗时=%.1fs'
          % (getattr(vp, 'editor', None) is not None,
             getattr(vp, 'init_error', None), time.perf_counter() - t0))
    check('A12 LoomGUI.editor 已绑定（bind_editor 真跑过）', win.editor is not None,
          type(win.editor).__name__ if win.editor is not None else None)
    # 再泵几帧，确认编辑器不掉链（帧内异常会进 viewport.frame_errors / 抛）
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    check('A13 回退后编辑器跑 20 帧无异常', win.editor is not None,
          'editor=%r' % (win.editor is not None,))

    _write_verdict()
    print('---- mode=%s: %d PASS / %d FAIL ----' % (MODE, _pass_n, len(_fails)))
    sys.stdout.flush()
    # 不调 win.close()：真窗口收尾会卡在驱动 teardown（父门只认 verdict）
    os._exit(0 if not _fails else 1)


main()
