# -*- coding: utf-8 -*-
"""
gui/panels/cmd_bridge_mixin.py — 命令桥（共享前置，规则 3）：GUI → EAI 命令统一翻译入口（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：把面板/工具栏/快捷键的一切点击翻译成 agent_commands 命令表里的
命令执行（_invoke_cmd 家族）、数值行编辑会话批、结果 toast 辅助
（_notify_or_print / _report_history_result）与编辑器 GL 资源钩子（_gl_guard）。
我不负责：任何面板布局构建、命令体本身（在 agent_commands）、事件过滤与帧驱动。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""


class CmdBridgeMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    def _notify_or_print(self, text, color=(240, 200, 90)):
        """editor 在时走状态栏 toast，不在时降级为 print（P0-1: 视口装配失败时
        editor 恒 None，设置面板的命令路径不能因此崩 —— Loom.exe 无控制台时这些
        行仍有意义，因为设置面板本身已可达）。"""
        e = self.editor
        if e is not None:
            try:
                e._notify(text, color)
                return
            except Exception:
                pass
        print('[Qt] ' + str(text))

    def _invoke_cmd(self, cmd_name, args=None, quiet=False, notify_error=True):
        """GUI → EAI 命令统一入口（Q-B7-56-1 裁定①, 2026-11-22）。

        裁定①: GUI 界面除「鼠标拾取/拖拽」与「开发者相机连贯移动」两个豁免面外,
        一切点击都翻译成命令表 (agent_commands._COMMANDS) 里的命令再执行 ——
        本方法即翻译器。原名 _invoke_ui_cmd（决策 B4 命令壳, UI 树专用）, 本批
        通用化为全 GUI 共用; 旧名保留为别名（UI 树 4 处调用点行为逐位不变）。

        执行语义（与 B4 原壳逐位一致）:
          1) 查命令表 → **直调命令函数**（不经 ac.dispatch 的 agent 作用域包裹
             —— GUI 翻译的命令 = 用户编辑: 进撤销栈, 但不进 agent 批作用域、
             不续租, D10=A 语义保持; 命令行 F12/远程才走 dispatch 缺省
             scope='agent'; 执行期本方法把命令作用域置 'user', 供命令层按需
             区分, 如 scene_save 对人类对话框授权路径的放行）；
          2) 错误 → _notify 出声（notify_error=False 时由调用方消费, 如
             _cmd_undo 交 _report_history_result, 防双 toast）；
          3) 命令日志（教学: 小白看到等价 EAI 命令, log_cmd）+ 刷 UI 树；
          4) 刷检查器（C3 联动）。
        quiet=True: 高频数值行（拖块逐像素）不逐条写日志/刷新 —— 记入
        _pending_quiet_cmd, 会话收尾 _spin_session_end 统一补一条 + 刷新。
        """
        import agent_commands as ac
        args = dict(args or {})
        fn = ac._COMMANDS.get(cmd_name)
        if fn is None:
            self._notify_or_print("UI 命令不存在: %s" % cmd_name, (235, 90, 90))
            return {'error': '命令不存在: %s' % cmd_name}
        try:
            ac._CMD_SCOPE.push('user')
            try:
                r = fn(self, args)
            finally:
                ac._CMD_SCOPE.pop()
        except Exception as e:
            self._notify_or_print("UI 操作异常: %r" % e, (235, 90, 90))
            return {'error': repr(e)}
        if isinstance(r, dict) and 'error' in r:
            if notify_error:
                self._notify_or_print("UI 操作失败: %s" % r['error'], (235, 90, 90))
            return r
        if quiet:
            # 高频数值行: 日志/刷新延后会话收尾 (一次编辑 = 一条教学命令)
            self._pending_quiet_cmd = (cmd_name, args)
            return r
        self._log_gui_cmd(cmd_name, args)
        # 刷检查器（C3 联动; 无检查器的桩环境 try 兜底, 不吞命令结果）
        self._insp_last_digest = None
        try:
            self._rebuild_inspector()
        except Exception:
            pass
        return r

    def _invoke_ui_cmd(self, cmd_name, **args):
        """（兼容别名, B4 命令壳旧名）→ _invoke_cmd. UI 树调用点行为逐位不变."""
        return self._invoke_cmd(cmd_name, args)

    def _log_gui_cmd(self, cmd_name, args):
        """命令日志（教学: 等价命令）+ 刷 UI 树; uitree 未建/异常时静默跳过
        （裸桩测试与极早启动期没有 uitree, 不该让命令执行本身失败）."""
        ut = getattr(self, 'uitree', None)
        if ut is None:
            return
        try:
            ut.log_cmd(cmd_name, dict(args))
            ut.refresh()
        except Exception:
            pass

    # ---- 数值行编辑会话 (Q-B7-56-1 裁定①: 命令化数值行的连续写合一步撤销) ----
    def _spin_session_begin(self, label):
        """数值行编辑会话开始（DragBlock 按下 / spinbox 首个 valueChanged）。

        会话内每条 apply 已是 EAI 命令（set_transform/light_set/camera_set, 各自
        自带一步撤销）; 不合并的话拖一次 = 几十步撤销。用 **GUI 自己的批**
        （absorb=True, owner='gui', 无租约）把会话内命令合成一步 —— 不是 agent 批:
        不经 agent_batch_begin、无租约续租, D10=A 的 agent 批作用域不受影响。
        批激活时若跑的是 agent 批, 先 end_batch 收口（历史保留, D10=A 用户编辑
        插入语义）再开 GUI 批。"""
        e = self.editor
        um = getattr(e, 'undo', None) if e is not None else None
        if um is None or not hasattr(um, 'begin_batch'):
            return
        try:
            if um.batch_active:
                if getattr(um, 'batch_owner', None) == 'gui':
                    return           # 已在本次会话批中（连续 valueChanged）
                um.end_batch()       # 用户编辑打断 agent 批: 先收口（历史保留）
            um.begin_batch('检查器: ' + (label or '数值'), lease_s=0,
                           absorb=True, owner='gui')
        except TypeError:
            pass                     # 兼容无 owner/lease 参数的旧 UndoManager
        self._pending_quiet_cmd = None

    def _spin_session_end(self, label):
        """数值行编辑会话结束（DragBlock 松开 / editingFinished）: 收口会话批
        （会话内无命令则不留撤销）+ 补一条教学等价命令日志 + 刷新（对齐旧
        on_finish 的 _refresh_all）。"""
        e = self.editor
        um = getattr(e, 'undo', None) if e is not None else None
        if um is not None and hasattr(um, 'end_batch') \
                and getattr(um, 'batch_owner', None) == 'gui':
            um.end_batch()
        pending = getattr(self, '_pending_quiet_cmd', None)
        if pending is not None:
            self._pending_quiet_cmd = None
            self._log_gui_cmd(*pending)
        self._refresh_all()

    def _cmd_vec_set(self, obj, kind, field, axis, v):
        """检查器数值行单轴写入 → EAI 命令（Q-B7-56-1 裁定①, 2026-11-22）。

        旧实现直调 agent_commands.vec_set（同名 helper 却没走命令表）—— 现翻译
        成等价命令: model → set_transform（x/y/z; rotation 用 rx/ry/rz, **度制**,
        命令层内部转弧度 —— 与命令行输 set_transform 逐字同义）, light →
        light_set（x/y/z）, camera → camera_set（x/y/z）。quiet=True: 高频单轴写
        不逐条刷 UI/写教学日志, 会话收尾统一处理（_spin_session_end）。
        """
        key = ('r' if field == 'rotation' else '') + str(axis).lower()
        cmd = {'model': 'set_transform', 'light': 'light_set',
               'camera': 'camera_set'}[kind]
        self._invoke_cmd(cmd, {'name': getattr(obj, 'name', None), key: v},
                         quiet=True)

    def _gl_guard(self):
        """编辑器 GL 资源创建钩子 (2026-08-21): UI 回调 (添加物体/导入/undo 等)
        里引擎建 VAO/VBO —— QOpenGLWidget 非 paintGL 时机默认未 makeCurrent,
        未激活 context 下 moderngl 资源会静默落错 context (VAO 有效但渲染零
        输出不报错; 用户实测"空场景启动后添加物体不显示"). Qt 规范: 非 paintGL
        使用 GL 前必须 makeCurrent; 引擎 _build_gpu 经 getattr 调用本钩子."""
        self.viewport.makeCurrent()

    def _report_history_result(self, res):
        """撤销/重做被拒或被批次租约挡住 -> 出声 (D10=B: 不允许静默无效).

        注意: LoomGUI 自身没有 _notify (见 ui/qt_uitree.py:_notify_win 的注释),
        toast 走 EditorApp._notify; 拿不到再退回状态栏 showMessage。

        P1-1 (Q-B7-56-2, 2026-11-22): 命令层 _history_result 把 blocked 归一成
        布尔 True (原因串在 error 键), 旧代码 "res.get('blocked') or ..." 会把
        toast 文案退化成 "True" —— 修法: 布尔 blocked 用 error 串出声, blocked
        本身是串 (editor._undo_action 原始返回) 时用本串。
        """
        if not isinstance(res, dict):
            return
        blk = res.get('blocked')
        if isinstance(blk, str) and blk:
            msg = blk
        else:
            msg = res.get('error')
        if not msg:
            return
        ed = getattr(self, 'editor', None)
        if ed is not None:
            try:
                ed._notify(str(msg), (240, 200, 90))
                return
            except Exception:
                pass
        try:
            self.statusBar().showMessage(str(msg), 4000)
        except Exception:
            pass
