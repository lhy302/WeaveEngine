# -*- coding: utf-8 -*-
"""test_mouse_lock_parity.py — P2 面「鼠标锁定与光标捕获」两端对拍门（真窗口，2026-11-18）。

人类判据（docs/guides/开发要求_后端API一致_JVM模型.md 唯一上位判据）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

本门验什么（Q-B7-37-1 P2）：**同一串**鼠标锁定/解锁/移动输入喂进两端**生产入口**，
逐项比对可观察结果（不是"各自为 True"）。十二组（①~⑦ = P2 原面；⑧~⑪ = F-1/F-2/F-6/F-7；
⑫ = Q-B7-40-1 打包播放器路径）：
  ① 状态位翻转      set_mouse_locked(True/False) / toggle_mouse_locked() 后
                    (mouse_locked, mouse_unlock_requested, 光标捕获位) 序列逐项相等
  ② 策略闸门        mouse_lock_allowed=False 时 F11 / 解锁键(Tab) / set_mouse_locked(True)
                    都不得锁定（玩家点了没反应 = 两端同样没反应，光标捕获位也不得翻）
  ③ 解锁请求链      mouse_unlock_requested 置位/消费序列（Tab→requested→apply→locked；
                    松开沿不重复翻转；Esc 不碰鼠标锁——两端一致）
  ④ 光标位置与增量  同一串光标事件经两端生产回调写入：mouse_pos 序列一致（含锁定期间）；
                    帧首结算后 mouse_rel 序列一致；解锁保持旧值（防突跳）、回锁重锚 (0,0)
  ⑤ 暂停期行为      logic_paused 时鼠标增量既不结算也不累积（B6 契约：mouse_rel 只能是
                    "本帧"增量）——两端一致；恢复后无积压
  ⑥ 键盘解锁键 Tab  按住 Tab 跨帧轮询解锁（P1 门 test_input_chain_parity ⑤ 的回归锚）
  ⑦ 暂停期解锁键    F9 暂停期间按解锁键（Tab）两端都必须能解锁（F-3）；按住跨帧
                    不得重复翻转（VK 一帧内 poll 两次 = 暂停分支 + 渲染帧采样，
                    GL 宿主路径也可能 advance_logic + render 同帧各 poll 一次）
  ⑧ F-6 mouse_pos   两端都有 int 像素成员 mouse_pos；同一串光标输入（未锁定/锁定/
                    解锁后三态）逐值相等；不是转发宿主桥 float pos
  ⑨ F-1 返回值      set_mouse_locked / toggle_mouse_locked 的返回值序列两端逐项相等
                    （含"不允许锁被拒绝"那两条 + 生产播放器守卫路径）
  ⑩ F-2 幂等        锁定中连续 3 帧重申 set_mouse_locked(True)：mouse_rel 不断流、
                    序列逐项相等（旧 VK 每帧都断流成 (0,0)）
  ⑪ F-7 两方向      set_mouse_lock_allowed(True)/(False) 两个方向后
                    (locked, requested, 捕获位) 三元组两端逐项相等
  ⑫ 打包播放器路径  runtime.PlayerApp（--run / 游戏包 opengl / build_entry 的生产入口）
                    与 GLEngine / VK **三端**返回值序列逐项相等；被拒分支必须落地后端
                    （旧 PlayerApp 恒 None + 早退不释放光标 —— Q-B7-40-1）

两端生产入口（真窗口，不拼假对象；§5 反模式 8）：
  GL : engine.GLEngine(640,400) 自建 GLFW 窗口（loom_glfw_window._init_glfw_window）
       · 键事件   → EngineCore.handle_key_event（内核 S1 唯一入口，两端同一份）
       · 光标事件 → 生产回调 loom_glfw_window._on_cursor_pos_cb（user_pointer 已由
                    _init_glfw_window:232 绑定；与 GLFW 投递同一函数）
       · 增量结算 → 生产事件泵 eng._handle_events()（_update_mouse_rel 是 GL 的结算点；
                    VK 的结算点在 advance_logic 帧首 consume_mouse_input —— 分工不同、
                    节奏必须一致，这正是本门要钉的）
       · 脚本 API → loom_input.InputMixin（set_mouse_locked/toggle/poll_unlock/...）
  VK : scene_driver.SceneDriver + 真 GLFW(NO_API) 窗口句柄经 driver._vk_glfw_window 注入
       （= vk_player._register_input:523-524 的真实注入点，fullscreen 门同款）
       · 键事件   → 同上（内核唯一入口）
       · 光标事件 → vk_ui.UIInputBridge.on_cursor（= vk_player._on_cursor:558-562 的全部内容）
       · 帧首     → vk_player.draw:643-668 逐行镜像（begin_frame → wants_camera 门控
                    feed_mouse_rel → advance_logic（帧首 consume_mouse_input 结算）→
                    poll_unlock_frame）——镜像保真由结构段源码锚点断言守住
       · 锁定回调 → vk_player._apply_cursor_mode:590-606 逐行镜像（_prev 重锚 +
                    runtime.apply_mouse_lock_backend —— 与 GL 播放器同一份后端落地工具）
       · 脚本 API → SceneDriver.set_mouse_locked / toggle_mouse_locked / ...
  GL 播放器（⑫）: runtime.PlayerApp(None, 640, 400, scene_data=空场景) —— **玩家实际
       发布**的打包游戏入口（build_entry / game_player / run_player 全走它）。它与
       GLEngine 必须逐项同值，否则"编辑器能跑、打包版不能"（本组就是这条的牙）。

夹具保真（§5 反模式 8 的牙）：桥必须是生产类 vk_ui.UIInputBridge 且按生产构造式
（vk_player.py:367 UIInputBridge(getattr(driver,'ui',None))）包 driver.ui；两端窗口都是
真 GLFW 句柄；帧首/回调镜像锚点有源码断言（结构段）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何"差不多"/阈值/容差都不许。

修前红证据（R1，HEAD=3d87dce / d7b1404 实测，原文见提交信息与交付报告）：
  R1 组⑤红：GL 暂停期 mouse_rel 逐帧结算新值 ((40,20),(20,-10),(-10,15))，VK 恒 (0,0)
    —— B6「暂停期既不结算也不累积」GL 侧未实现；用户可感知路径：F9 暂停 + F10 单步时
    脚本读 mouse_rel（GL 视角转 / VK 不转）。
    缺陷归属（只报告不修）：loom_glfw_window._update_mouse_rel（无 logic_paused 门控；
    run 循环 loom_render.py:1313 暂停期照跑泵）+ engine.GLEngine.advance_logic 暂停分支
    （engine.py:1446-1459 不清 mouse_rel）；VK 参照实现 scene_driver.py:1059-1062。

R1/F-3 修后（2026-11-18，本门 **37 条全绿**；修前 = 30 绿 / 7 红 = ⑤ + ⑦×2 +
结构锚点×3 + ④ 偶发 1 次）：
  · R1（Q-B7-39-1）：GL 泵结算点 `loom_glfw_window._update_mouse_rel` 加逻辑暂停门控
    —— 暂停期**只推进 _prev_cursor 基线、不结算 mouse_rel**（不结算不累积，恢复首帧
    只拿"恢复这一帧"的位移）；`engine.advance_logic` 暂停分支与 VK 逐行同语义
    清 `mouse_rel=(0,0)`。
  · F-3（Q-B7-39-4）：GL **三条暂停分支各 poll 一次**解锁键 —— `engine.advance_logic`
    暂停分支（宿主同步路径）/ `loom_render.render` 暂停分支（GLFW run() 玩家主循环，
    render 自己推进时钟、不经过 advance_logic）/ `loom_logic_thread` 暂停分支
    （Qt 宿主异步播放态）。按下沿判定（`_unlock_key_prev`）保证同帧重复 poll 不翻两次。
  · **未改 VK**（VK 是对的）；**未动 F-1/F-2/F-6/F-7**（另派单）。
F-1/F-2/F-6/F-7 修后（2026-11-18，Q-B7-40，**只改 VK 侧**）：本门 **52 条全绿**
（37 条原样 + 15 条新增，原有 37 条一条未动、基线未移）；修前 4 条各自单独回退
（gen.py 逐项开关，非读码推断）全部判红，红原文见交付报告与提交信息。
  · 组⑦ 的帧形：GL = 泵（物理键快照）→ 本帧 KEYDOWN → render；VK = 渲染帧镜像。
    泵每帧用 glfw.get_key 重建 script_keys，故"本帧按键"必须排在泵之后注入。

F-1/F-2/F-6/F-7 修后（2026-11-18，Q-B7-40；**只改 VK 侧**，GL 一行未动）：
  · F-1（组⑨）：VK set_mouse_locked 补 `return not denied`（True=已应用/已解锁，
    False=因"不允许锁"被拒绝）、toggle_mouse_locked 两条分支补 True/False；
    vk_player._install_lock_policy_guard 的守卫分支也补 `return False`
    （旧实现 return None —— 生产播放器路径同样会让脚本 if 两端走不同分支）。
    修前红：GL=[False,True,True,True,True,True,True,False,True]
            VK=[None,None,None,None,None,None,None,None,None]
  · F-2（组⑩）：VK set_mouse_locked **状态未变化时不触发 on_mouse_lock_changed**
    （新增 `_lock_backend_applied` 记录"后端已落地的那个状态"；启动即锁时
    __init__ 已按策略写好 mouse_locked，靠这一条例外保证光标模式仍会落地）。
    修前红：锁定中连续 3 帧重申 set(True)，GL mouse_rel=[(10,5),(10,5),(10,5)]、
            VK=[(0,0),(0,0),(0,0)]（断流一帧 = 每帧都断）。
  · F-6（组⑧）：VK 补 `mouse_pos` 成员 —— **int 像素元组**，初值 (0,0)，唯一更新点
    `SceneDriver._on_cursor_event`（由 vk_player._on_cursor = GLFW 光标回调调用，
    与 GL loom_glfw_window._on_cursor_pos_cb 同源同语义 `(int(x), int(y))`）。
    **不是**转发宿主桥 vk_ui.UIInputBridge.pos（那是 float，直接暴露会造出新的
    float vs int 差异）。修前红：GL=(100, 60) VK=None（脚本读 = AttributeError）。
  · F-7（组⑪）：VK set_mouse_lock_allowed 对齐 GL 两个方向 —— True→立即按
    [特殊场景 | 玩家解锁意图] 重算并应用；False→清 mouse_unlock_requested + 解锁。
    修前红：set_mouse_lock_allowed(True) 后 GL=(True,False,True) VK=(False,False,False)；
            set_mouse_lock_allowed(False) 后 GL=(False,False,False) VK=(False,True,False)。

历史附加发现（保留原文，F-1/F-2/F-6/F-7 四条已在上面结清）：
  F-3 F9 暂停期间按解锁键：VK 解锁（advance_logic 暂停分支自带 poll_unlock
      + vk_player 渲染帧采样，双保险）；GL 暂停帧**无人轮询**（GL 唯一轮询点 =
      update_scripts 首行 engine.py:995，暂停时不执行）——同一串输入两端结果不同。
      → **已修（2026-11-18，组⑦ 已加牙；见下「R1/F-3 修后」）**。
  F-5 ShowCursor 计数：GL _apply_cursor_backend 每次 set_mouse_locked 调用都无条件
      ShowCursor（loom_input.py:443，含状态未变的幂等调用）；VK apply_mouse_lock_backend
      同款（runtime.py:88/92）——反复重申锁定后解锁，光标显示计数不归零（两端同病，
      对拍中立，属共享质量问题）。
  F-6（**已修，2026-11-18 人类裁决「用户 API，VK端补全」**）: 原状 = GL 引擎有
      engine.mouse_pos（int 元组）；VK SceneDriver 无此成员（等观测量只在宿主桥
      vk_ui.UIInputBridge.pos，float 元组）→ 脚本读 engine.mouse_pos 在 VK 上
      AttributeError。修法见上「F-1/F-2/F-6/F-7 修后 · F-6」。
  F-7（**已修**）: 原状 = GL True→立即按意图应用（锁定）、False→清 requested + 解锁
      （loom_input.py:347-365，test_unlock_key I 段钉过 GL）；VK True→什么都不做、
      False→只解锁**不清 requested**（旧 scene_driver.py:1637-1647）。

Q-B7-40-1 修后（2026-11-18，**只改 GL 侧 runtime.py + 本门**，VK 一行未动）：
  本门 **62 条全绿**（原 52 条一条未动、基线未移 + 组⑫ 新增 10 条）。
  · 修法: runtime.PlayerApp.set_mouse_locked 不再自带实现，改为**委托**
    InputMixin.set_mouse_locked（`return super().set_mouse_locked(locked)`）——
    拒绝闸门 / 被拒先解锁 / 后端光标落地 / 状态变化才打日志全部只有一份
    （loom_input.py:367-403）。PlayerApp 的 toggle_mouse_locked /
    set_mouse_lock_allowed 本来就继承 InputMixin，本次**未新增覆盖**。
  · 修前红（探针 Loom/tests/_tmp/probe_q_b7_40_1.py，三端同一串脚本 API）:
      allowed=False set(True)   GLEngine=False PlayerApp=None SceneDriver=False
      allowed=True  set(True)   GLEngine=True  PlayerApp=None SceneDriver=True
      幂等重申 set(True)        GLEngine=True  PlayerApp=None SceneDriver=True
      set(False)                GLEngine=True  PlayerApp=None SceneDriver=True
      幂等重申 set(False)       GLEngine=True  PlayerApp=None SceneDriver=True
    被拒分支（锁定中直接关闸再 set(True)）: 捕获位 GLEngine=False PlayerApp=True
      SceneDriver=False —— PlayerApp 早退没落地后端，光标仍被捕获。
  · 修后绿: 同上九行三端逐项相等（全 bool）；被拒后捕获位三端都 False。
  · 用户可感知路径: 打包游戏（用户真正发布的那个 exe）里 `if engine.set_mouse_locked(True):`
    以前恒走 else；锁定中被拒时"光标出来了但动不了"。

结构断言改名防护（B7-16 复查 P0-1 教训）：结构段用**递归**扫描定位生产文件（排除
tests/），并同时覆盖当前名与历史名（_poll_unlock_local 必须不存在 = 批2已删的旧拷贝）。

Q-B7-43-1 修后（2026-11-18，**只改本门夹具 + 注释**，业务代码一行未动、断言表达式一字未改）：
  · 症状：本门 ④/⑤/⑩ 组「吸收帧」偶发假红，签名
    GL=((300,150),(20,50)) VK=((300,150),(0,0))（= GL 多出一份假位移）。
  · 根因（与 test_ui_hit_parity 同一根因，实测日志见提交信息）：glfw.set_cursor_pos
    底层是 Win32 SetCursorPos，**物理光标的落地是异步的**；而 GL 的增量结算点
    loom_glfw_window._update_mouse_rel:535 读的就是 glfw.get_cursor_pos。修前 gl_frame
    是「set_cursor_pos -> _handle_events（结算）」，少了「等落点真的生效」这一拍 ——
    结算读到**上一个**落点，于是本帧位移多算/少算一份。恰好 ④/⑤/⑩ 的「吸收帧」
    （刚切 CURSOR_DISABLED、_prev_cursor 被重锚成 None 的那一帧）把这份假增量整份
    记进 mouse_rel，VK 侧同一帧是 (0,0) → 对拍红。
  · 修法：新增夹具函数 settle_cursor()（见其注释）—— 结算前先「落点可见 + 队列静默」。
    只建输入前提，不改任何 check/seq_check 的表达式、不放宽任何语义、不加重跑逻辑。
  · 为什么没选「单窗口复用」：GL 侧句柄由 engine.GLEngine 构造时自建（带 OpenGL
    上下文），VK 侧要 NO_API 句柄；复用同一句柄要么改业务代码（禁止），要么让两端共用
    同一个 CURSOR 模式 —— 那本门 ①~③/⑨/⑪/⑫ 的「两端状态位各自翻转」就测不成了。
  · 有牙证明（造业务回归仍必须红）：把 VK 的 vk_ui.UIInputBridge.ui_active 改回跨帧
    判据（恢复 _pressed_elem 跨帧持按）→ 本门 ⑧ 组当场红；还原后绿。见提交信息原文。
"""
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import os
import sys
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import glfw                                                      # noqa: E402
import pygame                                                    # noqa: E402

import engine as E                                               # noqa: E402
import scene_driver as SD                                        # noqa: E402
import vk_player                                                 # noqa: E402
import vk_ui                                                     # noqa: E402  Q-B7-34-1: 夹具用生产那个桥类
import runtime                                                   # noqa: E402  两端共用的后端落地工具
from loom_input import DEFAULT_ACTIONS                           # noqa: E402
from loom_glfw_window import _on_cursor_pos_cb                   # noqa: E402  GL 生产光标回调

ok = True
_PAIRS = []                                                      # 收尾统一释放光标捕获
_PLAYER_APPS = []                    # ⑫ 打包播放器（PlayerApp）实例，收尾统一释放


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


FRAME_DT = 1 / 120.0          # 与 run_all 其它门一致的对拍帧步（只影响结算节奏，不影响判定）
KNOWN_DIFFS = []              # 已知差异登记表：必须为空；发现差异 = 红并报告，不许登记糊过去


# ============================ 结构段：递归源码扫描 ============================

def _find_src(fname):
    """递归找生产文件（排除 tests/ 下的探针与备份拷贝）。恰好一份才算数。"""
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        for skip in ('tests', '__pycache__'):
            if skip in dirnames:
                dirnames.remove(skip)
        if fname in filenames:
            hits.append(os.path.join(dirpath, fname))
    if len(hits) != 1:
        return None, hits
    with open(hits[0], 'r', encoding='utf-8') as f:
        return f.read(), hits


def src_has(fname, needle, must=True, why=''):
    src, hits = _find_src(fname)
    if src is None:
        check('结构：%s 定位（递归，排除 tests/）' % fname, False, '命中 %d 份: %s' % (len(hits), hits))
        return
    found = needle in src
    check('结构：%s %s %r' % (fname, '含' if must else '不含', needle), found if must else (not found), why)


print("=== 〇. 结构：唯一实现 / 镜像锚点 / 退出释放 / 登记表 ===")
# 解锁键唯一实现（D6=A）：VK 不许复制切换语义 —— 当前名与历史名都查
src_has('vk_player.py', 'def _poll_mouse_unlock_key', False,
        'VK 播放器不得自写解锁键轮询（委托 engine.GLEngine 唯一实现）')
src_has('scene_driver.py', 'def _poll_unlock_local', False,
        '批2已删的历史拷贝 _poll_unlock_local 不得回来（B7 之前的双实现病灶；docstring 提及不算）')
src_has('scene_driver.py', 'GLEngine._poll_mouse_unlock_key', True,
        'SceneDriver._poll_mouse_unlock_key 只做委托（唯一实现）')
# 本门帧首/回调镜像的生产锚点（镜像漂移 = 门失真，必须当场红）
src_has('vk_player.py', 'ui_bridge.begin_frame()', True, '帧首结算入口仍在')
src_has('vk_player.py', 'driver.feed_mouse_rel(', True, '光标增量生产喂入点仍在')
src_has('vk_player.py', 'poll_unlock_frame(driver)', True, '渲染帧解锁键采样仍在')
src_has('loom_glfw_window.py', 'def _update_mouse_rel', True, 'GL 泵结算点仍在')
src_has('loom_glfw_window.py', 'self.mouse_rel = (int(dx), int(dy))', True,
        'GL 帧增量 int 截断语义仍在')
# 退出释放（锁定态不得带出进程）
src_has('loom_render.py', 'self.set_mouse_locked(False)', True,
        'GL run() finally 退出释放鼠标（loom_render run 收尾）')
src_has('vk_player.py', '_release_cursor', True,
        'VK 渲染循环 finally 退出释放鼠标')
# R1/F-3 修后锚点（暂停期门控的唯一实现点；漂移 = 门失真，必须当场红）
src_has('loom_glfw_window.py', '_logic_paused_state', True,
        'GL 泵结算点的逻辑暂停门控仍在（R1：暂停不结算 mouse_rel）')
src_has('engine.py', 'self.poll_unlock()', True,
        'GL advance_logic 暂停分支的解锁键轮询仍在（F-3）')
src_has('loom_render.py', 'self.poll_unlock()', True,
        'GL 渲染帧（玩家主循环）暂停期解锁键采样仍在（F-3）')
check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)


# ============================ 夹具（真窗口，生产构造式） ============================

def _mode_disabled(win):
    try:
        return glfw.get_input_mode(win, glfw.CURSOR) == glfw.CURSOR_DISABLED
    except Exception:
        return None


class Pair:
    """一对生产后端 + 各自的生产输入入口（同一串事件喂两边）。"""

    def __init__(self):
        self.gl = E.GLEngine(640, 400)                 # 自建 GLFW 窗口 + 4.3 core 上下文
        self.gl.is_playing = True
        self.gl.actions = dict(DEFAULT_ACTIONS)        # 钉死默认键位：本门不测用户层改键
        self.gl.set_mouse_lock_allowed(False)          # 归零（防机器用户层配置漂移）
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        self.vk_win = glfw.create_window(640, 400, 'Loom VK parity (mouse lock gate)', None, None)
        glfw.window_hint(glfw.CLIENT_API, glfw.OPENGL_API)   # 还原提示，防污染后续 GL 窗口
        self.vk = SD.SceneDriver()
        self.vk.is_playing = True
        self.vk.actions = dict(DEFAULT_ACTIONS)
        # 生产注入点（vk_player._register_input:523-524）：F11 假全屏/光标落地都要这个句柄
        self.vk._vk_glfw_window = self.vk_win
        self.vk._vk_canvas = None
        # Q-B7-34-1：桥必须是生产那个类，构造式与生产逐字相同（vk_player.py:367）
        self.bridge = vk_ui.UIInputBridge(getattr(self.vk, 'ui', None))
        # vk_player._apply_cursor_mode:590-606 逐行镜像（win = 注入的真窗口）
        self._prev = [None]
        self._vk_mode = [None]                 # 最近一次真正落到 VK 窗口上的光标模式

        def _apply_cursor_mode(locked):
            self._prev[0] = None
            _m = bool(locked)
            _changed = self._vk_mode[0] is not _m
            self._vk_mode[0] = _m
            x, y = glfw.get_cursor_pos(self.vk_win)
            self.bridge.on_cursor(x, y)
            runtime.apply_mouse_lock_backend(self.vk_win, bool(locked), tag='VK 播放器')
            if _changed:
                # ★纯测试拓扑伪影隔离（**生产只有一个玩家窗口**）：
                # 本进程里同时活着多对真窗口，任一侧切到 CURSOR_DISABLED 时 GLFW 会把
                # 物理光标挪到该窗口中心（SetCursorPos）—— 这注入一条 raw motion，落进
                # **另一侧** disabled 窗口的虚拟坐标（GLFW virtualCursorPos），于是下一帧
                # glfw.get_cursor_pos 跳一个不可预测的值（本门 ④/⑤ 曾因此偶发红）。
                # 处理: 先排空这条伪影，再把 GL 的增量基线重锚（= 下一帧是吸收帧），
                # 之后两端位移才是"同一串光标输入"的真实结果。
                # **只在真实模式切换时做** —— 状态未变的重复回调不做（那正是 F-2 组⑩
                # 要钉的东西：若这里无条件重锚，F-2 未修也会变绿 = 门被测试自己糊掉）。
                pump(3, 0.02)
                try:
                    self.gl._prev_cursor = None
                except Exception:
                    pass

        self.vk.on_mouse_lock_changed = _apply_cursor_mode
        self.vk.set_mouse_lock_allowed(False)          # 归零
        # 生产不变量：玩家窗口持焦点（玩家点进窗口才玩）。本进程里同时活着多对窗口，
        # 后建的窗会抢走焦点 —— GLFW 3.4 实测：无焦点的 disabled 光标窗口虚拟坐标
        # 不更新（_update_mouse_rel 恒差 0）。夹具把焦点还给 GL 玩家窗口，恢复生产前提。
        glfw.focus_window(self.gl._glfw_win)
        _PAIRS.append(self)

    def allow(self, allowed):
        """两端同一串策略输入（生产脚本 API）。"""
        return (self.gl.set_mouse_lock_allowed(bool(allowed)),
                self.vk.set_mouse_lock_allowed(bool(allowed)))

    def lock(self, locked):
        """两端同一串锁定请求（生产脚本 API）。返回值**不比**（见文件头 F-1）。"""
        self.gl.set_mouse_locked(bool(locked))
        self.vk.set_mouse_locked(bool(locked))

    def toggle(self):
        return (self.gl.toggle_mouse_locked(), self.vk.toggle_mouse_locked())

    def key(self, pg, down=True):
        ev = SimpleNamespace(type='KEYDOWN' if down else 'KEYUP', key=pg, mod=0, unicode='')
        return (self.gl.handle_key_event(ev), self.vk.handle_key_event(ev))

    def poll(self):
        return (self.gl.poll_unlock(), self.vk.poll_unlock())

    def gl_frame(self, x, y):
        """GL 生产帧：物理光标落点 + 生产泵（poll_events + _update_mouse_rel 结算）
        + 生产光标回调（与 GLFW 投递同一函数；手动喂 = 等价事件注入）。"""
        glfw.set_cursor_pos(self.gl._glfw_win, x, y)
        # Q-B7-43-1：物理光标落地是异步的 —— 必须先 settle_cursor() 把落点与消息队列
        # 都排空，再让生产泵结算 mouse_rel（loom_glfw_window._update_mouse_rel:535 读
        # glfw.get_cursor_pos）。修前少了这一拍：结算读到**上一个**落点 → 位移多出一份
        # 假增量，④/⑤/⑩ 组的「吸收帧」偶发红 GL=((300,150),(20,50)) VK=((300,150),(0,0))。
        # 只建输入前提，不动任何断言。
        settle_cursor(self.gl._glfw_win, self.gl, x, y)
        self.gl._handle_events()
        _on_cursor_pos_cb(self.gl._glfw_win, x, y)
        return ((int(self.gl.mouse_pos[0]), int(self.gl.mouse_pos[1])),
                tuple(self.gl.mouse_rel))

    def _cursor(self, x, y):
        """vk_player._on_cursor:558-562 的逐行镜像：宿主桥 float 落点 + F-6 的 int 落点。

        F-6 的 int 落点在驱动侧 `_on_cursor_event`（生产唯一实现，见
        scene_driver._on_cursor_event）。这里用 getattr 取：**未实现时由组⑧ 的断言判红**，
        而不在这里抛 —— 否则一个未实现项会让整道门中断，看不到其它组的证据。
        """
        self.bridge.on_cursor(x, y)
        fn = getattr(self.vk, '_on_cursor_event', None)
        if callable(fn):
            fn(x, y)

    def vk_frame(self, x, y):
        """VK 生产帧：生产光标回调 + vk_player.draw 帧首逐行镜像（643-668）。"""
        self._cursor(x, y)                             # vk_player._on_cursor:558-562 的全部内容
        self.bridge.begin_frame()                      # vk_player.py:643
        _x, _y = self.bridge.pos
        _p = self._prev[0]
        if _p is not None and self.bridge.wants_camera():
            self.vk.feed_mouse_rel(_x - _p[0], _y - _p[1])   # vk_player.py:647-648
        self._prev[0] = (_x, _y)
        self.vk.advance_logic(FRAME_DT)                # vk_player.py:664（结算在其帧首）
        vk_player.poll_unlock_frame(self.vk)           # vk_player.py:668
        return ((int(self.bridge.pos[0]), int(self.bridge.pos[1])),
                tuple(self.vk.mouse_rel))

    def feed(self, x, y):
        return self.gl_frame(x, y), self.vk_frame(x, y)

    def pos(self):
        """两端**脚本可读的光标位置成员**（GL engine.mouse_pos / VK driver.mouse_pos）。

        缺成员返回 None（组⑧ 据此判红）；不做"退回宿主桥 float pos"的容错替代 ——
        那正是 F-6 要禁的假对齐（float vs int 会变成新的两端差异）。
        """
        return (getattr(self.gl, 'mouse_pos', None),
                getattr(self.vk, 'mouse_pos', None))

    def state(self):
        """两端状态位 + 光标捕获位（捕获位经 GLFW API 独立回读，不用引擎自报）。"""
        return (
            (bool(self.gl.mouse_locked), bool(self.gl.mouse_unlock_requested),
             _mode_disabled(self.gl._glfw_win)),
            (bool(self.vk.mouse_locked), bool(self.vk.mouse_unlock_requested),
             _mode_disabled(self.vk_win)),
        )


# ==================== Q-B7-43-1：物理光标落点/消息队列排空协议 ====================

_SETTLED_AT = {}          # id(win) -> 上一次已排空到位的注入点（pyglfw 的 window 不可哈希）


def settle_cursor(win, eng, x, y, maxit=40, dt=0.002, stable=2):
    """把物理光标真的落到 (x,y)，并把这次移动产生的 WM_MOUSEMOVE 全部派发干净。

    **这是夹具的输入前提，不是断言、不是重跑**（不碰任何 check 的表达式，不改任何被测
    语义；只在注入事件之前把「玩家真的把鼠标移到这里了」这个前提建好）。

    为什么必须先做（Q-B7-43-1 修前偶发假红的根因，实测证据见提交信息）：
      glfw.set_cursor_pos 底层是 Win32 SetCursorPos，**物理光标的落地是异步的**：
        · 紧跟着的 glfw.get_cursor_pos（= GetCursorPos + ScreenToClient，读物理光标）
          可能仍回读到**上一个**落点 —— 而生产 _on_mouse_button_cb 正是自己再读一次
          get_cursor_pos 来定 e.mouse_pos（loom_glfw_window.py:657-661），于是「按下
          帧」的 mouse_pos 被写成上一帧的位置 → 命中全落 root。本门 ①/② 组偶发假红的
          签名 GL=('root','root',None,None) 就是它。
        · 上一次 set_cursor_pos 产生的 WM_MOUSEMOVE 还可能排在消息队列里，晚一拍才被
          poll_events 派发，把 e.mouse_pos 覆盖回旧值。
      生产里这两件事都不可能发生：真实玩家的一次移动在 LBUTTONDOWN 之前一定已经投递完
      （Windows 保证同一窗口的鼠标消息相对有序），而且生产只有一个玩家窗口。夹具用
      set_cursor_pos 代替「玩家的手」，就必须先复刻这个顺序，再注入按键/滚轮。
      修前本门用「set_cursor_pos + 两次 poll_events」代替这一步 —— 少的就是这一拍。

    判据（两个阶段合成一个循环）：
      · 窗口内坐标：要求 glfw.get_cursor_pos 与 engine.mouse_pos 都**等于**注入点；
      · 画布外坐标（如 (-50,-50)）：物理光标会被桌面边界钳住，回读永远 != 注入点，
        退而求其次要求「回读已经真的动过（!= 注入前的值，或上一帧就注入的同一坐标）」
        且随后连续 stable 次不再变化（= 这次投递已落地、队列已静默）。
    返回 True = 排空到位；False = 到上限仍未到位（此时照旧往下走，红不红由断言决定 ——
    夹具**不**吞掉任何判定）。
    """
    t = (int(x), int(y))
    try:
        w, h = glfw.get_window_size(win)
        reachable = (0 <= t[0] < int(w)) and (0 <= t[1] < int(h))
        rb0 = tuple(int(v) for v in glfw.get_cursor_pos(win))
    except Exception:
        reachable, rb0 = False, None
    already = _SETTLED_AT.get(id(win)) == t
    ok = 0
    prev = None
    for _ in range(maxit):
        try:
            glfw.poll_events()
        except Exception:
            pass
        try:
            rb = tuple(int(v) for v in glfw.get_cursor_pos(win))
            mp = tuple(getattr(eng, 'mouse_pos', ()))
        except Exception:
            rb, mp = None, None
        if reachable:
            same = (rb == t and mp == t)
            if not same:
                # 切 CURSOR_DISABLED 后的首个轮询，GLFW 3.4 会把虚拟坐标重置为物理
                # 光标位置；这里再落一次 = 玩家把鼠标又移回注入点，直到回读收敛。
                try:
                    glfw.set_cursor_pos(win, x, y)
                except Exception:
                    pass
        else:
            same = ((rb != rb0 or already) and (rb, mp) == prev)
        prev = (rb, mp)
        ok = ok + 1 if same else 0
        if ok >= stable:
            _SETTLED_AT[id(win)] = t
            return True
        time.sleep(dt)
    _SETTLED_AT[id(win)] = t
    return False


def absorb(p, x, y, maxn=8):
    """吸收帧协议（Q-B7-43-1）：光标模式刚切换后的前若干帧只用来「让 GLFW 的虚拟坐标
    初始化到位」，值不进断言。

    实测（2026-11-18，机制探针 tests/_tmp/probe_q_b7_43_1_mech3.py）：切到
    CURSOR_DISABLED 后的**首个**轮询，GLFW 3.4 会把虚拟坐标重新初始化成物理光标位置
    （= 窗口中心附近，多窗测试进程里不可预测），于是那一帧 glfw.get_cursor_pos 与注入点
    不等 → 本帧位移多算一份假增量。修前协议是「固定丢 1 帧」—— 快机器上通常 1 帧就收敛，
    但这一步滞后时假增量就落进被断言的那一帧（④/⑤/⑩ 假红签名
    GL=((300,150),(20,50)) VK=((300,150),(0,0))）。
    现在改成**按条件**丢：一直丢到 glfw 回读到注入点（上限 maxn 帧），再交给断言。
    上限有界，只丢「虚拟坐标还没初始化到位」的帧 —— 不吞任何被测语义：真缺陷会让随后的
    锚帧继续红（⑩ 的「锚帧 mouse_rel 都是 (0,0)」、④ 的「锁定锚帧」都还在断言里）。
    """
    out = None
    for _ in range(maxn):
        out = p.feed(x, y)
        try:
            ok = (tuple(int(v) for v in glfw.get_cursor_pos(p.gl._glfw_win))
                  == (int(x), int(y)))
        except Exception:
            ok = False
        if ok:
            break
    return out


def pump(n=15, dt=0.02):
    """等窗口管理器落地（F11 全屏切换是异步的）。"""
    for _ in range(n):
        try:
            glfw.poll_events()
        except Exception:
            pass
        time.sleep(dt)


def seq_check(title, rows):
    """rows = [(label, gl值, vk值), ...]：逐行比对并打 GL vs VK 对照表。"""
    bad = [(lb, g, v) for (lb, g, v) in rows if g != v]
    for lb, g, v in rows:
        print('    %-26s GL=%-28s VK=%s' % (lb, g, v))
    check(title, not bad,
          '；'.join('%s: GL=%s VK=%s' % (lb, g, v) for lb, g, v in bad[:3])
          if bad else '%d 步逐项相等' % len(rows))


# ============================ ① 状态位翻转 ============================
print()
print("=== ①. 状态位翻转（set_mouse_locked / toggle_mouse_locked；生产脚本 API） ===")
p = Pair()
rows = []

def step(label):
    s = p.state()
    rows.append((label, s[0], s[1]))

p.allow(False)
step('基线 allowed=False')
p.allow(True)
p.lock(False)                      # 两端同串输入归到"允许但未锁"起点
step('allow(True)+set(False)')
p.lock(True)
step('set_mouse_locked(True)')
p.lock(False)
step('set_mouse_locked(False)')
p.toggle()
step('toggle_mouse_locked()#1')
p.toggle()
step('toggle_mouse_locked()#2')
p.lock(False)
step('set_mouse_locked(False)#2')
p.lock(True)
step('set_mouse_locked(True)#2')
p.allow(False)
step('set_mouse_lock_allowed(False)')
seq_check('① 状态位翻转：两端逐项相等（locked/requested/捕获位）', rows)

# ============================ ② 策略闸门（allowed=False） ============================
print()
print("=== ②. 策略闸门：allowed=False 时 F11 / Tab / set(True) 都不得锁定 ===")
p = Pair()
rows = []

def step2(label):
    s = p.state()
    rows.append((label, s[0], s[1]))

p.allow(False)
step2('基线')
p.lock(True)                       # 脚本试图锁 -> 必须被拒
step2('set_mouse_locked(True)')
p.toggle()                         # Tab 语义直调 -> 必须无响应
step2('toggle_mouse_locked()')
p.key(pygame.K_TAB, True)          # 解锁键走内核 -> 轮询必须不翻转
r = p.poll()
check('② Tab 轮询返回两端同值（同一引擎实现）', r[0] == r[1] is False, 'GL=%r VK=%r' % r)
step2('按 Tab + poll_unlock')
p.key(pygame.K_TAB, False)
p.poll()
step2('松 Tab + poll_unlock')
c = p.key(pygame.K_F11, True)      # F11 全屏是全屏门的事；这里只钉它**不得碰鼠标锁**
check('② F11 两端都被内核第①步消费', c == (True, True), 'GL=%r VK=%r' % (c[0], c[1]))
pump()
step2('按 F11（后）')
c = p.key(pygame.K_F11, True)      # 再按一次退出全屏（恢复窗口，卫生）
pump()
step2('再按 F11（退出全屏后）')
check('② F11 一进一出后两端全屏都还原（卫生）',
      bool(p.gl.fullscreen) is False and bool(getattr(p.vk, 'fullscreen', True)) is False,
      'GL=%r VK=%r' % (p.gl.fullscreen, getattr(p.vk, 'fullscreen', None)))
p.key(pygame.K_ESCAPE, True)       # Esc 与鼠标锁无关：两端都必须不碰
step2('按 Esc（后）')
p.key(pygame.K_ESCAPE, False)
seq_check('② 策略闸门：两端全程不锁、光标捕获位不翻', rows)

# ============================ ③ 解锁请求链（Tab 置位/消费） ============================
print()
print("=== ③. 解锁请求链：requested 置位/消费序列（Esc 不碰鼠标锁） ===")
p = Pair()
rows = []

def step3(label):
    s = p.state()
    rows.append((label, s[0], s[1]))

p.allow(True)
p.lock(True)                       # 起点锁定
step3('起点（锁定）')
p.key(pygame.K_TAB, True)
r = p.poll()
check('③ 按下帧 poll 两端都翻转（True）', r == (True, True), 'GL=%r VK=%r' % (r[0], r[1]))
step3('按 Tab + poll（解锁）')
p.key(pygame.K_TAB, False)
r = p.poll()
check('③ 松开帧 poll 两端都不翻转', r == (False, False), 'GL=%r VK=%r' % (r[0], r[1]))
step3('松 Tab + poll')
p.key(pygame.K_TAB, True)
r = p.poll()
check('③ 再按帧 poll 两端都翻转（回锁）', r == (True, True), 'GL=%r VK=%r' % (r[0], r[1]))
step3('再按 Tab + poll（回锁）')
p.key(pygame.K_TAB, False)
p.poll()
step3('再松 Tab + poll')
p.key(pygame.K_ESCAPE, True)       # Esc 只进键快照，不碰锁（两端一致 = 都不碰）
step3('按 Esc（后）')
p.key(pygame.K_ESCAPE, False)
step3('松 Esc（后）')
p.allow(False)                     # 关闸：GL 清 requested + 解锁（VK 只解锁，见文件头 F-7）
p.allow(True)
p.lock(False)                      # 归回"允许但未锁"（两端同串输入）
step3('关闸再开闸 + set(False)')
seq_check('③ 解锁请求链：两端逐项相等', rows)

# ============================ ④ 光标位置与增量 ============================
print()
print("=== ④. 光标位置与增量：同一串光标事件 → pos/rel 序列逐项相等 ===")
p = Pair()
rows = []
p.allow(True)
p.lock(False)
g, v = p.feed(100, 60)
rows.append(('未锁 feed(100,60)', g, v))
g, v = p.feed(140, 62)
rows.append(('未锁 feed(140,62)', g, v))
p.lock(True)
# 吸收帧（Q-B7-43-1：按条件丢到虚拟坐标初始化到位为止，见 absorb() 注释）。
# 生产里不存在该伪影（真实移动连续，两端首帧都由重锚定为 (0,0)）—— 这些帧只建立
# tracking 基线，值打印不进断言。
_ga, _va = absorb(p, 140, 62)
print('    （吸收帧不进断言：GL=%s VK=%s）' % (_ga, _va))
g, v = p.feed(140, 62)
check('④ 锁定后两端光标捕获位都翻（GLFW 回读）',
      _mode_disabled(p.gl._glfw_win) and _mode_disabled(p.vk_win),
      'GL=%r VK=%r' % (_mode_disabled(p.gl._glfw_win), _mode_disabled(p.vk_win)))
rows.append(('锁定锚帧 feed(140,62)', g, v))
g, v = p.feed(210, 85)
rows.append(('锁定 feed(210,85)', g, v))
g, v = p.feed(230, 95)
rows.append(('锁定 feed(230,95)', g, v))
g, v = p.feed(250, 120)
rows.append(('锁定 feed(250,120)', g, v))
p.lock(False)
g, v = p.feed(300, 150)
check('④ 解锁后两端捕获位都释放（GLFW 回读）',
      (not _mode_disabled(p.gl._glfw_win)) and (not _mode_disabled(p.vk_win)),
      'GL=%r VK=%r' % (_mode_disabled(p.gl._glfw_win), _mode_disabled(p.vk_win)))
rows.append(('解锁 feed(300,150)', g, v))
p.lock(True)
absorb(p, 300, 150)                # 吸收帧（同上，值不进断言）
g, v = p.feed(300, 150)
rows.append(('回锁锚帧 feed(300,150)', g, v))
g, v = p.feed(310, 155)
rows.append(('回锁 feed(310,155)', g, v))
seq_check('④ 光标位置与增量：两端逐项相等（pos, rel）', rows)

# ============================ ⑤ 暂停期行为（B6 契约） ============================
print()
print("=== ⑤. 暂停期：logic_paused 时增量既不结算也不累积（B6） ===")
p = Pair()
rows = []
p.allow(True)
g, v = p.feed(200, 80)             # 未锁预热帧：把两端的光标起点归到同一位置
rows.append(('未锁预热 feed(200,80)', g, v))
p.lock(True)
absorb(p, 200, 80)                 # 吸收帧（同组④，值不进断言）
g, v = p.feed(200, 80)
rows.append(('锁定锚帧 feed(200,80)', g, v))
g, v = p.feed(210, 85)
rows.append(('锁定 feed(210,85)（暂停前基线）', g, v))
p.key(pygame.K_F9, True)
p.key(pygame.K_F9, False)
check('⑤ F9 后两端都进入暂停', p.gl._logic_paused_state() and p.vk._logic_paused_state(),
      'GL=%r VK=%r' % (p.gl._logic_paused_state(), p.vk._logic_paused_state()))
g, v = p.feed(250, 105)
rows.append(('暂停 feed(250,105)', g, v))
g, v = p.feed(270, 95)
rows.append(('暂停 feed(270,95)', g, v))
g, v = p.feed(260, 110)
rows.append(('暂停 feed(260,110)', g, v))
_sg, _sv = p.state()
check('⑤ 暂停期两端都仍锁定且状态逐项相等（暂停不碰锁）', _sg == _sv and _sg[0] is True,
      'GL=%r VK=%r' % (_sg, _sv))
p.key(pygame.K_F9, True)
p.key(pygame.K_F9, False)
check('⑤ F9 后两端都恢复', (not p.gl._logic_paused_state()) and (not p.vk._logic_paused_state()),
      'GL=%r VK=%r' % (p.gl._logic_paused_state(), p.vk._logic_paused_state()))
g, v = p.feed(280, 120)
rows.append(('恢复 feed(280,120)', g, v))
g, v = p.feed(300, 140)
rows.append(('恢复 feed(300,140)', g, v))
seq_check('⑤ 暂停期行为：两端逐项相等（B6：暂停不结算不累积、恢复无积压）', rows)

# ============================ ⑥ Tab 跨帧轮询（P1 回归锚） ============================
print()
print("=== ⑥. Tab 跨帧轮询解锁（按住跨帧不重复翻转；P1 门⑤回归锚） ===")
p = Pair()
rows = []
rets = []

def step6(label):
    s = p.state()
    rows.append((label, s[0], s[1]))

p.allow(True)
p.lock(True)
step6('起点（锁定）')
p.key(pygame.K_TAB, True)
for i in range(4):
    rets.append(p.poll())
    step6('按住 Tab 轮询#%d' % (i + 1))
p.key(pygame.K_TAB, False)
for i in range(2):
    rets.append(p.poll())
    step6('松开 Tab 轮询#%d' % (i + 1))
p.key(pygame.K_TAB, True)
rets.append(p.poll())
step6('再按 Tab 轮询#1')
p.key(pygame.K_TAB, False)
rets.append(p.poll())
step6('再松 Tab 轮询#2')
_gl_rets = [a for a, b in rets]
_vk_rets = [b for a, b in rets]
_expect_rets = [True, False, False, False, False, False, True, False]
check('⑥ 轮询返回序列两端逐项相等且符合按下沿预期',
      _gl_rets == _vk_rets == _expect_rets,
      'GL=%s VK=%s 期望=%s' % (_gl_rets, _vk_rets, _expect_rets))
seq_check('⑥ Tab 跨帧轮询：两端状态逐项相等', rows)


# ============================ ⑦ 暂停期解锁键（F-3） ============================
print()
print("=== ⑦. 暂停期按解锁键：两端都必须能解锁（F-3：暂停不冻输入逃生通道） ===")
p = Pair()
rows = []
p.allow(True)
p.lock(True)
p.key(pygame.K_F9, True)
p.key(pygame.K_F9, False)
check('⑦ F9 后两端都进入暂停', p.gl._logic_paused_state() and p.vk._logic_paused_state(),
      'GL=%r VK=%r' % (p.gl._logic_paused_state(), p.vk._logic_paused_state()))


def vk_render_frame():
    """VK 生产渲染帧（vk_player.draw:643-668 逐行镜像，同组④/⑤的 vk_frame —— 只是
    不喂光标事件，本组只测解锁键轮询）。"""
    p.bridge.begin_frame()
    p.vk.advance_logic(FRAME_DT)
    vk_player.poll_unlock_frame(p.vk)


def gl_pump():
    """GL 生产泵（run() 主循环第一步：poll_events + 用 glfw.get_key 重建 script_keys）。
    ★顺序要点：泵每帧用**物理键真相**重建 script_keys，所以"本帧按键"必须排在泵之后
    注入 —— 真实按键由 poll_events 投递、泵内 get_key 也是 PRESS，两者同帧同值。"""
    p.gl._handle_events()


# 暂停期按解锁键：GL 泵 -> 本帧 KEYDOWN -> GL 渲染帧（暂停期唯一轮询点）；VK 渲染帧
gl_pump()
p.key(pygame.K_TAB, True)
p.gl.render(FRAME_DT)
vk_render_frame()
_sg, _sv = p.state()
rows.append(('暂停期按 Tab 一帧', _sg, _sv))
check('⑦ 暂停期按解锁键：两端都解锁了（状态位 + 光标捕获位都翻）',
      _sg[0] is False and _sv[0] is False and _sg[2] is False and _sv[2] is False,
      'GL=%r VK=%r' % (_sg, _sv))

# 按住不放再来一帧（泵照常，键态仍为按下）：按下沿语义 -> 不得再翻一次
# （VK 一帧内 poll 两次=暂停分支+渲染帧采样，GL 宿主路径也可能 advance_logic+render
#   同帧各 poll 一次 —— 双保险不得变成"翻两次"）
gl_pump()
p.key(pygame.K_TAB, True)
p.gl.render(FRAME_DT)
vk_render_frame()
_sg, _sv = p.state()
rows.append(('暂停期按住 Tab 第 2 帧', _sg, _sv))

# 松开：仍不翻
p.key(pygame.K_TAB, False)
gl_pump()
p.gl.render(FRAME_DT)
vk_render_frame()
_sg, _sv = p.state()
rows.append(('暂停期松 Tab', _sg, _sv))
seq_check('⑦ 暂停期解锁键：两端状态逐项相等（按住不重复翻转）', rows)

p.key(pygame.K_F9, True)
p.key(pygame.K_F9, False)
check('⑦ F9 后两端都恢复', (not p.gl._logic_paused_state()) and (not p.vk._logic_paused_state()),
      'GL=%r VK=%r' % (p.gl._logic_paused_state(), p.vk._logic_paused_state()))


# ============================ ⑧ F-6 mouse_pos 成员面 ============================
print()
print("=== ⑧. F-6 mouse_pos：两端同名同类型同语义（int 像素，不是桥的 float pos） ===")
p = Pair()
rows = []
p.allow(True)
p.lock(False)
def _is_int2(v):
    """2 元 int 元组（排除 float / list / bool —— 桥的 float pos 就是这条要挡的）。"""
    return (isinstance(v, tuple) and len(v) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in v))


_gp, _vp = p.pos()
check('⑧ 两端都有 mouse_pos 成员（脚本读 engine.mouse_pos 不再 AttributeError）',
      _gp is not None and _vp is not None, 'GL=%r VK=%r' % (_gp, _vp))
# 初值**不**逐值比：GL 窗口一建好 GLFW 就可能已投递一次真实光标位置（值 = 物理光标），
# 而 VK 侧本夹具没有注册真实窗口光标回调、只在 feed 时喂 —— 初值不可比（纯夹具差异，
# 不是后端差异）。值的一致性由下面的序列断言负责；这里只钉"类型与 GL 一致"。
check('⑧ 两端 mouse_pos 都是 2 元 int 元组（与 GL 同类型，不是 float / list）',
      _is_int2(_gp) and _is_int2(_vp), 'GL=%r VK=%r' % (_gp, _vp))


def step8(label, x, y):
    p.feed(x, y)
    g, v = p.pos()
    rows.append((label, g, v))


step8('未锁 feed(100,60)', 100, 60)
step8('未锁 feed(140,62)', 140, 62)
step8('未锁 feed(120.7,63.4)（float 入）', 120.7, 63.4)
p.lock(True)
step8('锁定 feed(120.7,63.4)', 120.7, 63.4)
step8('锁定 feed(210,85)', 210, 85)
step8('锁定 feed(233.9,97.2)（float 入）', 233.9, 97.2)
p.lock(False)
step8('解锁后 feed(300,150)', 300, 150)
step8('解锁后 feed(-5.5,-3.25)（负 float 入）', -5.5, -3.25)
seq_check('⑧ mouse_pos 序列：两端逐值相等（未锁定 / 锁定 / 解锁后三态）', rows)
_flat = [x for (_l, g, v) in rows for x in (v or ())]
check('⑧ mouse_pos 逐元素是 int（不是 float —— 不转发宿主桥 float pos）',
      bool(_flat) and all(isinstance(x, int) for x in _flat),
      'VK 值类型=%s' % sorted({type(x).__name__ for x in _flat}))
_gp_now, _vp_now = p.pos()
check('⑧ VK mouse_pos 与宿主桥 pos 同源（同一光标事件的 int 截断逐值相等）',
      _vp_now == (int(p.bridge.pos[0]), int(p.bridge.pos[1])),
      'VK=%r 桥=%r' % (_vp_now, p.bridge.pos))

# ============================ ⑨ F-1 返回值 ============================
print()
print("=== ⑨. F-1 返回值：set_mouse_locked / toggle_mouse_locked 两端逐项相等 ===")
p = Pair()
rows = []
p.allow(False)
rows.append(('allowed=False set(True)（被拒）',
             p.gl.set_mouse_locked(True), p.vk.set_mouse_locked(True)))
p.allow(True)
rows.append(('allowed=True set(True)', p.gl.set_mouse_locked(True), p.vk.set_mouse_locked(True)))
rows.append(('幂等重申 set(True)', p.gl.set_mouse_locked(True), p.vk.set_mouse_locked(True)))
rows.append(('set(False)', p.gl.set_mouse_locked(False), p.vk.set_mouse_locked(False)))
rows.append(('幂等重申 set(False)', p.gl.set_mouse_locked(False), p.vk.set_mouse_locked(False)))
rows.append(('toggle#1', p.gl.toggle_mouse_locked(), p.vk.toggle_mouse_locked()))
rows.append(('toggle#2', p.gl.toggle_mouse_locked(), p.vk.toggle_mouse_locked()))
p.allow(False)
rows.append(('allowed=False toggle（被拒）',
             p.gl.toggle_mouse_locked(), p.vk.toggle_mouse_locked()))
p.allow(True)
rows.append(('allowed=True toggle', p.gl.toggle_mouse_locked(), p.vk.toggle_mouse_locked()))
seq_check('⑨ 返回值序列：两端逐项相等（含被拒绝那两条）', rows)
_types = sorted({type(x).__name__ for (_l, g, v) in rows for x in (g, v)})
check('⑨ 返回值是 bool（不是 None —— 旧 VK 恒 None 会让脚本 if 两端走不同分支）',
      _types == ['bool'], '实测类型=%s' % _types)
check('⑨ 「不允许锁」时 set_mouse_locked(True) 两端都返回 False',
      rows[0][1] is False and rows[0][2] is False, 'GL=%r VK=%r' % (rows[0][1], rows[0][2]))
p2 = Pair()
p2.allow(False)
vk_player._install_lock_policy_guard(p2.vk)        # 生产 VK 播放器启动时装的同一守卫
_gret = p2.gl.set_mouse_locked(True)
_vret = p2.vk.set_mouse_locked(True)
check('⑨ 生产播放器守卫路径：被拒也返回 False（不是 None）',
      _gret is False and _vret is False, 'GL=%r VK=%r' % (_gret, _vret))

# ============================ ⑩ F-2 幂等重申不断流 ============================
print()
print("=== ⑩. F-2 幂等 set_mouse_locked(True)：锁定中连续重申不得断流一帧 ===")
p = Pair()
p.allow(True)
p.lock(True)
absorb(p, 200, 80)                 # 吸收帧：锁定切换后只建立增量基线（值不进断言）
_g0, _v0 = p.feed(200, 80)
check('⑩ 起点：两端都锁定、锚帧 mouse_rel 都是 (0,0)',
      _g0 == _v0 == ((200, 80), (0, 0)), 'GL=%s VK=%s' % (_g0, _v0))
rows = []
for _i in range(3):
    _x, _y = 210 + 10 * _i, 85 + 5 * _i
    p.gl.set_mouse_locked(True)    # 脚本每帧重申锁定（FPS 脚本的常见写法）
    p.vk.set_mouse_locked(True)
    _g, _v = p.feed(_x, _y)
    rows.append(('重申 set(True)#%d 后 feed(%d,%d)' % (_i + 1, _x, _y), _g, _v))
seq_check('⑩ 锁定中连续 3 帧重申 set(True)：mouse_rel 序列两端逐项相等', rows)
_rels = [rel for (_l, gv, vv) in rows for rel in (gv[1], vv[1])]
check('⑩ 每帧 mouse_rel 都非 (0,0)（不断流）',
      all(r != (0, 0) for r in _rels), '实测=%s' % (_rels,))

# ============================ ⑪ F-7 set_mouse_lock_allowed 两方向 ============================
print()
print("=== ⑪. F-7 set_mouse_lock_allowed 两方向：三元组逐项相等 ===")
p = Pair()
rows = []


def step11(label):
    s = p.state()
    rows.append((label, s[0], s[1]))


p.allow(False)
step11('基线 allowed=False')
p.allow(True)                      # 方向一：True -> 立即按当前意图应用（锁定）
step11('set_mouse_lock_allowed(True)')
_sg, _sv = p.state()
check('⑪ True 方向：两端都**立即**按意图锁上（不是等下一帧）',
      _sg[0] is True and _sv[0] is True and _sg[2] is True and _sv[2] is True,
      'GL=%r VK=%r' % (_sg, _sv))
p.key(pygame.K_TAB, True)          # 造出"有解锁意图"的起点（requested=True）
p.poll()
p.key(pygame.K_TAB, False)
p.poll()
step11('Tab 解锁（requested=True）')
p.allow(False)                     # 方向二：False -> 清 requested + 解锁
step11('set_mouse_lock_allowed(False)')
_sg, _sv = p.state()
check('⑪ False 方向：两端都清 mouse_unlock_requested 且解锁',
      _sg == (False, False, False) and _sv == (False, False, False),
      'GL=%r VK=%r' % (_sg, _sv))
p.allow(True)
step11('再 set_mouse_lock_allowed(True)')
seq_check('⑪ 两方向：两端三元组逐项相等（locked / requested / 捕获位）', rows)

# ============================ ⑫ 打包播放器路径返回值（Q-B7-40-1） ============================
print()
print("=== ⑫. 打包播放器路径返回值：PlayerApp 与 GLEngine / VK 三端逐项相等（Q-B7-40-1） ===")
# 为什么必须单独一组（⑨ 咬不到这条）: ⑨ 比的是 **GL 引擎**（编辑器 / GLEngine）与 VK，
# 但玩家实际发布的是**打包游戏**，它的 GL 路径是 runtime.PlayerApp（--run / 游戏包
# opengl 分支 / build_entry 直连）。PlayerApp 曾自带**第二份** set_mouse_locked 实现:
#   ① 恒返回 None —— ⑨ 用 GLEngine，永远看不到；
#   ② 被拒分支早退不落地后端（锁定中被拒 -> 只写 self.mouse_locked=False，不调后端，
#      光标仍被 CURSOR_DISABLED / ClipCursor 捕获 -> 玩家"光标出来了但动不了"）。
# 结果: 修完 VK 之后，打包版 GL 返回 None、VK 返回 True/False —— 在**用户发布路径**上
# 造出新的分叉（反模式 6「修 A 引入 B」）。本组用真窗口 + 生产入口三端对拍。
_EMPTY_SCENE = {'version': 10, 'objects': [], 'lights': [], 'ui': None}
p = Pair()                                                     # GL 引擎 + VK 播放器（生产构造式）
_app = runtime.PlayerApp(None, 640, 400, scene_data=_EMPTY_SCENE)   # 打包播放器生产入口
_PLAYER_APPS.append(_app)
_impls = (('GLEngine', p.gl), ('PlayerApp', _app), ('SceneDriver', p.vk))


def allow3(v):
    """三端同一串策略输入（生产脚本 API）。"""
    for _n, o in _impls:
        o.set_mouse_lock_allowed(bool(v))


def call3(label, fn):
    rows.append((label, fn(p.gl), fn(_app), fn(p.vk)))


def seq3_check(title, rows3):
    """rows3 = [(label, GLEngine, PlayerApp, VK), ...]：三端逐行比对。"""
    bad = [r for r in rows3 if not (r[1] == r[2] == r[3])]
    for lb, g, a, v in rows3:
        print('    %-34s GLEngine=%-6s PlayerApp=%-6s VK=%s' % (lb, g, a, v))
    check(title, not bad,
          '；'.join('%s: GLEngine=%r PlayerApp=%r VK=%r' % (lb, g, a, v) for (lb, g, a, v) in bad[:3])
          if bad else '%d 步三端逐项相等' % len(rows3))


rows = []
allow3(False)
call3('allowed=False set(True)（被拒）', lambda o: o.set_mouse_locked(True))
allow3(True)
call3('allowed=True set(True)', lambda o: o.set_mouse_locked(True))
call3('幂等重申 set(True)', lambda o: o.set_mouse_locked(True))
call3('set(False)', lambda o: o.set_mouse_locked(False))
call3('幂等重申 set(False)', lambda o: o.set_mouse_locked(False))
call3('toggle#1', lambda o: o.toggle_mouse_locked())
call3('toggle#2', lambda o: o.toggle_mouse_locked())
allow3(False)
call3('allowed=False toggle（被拒）', lambda o: o.toggle_mouse_locked())
allow3(True)
call3('allowed=True toggle', lambda o: o.toggle_mouse_locked())
seq3_check('⑫ 打包播放器返回值序列：三端逐项相等（含被拒那两条）', rows)
_types3 = sorted({type(x).__name__ for (_l, g, a, v) in rows for x in (g, a, v)})
check('⑫ 三端返回值都是 bool（PlayerApp 旧实现恒 None，脚本 if 会走不同分支）',
      _types3 == ['bool'], '实测类型=%s' % _types3)
check('⑫ 「不允许锁」时三端 set_mouse_locked(True) 都返回 False',
      rows[0][1] is False and rows[0][2] is False and rows[0][3] is False,
      'GLEngine=%r PlayerApp=%r VK=%r' % (rows[0][1], rows[0][2], rows[0][3]))
# 被拒分支**不许早退**：锁定中被拒 -> 必须真的把后端光标放出来（玩家可感知）
for _n, o in _impls:
    o.set_mouse_lock_allowed(True)
    o.set_mouse_locked(True)
_cap_locked = {'GLEngine': _mode_disabled(p.gl._glfw_win), 'PlayerApp': _mode_disabled(_app._glfw_win),
               'SceneDriver': _mode_disabled(p.vk_win)}
check('⑫ 前置：三端都真的锁上了（光标捕获位 GLFW 回读 True）',
      set(_cap_locked.values()) == {True}, _cap_locked)
_denied3 = []
for _n, o in _impls:
    o.mouse_lock_allowed = False       # 直接关闸（不经过 set_mouse_lock_allowed: 模拟脚本误调）
    _denied3.append((_n, o.set_mouse_locked(True)))
_cap_denied = {'GLEngine': _mode_disabled(p.gl._glfw_win), 'PlayerApp': _mode_disabled(_app._glfw_win),
               'SceneDriver': _mode_disabled(p.vk_win)}
check('⑫ 锁定中被拒：三端都返回 False 且光标捕获位被**真的释放**（不许早退不落地后端）',
      all(r is False for (_n, r) in _denied3) and set(_cap_denied.values()) == {False},
      '返回=%r 捕获位=%r' % (_denied3, _cap_denied))
for _n, o in _impls:
    o.mouse_lock_allowed = True
    o.set_mouse_locked(False)
# 结构锚点: 播放器侧不得再长出第二份实现（docs/guides/开发要求_功能解耦与模块化.md 规则 5/6）
# 直读 ROOT/runtime.py（不走 _find_src: archive/bench/_bench_stable 与 _bench_ws 各有一份
# 同名 runtime.py，递归定位会命中 3 份而无法判定"恰好一份"）。
_rt = open(os.path.join(ROOT, 'runtime.py'), encoding='utf-8').read()
check('⑫ 结构：PlayerApp.set_mouse_locked 委托 InputMixin（super()），不再另写一套',
      'return super().set_mouse_locked(locked)' in _rt, 'PlayerApp 只许走这一条实现')
check('⑫ 结构：runtime.py 的返回契约与 InputMixin:378 一字不差',
      '返回: True=已应用（或已解锁）; False=因"不允许锁"被拒绝。' in _rt, '与 loom_input.py:378 同一句话')
check('⑫ 结构：旧的「被拒分支早退不落地后端」实现已不存在',
      '_lock_denied_logged' not in _rt and "apply_mouse_lock_backend(getattr(self, '_glfw_win'" not in _rt,
      '旧病灶（早退不落地后端）不得复活')
check('⑫ 结构：PlayerApp 不自带 toggle_mouse_locked / set_mouse_lock_allowed（继承即唯一实现）',
      'def toggle_mouse_locked' not in _rt and 'def set_mouse_lock_allowed' not in _rt,
      '第二份实现不得复活')
check('⑫ 收尾：打包播放器光标捕获已释放（不把 ClipCursor/隐藏光标带出进程）',
      _mode_disabled(_app._glfw_win) is False, _mode_disabled(_app._glfw_win))


# ============================ 收尾：必须释放光标捕获 ============================
print()
print("=== 收尾：释放两端光标捕获（不许把 ClipCursor/隐藏光标带出进程） ===")
cleanup_ok = True
for i, pp in enumerate(_PAIRS):
    try:
        pp.gl.set_mouse_lock_allowed(False)
        pp.vk.set_mouse_lock_allowed(False)
        if _mode_disabled(pp.gl._glfw_win) or _mode_disabled(pp.vk_win):
            cleanup_ok = False
    except Exception as e:
        cleanup_ok = False
        print('FAIL 收尾释放第 %d 对失败: %r' % (i + 1, e))
check('收尾：全部对已释放（两端光标模式回 NORMAL）', cleanup_ok)

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
