# -*- coding: utf-8 -*-
"""remote_launch.py — 播放器远程模式三态（off / on / auto）的**唯一实现**。

Q-B7-55-1（2026-11-22，agent-75）。背景：
  LOOM_REMOTE_MODE 的入口层三态收口原先只在 Loom.py 的播放分支
  （_launch_player）；build_entry.py 的 --run / 游戏配置.json 播放分支没有
  同等处理 → 同一份 env + argv 在源码入口与编译入口的**执行面**不同
  （后端**决策**面已由 B7-54 同源收口，见 Q-B7-54-1）。本模块把三态逻辑
  抽成唯一一份，Loom.py 与 build_entry.py 都只做薄转调，不允许再有第二份。

本模块负责（规则 5.5：全仓唯一实现）:
  1) REMOTE_ON_VALUES / remote_mode()  —— 取值集合 + 三态归一；
  2) install_present_watch()          —— auto 模式装"上屏健康监视"（判据/阈值
     仍在引擎 loom_render.should_fallback_remote，本模块不复制）；
  3) launch_native() / launch_player() —— 三态执行面收口（阻塞启动）。

依赖方向（无 import 环）:
  Loom.py / build_entry.py -> hostenv.remote_launch -> run_player（函数内惰性 import）
  run_player -> hostenv.backend_guard（模块级）；本模块 module 级只 import os/sys，
  不 import run_player，也不 import Loom.py —— hostenv 不会反向依赖入口层。
  hostenv/__init__ 不 re-export 本模块（入口按全名 import hostenv.remote_launch，
  避免 hostenv 包初始化时把入口依赖带进来）。
"""
import os
import sys

# 环境变量名与"算 on"的取值集合（全仓唯一一份；未知值按 off，保持旧语义）。
REMOTE_MODE_ENV = 'LOOM_REMOTE_MODE'
REMOTE_ON_VALUES = ('1', 'on', 'true', 'yes', 'remote')
REMOTE_MODES = ('off', 'on', 'auto')


def remote_mode(environ=None):
    """归一 LOOM_REMOTE_MODE -> 'off' | 'on' | 'auto'。

    environ 仅测试注入用（传 dict）；缺省读进程环境 os.environ。
    未知值 / 空值 → 'off'（与 B7-54 前 Loom.py 逐位一致）。
    """
    env = os.environ if environ is None else environ
    v = (env.get(REMOTE_MODE_ENV) or '').strip().lower()
    if v == 'auto':
        return 'auto'
    if v in REMOTE_ON_VALUES:
        return 'on'
    return 'off'


def install_present_watch(threshold=3):
    """auto 模式: 装一个上屏健康监视，命中引擎判据后让原生循环退出。

    为什么包在 PlayerApp.run 上: 原生播放是**阻塞**调用 (run_backend -> eng.run())，
    入口层拿不到引擎实例；而 present 健康是引擎实例态 (loom_render.present_health /
    should_fallback_remote)。这里只做"观测 + 请求退出"——判据、阈值、计数全在引擎，
    本函数不复制。返回 state dict，调用方据此决定是否重启为 remote。
    """
    state = {'fallback': False, 'streak': 0, 'last_error': None}
    try:
        import threading
        from runtime import PlayerApp
    except Exception as e:
        print('[remote] auto: 无法安装上屏健康监视 (%r) -> 按原生模式运行' % (e,))
        return state
    if getattr(PlayerApp, '_loom_present_watch_installed', False):
        return state
    orig_run = PlayerApp.run

    def run(self, *a, **k):
        stop = threading.Event()

        def _watch():
            while not stop.is_set():
                try:
                    if self.should_fallback_remote(threshold):
                        h = self.present_health()
                        state['fallback'] = True
                        state['streak'] = h.get('fail_streak')
                        state['last_error'] = h.get('last_error')
                        # 结束原生渲染循环 -> 回到入口层做一次 remote 重启。
                        # 先等循环真正起来（run() 开头会 self._running=True），
                        # 否则起跑竞态里这一下会被覆盖，窗口就再也收不掉。
                        while not stop.is_set():
                            try:
                                if getattr(self, '_running', False):
                                    self._running = False
                                    return
                            except Exception:
                                return
                            stop.wait(0.02)
                        return
                except Exception:
                    return          # 引擎不支持下屏健康 (无 _present_*) -> 不监视
                stop.wait(0.1)   # 上屏失败后尽快收口 (白屏停留 <=100ms 级)

        threading.Thread(target=_watch, name='loom-present-watch',
                         daemon=True).start()
        try:
            return orig_run(self, *a, **k)
        finally:
            stop.set()

    PlayerApp.run = run
    PlayerApp._loom_present_watch_installed = True
    return state


def launch_native(scene, width=1280, height=800, argv=None):
    """原生 present 启动（--backend > 设置 render_api > 默认）。

    后端解析 / 选择 / 启动仍走 run_player 唯一事实源
    （parse_backend_arg / resolve_backend / run_backend），本模块不复制。
    """
    from run_player import parse_backend_arg, resolve_backend, run_backend
    cli = parse_backend_arg(sys.argv if argv is None else argv)
    run_backend(resolve_backend(cli), scene, width=width, height=height,
                explicit=(cli is not None))


def launch_player(scene, width=1280, height=800, argv=None):
    """按 --backend > 设置 render_api > 默认 的统一策略启动播放器（三态收口）。

    LOOM_REMOTE_MODE:
      · on/1  (离屏 GL + Qt 窗口白屏兜底) 强制 GL —— 该模式本身就是"GL 不可见时
        改走离屏读回", 与 Vulkan 无关, 必须优先（2026-11-07 scan_11 P-07: 该优先
        规则必须在**本函数体**里实现, 否则"游戏配置.json 双击启动"那条路径没有兜底）。
      · auto  (2026-11-09 E2): 先按原生 present 启动; 若引擎判 should_fallback_remote(3)
        为真（连续上屏失败），**重启一次**为 on 等价路径并打印原因。
      · off/0 (默认): 原生启动, 旧行为。

    显式 --backend 由 parse_backend_arg 判定, 交给 run_player 的后端策略
    （Q6: 显式 vulkan 失败只报错不改写设置; 设置/默认走到 vulkan 失败则把
    设置回退成 opengl 并崩一次）。
    """
    mode = remote_mode()
    if mode == 'on':
        from loom_player_window import run_player_window
        run_player_window(scene, width=width, height=height)
        return
    if mode != 'auto':
        launch_native(scene, width, height, argv=argv)
        return
    # ---- auto: 原生优先, 只在引擎判定失败后降级一次 ----
    state = install_present_watch(3)
    launch_native(scene, width, height, argv=argv)
    if not state.get('fallback'):
        return
    print('[remote] 原生上屏连续失败 %s 次 (最近错误: %r) -> 自动降级为离屏回读'
          ' (等价于 LOOM_REMOTE_MODE=1), 本次只重启一次'
          % (state.get('streak'), state.get('last_error')))
    from loom_player_window import run_player_window
    run_player_window(scene, width=width, height=height)
