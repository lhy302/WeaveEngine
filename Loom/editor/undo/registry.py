# -*- coding: utf-8 -*-
"""
undo 基础设施 — 命令基类 / 批次命令 / UndoManager（原 Loom/undo.py 尾段；
目录重构 B4 批 2026-11-21 按命令域拆分为 editor/undo/ 包，本文件 = 基础设施域）。

快照工具与各域命令见 cmd_object / cmd_light / cmd_camera / cmd_scene；
包入口 editor/undo/__init__.py re-export 全部旧名（Loom/undo.py 门面再以
sys.modules 别名保仓外 'import undo' 旧名，读写/monkeypatch 同一包对象）。

约定（原文照抄）:
  - 每个命令 do() 之后才 push 到 undo 栈 (push 即执行)。
  - 命令里不做场景保存, 只改运行时状态; 保存由编辑器显式触发。
  - Point3D 是 namedtuple, 快照一律存 tuple, 应用时重建 Point3D。
"""
import time


# ---------------- 命令基类 ----------------

class Command:
    label = "命令"

    def do(self):
        raise NotImplementedError

    def undo(self):
        raise NotImplementedError

# ---------------- 批次命令 (2026-11-07 D: Agent 批次一键撤销) ----------------

class BatchCommandError(Exception):
    """批次整体 do/undo 有子命令失败时抛出 (2026-11-08 批4 / P-04-06).

    语义: 已经尽力把能回退的都回退了 (逐条容错, 不中断), 但整批**不算成功** ——
    调用方必须拿到"失败清单"而不是被静默吞掉 (SEM-SILENT 是上轮审计反复命中的
    缺陷类型)。审计报告: docs/audit/scan_beta3_04_editor_agent_visual.md P-04-06。
    """

    def __init__(self, batch, direction, failed):
        self.batch = batch
        self.direction = direction
        self.failed = list(failed)
        names = ', '.join(str(getattr(c, 'label', c)) for c, _ in self.failed[:4])
        Exception.__init__(
            self, '批次"%s"%s部分失败 (%d/%d): %s'
            % (getattr(batch, 'label', '?'),
               '撤销' if direction == 'undo' else '重做',
               len(self.failed), len(getattr(batch, 'cmds', ()) or ()), names))

class BatchCommand(Command):
    """把批内多条命令合成"一步"撤销: undo 逆序, redo 正序.

    构造时命令**已经执行过** (批内 push 正常 do()), 因此 do()/undo() 只负责
    整体重做/回退, end_batch 压栈时绝不重复调用 do() (否则同一批操作会执行两遍).

    2026-11-08 批4 (P-04-06): 逐条容错 —— 一条失败不再中断整批:
      · 继续走完全部子命令 (避免"回退一半"的中间态扩散);
      · 失败项存进 self.failed 并抛 BatchCommandError, 让 UndoManager/GUI 出声;
      · UndoManager.undo/redo 失败时不弹栈, 记录保留 -> 可诊断后重试。
    """

    def __init__(self, label, cmds):
        self.label = label or ("批量操作(%d)" % len(cmds))
        self.cmds = list(cmds)
        self.failed = []          # [(cmd, exc)] 最近一次 do/undo 的失败项

    def _run(self, seq, direction):
        self.failed = []
        for c in seq:
            try:
                (c.do if direction == 'do' else c.undo)()
            except Exception as e:
                self.failed.append((c, e))
        if self.failed:
            raise BatchCommandError(self, direction, self.failed)

    def do(self):
        self._run(self.cmds, 'do')

    def undo(self):
        self._run(reversed(self.cmds), 'undo')

# ---------------- 撤销管理器 ----------------

class UndoManager:
    """双栈撤销管理器 + **Agent 批次租约**（2026-11-08 批4 / 裁决 D10=A+B）.

    批次租约:
      · begin_batch 记一个截止时刻（默认 30s），批内每条写命令续租；
      · 到点由 tick_batch() 自动 end_batch —— 把已收命令**收口成一步**（历史
        保留、可撤销），绝不丢弃。这治的是"Agent 断连后批次悬挂、用户的撤销栈
        被永久锁死"（审计 P-04-05）。
      · absorb=True 的批次（直调 API / 旧行为）无条件把 push 吸进批；
        absorb=False 的批次（真 Agent 批次）只吸"agent 命令作用域内"的写命令 ——
        用户自己的编辑既不进批、也不续租（D10-A 附注），且先收口已收到的批命令，
        保证历史时间顺序。
      · 租约未到期时 undo/redo 一律拒绝并把原因写进 last_refusal（D10=B），
        而不是静默弹掉批次之外的历史（审计 P-04-04）。
    """

    BATCH_LEASE_S = 30.0

    def __init__(self, limit=100):
        self.undo_stack = []
        self.redo_stack = []
        self.limit = limit
        # 批次状态 (None = 不在批次内; list = 批内已执行、待合成的命令)
        self._batch = None
        self._batch_label = None
        self._batch_lease = float(self.BATCH_LEASE_S)
        self._batch_deadline = None      # time.monotonic() 截止; None = 不设租约
        self._batch_absorb = True
        self._agent_depth = 0            # >0 = 正在执行 Agent 命令 (AgentService 包裹)
        # 出声通道 (GUI/EAI 读): 最近一次失败 / 拒绝 / 自动收口
        self.last_error = None
        self.last_refusal = None
        self.last_closed = None

    # ---- Agent 命令作用域 (AgentService._run_one 包裹 dispatch) ----
    def agent_command_begin(self):
        self._agent_depth += 1

    def agent_command_end(self):
        self._agent_depth = max(0, self._agent_depth - 1)

    @property
    def in_agent_command(self):
        return self._agent_depth > 0

    # ---- 批次 API (agent_batch_begin/end/cancel 命令层调用) ----
    @property
    def batch_active(self):
        return self._batch is not None

    @property
    def batch_size(self):
        return len(self._batch) if self._batch is not None else 0

    @property
    def batch_lease_s(self):
        return self._batch_lease

    def batch_remaining(self, now=None):
        """批次剩余租约秒数 (无批次/不设租约 -> None; 已过期 -> 0.0)."""
        if self._batch is None or self._batch_deadline is None:
            return None
        now = time.monotonic() if now is None else float(now)
        return max(0.0, self._batch_deadline - now)

    def batch_expired(self, now=None):
        rem = self.batch_remaining(now)
        return rem is not None and rem <= 0.0

    def _batch_touch(self, now=None):
        """续租 (只有批内写命令走这里). lease<=0 = 不设租约 (deadline 恒 None)."""
        if self._batch_lease <= 0:
            self._batch_deadline = None
            return
        now = time.monotonic() if now is None else float(now)
        self._batch_deadline = now + self._batch_lease

    def tick_batch(self, now=None):
        """到点自动收口: end_batch (历史保留). 返回被收口的 BatchCommand 或 None."""
        if not self.batch_expired(now):
            return None
        batch = self.end_batch()
        if batch is not None:
            self.last_closed = batch
        return batch

    def begin_batch(self, label=None, lease_s=None, absorb=True):
        """开始收集批次. 已有未结束的批次 -> 先 cancel 旧批 (防悬挂), 返回 True.

        lease_s: 租约秒数; None=默认 30s, <=0 = 不设租约 (无限期, 仅供测试/兼容).
        absorb : True=push 无条件吸进批 (旧行为); False=只吸 Agent 命令作用域内的.
        """
        had_stale = self._batch is not None
        if had_stale:
            self.cancel_batch()
        self._batch = []
        self._batch_label = label
        self._batch_lease = float(self.BATCH_LEASE_S if lease_s is None else lease_s)
        self._batch_absorb = bool(absorb)
        self._batch_deadline = None
        if self._batch_lease > 0:
            self._batch_touch()
        return had_stale

    def end_batch(self):
        """把批内命令合成一个 BatchCommand 压栈 (不重复执行). 无批次返回 None."""
        if self._batch is None:
            return None
        cmds = self._batch
        self._batch = None
        label = self._batch_label
        self._batch_label = None
        self._batch_deadline = None
        if not cmds:
            return None
        batch = BatchCommand(label, cmds)
        self._append(batch)
        return batch

    def cancel_batch(self):
        """丢弃当前批次: 批内命令已执行过的 do() 不回滚, 也不留下撤销记录.

        2026-11-08 批4 (P-04-03): 与 _append 口径统一 —— 批内 do() 已经改过场景,
        重做栈里的旧命令必须在新状态上失效, 否则 Ctrl+Y 会把"回退过的旧命令"
        重放到"没被记录的批改动"之上。返回被丢弃的命令条数。
        """
        if self._batch is None:
            return 0
        n = len(self._batch)
        self._batch = None
        self._batch_label = None
        self._batch_deadline = None
        self.redo_stack.clear()
        return n

    def _split_batch_for_user_edit(self):
        """用户编辑插进批次中间: 已收到的批命令先收口成一步 (保时间顺序), 再重开同批.

        用户编辑不续租、不进批 (D10-A 附注); 重开同标签/同租约/同 absorb 的批次,
        让 Agent 后续命令仍归一批, 而用户那一步单独留在历史里。
        """
        label, lease, absorb = self._batch_label, self._batch_lease, self._batch_absorb
        self.end_batch()
        self.begin_batch(label, lease_s=lease, absorb=absorb)

    def _append(self, cmd):
        """压入撤销栈 (限长) + 清空重做栈 (push/push_no_do/end_batch 共用)."""
        self.undo_stack.append(cmd)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        return cmd

    def _absorb_into_batch(self, cmd):
        self._batch.append(cmd)
        self._batch_touch()
        return cmd

    def push(self, cmd):
        """执行 cmd 并压入撤销栈, 同时清空重做栈.

        批次进行中 (lease 内): absorb=True 无条件收进批并续租; absorb=False 时
        只有 Agent 命令作用域内才收进批, 用户编辑先收口批再单独压栈。
        """
        self.tick_batch()
        cmd.do()
        if self._batch is not None:
            if self._batch_absorb or self.in_agent_command:
                return self._absorb_into_batch(cmd)
            self._split_batch_for_user_edit()
        return self._append(cmd)

    def push_no_do(self, cmd):
        """只压栈不执行 cmd.do() —— 用于"命令函数已执行完修改"的场景
        (如 ui_set 已改完字段, 只需记录快照差异). 2026-10-18 阶段5.

        批次语义与 push 完全一致 (含租约/作用域判定)。
        """
        self.tick_batch()
        if self._batch is not None:
            if self._batch_absorb or self.in_agent_command:
                return self._absorb_into_batch(cmd)
            self._split_batch_for_user_edit()
        return self._append(cmd)

    def undo_block_reason(self, now=None):
        """批次租约内返回拒绝文案 (D10=B), 否则 None (无批次 / 已自动收口)."""
        self.tick_batch(now)
        if self._batch is None:
            return None
        rem = self.batch_remaining(now)
        if rem is None:
            return 'Agent 批次进行中，暂不可撤销'
        secs = int(rem)
        if rem > secs:
            secs += 1
        return 'Agent 批次进行中（剩余 %ds），暂不可撤销' % secs

    def undo(self):
        """撤销一步. 失败不弹栈 (记录保留, 可重试) 并把原因写进 last_error."""
        self.last_error = None
        reason = self.undo_block_reason()
        if reason:
            self.last_refusal = reason
            return None
        self.last_refusal = None
        if not self.undo_stack:
            return None
        cmd = self.undo_stack[-1]
        try:
            cmd.undo()
        except Exception as e:
            # P-04-06: 只记录不吞 —— 栈不动, 用户/Agent 能看到"撤销失败 + 原因"
            self.last_error = '撤销失败 (%s): %s' % (getattr(cmd, 'label', cmd), e)
            return None
        self.undo_stack.pop()
        self.redo_stack.append(cmd)
        return cmd

    def redo(self):
        """重做一步 (批次租约内同样拒绝; 失败不弹栈并记录原因)."""
        self.last_error = None
        reason = self.undo_block_reason()
        if reason:
            self.last_refusal = reason
            return None
        self.last_refusal = None
        if not self.redo_stack:
            return None
        cmd = self.redo_stack[-1]
        try:
            cmd.do()
        except Exception as e:
            self.last_error = '重做失败 (%s): %s' % (getattr(cmd, 'label', cmd), e)
            return None
        self.redo_stack.pop()
        self.undo_stack.append(cmd)
        return cmd

    @property
    def can_undo(self):
        return bool(self.undo_stack)

    @property
    def can_redo(self):
        return bool(self.redo_stack)

    def undo_label(self):
        return self.undo_stack[-1].label if self.undo_stack else ""

    def redo_label(self):
        return self.redo_stack[-1].label if self.redo_stack else ""

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        # 2026-11-07 D: 换场/清栈时批次状态一并复位 (防跨场景悬挂)
        self._batch = None
        self._batch_label = None
        self._batch_deadline = None
        self.last_error = None
        self.last_refusal = None
        self.last_closed = None
