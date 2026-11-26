# -*- coding: utf-8 -*-
"""
gui/panels/status_mixin.py — 状态栏 + EAI 可视化（Agent 进度/红点/批次租约）（Q-B7-38-1 第 8 批，自 gui/main_window.py 纯搬迁）


我负责：状态栏构建与选中/TPS/FPS 状态刷新、AgentService 的执行进度回调
（状态栏占用/红点/空闲恢复/批次租约可视化/窗口销毁静默）。
我不负责：工具栏构建（toolbar_mixin）、事件过滤（主窗口）。

搬迁纪律（见 docs/guides/开发要求_功能解耦与模块化.md §3）：方法体逐字未动，
只改 def 归属与 import 头；LoomGUI 经 gui/main_window.py 的基类装配混入本类。
"""

import json

from PySide6.QtCore import QTimer

from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QToolButton,
)


class StatusMixin:
    # 混入 LoomGUI（gui/main_window.py 基类装配）；以下方法体逐字未动。

    def _build_statusbar(self):
        self._msg_label = QLabel("")
        self._msg_label.setStyleSheet("color:#666;")
        self.statusBar().addPermanentWidget(self._msg_label)
        # 2026-10-19 移动: UI树/命令行开关按钮移到主工具栏左上角（用户要求）
        # 原因: 状态栏在窗口较小时可能被挤掉看不见，工具栏始终可见。
        sb = QToolButton()
        sb.setText("设置")
        sb.setAutoRaise(True)
        sb.clicked.connect(self._cmd_settings)
        self.statusBar().addPermanentWidget(sb)

    def _refresh_status(self):
        e = self.editor
        if e is None:
            return
        m = e._selected()
        if m is not None:
            sel = m.name
        elif e._selected_light() is not None:
            sel = "光源: " + e._selected_light().name
        elif e._selected_camera() is not None:
            sel = "相机: " + e._selected_camera().name
        else:
            sel = "无"
        # TPS 实测 (分离批5, 用户需求: FPS 旁直读逻辑时钟走没走/停没停)
        tps = e.get_tps() if e.is_playing else 0.0
        tps_txt = ("TPS: %.1f" % tps) if e.is_playing else "TPS: —"
        if e.is_playing and getattr(e, '_logic_paused', False):
            tps_txt = "TPS: 已暂停 (F10 步进)"
        txt = ("FPS: %d | %s | 对象: %d | 光源: %d | 摄像机: %d | 选中: %s | "
               "相机距离: %.1f%s" % (e.fps, tps_txt, len(e.models), len(e.lights),
                                   len(e.cameras), sel, e.camera_distance,
                                   " | → 播放中" if e.is_playing else ""))
        # ★B4c (2026-10-16): 物理线程建失败 (系统极限工况) 醒目提示
        if getattr(e, '_phys_pipe_sysfail', False):
            txt = ("!!! 物理线程创建失败 (系统资源耗尽?) — 立即保存并关闭软件 !!! "
                   "| " + txt)
            self._msg_label.setText("⚠️ 物理线程创建失败，请立即保存并关闭软件")
            self._msg_label.setStyleSheet("color:#d33;font-weight:bold;")
            self.statusBar().showMessage(txt)
            # 一次性弹窗 (避免轮询反复弹)
            if not getattr(self, '_phys_sysfail_notified', False):
                self._phys_sysfail_notified = True
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(
                    self, "系统资源告警",
                    "物理线程创建失败，可能原因：系统线程数或内存耗尽。\n\n"
                    "引擎已降级为主线程串行跑物理（功能可用但性能下降）。\n\n"
                    "★ 请立即保存场景并关闭软件，排查系统资源占用。\n"
                    "★ 继续运行可能进一步耗尽资源，下次崩溃可能是整个系统。\n\n"
                    "Physics thread failed (OS thread/memory exhausted?).\n"
                    "Degraded to main-thread physics. SAVE & CLOSE NOW.")
            return
        # 2026-11-07 EAI 可视化 (B): Agent 进度正占用状态栏时, 300ms 轮询
        # 不得覆盖; 空闲 1.5s 后 _agent_idle 会主动回调本函数恢复默认文本.
        if getattr(self, '_agent_status_active', False):
            return
        self.statusBar().showMessage(txt)

    # ---------------- EAI 可视化 (B, 2026-11-07) ----------------
    # AgentService 每执行一条命令回调下列钩子 (getattr 存在才调用, 本类全实现):
    #   _agent_progress(cmd, args, done, total) -> 状态栏进度
    #   _agent_busy(active)                     -> 工具栏红点 + 状态栏变色
    #   _agent_after_command()                  -> 视口立即重绘
    @staticmethod
    def _agent_args_summary(args, limit=40):
        """命令参数 -> 'k=v k=v' 摘要, 超过 limit 字符截断 (末尾省略号)."""
        if not args:
            return ''
        if not isinstance(args, dict):
            txt = str(args)
        else:
            parts = []
            for k, v in args.items():
                if isinstance(v, (dict, list, tuple)):
                    try:
                        v = json.dumps(v, ensure_ascii=False,
                                       separators=(',', ':'))
                    except Exception:
                        v = str(v)
                else:
                    v = str(v)
                parts.append('%s=%s' % (k, v))
            txt = ' '.join(parts)
        txt = txt.replace('\n', ' ').replace('\r', ' ')
        if limit and len(txt) > limit:
            txt = txt[:max(0, limit - 1)] + '…'
        return txt

    def _agent_progress(self, cmd, args, done, total):
        """状态栏: 'AI: <cmd> <参数摘要≤40> (done/total)'.

        窗口已销毁时直接返回 —— 既不碰 QWidget, 也不再排新的空闲定时器
        (U-02: 保证"销毁后静默停表", 而不是每来一条命令再抛一次)。
        """
        if getattr(self, '_agent_gui_dead', False):
            return
        try:
            done_i, total_i = int(done), int(total)
        except Exception:
            done_i, total_i = 0, 0
        summ = self._agent_args_summary(args)
        txt = "AI: %s%s (%d/%d)" % (
            cmd, (" " + summ) if summ else "", done_i, total_i)
        rem = getattr(self, '_agent_batch_remaining', None)
        if rem is not None:
            txt += " · 批次剩余 %ds" % int(rem)
        self._agent_status_active = True
        self.statusBar().showMessage(txt)
        if self._agent_busy_active:
            self.statusBar().setStyleSheet("color:#e06c75;")
        # 空闲 1.5s 恢复默认文本; token 防重入: 新命令让旧定时器自动作废.
        self._agent_idle_token += 1
        tok = self._agent_idle_token
        QTimer.singleShot(1500, lambda: self._agent_idle(tok))

    def _agent_gui_alive(self):
        """窗口底层 C++ 对象是否还活着 (2026-11-08 批4 · 审计 U-02).

        Qt 里窗口 close/deleteLater 之后, 再调它任何方法都会抛
        RuntimeError("Internal C++ object already deleted")。定时器是
        QTimer.singleShot 排的一次性回调, 排完就没了 —— 真正要防的是
        "_refresh_status 抛出来后每来一条命令又排一个新定时器、每次再抛一遍"。
        """
        if getattr(self, '_agent_gui_dead', False):
            return False
        try:
            self.statusBar()
            return True
        except RuntimeError as e:            # 只认"对象已销毁"这一类
            self._agent_gui_dead = True
            self._agent_gui_warn_once('statusBar 已失效 (%s): %s'
                                      % (type(e).__name__, e))
            return False
        except Exception as e:               # 其它异常: 记一次原因, 复现照旧
            self._agent_gui_warn_once('statusBar 访问异常: %r' % (e,))
            return False

    def _agent_gui_warn_once(self, reason):
        """GUI 已销毁/异常时只告警一次 (之后静默, 避免每帧刷屏)."""
        if getattr(self, '_agent_gui_warned', False):
            return
        self._agent_gui_warned = True
        try:
            import sys as _sys
            print('[agent] GUI 状态栏不可用, 之后静默: %s' % reason,
                  file=_sys.stderr)
        except Exception as e:
            self._agent_gui_warned = False
            print('[agent] 告警输出失败: %r (原因: %s)' % (e, reason))

    def _agent_idle(self, token):
        """1.5s 无新命令: 释放状态栏, 回落 _refresh_status 的默认文本.

        2026-11-08 批4 (审计 U-02): 旧实现把 `_refresh_status()` 放在所有 try 之外,
        窗口销毁后定时器一触发就抛 RuntimeError; 现在:
          · 先判窗口是否还活着 (_agent_gui_alive, 销毁即静默停表);
          · _refresh_status 包 try, 失败**只告警一次并带原因** (不无差别吞).
        """
        if token != getattr(self, '_agent_idle_token', -1):
            return                      # 期间又来了新命令, 旧定时器作废
        if getattr(self, '_agent_batch_active', False):
            return                      # 批次提示占用状态栏 (D10 可视化), 不清
        if not self._agent_gui_alive():
            return                      # 窗口已销毁: 静默停止, 不再碰任何 QWidget
        self._agent_status_active = False
        if not self._agent_busy_active:
            try:
                self.statusBar().setStyleSheet("")
            except RuntimeError as e:
                self._agent_gui_warn_once('setStyleSheet 失败 (%s): %s'
                                          % (type(e).__name__, e))
                return
        try:
            self.statusBar().clearMessage()
        except RuntimeError as e:
            self._agent_gui_warn_once('clearMessage 失败 (%s): %s'
                                      % (type(e).__name__, e))
            return
        try:
            self._refresh_status()
        except RuntimeError as e:
            self._agent_gui_warn_once('_refresh_status 失败 (%s): %s'
                                      % (type(e).__name__, e))
        except Exception as e:
            # 非"对象已销毁"类异常: 只告警一次, 带上类型与原因, 不静默
            self._agent_gui_warn_once('_refresh_status 异常: %r' % (e,))

    @staticmethod
    def _agent_tb_visible(act, widget, visible):
        """QToolBar 内控件的可靠显隐: 先切 QWidgetAction, 再切控件本身.

        只切 action 时, 若窗口 show 时 action 恰好不可见, 工具栏会给控件打上
        显式 hide 标记, 之后再 action.setVisible(True) 控件仍不出现 (实测)."""
        visible = bool(visible)
        if act is not None:
            act.setVisible(visible)
        if widget is not None:
            widget.setVisible(visible)

    def _agent_busy(self, active):
        """工具栏红点显隐 + 状态栏文字颜色 (#e06c75 表示 Agent 执行中)."""
        self._agent_busy_active = bool(active)
        self._agent_tb_visible(getattr(self, '_act_agent_busy', None),
                               getattr(self, '_lbl_agent_busy', None),
                               self._agent_busy_active)
        try:
            if self._agent_busy_active:
                self.statusBar().setStyleSheet("color:#e06c75;")
                if not self._agent_status_active:
                    self.statusBar().showMessage("AI: 操作中…")
            else:
                self.statusBar().setStyleSheet("")
                if not self._agent_status_active:
                    self.statusBar().clearMessage()
        except Exception:
            pass

    def _agent_batch_status(self, remaining):
        """Agent 批次租约状态 (2026-11-08 批4 / 裁决 D10).

        remaining=None -> 批次结束/没有批次: 清提示并回落默认文本;
        remaining=数字  -> 状态栏 'Agent 批次进行中（剩余 Xs）'.

        AgentService 每拍调 (只在"剩余秒数变化"时), 所以这里不做节流。
        """
        self._agent_batch_remaining = None if remaining is None else int(remaining)
        self._agent_batch_active = remaining is not None
        try:
            if remaining is None:
                self._agent_status_active = False
                self.statusBar().setStyleSheet("")
                self.statusBar().clearMessage()
                self._refresh_status()
            else:
                self._agent_status_active = True
                self.statusBar().showMessage(
                    "Agent 批次进行中（剩余 %ds）" % int(remaining))
        except Exception as e:
            print("[agent] 批次状态栏更新失败: %r" % (e,))

    def _agent_after_command(self):
        """每条命令执行完强制重绘视口, 保证人眼立刻看到结果."""
        vp = getattr(self, 'viewport', None)
        if vp is not None:
            try:
                vp.update()
            finally:
                vp.repaint()

    def _bind_agent_service(self, agent):
        """--agent 分支 / 测试: 绑定 AgentService (可视化钩子由服务侧 getattr 调用)."""
        self._agent_service = agent
        return agent
