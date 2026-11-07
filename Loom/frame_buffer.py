# -*- coding: utf-8 -*-
"""
frame_buffer.py — 逻辑帧预取缓冲 (TPS 缓冲实验, 2026-09-06)

用户设想 (2026-09-05): "引入一两帧的逻辑帧缓冲区, 尽可能让渲染帧不会缺数据;
万一某帧 CPU 算慢了, 缓冲区内帧也可以顶上保证 TPS 不变化, 后面 CPU 算快一点
顶上。缓冲区应该存算好的数据。"

实现形态 (定案):
  预取帧的产物 (插值快照 / AABB / 光源 VP / 碰撞对) 天然按 _logic_gen 缓存在
  引擎既有缓存里, 无需搬数据 —— 缓冲区只做**记账**: 渲染帧尾若 accumulator
  已积累出未来逻辑帧 (且本帧渲染富余), 提前执行 _logic_frame 并记账;
  下一渲染帧 clk.advance 轮到该帧时直接消费 (跳过重跑)。

  效果: 尖峰渲染帧 (GC/加载/系统抖动) 到来时逻辑帧成品已在缓存, TPS 节律
  不被单帧尖峰拖慢; 尖峰过后 accumulator 停止预取, CPU 自然还债。
  平均负载饱和时无富余 → 预取自然停 → 行为与不开完全一致 (无负收益路径)。

闸门 (用户定案 2026-09-06): logic_fps >= 30 才允许开启 (单帧时间越长,
缓冲引入的延迟越大, 得不偿失); 关闭时 TPS 照常实测, 行为逐位同旧。

边界 (诚实声明):
  - 输入采样仍在渲染帧 (advance 消费预取帧时无新输入) — 键盘/脚本 API 的
    read 端响应延迟最多增加 1 逻辑帧 (30Hz 时 33ms, 远低于人类感知阈);
  - 碰撞事件派发仍走 _parallel_shadow_and_collision 的 _disp_gen 节流,
    预取帧的 pairs 只在其"所属渲染帧"派发 (与旧序一致, 语义零变化)。

纯逻辑零依赖 (无 engine import), tests 单测直调。
★B7b 退役 (2026-10-16): 删 LOOM_NO_FRAMEBUF 环境逃生门 (A/B 对拍门);
  开关由设置面 frame_buffer_tps / frame_buffer_fps 控制。
"""
import time


class FrameBufferLedger:
    """逻辑帧预取记账器 (无数据搬运, 只记账 + 预算控制)."""

    def __init__(self, max_depth=2):
        # 深度 = 最多提前几个逻辑帧 (用户设想 "1到两帧"; 2 = 上限)
        self.max_depth = max(1, int(max_depth))
        self.enabled = False
        # 在途预取数: 已提前算好但尚未被 advance 消费的逻辑帧数
        self.outstanding = 0
        # 度量 (engine_metrics 观测面)
        self.hits = 0          # advance 消费预取帧次数 (缓冲命中)
        self.prefetches = 0    # 预取执行总次数
        self.rejected = 0      # 因深度/预算拒绝的预取机会 (观测用)

    # ---------- 开关 (设置面 + 闸门) ----------
    def configure(self, settings, logic_fps):
        """由设置.json 决定开关。闸门: logic_fps >= 30 才可开。
        ★B7b 退役 (2026-10-16): 删 LOOM_NO_FRAMEBUF 环境逃生门。"""
        want = bool(settings.get('frame_buffer_tps', False))
        self.enabled = bool(want and logic_fps >= 30.0)
        if not self.enabled:
            self.reset()
        return self.enabled

    def reset(self):
        """播放边界/开关切换: 清记账 (缓存本体由 engine 既有 reset 语义管)."""
        self.outstanding = 0

    # ---------- 渲染帧尾: 预取决策 ----------
    def should_prefetch(self, budget_s):
        """本渲染帧尾是否再预取一个逻辑帧 (常备成品语义):
        开启 + 未超深度 + 本帧预算富余 → 预取 (不依赖 accumulator 积压 —
        死亡螺旋保险会把积压追平/丢弃, 积压判据永不触发; 常备 1-2 帧成品
        才是缓冲区本义: 尖峰帧到点直接消费, 不重算).
        budget_s: 本渲染帧已消耗墙钟. 超预算红线 12ms = 本帧不富余不预取."""
        if not self.enabled:
            return False
        if self.outstanding >= self.max_depth:
            self.rejected += 1
            return False
        if budget_s > 0.012:            # 预算红线: 渲染帧已花 >12ms = 不富余
            self.rejected += 1
            return False
        return True

    def record_prefetch(self):
        """预取执行后记账."""
        self.outstanding += 1
        self.prefetches += 1

    # ---------- advance 消费端 ----------
    def consume(self):
        """clk.advance 轮到已预取的帧: 记账翻页 (调用方跳过重跑 _logic_frame).
        返回 True = 本帧是预取成品 (命中); False = 正常现算."""
        if self.outstanding > 0:
            self.outstanding -= 1
            self.hits += 1
            return True
        return False

    def metrics(self):
        """观测面 (engine_metrics 汇入): 命中率等."""
        return {
            'enabled': self.enabled,
            'outstanding': self.outstanding,
            'max_depth': self.max_depth,
            'prefetches': self.prefetches,
            'hits': self.hits,
            'rejected': self.rejected,
        }


def ledger_from_settings(settings, logic_fps):
    """设置.json -> Ledger (闸门在 configure; 便捷构造)."""
    led = FrameBufferLedger(max_depth=int(settings.get('frame_buffer_depth', 2)))
    led.configure(settings, logic_fps)
    return led


class RenderFrameBuffer:
    """FPS 缓冲 (渲染帧预画, 2026-09-06 实验二):

    限帧档位 (>=60) 下 _on_tick 帧首有 wait_until 混合等待空窗 (数 ms) —
    本类把这段空闲用于**把下一渲染帧预画进离屏 FBO**, 到节拍点 paintGL
    直接 blit 上屏 (零重画). 相机/输入仍按节拍点采样 (预画内容与正常画
    一致, 只是提前了等待时长), 平均负载饱和 (等待空窗=0) 时自然不预画.

    与 TPS 缓冲 (FrameBufferLedger) 完全独立: 各自闸门/开关/度量.
    预画走 engine.render 的"纯渲染路径" — 逻辑推进跳过 (_advanced 标记),
    GL 状态由 render 自身建立 (与正常帧同一管线, 无额外状态假设).

    闸门 (用户定案 2026-09-06): fps_limit ∈ {60,90,120,240} 才可开
    (无上限=画一帧显一帧无节拍; auto 由 resolve 时换算为数值再判).
    """

    def __init__(self):
        self.enabled = False
        self.fps_limit = None          # 已解析档位 (数值 or 'unlimited')
        # 离屏画布 (engine 持 GL ctx; 惰性建, 尺寸跟随)
        self._fb = None
        self._fbo = None
        self._depth = None             # 深度附件 (预画需要真实深度测试)
        self._size = (0, 0)
        # 2026-11-07 P1 (Q8=A): 预画必须真正落到离屏 FBO. e.render 内部通过
        # engine._screen_fb() 绑定渲染目标; begin() 需要临时把 engine 的
        # _external_fb 指向本 FBO, commit/abort 再恢复.
        self._engine = None
        self._prev_external = None     # (external_ctx, external_fb) 恢复用
        # 状态机: idle(无预画) -> ready(预画完成待 blit)
        self.state = 'idle'
        # 度量
        self.preframes = 0             # 预画次数
        self.blit_hits = 0             # 预画被消费 (blit 上屏) 次数
        self.rejected = 0              # 因预算/开关放弃的预画机会

    # ---------- 开关 ----------
    def configure(self, settings, fps_limit):
        """fps_limit: 已解析档位 ('auto' 已换算). 闸门 >=60 且非 unlimited。
        ★B7b 退役 (2026-10-16): 删 LOOM_NO_FRAMEBUF 环境逃生门。"""
        self.fps_limit = fps_limit
        want = bool(settings.get('frame_buffer_fps', False))
        try:
            ok = want and fps_limit not in (None, 'unlimited') \
                and int(fps_limit) >= 60
        except (TypeError, ValueError):
            ok = False
        self.enabled = ok
        if not ok:
            self.state = 'idle'
            self._release()
        return ok

    def reset(self):
        """播放边界: 预画作废 (下一节拍正常画)."""
        self.state = 'idle'

    # ---------- 预画决策 ----------
    def should_preframe(self, now, tick_target):
        """等待空窗足够 (距节拍点 > 3ms) 且当前无在途预画."""
        if not self.enabled or self.state != 'idle':
            return False
        if tick_target is None:
            return False
        if tick_target - now < 0.003:  # 空窗 <3ms: 预画来不及, 放弃
            self.rejected += 1
            return False
        return True

    # ---------- GL 资源 (engine 侧驱动) ----------
    def ensure_canvas(self, ctx, w, h):
        """离屏画布 (RGB + 深度), 尺寸变化重建.
        2026-11-07 Q8=A: 旧实现只有颜色附件 -> 预画帧无深度缓冲, 深度测试
        失效 (近处物体被远处覆盖/黑帧). 补 depth renderbuffer 附件."""
        if self._fb is not None and self._size == (w, h):
            return
        self._release()
        self._fb = ctx.texture((w, h), 4, dtype='f1')
        self._fb.filter = (3553, 3553)  # GL_LINEAR
        depth = None
        try:
            depth = ctx.depth_renderbuffer((w, h))
        except Exception:
            try:
                depth = ctx.depth_texture((w, h))
            except Exception:
                depth = None           # 测试桩/旧 moderngl: 无深度附件也不崩
        self._depth = depth
        kwargs = {'color_attachments': [self._fb]}
        if depth is not None:
            kwargs['depth_attachment'] = depth
        self._fbo = ctx.framebuffer(**kwargs)
        self._size = (w, h)

    def _resolve_engine(self, ctx):
        """找到持有本缓冲的引擎 (engine.__init__ 只 new 本对象, 未回传引用).

        优先按 _render_buf is self 精确匹配; 退化按 ctx 身份匹配. 只在 begin
        时惰性解析, 无额外生命周期假设.
        """
        if self._engine is not None:
            return self._engine
        try:
            from engine import GLEngine
            live = [r() for r in tuple(getattr(GLEngine, '_LIVE_INSTANCES', ()))]
            for e in live:
                if e is not None and getattr(e, '_render_buf', None) is self:
                    self._engine = e
                    return e
            for e in live:
                if e is not None and getattr(e, 'ctx', None) is ctx:
                    self._engine = e
                    return e
        except Exception:
            pass
        return None

    def _restore_external_fb(self):
        """恢复引擎渲染目标 (预画把 _external_fb 临时指向离屏 FBO)."""
        if self._engine is not None and self._prev_external is not None:
            ext_ctx, ext_fb = self._prev_external
            try:
                if ext_ctx is not None:
                    self._engine._external_ctx = ext_ctx
                self._engine._external_fb = ext_fb
            except Exception:
                pass
        self._prev_external = None

    def begin(self, ctx, w, h, engine=None):
        """预画开始: 绑定离屏 FBO + 临时重定向引擎渲染目标. 返回 True = 可以画.

        2026-11-07 Q8=A: e.render 内部经 engine._screen_fb() 绑定 widget FBO,
        旧 begin 只 use() 离屏 FBO -> 实际画到屏幕, 离屏空白, 下一拍 blit
        空白 = 黑帧. 这里在渲染期间把 engine._external_fb 指向离屏 FBO.
        """
        if not self.enabled:
            return False
        self.ensure_canvas(ctx, w, h)
        eng = engine if engine is not None else self._resolve_engine(ctx)
        if eng is not None:
            self._engine = eng
        self._prev_external = None
        if eng is not None:
            self._prev_external = (getattr(eng, '_external_ctx', None),
                                   getattr(eng, '_external_fb', None))
            try:
                eng._external_ctx = True      # 强制走 _screen_fb() 分支
                eng._external_fb = self._fbo
            except Exception:
                self._prev_external = None
        self._fbo.use()
        try:
            ctx.viewport = (0, 0, w, h)
            ctx.scissor = None
        except Exception:
            pass
        try:
            ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        except TypeError:
            try:
                ctx.clear(0.0, 0.0, 0.0, 1.0)
            except Exception:
                pass
        return True

    def commit(self):
        """预画完成 → ready (等待节拍点消费). 恢复引擎渲染目标."""
        if self.enabled and self._fbo is not None:
            self.state = 'ready'
            self.preframes += 1
        self._restore_external_fb()

    def abort(self):
        """预画中断 (异常/resize): 作废回 idle. 恢复引擎渲染目标."""
        self.state = 'idle'
        self._restore_external_fb()

    # ---------- 消费 ----------
    def has_ready(self):
        return self.state == 'ready' and self._fbo is not None

    def blit(self, ctx, target_fb):
        """预画帧整块上屏 (目标 = widget FBO). 只拷颜色不拷深度 (上屏即终帧).
        返回 True = 成功 (调用方跳过整帧重画)."""
        if not self.has_ready():
            return False
        ctx.copy_framebuffer(target_fb, self._fbo)
        self.blit_hits += 1
        self.state = 'idle'
        return True

    def _release(self):
        # 预画中途释放: 先恢复引擎原渲染目标 (若 begin 已临时改写)
        self._restore_external_fb()
        # 引擎若仍指向本 FBO, 摘掉引用防悬空绑定
        if self._engine is not None and \
                getattr(self._engine, '_external_fb', None) is self._fbo:
            try:
                self._engine._external_fb = None
            except Exception:
                pass
        if self._fbo is not None:
            try:
                self._fbo.release()
            except Exception:
                pass
            self._fbo = None
        if self._depth is not None:
            try:
                self._depth.release()
            except Exception:
                pass
            self._depth = None
        if self._fb is not None:
            try:
                self._fb.release()
            except Exception:
                pass
            self._fb = None
        self._size = (0, 0)

    def metrics(self):
        return {
            'enabled': self.enabled,
            'fps_limit': self.fps_limit,
            'state': self.state,
            'preframes': self.preframes,
            'blit_hits': self.blit_hits,
            'rejected': self.rejected,
        }
