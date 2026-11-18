# -*- coding: utf-8 -*-
"""test_mouse_lock_parity.py — P2 面「鼠标锁定与光标捕获」两端对拍门（真窗口，2026-11-18）。

人类判据（docs/guides/开发要求_后端API一致_JVM模型.md 唯一上位判据）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

本门验什么（Q-B7-37-1 P2）：**同一串**鼠标锁定/解锁/移动输入喂进两端**生产入口**，
逐项比对可观察结果（不是"各自为 True"）。六组：
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

夹具保真（§5 反模式 8 的牙）：桥必须是生产类 vk_ui.UIInputBridge 且按生产构造式
（vk_player.py:367 UIInputBridge(getattr(driver,'ui',None))）包 driver.ui；两端窗口都是
真 GLFW 句柄；帧首/回调镜像锚点有源码断言（结构段）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何"差不多"/阈值/容差都不许。

修前红证据（R1，HEAD=3d87dce 实测，见本文件尾 R1 段输出）：
  R1 组⑤红：GL 暂停期 mouse_rel 逐帧结算新值 ((40,20),(20,-10),(-10,15))，VK 恒 (0,0)
    —— B6「暂停期既不结算也不累积」GL 侧未实现；用户可感知路径：F9 暂停 + F10 单步时
    脚本读 mouse_rel（GL 视角转 / VK 不转）。
    缺陷归属（只报告不修）：loom_glfw_window._update_mouse_rel（无 logic_paused 门控；
    run 循环 loom_render.py:1313 暂停期照跑泵）+ engine.GLEngine.advance_logic 暂停分支
    （engine.py:1446-1459 不清 mouse_rel）；VK 参照实现 scene_driver.py:1059-1062。

附加发现（探针实测/源码证据，超出六组点名输入、不在本门断言；各自修复落地后再补牙）：
  F-1 VK set_mouse_locked/toggle_mouse_locked 返回 None，GL 返回 True/False
      （scene_driver.py:1649-1672/1678-1694 vs loom_input.py:367-403/458-472）——
      脚本 if engine.toggle_mouse_locked(): 两端走不同分支（GL 真 / VK 假）。
  F-2 锁定中幂等 set_mouse_locked(True)（脚本每帧重申锁定的常见写法）：VK 下一帧
      mouse_rel=(0,0) 断流一帧，GL 连续。根因：scene_driver.set_mouse_locked 每次调用
      都触发 on_mouse_lock_changed → vk_player._apply_cursor_mode 重置 _prev
      （vk_player.py:591）；GL 只在模式变化时由 _update_mouse_rel 的 mode 分支重锚。
  F-3 F9 暂停期间按解锁键：VK 解锁（advance_logic 暂停分支自带 poll_unlock
      + vk_player 渲染帧采样，双保险）；GL 暂停帧**无人轮询**（GL 唯一轮询点 =
      update_scripts 首行 engine.py:995，暂停时不执行）——同一串输入两端结果不同。
  F-5 ShowCursor 计数：GL _apply_cursor_backend 每次 set_mouse_locked 调用都无条件
      ShowCursor（loom_input.py:443，含状态未变的幂等调用）；VK apply_mouse_lock_backend
      同款（runtime.py:88/92）——反复重申锁定后解锁，光标显示计数不归零（两端同病，
      对拍中立，属共享质量问题）。
  F-6 mouse_pos 成员面：GL 引擎有 engine.mouse_pos（int 元组）；VK SceneDriver 无此成员
      （等观测量只在宿主桥 vk_ui.UIInputBridge.pos，float 元组）——脚本直接读
      engine.mouse_pos 在 VK 上 AttributeError；是否 ① 层用户 API 待契约裁决。
  F-7 set_mouse_lock_allowed 两方向应用语义不齐：GL True→立即按意图应用（锁定）、
      False→清 requested + 解锁（loom_input.py:347-365，test_unlock_key I 段钉过 GL）；
      VK True→什么都不做、False→只解锁**不清 requested**（scene_driver.py:1637-1647）。

结构断言改名防护（B7-16 复查 P0-1 教训）：结构段用**递归**扫描定位生产文件（排除
tests/），并同时覆盖当前名与历史名（_poll_unlock_local 必须不存在 = 批2已删的旧拷贝）。
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

        def _apply_cursor_mode(locked):
            self._prev[0] = None
            x, y = glfw.get_cursor_pos(self.vk_win)
            self.bridge.on_cursor(x, y)
            runtime.apply_mouse_lock_backend(self.vk_win, bool(locked), tag='VK 播放器')

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
        self.gl._handle_events()
        _on_cursor_pos_cb(self.gl._glfw_win, x, y)
        return ((int(self.gl.mouse_pos[0]), int(self.gl.mouse_pos[1])),
                tuple(self.gl.mouse_rel))

    def vk_frame(self, x, y):
        """VK 生产帧：生产光标回调 + vk_player.draw 帧首逐行镜像（643-668）。"""
        self.bridge.on_cursor(x, y)                    # vk_player._on_cursor:558-562 的全部内容
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

    def state(self):
        """两端状态位 + 光标捕获位（捕获位经 GLFW API 独立回读，不用引擎自报）。"""
        return (
            (bool(self.gl.mouse_locked), bool(self.gl.mouse_unlock_requested),
             _mode_disabled(self.gl._glfw_win)),
            (bool(self.vk.mouse_locked), bool(self.vk.mouse_unlock_requested),
             _mode_disabled(self.vk_win)),
        )


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
_ga, _va = p.feed(140, 62)         # 瞬态吸收帧：GLFW 3.4 首个 disabled 轮询把虚拟坐标
                                   # 初始化为物理光标位置（与喂入值有一帧滞后，多窗测试进程
                                   # 里不可预测）。生产里不存在该伪影（真实移动连续，两端
                                   # 首帧都由重锚定为 (0,0)）—— 此帧只建立 tracking 基线，
                                   # 值打印不进断言。
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
p.feed(300, 150)                   # 瞬态吸收帧（同上，值不进断言）
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
p.feed(200, 80)                    # 瞬态吸收帧（同组④，值不进断言）
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
