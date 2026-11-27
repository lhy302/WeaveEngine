# -*- coding: utf-8 -*-

"""test_mouse_rel_ui_consumed_parity.py — Q-B7-43-2：UI 消费帧的 mouse_rel / ui_consumed 两端对拍门.

人类裁决（2026-11-22，最高依据）：「选 A，并且同时给 VK 补 ui_consumed」=
  · A = 以 GL 为准：mouse_rel 的语义是「本帧鼠标物理位移增量」，**不管**这一帧鼠标
    事件是否被 UI 消费（GL 基准：loom_glfw_window._update_mouse_rel 无条件结算，
    暂停期除外）；
  · 同时给 VK 补 ui_consumed：VK 必须暴露与 GL 同语义的「本帧鼠标事件被 UI 消费」
    标志（bool，每帧由 player 从 ui_bridge 写入 = not ui_bridge.wants_camera()），
    否则脚本在 VK 上无法判断本帧输入是否被 UI 吃掉。

四组（先红后绿）：
  A mouse_rel 语义     构造「本帧鼠标被 UI 消费」的帧（按下按钮同时移动光标），
                       两端 mouse_rel 都等于**物理增量**（非 0）且逐位相等
                       （同一列输入序列驱动两端，期望值写死，不取自任何一端）。
  B ui_consumed 可见性 两端 ui_consumed 都存在、类型 bool、同帧取值相等
                       （消费帧 True / 非消费帧 False）。
  C 相机不回归         UI 消费帧两端相机位姿都不变（GL：PlayerApp.move_camera/
                       rotate_camera 的 ui_consumed 早退；VK：apply_editor_camera_mouse
                       新增同语义早退）。不许让 VK 在 UI 拖动时开始转视角 —— 那是回归。
                       滚轮**不连坐**（与 GL editor._update_camera 的 B7-28 P-09 语义一致：
                       只有「滚轮本身被 ScrollView 吃掉」才不给相机）。
  D 结构               feed_mouse_rel 调用点不再被 wants_camera 包裹（AST）；
                       ui_consumed 写入点两端各一处（GL runtime.py / VK player.py），
                       且 VK 写入点排在 begin_frame 之后、feed 之前；
                       VK apply_editor_camera_mouse 有 ui_consumed 早退、
                       GL PlayerApp.move_camera/rotate_camera 早退仍在、
                       共享编辑器相机（_EditorCore._update_camera 的 _ui_lock）仍在。
                       相机早退**不在**共享实现里（GL 在 runtime.PlayerApp 覆写、
                       VK 在 SceneDriver.apply_editor_camera_mouse，各为后端内部，
                       与编辑器路径的共享 _ui_lock 是两条路径），故无 is 同源断言、
                       改为「两端定义点各一处」断言。

考古（2026-11-22，HEAD=fc99d75 实测）：
  · 脚本看到的 engine 对象：GL = runtime.PlayerApp（runtime.py:105，GLEngine 子类）；
    VK = render/vk/driver.SceneDriver（driver.py:488）。ui_consumed 的对齐面 =
    PlayerApp.ui_consumed ↔ SceneDriver.ui_consumed。
  · mouse_rel 的相机消费者：GL = 玩家脚本（script/scripts.py:686/742 读 e.mouse_rel）
    + 编辑器相机（editor/core.py:2785 _update_camera，_ui_lock 早退）；VK = 玩家脚本同式
    + apply_editor_camera_mouse（driver.py:1859，右键转视角，旧实现无 ui_consumed 早退、
    靠 player 不喂挡住）。GL 引擎侧 keyboard 相机早退在 runtime.py:306-316。
  · 编辑器路径（_EditorCore 两端共用 _dispatch_ui_mouse + _update_camera 的 _ui_lock）
    已一致 —— 本任务不动。

修前必红（本门随「修前」提交，镜像修前生产 vk_player.draw:653-659）：
  当前 VK feed 被 wants_camera 门控 → UI 消费帧 mouse_rel=(0,0)（GL=物理增量）
  → A 红；SceneDriver 无 ui_consumed → B 红；apply_editor_camera_mouse 无早退 → C 红；
  D 的结构断言按修前现状判红。
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


import ast                                                        # noqa: E402
import copy                                                       # noqa: E402
import time                                                       # noqa: E402

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ['LOOM_NO_DIALOG'] = '1'

import glfw                                                       # noqa: E402

import loom_ui                                                    # noqa: E402  两端同一个生产 UI 管理器
import scene.contract as _scene_contract                          # noqa: E402  场景版本号单点
import runtime                                                    # noqa: E402  GL 打包播放器（生产入口）
import render.vk.driver as SD                                     # noqa: E402
import render.vk.ui as vk_ui                                      # noqa: E402  夹具用生产那个桥类
from render.gl.window import (_on_cursor_pos_cb,                  # noqa: E402  GL 生产光标回调
                              _on_mouse_button_cb)                # noqa: E402  GL 生产鼠标键回调
from loom_ui import Button                                        # noqa: E402

ok = True
_PAIRS = []

W, H = 640, 400
FRAME_DT = 1 / 120.0
_EMPTY_SCENE = {'version': _scene_contract.CURRENT_VERSION,
                'objects': [], 'lights': [], 'ui': None}

KNOWN_DIFFS = []              # 已知差异登记表：必须为空；发现差异 = 红并报告，不许登记糊过去


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def seq_check(title, rows):
    """rows = [(label, gl值, vk值), ...]：逐行比对并打 GL vs VK 对照表。"""
    bad = [(lb, g, v) for (lb, g, v) in rows if g != v]
    for lb, g, v in rows:
        print('    %-34s GL=%-22s VK=%s' % (lb, g, v))
    check(title + '（%d 行，两端逐行相等）' % len(rows), not bad, bad[:4])


# ============================ 结构段（D 组的一部分：先读源码，不建窗口） ============================

def _read_prod(fname):
    """读生产模块源码（ROOT 顶层）。同名副本（archive/bench/…）不参与判定。"""
    p = os.path.join(ROOT, fname)
    if not os.path.isfile(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


def src_has(fname, needle, must=True, why=''):
    src = _read_prod(fname)
    if src is None:
        check('结构：%s 可读' % fname, False, 'ROOT 下没有该生产模块')
        return
    found = needle in src
    check('结构：%s %s %r' % (fname, '含' if must else '不含', needle),
          found if must else (not found), why)


def _count(src, needle):
    return src.count(needle) if src else 0


print("=== 〇. 结构：feed 门控 / ui_consumed 写入点（D 组；修前按现状红） ===")
_vk_player_src = _read_prod('render/vk/player.py') or ''
_vk_driver_src = _read_prod('render/vk/driver.py') or ''
_gl_runtime_src = _read_prod('runtime.py') or ''
_gl_window_src = _read_prod('render/gl/window.py') or ''
_editor_src = _read_prod('editor/core.py') or ''

# D-1：feed_mouse_rel 生产调用点必须**不再**被 wants_camera 包裹（AST 判定，不靠文本巧合）。
_vk_player_ast = None
try:
    _vk_player_ast = ast.parse(_vk_player_src, filename='render/vk/player.py')
except Exception as e:
    check('结构：render/vk/player.py 可解析', False, repr(e))


def _feed_gated_by_wants_camera(tree):
    """在 player.py 的 AST 里找 driver.feed_mouse_rel(...) 调用；返回它是否被
    任一 enclosing If 的 test 里的 wants_camera 调用门控。"""
    found_call = False
    gated = False

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_If(self, node):
            self.stack.append(node.test)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            f = node.func
            is_feed = (isinstance(f, ast.Attribute) and f.attr == 'feed_mouse_rel')
            if is_feed:
                nonlocal found_call, gated
                found_call = True
                for test in self.stack:
                    for sub in ast.walk(test):
                        if isinstance(sub, ast.Attribute) and sub.attr == 'wants_camera':
                            gated = True
            self.generic_visit(node)

    _V().visit(tree)
    return found_call, gated


if _vk_player_ast is not None:
    _found, _gated = _feed_gated_by_wants_camera(_vk_player_ast)
    check('结构：player.py 里存在 driver.feed_mouse_rel( 生产调用点', _found)
    check('结构（Q-B7-43-2·A）：feed_mouse_rel 调用点不被 wants_camera 包裹'
          '（mouse_rel = 本帧物理增量，与 GL _update_mouse_rel 无条件结算同语义；'
          '消费位由 ui_consumed 单独暴露）',
          _found and not _gated, 'found=%s gated=%s' % (_found, _gated))

# D-2：ui_consumed 写入点两端各一处（GL 基准 runtime.py:297 那一行 + VK player 每帧写入）。
check('结构：GL 的 ui_consumed 基准语义仍在（runtime.py 恰好一处 self.ui_consumed = consumed）',
      _count(_gl_runtime_src, 'self.ui_consumed = consumed') == 1,
      _count(_gl_runtime_src, 'self.ui_consumed = consumed'))
check('结构（Q-B7-43-2·B）：VK player 每帧把消费位写到 driver.ui_consumed（恰好一处）',
      _count(_vk_player_src, 'driver.ui_consumed =') == 1,
      _count(_vk_player_src, 'driver.ui_consumed ='))
check('结构：VK player 的写入式 = not ui_bridge.wants_camera()（与 GL 的 not ui_consumed 同语义）',
      'driver.ui_consumed = not ui_bridge.wants_camera()' in _vk_player_src)

# D-3：写入时序 —— begin_frame 之后、feed 之前（与 GL「先 _dispatch_ui_mouse 再消费」同序）。
_i_begin = _vk_player_src.find('ui_bridge.begin_frame()')
_i_write = _vk_player_src.find('driver.ui_consumed =')
_i_feed = _vk_player_src.find('driver.feed_mouse_rel(')
check('结构（Q-B7-43-2）：VK 帧首时序 = begin_frame → ui_consumed 写入 → feed_mouse_rel',
      0 <= _i_begin < _i_write < _i_feed, (_i_begin, _i_write, _i_feed))

# D-4：相机早退定义点 —— GL runtime.PlayerApp.move_camera/rotate_camera 的早退仍在（基准）；
#      VK apply_editor_camera_mouse 补同语义早退（滚轮不连坐，早退只锁右键转视角）。
check('结构：GL 相机早退仍在（runtime.py move_camera/rotate_camera 各一处 ui_consumed 早退）',
      _count(_gl_runtime_src, "if getattr(self, 'ui_consumed', False):") == 2,
      _count(_gl_runtime_src, "if getattr(self, 'ui_consumed', False):"))
check('结构（Q-B7-43-2·C）：VK apply_editor_camera_mouse 有 ui_consumed 早退'
      '（不许再靠「不喂」挡相机 —— 那条路已按裁决 A 打开）',
      "getattr(self, 'ui_consumed', False)" in
      (_vk_driver_src[_vk_driver_src.find('def apply_editor_camera_mouse'):
                      _vk_driver_src.find('def apply_editor_camera_mouse') + 4000]
       if 'def apply_editor_camera_mouse' in _vk_driver_src else ''))
_i_apm = _vk_driver_src.find('def apply_editor_camera_mouse')
_apm_body = _vk_driver_src[_i_apm: _vk_driver_src.find('def ', _i_apm + 10)] if _i_apm >= 0 else ''
check('结构：VK apply_editor_camera_mouse 的早退**只锁转视角、不连坐滚轮**'
      '（早退点在滚轮消费之后、mouse_rel 消费之前 = 对齐 GL editor._update_camera 的 '
      'B7-28 P-09 语义）',
      _i_apm >= 0
      and "getattr(self, 'ui_consumed', False)" in _apm_body
      and _apm_body.find("getattr(self, 'ui_consumed', False)") > _apm_body.find('self.mouse_wheel = 0')
      and _apm_body.find("getattr(self, 'ui_consumed', False)") < _apm_body.find('mx, my = self.mouse_rel'),
      '早退相对位置 wheel=%s look=%s 早退=%s' % (_apm_body.find('self.mouse_wheel = 0'),
                                                _apm_body.find('mx, my = self.mouse_rel'),
                                                _apm_body.find("getattr(self, 'ui_consumed', False)")))
check('结构：共享编辑器相机的早退仍在（两端共用的 _EditorCore._update_camera _ui_lock）',
      "_ui_lock = bool(getattr(self, 'ui_consumed', False))" in _editor_src)
check('结构：GL 泵的无条件结算语义仍在（window.py：self.mouse_rel = (int(dx), int(dy))）',
      'self.mouse_rel = (int(dx), int(dy))' in _gl_window_src,
      '裁决 A 的 GL 基准不许被本任务改动')
check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)



# ============================ 夹具（真窗口，生产构造式；同 test_ui_hit_parity 的成熟做法） ============================

_SETTLED_AT = {}          # id(win) -> 上一次已排空到位的注入点


def settle_cursor(win, eng, x, y, maxit=40, dt=0.002, stable=3):
    """把物理光标真的落到 (x,y)，并把这次移动产生的 WM_MOUSEMOVE 全部派发干净。

    与 test_ui_hit_parity.settle_cursor（Q-B7-43-1/43-1 修后版）同一协议、同一判据
    （只看回读，Q-B7-43-2 P0-1）：glfw.set_cursor_pos 底层是 Win32 SetCursorPos，
    物理光标落地是异步的 —— 不先排空，GL 的增量结算点 _update_mouse_rel 会读到
    上一个落点（夹具自造假位移）。本门整列输入都用窗口内坐标（reachable 分支）。
    """
    t = (int(x), int(y))
    try:
        w, h = glfw.get_window_size(win)
        reachable = (0 <= t[0] < int(w)) and (0 <= t[1] < int(h))
        rb0 = tuple(int(v) for v in glfw.get_cursor_pos(win))
    except Exception:
        reachable, rb0 = False, None
    already = _SETTLED_AT.get(id(win)) == t
    okc = 0
    prev = None
    for _ in range(maxit):
        try:
            glfw.poll_events()
        except Exception:
            pass
        try:
            rb = tuple(int(v) for v in glfw.get_cursor_pos(win))
        except Exception:
            rb = None
        if reachable:
            same = (rb == t)
            if not same:
                try:
                    glfw.set_cursor_pos(win, x, y)
                except Exception:
                    pass
        else:
            same = ((rb != rb0 or already) and (rb,) == prev)
        prev = (rb,)
        okc = okc + 1 if same else 0
        if okc >= stable:
            _SETTLED_AT[id(win)] = t
            return True
        time.sleep(dt)
    _SETTLED_AT[id(win)] = t
    return False


def pump(n=6, dt=0.02):
    for _ in range(n):
        try:
            glfw.poll_events()
        except Exception:
            pass
        time.sleep(dt)


def _build_ui(mgr, clicks):
    """两端各搭同一棵最小树：一个会吃点击的按钮（消费帧的发生器）。
    几何：btn (20,20,120,32)  → x∈[20,140) y∈[20,52)。"""
    c = mgr.canvases[0]
    btn = Button(name='btn', rect=(20, 20, 120, 32), text='OK',
                 on_click=lambda: clicks.append('btn'))
    c.root.add_child(btn)
    return {'btn': btn}


class Pair:
    """一对生产后端 + 各自的生产 UI 派发入口（同一串事件喂两边）。"""

    def __init__(self):
        # GL：打包播放器（真 GLFW 窗口 + 生产 UI 鼠标派发）
        self.gl = runtime.PlayerApp(None, W, H, scene_data=_EMPTY_SCENE)
        self.gl.is_playing = True
        # VK：真 GLFW(NO_API) 窗口句柄（= vk_player._register_input 的真实注入点）
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        self.vk_win = glfw.create_window(W, H, 'Loom parity (mouse rel ui consumed)', None, None)
        glfw.window_hint(glfw.CLIENT_API, glfw.OPENGL_API)   # 还原提示，防污染后续 GL 窗口
        self.vk = SD.SceneDriver()
        self.vk.is_playing = True
        self.vk._vk_glfw_window = self.vk_win
        self.vk.ui.resize(W, H)                              # 画布尺寸对齐窗口（同 test_ui_hit_parity）
        # 生产桥，构造式与 render/vk/player.py 逐字相同
        self.bridge = vk_ui.UIInputBridge(getattr(self.vk, 'ui', None))
        self.clicks_gl = []
        self.clicks_vk = []
        self.elems_gl = _build_ui(self.gl.ui, self.clicks_gl)
        self.elems_vk = _build_ui(self.vk.ui, self.clicks_vk)
        # 生产不变量：玩家窗口持焦点
        glfw.focus_window(self.gl._glfw_win)
        for _ in range(4):
            try:
                glfw.poll_events()
            except Exception:
                pass
        self._prev = None            # VK 侧上一帧光标（vk_player.draw 的 _prev）
        _PAIRS.append(self)

    def lock_both(self):
        """两端一起上锁 + 两端增量基线一起重锚（= 一帧吸收帧）。同 test_ui_hit_parity.lock_both。"""
        self.gl.set_mouse_lock_allowed(True)
        self.vk.set_mouse_lock_allowed(True)
        self.gl.set_mouse_locked(True)
        self.vk.set_mouse_locked(True)
        pump(3, 0.02)
        # 2026-11-23 终审 P1-1 加固（夹具级，断言一字不动；Q-B7-43-1 settle 协议同型）：
        # GLFW 新进程的首帧可能合成 focus/cursor-enter 事件，使锁后第一帧
        # GL ui.dispatch_mouse 偶发返回 consumed=True（终审实测 8 次冷跑 1 次，
        # GL=True/VK=False —— 两端判据序列起点不一致）。上锁后先把 GL 泵到 UI
        # 稳定（ui_consumed=False，上限 10 帧防死循环），再开始 6 帧判据序列。
        # 若去掉本加固后仍稳定复现 GL=True，则是产品行为，须另立裁决单（未复现）。
        for _ in range(10):
            self.gl._handle_events()
            if not bool(self.gl.ui_consumed):
                break
        try:
            self.gl._prev_cursor = None
        except Exception:
            pass
        self._prev = None
        return (bool(self.gl.mouse_locked), bool(self.vk.mouse_locked))

    # ---------------- GL 生产帧 ----------------
    def gl_frame(self, x, y, press=False, release=False):
        """GL 生产帧：GLFW 投递光标/按键 → 生产泵（poll + _update_mouse_rel 结算）
        → 生产 UI 派发（_handle_events → _dispatch_ui_mouse）。"""
        win = self.gl._glfw_win
        glfw.set_cursor_pos(win, x, y)
        settle_cursor(win, self.gl, x, y)
        _on_cursor_pos_cb(win, x, y)
        if press:
            _on_mouse_button_cb(win, glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)
        if release:
            _on_mouse_button_cb(win, glfw.MOUSE_BUTTON_LEFT, glfw.RELEASE, 0)
        self.gl._handle_events()          # 生产泵 + _dispatch_ui_mouse
        return {
            'pos': tuple(self.gl.mouse_pos),
            'consumed': bool(self.gl.ui_consumed),
            'rel': tuple(self.gl.mouse_rel),   # 裁决 A：无条件结算的物理增量
            'has_ui_consumed': hasattr(self.gl, 'ui_consumed'),
        }

    # ---------------- VK 生产帧（vk_player.draw 帧首逐行镜像） ----------------
    def vk_frame(self, x, y, press=False, release=False):
        """VK 生产帧：vk_player 回调逐行镜像 + vk_player.draw 帧首逐行镜像。

        修后镜像（Q-B7-43-2 落地，2026-11-22）：begin_frame → driver.ui_consumed 写入
        → 无条件 feed_mouse_rel。修前版（随修前提交 077a3bd）是 begin_frame →
        wants_camera 门控 feed。镜像漂移由 D 组结构断言守住（两边必须同步改）。
        """
        # ---- vk_player._on_cursor / _on_mouse_button ----
        self.bridge.on_cursor(x, y)
        self.vk._on_cursor_event(x, y)
        if press or release:
            lst = list(self.vk.mouse_buttons)
            lst[0] = bool(press)
            self.vk.mouse_buttons = tuple(lst)
        if press:
            self.bridge.on_mouse_button(1, True)
        if release:
            self.bridge.on_mouse_button(1, False)
        # ---- vk_player.draw 帧首（Q-B7-43-2 修后镜像：begin_frame → ui_consumed 写入
        #      → 无条件 feed）----
        self.bridge.begin_frame()
        self.vk.ui_consumed = (not self.bridge.wants_camera())   # 生产：player.py 帧首新增行
        _x, _y = self.bridge.pos
        _p = self._prev
        if _p is not None:                                        # 生产：无条件喂（裁决 A）
            self.vk.feed_mouse_rel(_x - _p[0], _y - _p[1])
        self._prev = (_x, _y)
        # ---- vk_player.draw: advance_logic（帧首 consume_mouse_input 结算） ----
        self.vk.advance_logic(FRAME_DT)
        # ★F-6 同款防崩：缺成员由 B 组断言判红，夹具不抛（否则一个未实现项中断整道门）
        return {
            'pos': (int(_x), int(_y)),
            'consumed': getattr(self.vk, 'ui_consumed', None),
            'rel': tuple(self.vk.mouse_rel),
            'has_ui_consumed': hasattr(self.vk, 'ui_consumed'),
        }

    def frame(self, x, y, press=False, release=False):
        return (self.gl_frame(x, y, press, release), self.vk_frame(x, y, press, release))


# ============================ A 组：UI 消费帧的 mouse_rel = 物理增量 ============================
print()
print("=== A. mouse_rel 语义：UI 消费帧两端 mouse_rel 都等于本帧物理增量（非 0、逐位相等） ===")
print("    （人类裁决 2026-11-22「选 A」：以 GL 为准 —— mouse_rel 不管 UI 是否消费都结算物理增量）")
p = Pair()
_lk = p.lock_both()
check('A 前提：两端都已上锁（mouse_rel 结算的生产前提，与 GL 的 CURSOR_DISABLED 同源）',
      _lk == (True, True), _lk)

# 同一列输入序列驱动两端；期望值由**输入序列**写死（不取自任何一端）。
#   帧1 (50,36)  吸收帧（重锚后第一帧，无增量）
#   帧2 (60,36)  悬停移动            → consumed=False, rel=(10,0)
#   帧3 (70,36)  按下按钮**同时**右移 → consumed=True,  rel=(10,0)  ★裁决 A 的判据帧
#   帧4 (80,36)  持按移动（无新事件）  → consumed=False, rel=(10,0)
#   帧5 (80,36)  松开（原位）         → consumed=True,  rel=(0,0)
#   帧6 (90,36)  松开后移动           → consumed=False, rel=(10,0)
_SEQ = [
    ('帧1 吸收帧 (50,36)',            50, 36, False, False, False, (0, 0)),
    ('帧2 悬停移动 (60,36)',          60, 36, False, False, False, (10, 0)),
    ('帧3 按下按钮同时右移 (70,36)',  70, 36, True,  False, True,  (10, 0)),
    ('帧4 持按移动 (80,36)',          80, 36, False, False, False, (10, 0)),
    ('帧5 松开按钮 (80,36)',          80, 36, False, True,  True,  (0, 0)),
    ('帧6 松开后移动 (90,36)',        90, 36, False, False, False, (10, 0)),
]

_rows_a = []
_rows_b = []
for (label, x, y, press, release, exp_consumed, exp_rel) in _SEQ:
    g, v = p.frame(x, y, press, release)
    _rows_a.append((label + ' ·mouse_rel', tuple(g['rel']), tuple(v['rel'])))
    _rows_b.append((label + ' ·ui_consumed', g['consumed'], v['consumed']))
    check('A %s：两端 mouse_rel 都 = 物理增量 %s（逐位相等）' % (label, exp_rel),
          tuple(g['rel']) == tuple(v['rel']) == exp_rel,
          (tuple(g['rel']), tuple(v['rel'])))
    check('A %s：两端「本帧被 UI 消费」判定一致且 = 期望 %s' % (label, exp_consumed),
          g['consumed'] == v['consumed'] == exp_consumed,
          (g['consumed'], v['consumed']))
# 裁决 A 的关键帧：消费帧的 mouse_rel 非 0（物理增量不因 UI 消费而丢失）。
check('A 消费帧（帧3 按下按钮同时右移）两端 mouse_rel 都非 0 —— 物理增量不因 UI 消费而清零',
      _rows_a[2][1] == (10, 0) and _rows_a[2][2] == (10, 0), _rows_a[2])
seq_check('A 全序列：mouse_rel 两端逐帧逐位相等', _rows_a)


# ============================ B 组：ui_consumed 可见性 ============================
print()
print("=== B. ui_consumed 可见性：两端都存在、bool、同帧取值相等（消费帧 True / 非消费帧 False） ===")
check('B 前提：GL PlayerApp.ui_consumed 存在（runtime.py 生产写入，本任务不改 GL）',
      all(g['has_ui_consumed'] for (g, _v) in [p.frame(95, 36)]),
      'has_ui_consumed')
_g, _v = p.frame(95, 36)
check('B 两端 ui_consumed 都存在（脚本 if engine.ui_consumed: 两端都能跑）',
      _g['has_ui_consumed'] and _v['has_ui_consumed'],
      (_g['has_ui_consumed'], _v['has_ui_consumed']))
check('B 两端 ui_consumed 都是 bool 类型',
      isinstance(getattr(p.gl, 'ui_consumed', None), bool)
      and isinstance(getattr(p.vk, 'ui_consumed', None), bool),
      (type(getattr(p.gl, 'ui_consumed', None)), type(getattr(p.vk, 'ui_consumed', None))))
seq_check('B 全序列：ui_consumed 两端逐帧相等（消费帧 True / 非消费帧 False）', _rows_b)
# 消费帧 / 非消费帧各验一次「非消费帧必须是 False」的实值（防止恒 True 的假对齐）。
_g, _v = p.frame(100, 36)                      # 无事件 → 非消费帧
_gl_uic, _vk_uic = getattr(p.gl, 'ui_consumed', None), getattr(p.vk, 'ui_consumed', None)
check('B 非消费帧：两端 ui_consumed 都取 False',
      _gl_uic is False and _vk_uic is False,
      (_gl_uic, _vk_uic))
_g, _v = p.frame(100, 36, press=True)          # 按钮上按下 → 消费帧
_gl_uic, _vk_uic = getattr(p.gl, 'ui_consumed', None), getattr(p.vk, 'ui_consumed', None)
check('B 消费帧：两端 ui_consumed 都取 True',
      _gl_uic is True and _vk_uic is True,
      (_gl_uic, _vk_uic))


# ============================ C 组：相机不回归 ============================
print()
print("=== C. 相机不回归：UI 消费帧两端相机位姿都不变（滚轮不连坐） ===")

# ---- GL：PlayerApp.move_camera / rotate_camera 的 ui_consumed 早退（生产方法，真对象） ----
_gl = p.gl
_key = getattr(_gl, '_key', {}) or {}
_ks = getattr(_gl, 'key_state', None)
check('C 前提：GL 相机键位表与 key_state 可用', bool(_key) and _ks is not None, (bool(_key), _ks is not None))
if _key and _ks is not None:
    _ks[_key['LOOK_LEFT']] = True
    _ks[_key['CAMERA_FORWARD']] = True
    # 控制帧：ui_consumed=False → 相机真的会动（证明断言不是恒真）
    _gl.ui_consumed = False
    _pos_t = lambda c: (c.x, c.y, c.z)
    _yaw0, _pos0 = _gl.camera_yaw, _pos_t(_gl.camera)
    _gl.rotate_camera(FRAME_DT)
    _gl.move_camera(FRAME_DT)
    _moved = (_gl.camera_yaw != _yaw0) or (_pos_t(_gl.camera) != _pos0)
    check('C 控制帧：GL 在 ui_consumed=False 时相机真的动了（断言非恒真）', _moved,
          (_yaw0, _gl.camera_yaw, _pos0, _pos_t(_gl.camera)))
    # 消费帧：ui_consumed=True → 相机位姿不变（生产早退，runtime.py:306-316）
    _gl.ui_consumed = True
    _yaw1, _pitch1, _pos1 = _gl.camera_yaw, _gl.camera_pitch, _pos_t(_gl.camera)
    _gl.rotate_camera(FRAME_DT)
    _gl.move_camera(FRAME_DT)
    check('C GL 消费帧：相机位姿不变（rotate_camera/move_camera 的 ui_consumed 早退）',
          (_gl.camera_yaw, _gl.camera_pitch, _pos_t(_gl.camera)) == (_yaw1, _pitch1, _pos1),
          ((_yaw1, _pitch1, _pos1), (_gl.camera_yaw, _gl.camera_pitch, _pos_t(_gl.camera))))
    _ks[_key['LOOK_LEFT']] = False
    _ks[_key['CAMERA_FORWARD']] = False

# ---- VK：apply_editor_camera_mouse 的 ui_consumed 早退（本任务新增；bare driver 无窗口直驱） ----
def _vk_cam_driver():
    d = SD.SceneDriver()
    d._bridge_disabled = True                     # 只比相机，不建物理桥（快 + 无日志）
    d.build_scene_from_data(copy.deepcopy(
        {'version': _scene_contract.CURRENT_VERSION,
         'camera': {'target': [0, 0, 0], 'distance': 10.0, 'yaw': 0.6, 'pitch': -0.35},
         'cameras': [], 'active_camera': None, 'materials': [], 'lights': [], 'objects': []}))
    d.mouse_lock_allowed = True
    d.set_mouse_locked(True)
    return d


_d = _vk_cam_driver()
check('C 前提：VK 轨道相机就绪（orbit_mode / mouse_locked）',
      getattr(_d, 'orbit_mode', True) is True and _d.mouse_locked is True,
      (_d.orbit_mode, _d.mouse_locked))
# 控制帧：ui_consumed=False + 右键按住 + 增量 → yaw 真的转（断言非恒真）
_d.ui_consumed = False
_d.mouse_buttons = (False, False, True)
_d.feed_mouse_rel(30, 0)
_d.consume_mouse_input()
_yaw0 = _d.yaw
_d.apply_editor_camera_mouse()
check('C 控制帧：VK 在 ui_consumed=False 时相机真的转了（断言非恒真）',
      _d.yaw != _yaw0, (_yaw0, _d.yaw))
# 消费帧：ui_consumed=True + 同样的增量 → yaw/pitch 不变（不许让 VK 在 UI 拖动时开始转视角）
_d2 = _vk_cam_driver()
_d2.ui_consumed = True
_d2.mouse_buttons = (False, False, True)
_d2.feed_mouse_rel(30, 0)
_d2.consume_mouse_input()
_yaw1, _pitch1 = _d2.yaw, _d2.pitch
_d2.apply_editor_camera_mouse()
check('C VK 消费帧：相机位姿不变（apply_editor_camera_mouse 的 ui_consumed 早退；'
      '不许再靠「不喂」实现 —— 那条路已被裁决 A 打开）',
      (_d2.yaw, _d2.pitch) == (_yaw1, _pitch1), ((_yaw1, _pitch1), (_d2.yaw, _d2.pitch)))
# 滚轮不连坐：消费帧里滚轮照常推拉（与 GL editor._update_camera 的 B7-28 P-09 语义一致）
_d3 = _vk_cam_driver()
_d3.ui_consumed = True
_d3.mouse_wheel = 1
_dist0 = _d3.distance
_d3.apply_editor_camera_mouse()
check('C VK 消费帧：滚轮照常推拉相机（不连坐；GL editor._update_camera 同语义）',
      _d3.distance != _dist0, (_dist0, _d3.distance))


# ============================ D 组其余结构断言（读修后语义的镜像锚点） ============================
print()
print("=== D. 结构：镜像锚点（本门 vk_frame 与生产的逐行镜像关系） ===")
# 本门夹具的 VK 帧镜像生产 vk_player.draw 帧首。生产改（feed 去门控 / ui_consumed 写入），
# 夹具必须同步改 —— 该同步关系由 〇 段的 D-1/D-2/D-3 结构断言 + 本段的生产锚点共同守住。
src_has('render/vk/player.py', 'ui_bridge.begin_frame()', True, 'VK 帧首结算入口仍在')
src_has('runtime.py', 'def _dispatch_ui_mouse', True, 'GL 播放器的 UI 鼠标派发入口仍在')
src_has('render/vk/ui.py', 'def wants_camera', True,
        'VK 桥的消费位判据仍在（ui_consumed 的取值来源，不许删）')
src_has('render/gl/window.py', 'def _update_mouse_rel', True, 'GL 泵结算点仍在')


# ============================ 收尾 ============================
print()
print("=== 收尾：真窗口关闭（不把窗口/光标捕获带出进程） ===")
cleanup_ok = True
for i, pp in enumerate(_PAIRS):
    try:
        if getattr(pp.gl, 'mouse_locked', False):
            pp.gl.set_mouse_lock_allowed(False)
            pp.gl.set_mouse_locked(False)
        if getattr(pp.vk, 'mouse_locked', False):
            pp.vk.set_mouse_lock_allowed(False)
            pp.vk.set_mouse_locked(False)
        glfw.destroy_window(pp.vk_win)
    except Exception as e:
        cleanup_ok = False
        print('FAIL 收尾第 %d 对失败: %r' % (i + 1, e))
check('收尾：鼠标都未处于锁定态 + VK 句柄已销毁（不把光标捕获带出进程）', cleanup_ok)


print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
