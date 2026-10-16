# -*- coding: utf-8 -*-
"""
core_clock.py — 逻辑帧/渲染帧分离核心时钟 (分离批5 架构重对齐, 2026-09-05)

FixedStepClock = Unity Player Loop 的 accumulator 模型 (批5 重构定案):
  - **单 accumulator**: 只有逻辑帧是调度单位 (整个场景的最高同步点);
    每逻辑帧内部按 phys_substeps 自动跑 N 次物理子步 (Unity 模型:
    物理步长 = 物理引擎内部参数 fixed_dt, 不是用户频率旋钮 — 双 accumulator
    与 physics_fps 设置为批1 的过度设计, 批5 移除);
  - phys_substep_dt: 物理子步固定步长 (默认 1/60, Jolt 穿透安全);
    N = ceil(fixed_dt / phys_substep_dt); N==1 时子步 dt:=fixed_dt
    (物理与逻辑同拍, 高逻辑帧率下不缩步长);
  - maximum_logic_delta: 单渲染帧计入的逻辑时间上限 (死亡螺旋保险,
    Unity Time.maximumDeltaTime 精神);
  - max_steps_per_frame: 单渲染帧逻辑步数上限, 超限丢积压 (Unity
    Time.maximumFixedTimestep 精神);
  - time_scale: 暂停=0 / 慢放=0.5 (Unity Time.timeScale 精神);
  - alpha: 渲染帧位于 curr 逻辑帧内的进度 [0,1), 插值层消费。

纯逻辑零依赖 (无 pygame/engine import), tests 单测直调。
分离总开关由 split_enabled() 从设置面判定 (logic_fps<=0 = 绑死模式);
★B7b 退役 (2026-10-16): LOOM_NO_SPLIT 环境逃生门已删 (死代码清理)。
"""
import math
import time


class FixedStepClock:
    """固定步长单 accumulator 时钟 (逻辑帧 = 最高同步点, 物理在帧内子步)."""

    def __init__(self, logic_fps=30.0, phys_substep_dt=1.0 / 60.0,
                 maximum_logic_delta=0.333, time_scale=1.0,
                 max_steps_per_frame=None):
        self.logic_fps = float(logic_fps)
        self.phys_substep_dt = float(phys_substep_dt)
        self.maximum_logic_delta = float(maximum_logic_delta)
        self.time_scale = float(time_scale)
        # max_steps_per_frame=None = 自适应 (按 maximum_logic_delta/fdt 预算:
        # 每渲染帧最多追 maximum_logic_delta 秒的逻辑时间 — 重场景 1 帧,
        # 轻场景多帧; 防死亡螺旋: 逻辑帧贵时绝不背 2+ 帧积压).
        self._max_steps_explicit = (None if max_steps_per_frame is None
                                    else int(max_steps_per_frame))
        self.max_steps_per_frame = (self._max_steps_explicit if
                                    self._max_steps_explicit is not None else 1)
        self.alpha = 0.0                 # 渲染帧插值系数 [0,1)
        self.steps = 0                   # 上渲染帧逻辑步数 (HUD/调试)
        self.phys_steps = 0              # 上渲染帧物理子步累计 (HUD/调试)
        self._acc = 0.0                  # 逻辑 accumulator (秒)
        self._last = None                # 上次 advance 时间戳 (None=首帧)
        # 逻辑帧回调: [fn(fixed_dt), ...] — 物理/脚本/音频/动画全在里面,
        # 由 engine._logic_frame 组织帧内段次序 (批5/批6 流水线挂点)
        self.on_logic_step = []
        self._recalc()                   # 算 sub_steps / sub_dt

    def _recalc(self):
        """由 logic_fps + phys_substep_dt 定每逻辑帧物理子步数 (编译期定常数):
        N = ceil(fixed_dt / sub_dt); N==1 时子步 dt 拉齐 fixed_dt (物理与逻辑
        同拍 — 子步不比逻辑步更细时保留更大步长, 与 Unity 单步语义一致)."""
        fdt = 1.0 / max(self.logic_fps, 1e-6)
        sdt = max(float(self.phys_substep_dt), 1e-6)
        n = int(math.ceil(fdt / sdt - 1e-9))
        if n < 1:
            n = 1
        self._sub_steps = n
        self._sub_dt = fdt if n == 1 else sdt
        # 步数上限自适应 (未显式指定时): 每渲染帧最多追 maximum_logic_delta
        # 秒的逻辑时间 (Unity Time.maximumDeltaTime 精神, 默认收紧到 0.05s —
        # 逻辑帧贵时 1 帧/渲染帧, 时间膨胀代替帧率崩塌)
        if self._max_steps_explicit is None:
            self.max_steps_per_frame = max(
                1, int(round(self.maximum_logic_delta / fdt)))

    # ---- 步长 (fps<=0 防御: 调用方逃生门不会进来, 这里兜底不除零) ----
    @property
    def fixed_dt(self):
        return 1.0 / max(self.logic_fps, 1e-6)

    def set_fps(self, logic_fps=None, phys_substep_dt=None):
        """运行中改频 (设置面板/脚本): 累积器按新步长继续 (小数余量保留,
        不追帧不跳步); 子步数随之重算 (下一逻辑帧生效)."""
        if logic_fps is not None and logic_fps > 0:
            self.logic_fps = float(logic_fps)
        if phys_substep_dt is not None and phys_substep_dt > 0:
            self.phys_substep_dt = float(phys_substep_dt)
        self._recalc()

    def step_once(self):
        """步进播放 (开发者功能, 2026-09-05): 强制恰好跑 1 个逻辑帧
        (不管 accumulator 余量 — dt 直注 fixed_dt 后排干)。
        用于逐帧验证逻辑行为/解耦验证 (1TPS 观感: 手动步进 + 渲染帧照跑)。
        返回 (steps, phys_steps) = (1, N)。"""
        self._acc += self.fixed_dt
        return self.advance(0.0)

    def pending_steps(self):
        """accumulator 中已到期但未执行的未来逻辑帧数 (预取决策输入):
        每渲染帧 advance 后余量 / fdt 的整数部分 (本帧已跑完的不算)."""
        fdt = self.fixed_dt
        return int(self._acc / fdt) if fdt > 0 else 0

    def advance(self, render_dt=None):
        """每渲染帧调一次. render_dt=None 则内部实测墙钟 (首帧 0 步).
        返回 (steps, phys_steps) — phys_steps = 本帧子步累计 (兼容旧观测面).
        TPS 缓冲 (2026-09-06): 回调列表带 ledger 时, 预取过的帧跳过重跑
        (成品已在引擎缓存) — 时间轴/alpha 语义零变化, 只省计算."""
        if render_dt is None:
            now = time.perf_counter()
            render_dt = 0.0 if self._last is None else now - self._last
            self._last = now
        # 死亡螺旋保险: 单帧计入时间封顶 (Unity maximumDeltaTime)
        dt = min(max(render_dt, 0.0), self.maximum_logic_delta) * self.time_scale
        self._acc += dt
        steps = 0
        psteps = 0
        fdt = self.fixed_dt
        ledger = getattr(self, 'frame_buffer', None)
        while self._acc >= fdt and steps < self.max_steps_per_frame:
            if ledger is not None and ledger.consume():
                pass                     # 预取成品: 帧体已跑过, 只翻记账
            else:
                for fn in tuple(self.on_logic_step):
                    fn(fdt)              # 逻辑帧 = 最高同步点 (物理子步在内)
            self._acc -= fdt
            steps += 1
            psteps += self._sub_steps
        if steps == self.max_steps_per_frame and self._acc >= fdt:
            self._acc = 0.0              # 积压丢弃 (死亡螺旋保险)
        self.steps = steps
        self.phys_steps = psteps
        # alpha: 渲染帧在 curr 逻辑帧内的进度 (插值层只看逻辑 alpha)
        self.alpha = self._acc / fdt if steps or self._acc > 0.0 else 0.0
        return steps, psteps

    def reset(self):
        """边界对齐 (场景加载/进出播放): 清累积器+首帧重锚, alpha=0."""
        self._acc = 0.0
        self._last = None
        self.alpha = 0.0
        self.steps = self.phys_steps = 0
        # TPS 缓冲: 预取记账一并清 (预取帧产物由 engine 侧 prep/interp reset 覆盖)
        led = getattr(self, 'frame_buffer', None)
        if led is not None:
            led.reset()

    # ---- 批5 公开只读面 (engine/driver 消费; 私有名只类内用) ----
    @property
    def sub_steps(self):
        """每逻辑帧物理子步数 N = ceil(fixed_dt / sub_dt) (编译期定常数)."""
        return self._sub_steps

    @property
    def sub_dt(self):
        """物理子步固定步长 (N==1 时 = fixed_dt, 物理与逻辑同拍)."""
        return self._sub_dt


def clock_from_settings(settings):
    """设置.json -> FixedStepClock (guiloader.load_settings('loom') 产物).
    逃生门判定也在这: logic_fps<=0 返回 None (调用方回退旧绑死模式).
    子步长来源 (批5 最终口径):
      ① "phys_substep_dt" >0 直接用 (新内部参数键, 高级开发者);
      ② 旧键 "physics_fps" >=50 才换算 1/pf (<50 视为误设, 兜底 60Hz
         防薄地板穿透); 键已从用户面撤下, 一代后移除本段."""
    lf = float(settings.get("logic_fps", 30))
    if lf <= 0:
        return None
    sdt = float(settings.get("phys_substep_dt", 0) or 0)
    if sdt <= 0:
        pf = float(settings.get("physics_fps", 0))
        sdt = (1.0 / pf) if pf >= 50.0 else (1.0 / 60.0)
    return FixedStepClock(logic_fps=lf, phys_substep_dt=sdt)


def split_enabled(settings=None):
    """分离总开关: logic_fps<=0 = 旧绑死模式 (用户配置路径)。

    ★B7b 退役 (2026-10-16): 删 LOOM_NO_SPLIT 环境逃生门 (A/B 对拍门)。
    绑死模式仍可由设置 logic_fps<=0 触发 (用户配置, 非逃生门)。
    彻底移除绑死模式架构 = 单独立项 (见 handoff 台账 8.2)。"""
    if settings is None:
        try:
            import guiloader
            settings = guiloader.load_settings('loom')
        except Exception:
            settings = {}
    return float(settings.get("logic_fps", 30)) > 0
