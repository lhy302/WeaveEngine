# -*- coding: utf-8 -*-
"""test_ui_hit_parity.py — P3 面「UI 命中与焦点」两端对拍门（真窗口，2026-11-18）。

人类判据（docs/guides/开发要求_后端API一致_JVM模型.md 唯一上位判据）：
  「两种后端没有用户可感知的差异……如同 JVM 虚拟机在任何 CPU 上都保证字节码解析效果
    一样，不管选择什么后端对用户脚本的表现一致。」

本门验什么（Q-B7-37-1 P3）：**同一 UI 树 + 同一串鼠标/键盘/滚轮输入**喂进两端
**生产入口**，逐项比对用户可感知结果（不是「各自为 True」）。六组：
  ① 点击命中        同一光标位置 → 两端「命中的控件」是同一个（按 id/name 比，不比对象
                    地址）。覆盖：命中按钮 / 空白区 / 重叠控件（后加者在上）/ 移出画布；
                    并比「哪个控件的 on_click 真的被调了几次」（副作用，不是命中猜测）。
  ② 焦点与键盘      点击输入框后两端 _focused 是同一个控件；键盘/文本进同一个控件
                    （dispatch_key / dispatch_text 与内核入口都返回 True，文本内容一致）；
                    点别处两端一起失焦；无焦点时两端都不消费。
  ③ hover 状态      光标移动后两端「hover 中的控件集合」逐项相等（递归扫整棵树取
                    _hover=True 的名字集合，不是只看 UIManager._hovered 一个）。
  ④ 滚动消费        滚轮在**可滚** ScrollView 上 → 两端「是否被 UI 消费」相等且真滚动
                    （scroll_pos 逐值相等）；在不可滚 ScrollView / 按钮 / 空白上 → 两端
                    都不消费；**并且**两端「脚本可见的滚轮」逐值相等（消费了就不该再
                    给脚本，没消费就该给）。
  ⑤ UI 消费对引擎的屏蔽  点中按钮时两端都把这次点击从引擎交互路径上屏蔽
                    （GL ui_consumed=True / VK wants_camera()=False），点空白时两端都
                    不消费这次点击；点击全程两端 key_state 的「True 键集合」都保持为空
                    （键盘侧已由 test_input_chain_parity ⑥ 覆盖，这里补鼠标侧）。
  ⑥ 坐标系一致性    GL 的 mouse_pos（int 像素）与 VK 的 mouse_pos（F-6 刚补的 int 像素）
                    喂同一 UI 树 → 命中结果相同；逐值相等 + 逐元素 int + 固定期望表
                    （期望值由夹具的几何写死，不取自任何一端 = 防 DPI/原点/Y 轴翻转）。
  ⑦ 窗口 resize     两端窗口 640x400 -> 800x500 -> 200x100（低于下限 -> 钳到 320x240）：
                    「UI 画布尺寸 / anchor 布局结果 / 同一坐标的命中结果（含画布外）」逐项
                    相等，且各自 = 写死的期望表（Q-B7-41-1 修后新增）。
  ⑧ 跨帧持按        按住 UI 控件 / 空白区按下未松开 / 拖动滑条：每帧比
                    (GL ui_consumed, VK not wants_camera, 相机实际拿到的增量) 三元组逐项
                    相等（Q-B7-41-2 修后新增；增量口径见该组 press_step 的说明）。

两端生产入口（真窗口，不拼假对象；§5 反模式 8）：
  GL : runtime.PlayerApp(None, 640, 400, scene_data=空场景)
       —— **玩家实际发布的打包 GL 入口**（build_entry / game_player / --run 全走它），
          它的 UI 鼠标派发是 runtime.PlayerApp._dispatch_ui_mouse（runtime.py:244-279），
          由 _handle_events（runtime.py:281-285）每帧调用一次。
       · 光标 → loom_glfw_window._on_cursor_pos_cb（GLFW cursor_pos_callback 投递的同一
                函数，int 像素落点 render/gl/window.py:634-644）
       · 按键 → loom_glfw_window._on_mouse_button_cb（GLFW mouse_button_callback 同一函数）
       · 滚轮 → loom_glfw_window._on_scroll_cb（GLFW scroll_callback 同一函数）
       · 帧首 → app._handle_events()（生产泵：poll_events → pending → _dispatch_ui_mouse）
  VK : scene_driver.SceneDriver + 真 GLFW(NO_API) 窗口句柄（vk_player._register_input:525
       的真实注入点 driver._vk_glfw_window）
       · 光标/按键/滚轮 → vk_ui.UIInputBridge（生产桥，构造式与 render/vk/player.py:371 逐字相同）
       · 帧首 → vk_player.draw 帧首逐行镜像（Q-B7-43-2 修后：begin_frame →
                driver.ui_consumed 写入 → **无条件** feed_mouse_rel → 滚轮专属判据 →
                advance_logic；修前是 wants_camera 门控喂）—— 镜像保真由结构段源码
                锚点断言守住
       · int 像素落点 → SceneDriver._on_cursor_event（= vk_player._on_cursor:568 的生产调用）
  键盘/文本（两端同一份）→ 内核 EngineCore.handle_key_event 第③步 / handle_text_input
       （engine_core.py:185-196 / 227-244）—— 键与文本的 UI 派发**唯一写者**就在内核里。

夹具保真（§5 反模式 8 的牙）：两端都用**生产 UI 管理器** loom_ui.UIManager（GL 由
GLEngine.__init__ render/gl/engine.py:401-404 建、VK 由 SceneDriver.__init__ render/vk/driver.py:629-632
建），**不是**测试里新搭的假 UI；两端 UI 树由同一个 _build_ui() 用**同一批脚本级 API 调用**
搭出来（同一棵树 = 同一串用户脚本）；桥必须是生产类 vk_ui.UIInputBridge 且按生产构造式
包 driver.ui（见 〇 段的「桥 ui is driver.ui」断言）。

已知差异登记表：**必须为空**（KNOWN_DIFFS）。任何「差不多」/阈值/容差都不许。

修前红证据（2026-11-18，HEAD=bac4c14 实测，原文见提交信息与交付报告）：
  P3-1 组④红：滚轮停在**可滚 ScrollView** 上时，两端「脚本可见的滚轮」不等 ——
    GL engine.mouse_wheel=-3 / VK driver.mouse_wheel=0（同一串输入、同一棵树）。
    用户可感知路径：游戏脚本读 engine.mouse_wheel 做镜头缩放/切武器时，GL 在滚动列表
    的同时还会缩放/切换，VK 不会（同一份脚本两端表现不同）。
    缺陷归属（只报告不修）：GL 侧滚轮**没有**按「滚轮是否被 UI 消费」门控 ——
      · runtime.py:244-279 _dispatch_ui_mouse 只把 wheel 交给 dispatch_mouse，不回收
      · render/gl/window.py:441/475-477 _handle_events 无条件写 self.mouse_wheel
    参照实现（正确的一侧）：render/vk/player.py:656-666 + render/vk/ui.UIInputBridge.begin_frame
      （last_wheel_consumed / _wheel_taken_by_scrollview，2026-11-07 P-09 修复）。
    → 本门按「修前红」提交（照 P1/P2 先例）；GL 侧未改一行。

结构断言改名防护（B7-16 复查 P0-1 教训）：结构段用**递归**扫描定位生产文件（排除
tests/ 与 __pycache__/_tmp），并同时覆盖**当前名与历史名** ——
  · 命中测试只许在 ui/canvas/element.py + ui/canvas/manager.py（当前名 hit_test / _hit_screen；历史名/可能拷贝名
    _hit_test、hit_test_screen 一律不许出现在别的生产文件里）；
  · scene_driver 里 2026-10-18 被淘汰的 _DriverUI 空壳不得复活（历史名）；
  · 命中入口 _dispatch_ui_mouse 只许在 runtime.py（GL 播放器）与 editor.py（编辑器）里，
    VK 侧只许经 vk_ui.UIInputBridge（当前名 begin_frame / 历史名 on_key/on_text 已在
    test_vk_ui_input.py 静态断言里守住）。

两项相邻留痕已按人类裁决修掉（2026-11-18，本门扩到 ⑦/⑧ 组，修前必红证据见
交付报告与提交信息）：
  · ~~VK 侧没有 ui.resize 调用点（窗口 resize 后 UI 画布不跟随）~~ -> **Q-B7-41-1 已修**
    （裁决「判为缺陷，VK 补 ui.resize」）：唯一实现抽到共享前置 Loom/loom_ui_resize.py
    （口径与 GL _on_resize 逐条一致：int 截断 + 下限 320x240），vk_player.draw 帧首在
    begin_frame **之前**调用（与 GL「先 _on_resize 再 _dispatch_ui_mouse」同序）。
    门 = ⑦ 组；GL 一行未动（基准）。
  · ~~按住 UI 控件/在空白区按下未松开时 VK wants_camera()=False 而 GL ui_consumed=False~~
    -> **Q-B7-41-2 已修**（裁决「以 GL 为准」）：vk_ui.UIInputBridge 的 ui_active 改成
    **只看本帧** dispatch_mouse 的返回值（= GL 的 ui_consumed），跨帧的
    「按下未松开/拖动中/pointer-down 未 up」三个判据已删除（拖动滑条仍抢相机，因为
    dispatch_mouse 的拖动分支每帧返回 consumed=True）；render/vk/ui.py 里那段「与 GL 的
    ui_consumed 不同」的注释已同步删改为事实（反模式 10）。门 = ⑧ 组。

~~已知残差~~（**Q-B7-43-2 已修**，2026-11-22 人类裁决「选 A，并且同时给 VK 补 ui_consumed」）：
GL 的 engine.mouse_rel 在「本帧被 UI 消费」时仍是非 0（脚本可读）—— 现两端同语义：
VK 的 vk_player.draw 帧首也**无条件**喂（mouse_rel = 本帧物理增量），且消费位单独暴露为
driver.ui_consumed（= GL 的 PlayerApp.ui_consumed 同语义）。「消费帧相机不转」由相机
消费点的 ui_consumed 早退承担（GL: runtime.PlayerApp.move_camera/rotate_camera；
VK: SceneDriver.apply_editor_camera_mouse，编辑器路径两端共用 _EditorCore._ui_lock）。
门 = tests/test_mouse_rel_ui_consumed_parity.py（A/B/C/D 四组）；本门 ⑧ 组口径同步更新（夹具镜像 + 注释，断言表达式一字未改）。

Q-B7-43-1 修后（2026-11-18，**只改本门夹具 + 注释**，业务代码一行未动、断言表达式一字未改）：
  · 症状：本门 ①/②/③ 组偶发假红，签名 GL=('root','root',None,None) 而 VK 正确
    （干净 HEAD 也复现 → 与本轮任何改动无关，是夹具自身的竞态）。实测修前 2/20 次红。
  · 根因（实测日志见提交信息）：glfw.set_cursor_pos 底层是 Win32 SetCursorPos，
    **物理光标的落地是异步的**。修前 gl_frame 只「set_cursor_pos + 两次 poll_events」
    就当光标已到位，于是：
      (a) 生产 _on_mouse_button_cb 自己再读一次 glfw.get_cursor_pos
          （render/gl/window.py:657-661）时，回读到的是**上一个**落点 → 按下帧的
          e.mouse_pos 被写成上一帧的位置 → 命中全落 root（= 本门假红签名）；
      (b) 上一次 set_cursor_pos 产生的 WM_MOUSEMOVE 还排在消息队列里，晚一拍才被
          poll_events 派发，把 e.mouse_pos 覆盖回旧值。
    生产里两者都不存在：真实玩家的一次移动在 LBUTTONDOWN 之前一定已经投递完（Windows
    保证同一窗口鼠标消息相对有序），且生产只有一个玩家窗口。
  · 修法：新增夹具函数 settle_cursor()（见其注释）—— 注入事件前先「落点可见 + 队列
    静默」再喂 _on_cursor_pos_cb / _on_mouse_button_cb。**只是建输入前提**，不改任何
    check/seq_check 的表达式、不放宽任何语义、不加任何重跑逻辑。
  · 为什么没选「单窗口复用」：GL 侧的 GLFW 句柄由 runtime.PlayerApp / engine.GLEngine
    构造时自建并绑定 OpenGL 上下文，VK 侧要的是 NO_API 句柄；复用同一个句柄要么改业务
    代码（本任务禁止），要么让 VK 用 GL 的窗口 —— 那会污染 GL 的 GLFW 回调 user_pointer
    并让两端共用同一个 CURSOR 模式（等于改生产接线，且 ⑧ 组「两端一起上锁」就测不成了）。
  · 有牙证明（造业务回归仍必须红）：把 GL 的 runtime.PlayerApp._dispatch_ui_mouse 的
    ui_consumed 恒置 False → 本门 ⑤/⑧ 组当场红；还原后绿。见提交信息原文。
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_SAVE_MIGRATE'] = '1'
os.environ['LOOM_NO_PARALLEL'] = '1'
os.environ.setdefault('LOOM_NO_DIALOG', '1')

import glfw                                                      # noqa: E402
import pygame                                                    # noqa: E402

import loom_ui                                                   # noqa: E402  两端同一个生产 UI 管理器
import loom_ui_resize                                            # noqa: E402  ⑦ 的共享前置（VK 侧唯一实现）
import scene.contract as _scene_contract                                       # noqa: E402  场景版本号单点（不写死）
import runtime                                                   # noqa: E402  GL 打包播放器（生产入口）
import render.vk.driver as SD                                        # noqa: E402
import render.vk.player as vk_player                                                 # noqa: E402
import render.vk.ui as vk_ui                                                     # noqa: E402  夹具用生产那个桥类
from render.gl.window import (_on_cursor_pos_cb,                  # noqa: E402  GL 生产光标回调
                              _on_mouse_button_cb,               # noqa: E402  GL 生产鼠标键回调
                              _on_scroll_cb,                     # noqa: E402  GL 生产滚轮回调
                              _on_window_size_cb)                # noqa: E402  GL 生产窗口尺寸回调（⑦）
from loom_ui import (UIManager, Button, InputField, ScrollView,     # noqa: E402
                     Slider)                                      # noqa: E402  ⑧ 拖动门控夹具

ok = True
_PAIRS = []                       # 收尾统一释放

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


# ============================ 结构段：递归源码扫描 ============================

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


def _prod_py_files():
    """生产 .py 清单（排除 tests/ __pycache__/_tmp/archive）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in ('tests', '__pycache__', '_tmp', 'archive', '.git'))
        for fn in sorted(filenames):
            if fn.endswith('.py'):
                out.append(os.path.join(dirpath, fn))
    return out


_HIT_HOMES = ('ui/canvas/element.py', 'ui/canvas/manager.py')                # Q-B7-38-1 第7批: 命中实现搬进 ui/canvas/ 包 (原 loom_ui.py)
                # 仅元素基类 UIElement.hit_test + 容器 UIManager.hit_test/_hit_screen。
def _grep_prod(needle):
    """在生产 .py 里找 needle，返回 [(相对路径, 行号), ...]。"""
    hits = []
    for p in _prod_py_files():
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if needle in line:
                        hits.append((os.path.relpath(p, ROOT).replace('\\', '/'), i))
        except Exception:
            continue
    return hits


print("=== 〇. 结构：唯一 UI 管理器 / 唯一命中实现 / 两端生产派发入口 / 登记表 ===")
# ① 两端都用**生产那个** UIManager（不是各写一套 UI 树/命中）
src_has('render/gl/engine.py', 'self.ui = UIManager()', True,
        'GL 引擎的 UI 管理器是生产 loom_ui.UIManager（render/gl/engine.py:401）')
src_has('render/vk/driver.py', 'self.ui = UIManager()', True,
        'VK 驱动的 UI 管理器是同一个生产 UIManager（render/vk/driver.py:629）')
# 历史名：2026-10-18 淘汰的 _DriverUI 空壳不得复活（它没有命中测试 = VK 点不动 UI 的病灶）。
# 只查**代码用法**（class / 实例化）：render/vk/driver.py 的注释里提到这个名字是留痕，不算复活。
src_has('render/vk/driver.py', 'class _DriverUI', False,
        '历史空壳 _DriverUI 不得复活（淘汰于 72f513b；复活即 VK 又没命中实现）')
src_has('render/vk/driver.py', '_DriverUI(', False,
        '历史空壳 _DriverUI 不得被实例化（注释提及不算，代码用法才算）')
# ② 命中测试只有一份实现（当前名 hit_test / _hit_screen）
_hit_defs = [h for h in _grep_prod('def hit_test')] + [h for h in _grep_prod('def _hit_screen')]
_offenders = sorted({p for (p, _ln) in _hit_defs if p not in _HIT_HOMES})
check('结构：命中测试只由 loom_ui.py 实现（其它生产文件 0 处 def hit_test/_hit_screen）',
      not _offenders, '越界实现: %s' % _offenders)
check('结构：loom_ui.py 里恰好三处命中定义（UIElement.hit_test + UIManager.hit_test + '
      'UIManager._hit_screen 的内部规则）',
      len([1 for (p, _l) in _hit_defs if p in _HIT_HOMES]) == 3, _hit_defs)
# 历史名 / 可能拷贝名：别的文件里不许出现命中测试的改名副本
for _hist in ('def _hit_test(', 'def hit_test_screen(', 'def _hit_test_screen('):
    _h = _grep_prod(_hist)
    check('结构：历史名 %r 在全部生产文件里不存在（改名拷贝不得复活）' % _hist, not _h, _h[:4])
# ③ 两端各自的**生产** UI 鼠标派发入口仍在（漂移 = 门失真，必须当场红）
src_has('runtime.py', 'def _dispatch_ui_mouse', True,
        'GL 打包播放器的 UI 鼠标派发入口仍在（runtime.py:244）')
src_has('runtime.py', 'ui.dispatch_mouse(', True, 'GL 播放器确实把事件交给 UIManager')
src_has('runtime.py', 'ui.update_hover_only(', True,
        'GL 播放器未被消费时仍更新 hover（与 VK 桥同序）')
src_has('runtime.py', 'self._dispatch_ui_mouse()', True, 'GL 播放器帧首真的调它（:285）')
src_has('render/vk/ui.py', 'consumed = bool(ui.dispatch_mouse(self.pos, pressed, released, wheel))',
        True, 'VK 生产桥确实把事件交给同一个 UIManager（render/vk/ui.py:859）')
src_has('render/vk/ui.py', 'ui.update_hover_only(self.pos)', True, 'VK 桥未被消费时也更新 hover')
src_has('render/vk/player.py', "UIInputBridge(getattr(driver, 'ui', None))", True,
        '生产构造式：桥包的就是 driver.ui（render/vk/player.py:371）')
src_has('render/vk/player.py', 'ui_bridge.begin_frame()', True, 'VK 帧首真的结算（render/vk/player.py:649）')
src_has('render/vk/player.py', '_wheel_taken_by_scrollview(_ui_now, ui_bridge.pos)', True,
        'VK 滚轮专属判据的生产调用点仍在（render/vk/player.py:662-663）')
# VK 不许另写一套 GL 播放器的派发（一个功能一个文件，规则 5/6）
src_has('render/vk/ui.py', 'def _dispatch_ui_mouse', False,
        'VK 不得复制 GL 播放器的派发函数（同一件事只许一份实现）')
src_has('runtime.py', 'class UIManager', False, 'GL 播放器不得自带第二份 UIManager 实现')
# ④ 两端 int 像素光标落点（组⑥的判据基础；F-6 刚补的 VK 侧）
src_has('render/gl/window.py', 'e.mouse_pos = (int(x), int(y))', True,
        'GL 的 mouse_pos 是 int 像素（render/gl/window.py:638）')
src_has('render/vk/driver.py', 'self.mouse_pos = (int(x), int(y))', True,
        'VK 的 mouse_pos 也是 int 像素（render/vk/driver.py:1762，F-6）')
# ⑤ 键/文本的 UI 派发唯一写者在内核（两端同一份）
src_has('core/engine_core.py', 'ui.dispatch_key(k, getattr(ev, \'mod\', 0) or 0)', True,
        '内核第③步是键的 UI 派发唯一写者（core/engine_core.py:193）')
src_has('core/engine_core.py', 'ui.dispatch_text(text)', True,
        '内核 handle_text_input 是文本的 UI 派发唯一写者（core/engine_core.py:235）')
check('已知差异登记表为空（不许登记任何容差）', not KNOWN_DIFFS, KNOWN_DIFFS)

# ⑥ ⑦/⑧ 两面的**生产调用点**锚点（漂移 = 门失真，必须当场红）
# Q-B7-41-1：VK 生产帧首必须把 UI 画布同步到窗口尺寸（GL 基准是 _on_resize）
src_has('render/vk/player.py', 'sync_ui_canvas(_ui_now,', True,
        'VK 生产帧首调 UI 画布同步（Q-B7-41-1；参数 = driver.ui + 宿主窗口句柄 + 兜底尺寸）')
_vp_src = _read_prod('render/vk/player.py') or ''
_i_sync = _vp_src.find('sync_ui_canvas(_ui_now,')
_i_begin = _vp_src.find('ui_bridge.begin_frame()')
check('结构：VK 的 UI 画布同步排在 begin_frame **之前**（与 GL「先 _on_resize 再 '
      '_dispatch_ui_mouse」同序，否则本帧命中用旧画布尺寸）',
      0 <= _i_sync < _i_begin, (_i_sync, _i_begin))
_resize_defs = _grep_prod('def sync_ui_canvas')
check('结构：UI 画布同步只由 loom_ui_resize.py 实现（其它生产文件 0 处）',
      [p for (p, _l) in _resize_defs] == ['loom_ui_resize.py'], _resize_defs)
_ui_resize_calls = []
for _p in _prod_py_files():
    try:
        with open(_p, 'r', encoding='utf-8', errors='replace') as _f:
            for _ln, _line in enumerate(_f, 1):
                if _line.strip().startswith('#'):
                    continue          # 注释里提到 ui.resize(...) 不算调用点（反模式 10 的注释≠代码）
                if 'ui.resize(' in _line:
                    _ui_resize_calls.append(
                        (os.path.relpath(_p, ROOT).replace('\\', '/'), _ln))
    except Exception:
        continue
check('结构：ui.resize 的生产调用点恰好 2 处（GL 基准 render/gl/window.py + VK 侧唯一'
      '实现 loom_ui_resize.py）—— 修前 VK 侧是 0 处（Q-B7-41-1）',
      len(_ui_resize_calls) == 2
      and sorted({p for (p, _l) in _ui_resize_calls})
      == ['loom_ui_resize.py', 'render/gl/window.py'],
      _ui_resize_calls)
src_has('render/gl/window.py', 'ui.resize(self.width, self.height)', True,
        'GL 的 _on_resize 仍是基准（本任务 GL 一行未动）')
src_has('loom_ui_resize.py', 'max(UI_MIN_W, int(w)), max(UI_MIN_H, int(h))', True,
        'VK 侧钳制口径与 GL 同值（320x240 + int 截断）')
# Q-B7-41-2：VK 的相机门控只看**本帧**消费位（以 GL 为准），跨帧判据不得复活
src_has('runtime.py', 'self.ui_consumed = consumed', True,
        'GL 的基准语义仍在：ui_consumed 只看本帧 dispatch_mouse 的返回值')
src_has('render/vk/ui.py', 'self.ui_active = bool(consumed)', True,
        'VK 的相机门控 = 本帧消费位（Q-B7-41-2「以 GL 为准」）')
src_has('render/vk/ui.py', "for attr in ('_pressed_elem', '_dragging_elem', '_last_pointer_down')",
        False, '跨帧持按判据不得复活（Q-B7-41-2 修前的差异来源）')


# ============================ 夹具（真窗口，生产构造式） ============================

def _build_ui(mgr, clicks):
    """用**同一批脚本级 API** 在两端各搭同一棵树（同一棵树 = 同一串用户脚本）。

    画布 640x400（= 窗口尺寸），几何（像素，y 向下）：
      btn         (20, 20,120,32)   x∈[20,140) y∈[20,52)
      inp         (20, 70,220,30)   x∈[20,240) y∈[70,100)
      sv          (300,100,200,150) 可滚（内容 200x800）; 子 inner(10,10,100,32)
                  → 屏幕 x∈[310,410) y∈[110,142)
      svn         (300,280,200,60)  不可滚（内容 200x60）
      ov_bottom   (20,300,100,40)   x∈[20,120) y∈[300,340)
      ov_top      (40,310,100,40)   x∈[40,140) y∈[310,350)  ← **后加 = 画在上面**
    """
    c = mgr.canvases[0]
    btn = Button(name='btn', rect=(20, 20, 120, 32), text='OK',
                 on_click=lambda: clicks.append('btn'))
    inp = InputField(name='inp', rect=(20, 70, 220, 30),
                     on_submit=lambda t: clicks.append('submit:' + t))
    sv = ScrollView(name='sv', rect=(300, 100, 200, 150), content_size=(200, 800))
    sv.add_child(Button(name='inner', rect=(10, 10, 100, 32), text='IN',
                        on_click=lambda: clicks.append('inner')))
    svn = ScrollView(name='svn', rect=(300, 280, 200, 60), content_size=(200, 60))
    ov_bottom = Button(name='ov_bottom', rect=(20, 300, 100, 40), text='B',
                       on_click=lambda: clicks.append('ov_bottom'))
    ov_top = Button(name='ov_top', rect=(40, 310, 100, 40), text='T',
                    on_click=lambda: clicks.append('ov_top'))
    for e in (btn, inp, sv, svn, ov_bottom, ov_top):
        c.root.add_child(e)
    return {'btn': btn, 'inp': inp, 'sv': sv, 'svn': svn,
            'ov_bottom': ov_bottom, 'ov_top': ov_top}


class Pair:
    """一对生产后端 + 各自的生产 UI 派发入口（同一串事件喂两边）。"""

    def __init__(self):
        # GL：打包播放器（真 GLFW 窗口 + 生产 UI 鼠标派发）
        self.gl = runtime.PlayerApp(None, W, H, scene_data=_EMPTY_SCENE)
        self.gl.is_playing = True
        # VK：真 GLFW(NO_API) 窗口句柄（= vk_player._register_input:525 的真实注入点）
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        self.vk_win = glfw.create_window(W, H, 'Loom parity (ui hit gate)', None, None)
        glfw.window_hint(glfw.CLIENT_API, glfw.OPENGL_API)   # 还原提示，防污染后续 GL 窗口
        self.vk = SD.SceneDriver()
        self.vk.is_playing = True
        self.vk._vk_glfw_window = self.vk_win
        # 生产里两端 UI 画布尺寸都等于窗口尺寸：GL 由 loom_glfw_window._on_resize
        # （:258-263）同步；VK 在 SceneDriver.__init__（:629-632）按 width/height 建
        # （构造默认 1280x800）。本夹具两端窗口同为 640x400，故把 VK 画布显式对齐到
        # 同一尺寸 —— 只对齐「窗口尺寸」这个前提，不改任何命中/布局逻辑。
        # （VK 侧没有 ui.resize 调用点这件事本身见文件头「留痕」。）
        self.vk.ui.resize(W, H)
        # Q-B7-34-1：桥必须是生产那个类，构造式与生产逐字相同（render/vk/player.py:371）
        self.bridge = vk_ui.UIInputBridge(getattr(self.vk, 'ui', None))
        self.clicks_gl = []
        self.clicks_vk = []
        self.elems_gl = _build_ui(self.gl.ui, self.clicks_gl)
        self.elems_vk = _build_ui(self.vk.ui, self.clicks_vk)
        # 生产不变量：玩家窗口持焦点（本进程里同时活着两个真窗口，后建的会抢焦点）
        glfw.focus_window(self.gl._glfw_win)
        for _ in range(4):
            try:
                glfw.poll_events()
            except Exception:
                pass
        self._prev = None            # VK 侧上一帧光标 (vk_player.draw 的 _prev)
        _PAIRS.append(self)

    # ---------------- ⑦ 窗口 resize（两端生产路径） ----------------
    def resize_both(self, w, h):
        """两端窗口一起改到 (w,h)，并各自走**生产**的尺寸同步路径。

        GL : glfw.set_window_size -> WM_SIZE -> loom_glfw_window._on_window_size_cb
             -> _on_resize -> ui.resize(...)（生产回调；本进程里 WM 投递可能晚一拍，
             所以再显式调**同一个回调**一次 = 等价事件注入，同本门其它事件的注入方式。
             回调参数取窗口**实际**尺寸（get_window_size 回读 = 独立判据）。
        VK : glfw.set_window_size -> 下一帧 vk_player.draw 帧首 sync_ui_canvas
             （读 get_window_size = 与 GL 同源；见 vk_frame 的镜像）。
        """
        gw = self.gl._glfw_win
        glfw.set_window_size(gw, w, h)
        glfw.set_window_size(self.vk_win, w, h)
        pump(4, 0.02)
        _gw = tuple(int(v) for v in glfw.get_window_size(gw))
        _on_window_size_cb(gw, _gw[0], _gw[1])          # GL 生产回调（同一函数）
        self.vk_frame(*(self.bridge.pos))                # VK 生产帧（帧首同步画布）
        _vw = tuple(int(v) for v in glfw.get_window_size(self.vk_win))
        return (_gw, _vw)

    # ---------------- ⑧ 鼠标上锁（生产脚本 API） ----------------
    def lock_both(self):
        """两端一起上锁 + 两端增量基线一起重锚（= 一帧吸收帧）。

        GL 的增量基线是 loom_glfw_window._prev_cursor（生产 _update_mouse_rel 里用）；
        VK 的增量基线是 vk_player._apply_cursor_mode 置空的 _prev（生产同款吸收帧）。
        本进程里同时活着多对真窗口：任一侧切 CURSOR_DISABLED 时 GLFW 会把物理光标挪进
        该窗口 -> 另一侧收到一条 raw motion（P2 门踩过的伪影），故先 pump 排空再重锚。
        """
        self.gl.set_mouse_lock_allowed(True)
        self.vk.set_mouse_lock_allowed(True)
        self.gl.set_mouse_locked(True)
        self.vk.set_mouse_locked(True)
        pump(3, 0.02)
        try:
            self.gl._prev_cursor = None
        except Exception:
            pass
        self._prev = None
        return (bool(self.gl.mouse_locked), bool(self.vk.mouse_locked))

    # ---------------- GL 生产帧 ----------------
    def gl_frame(self, x, y, press=False, release=False, wheel=0):
        """GL 生产帧：GLFW 投递光标/按键/滚轮 → 生产泵（poll + 结算）→ 生产 UI 派发。

        与真实运行时的同帧顺序一致（GLFW 回调 -> loom_glfw_window._handle_events ->
        runtime.PlayerApp._dispatch_ui_mouse）。物理光标先落到位，是因为生产
        _on_mouse_button_cb 会自己读 glfw.get_cursor_pos（render/gl/window.py:657-661）；
        手动再喂一次 _on_cursor_pos_cb 是因为本进程里窗口不持真实鼠标焦点时 WM_MOUSEMOVE
        会晚一个 poll 才到 —— 喂的是 **GLFW 投递的同一个函数**（等价事件注入，同 P2 门）。
        Q-B7-43-1（夹具竞态）：物理光标落地是**异步**的，所以注入前必须先 settle_cursor()
        把落点与消息队列都排空（见该函数注释），否则按下帧的 mouse_pos 会被写成上一帧
        的位置（假红）。这只建前提，不动任何断言。
        Q-B7-43-2（P0-1）：settle 的收敛判据已收成「只看回读」（旧判据在 ⑧ 组的
        CURSOR_DISABLED 下永不收敛，每帧空转 40 次重落，重落位移会泄进 engine.mouse_rel）。
        所有重落都发生在 self.gl._handle_events()（= pump）**之前**；断言帧不额外 settle。
        """
        win = self.gl._glfw_win
        glfw.set_cursor_pos(win, x, y)
        # Q-B7-43-1：先把「物理光标真的落在 (x,y) + 这次移动的消息已派发干净」建好，
        # 再注入光标/按键/滚轮（修前只 poll 两次 = 少这一拍，偶发把 mouse_pos 写成上一帧
        # 的位置 → ①/② 组假红 GL=('root','root',None,None)）。
        settle_cursor(win, self.gl, x, y)
        _on_cursor_pos_cb(win, x, y)
        if press:
            _on_mouse_button_cb(win, glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)
        if release:
            _on_mouse_button_cb(win, glfw.MOUSE_BUTTON_LEFT, glfw.RELEASE, 0)
        if wheel:
            _on_scroll_cb(win, 0, wheel)
        self.gl._handle_events()          # 生产泵 + _dispatch_ui_mouse
        return {
            'pos': tuple(self.gl.mouse_pos),
            'consumed': bool(self.gl.ui_consumed),
            'wheel': int(self.gl.mouse_wheel),
            'rel': tuple(self.gl.mouse_rel),  # ⑧：生产泵结算出的本帧增量
            'keys_true': tuple(sorted(k for k, v in (self.gl.key_state or {}).items() if v)),
        }

    # ---------------- VK 生产帧 ----------------
    def vk_frame(self, x, y, press=False, release=False, wheel=0):
        """VK 生产帧：vk_player 回调逐行镜像 + draw:646-674 帧首逐行镜像。"""
        # ---- vk_player._on_cursor:560-568 ----
        self.bridge.on_cursor(x, y)
        self.vk._on_cursor_event(x, y)          # F-6 的 int 像素落点（生产唯一实现）
        # ---- vk_player._on_mouse_button:573-581 ----
        if press or release:
            lst = list(self.vk.mouse_buttons)
            lst[0] = bool(press)
            self.vk.mouse_buttons = tuple(lst)
        if press:
            self.bridge.on_mouse_button(1, True)
        if release:
            self.bridge.on_mouse_button(1, False)
        # ---- vk_player._on_scroll:583-587 ----
        if wheel:
            self.bridge.on_scroll(wheel)
        # ---- vk_player.draw:646-666 ----
        _ui_now = getattr(self.vk, 'ui', None)
        if _ui_now is not None and _ui_now is not self.bridge.ui:
            self.bridge.ui = _ui_now
        # ---- vk_player.draw 帧首（Q-B7-41-1）：UI 画布跟随窗口尺寸 ----
        # 生产那一行是 sync_ui_canvas(_ui_now, driver._vk_glfw_window, (w, h))
        # （loom_ui_resize 唯一实现）；这里逐行镜像，句柄取生产同一个注入点。
        if not getattr(self.vk, 'fullscreen', False):   # 与 GL _on_window_size_cb 同款门控
            loom_ui_resize.sync_ui_canvas(_ui_now,
                                          getattr(self.vk, '_vk_glfw_window', None),
                                          None)
        self.bridge.begin_frame()
        # Q-B7-43-2（2026-11-22 裁决 A）：生产 vk_player.draw 帧首改为「begin_frame →
        # driver.ui_consumed 写入 → **无条件** feed」—— 修前的 wants_camera 门控已删，
        # 本夹具逐行镜像同步（镜像漂移由 〇 段结构锚点守住）。
        self.vk.ui_consumed = (not self.bridge.wants_camera())
        _x, _y = self.bridge.pos
        _fed = (0, 0)                    # 本帧喂给 driver 的物理增量（裁决 A：无条件）
        if self._prev is not None:
            _fed = (_x - self._prev[0], _y - self._prev[1])
            self.vk.feed_mouse_rel(_fed[0], _fed[1])
        self._prev = (_x, _y)
        _wh = self.bridge.last_wheel
        if _wh:
            _taken = (self.bridge.last_wheel_consumed
                      and vk_ui._wheel_taken_by_scrollview(_ui_now, self.bridge.pos))
            if not _taken:
                self.vk.mouse_wheel += _wh
                self.bridge.last_wheel_consumed = False
        # 脚本在**本帧** update_scripts 里读到的值（advance_logic 帧末才清）
        wheel_visible = int(self.vk.mouse_wheel)
        # ---- vk_player.draw:670-674 ----
        self.vk.advance_logic(FRAME_DT)
        return {
            'pos': tuple(self.bridge.pos),
            'consumed': bool(self.bridge.last_consumed),
            'wheel_consumed': bool(self.bridge.last_wheel_consumed),
            'wants_camera': bool(self.bridge.wants_camera()),
            'wheel': wheel_visible,
            'cam_rel': ((0, 0) if bool(self.vk.ui_consumed) else tuple(_fed)),
            # ⑧：相机实际拿到的增量 —— Q-B7-43-2 修后口径：喂入无条件（裁决 A），但
            # 相机消费点（apply_editor_camera_mouse / 脚本消费路径）在 ui_consumed=True
            # 时早退（对齐 GL PlayerApp.move_camera/rotate_camera 早退），消费帧 = (0,0)。
            'rel': tuple(self.vk.mouse_rel),  # ⑧ 对照用（driver 结算值 = 本帧物理增量）
            'keys_true': tuple(sorted(k for k, v in (self.vk.key_state or {}).items() if v)),
        }

    def frame(self, x, y, press=False, release=False, wheel=0):
        return (self.gl_frame(x, y, press, release, wheel),
                self.vk_frame(x, y, press, release, wheel))

    # ---------------- 两端可观察状态（同一套口径） ----------------
    def ui_state(self, x, y):
        """两端 UI 状态快照（按 name 比，不比对象地址）。"""
        out = []
        for mgr, pos in ((self.gl.ui, self.gl.mouse_pos), (self.vk.ui, self.bridge.pos)):
            _c, elem = mgr.hit_test(pos)
            out.append({
                'hit': getattr(elem, 'name', None),
                'hovered': getattr(getattr(mgr, '_hovered', None), 'name', None),
                'pressed': getattr(getattr(mgr, '_pressed_elem', None), 'name', None),
                'focused': getattr(mgr.focused(), 'name', None),
                'hoverset': tuple(sorted(e.name for e in mgr.canvases[0].root.walk()
                                         if getattr(e, '_hover', False))),
            })
        return out

    def click_counts(self):
        from collections import Counter
        return (tuple(sorted(Counter(self.clicks_gl).items())),
                tuple(sorted(Counter(self.clicks_vk).items())))


# ==================== Q-B7-43-1：物理光标落点/消息队列排空协议 ====================

_SETTLED_AT = {}          # id(win) -> 上一次已排空到位的注入点（pyglfw 的 window 不可哈希）


def settle_cursor(win, eng, x, y, maxit=40, dt=0.002, stable=3):
    # stable=3（Q-B7-43-2）：比原来多一轮静默确认 = 多一个「吸收帧」，把重落/迟到
    # 的 WM_MOUSEMOVE 全部排空在 pump 之前；重落本身仍只发生在 pump 之前。
    """把物理光标真的落到 (x,y)，并把这次移动产生的 WM_MOUSEMOVE 全部派发干净。

    **这是夹具的输入前提，不是断言、不是重跑**（不碰任何 check 的表达式，不改任何被测
    语义；只在注入事件之前把「玩家真的把鼠标移到这里了」这个前提建好）。

    为什么必须先做（Q-B7-43-1 修前偶发假红的根因，实测证据见提交信息）：
      glfw.set_cursor_pos 底层是 Win32 SetCursorPos，**物理光标的落地是异步的**：
        · 紧跟着的 glfw.get_cursor_pos（= GetCursorPos + ScreenToClient，读物理光标）
          可能仍回读到**上一个**落点 —— 而生产 _on_mouse_button_cb 正是自己再读一次
          get_cursor_pos 来定 e.mouse_pos（render/gl/window.py:657-661），于是「按下
          帧」的 mouse_pos 被写成上一帧的位置 → 命中全落 root。本门 ①/② 组偶发假红的
          签名 GL=('root','root',None,None) 就是它。
        · 上一次 set_cursor_pos 产生的 WM_MOUSEMOVE 还可能排在消息队列里，晚一拍才被
          poll_events 派发，把 e.mouse_pos 覆盖回旧值。
      生产里这两件事都不可能发生：真实玩家的一次移动在 LBUTTONDOWN 之前一定已经投递完
      （Windows 保证同一窗口的鼠标消息相对有序），而且生产只有一个玩家窗口。夹具用
      set_cursor_pos 代替「玩家的手」，就必须先复刻这个顺序，再注入按键/滚轮。
      修前本门用「set_cursor_pos + 两次 poll_events」代替这一步 —— 少的就是这一拍。

    判据（两个阶段合成一个循环）：
      · 窗口内坐标：要求 glfw.get_cursor_pos（= 物理/虚拟光标的**回读**）等于注入点；
        **不看** engine.mouse_pos（★Q-B7-43-2，理由见下）；
      · 画布外坐标（如 (-50,-50)）：物理光标会被桌面边界钳住，回读永远 != 注入点，
        退而求其次要求「回读已经真的动过（!= 注入前的值，或上一帧就注入的同一坐标）」
        且随后连续 stable 次不再变化（= 这次投递已落地、队列已静默）。
    返回 True = 排空到位；False = 到上限仍未到位（此时照旧往下走，红不红由断言决定 ——
    夹具**不**吞掉任何判定）。

    ★Q-B7-43-2（P0-1，2026-11-19）：判据从「回读 == 注入点 **且** engine.mouse_pos ==
    注入点」收成「回读 == 注入点」。为什么必须收（实测，不是推测）：
      · 生产读光标的两个地方读的都是 glfw.get_cursor_pos —— _on_mouse_button_cb
        （render/gl/window.py:657-661）与 _update_mouse_rel（:537），**不是** mouse_pos；
        mouse_pos 由 gl_frame 随后显式注入的 _on_cursor_pos_cb(win, x, y) 兜底；
      · CURSOR_DISABLED（⑧ 组 lock_both 之后）下 set_cursor_pos 只把**虚拟坐标**置为
        (x,y)、物理光标回窗口中心，**不派发** cursor_pos 回调 -> engine.mouse_pos 停在
        上一帧的值 -> 旧判据在本组**永不收敛**，每帧空转满 40 次重落。
        实测（_tmp 探针，1 次运行）：settle 调用 64 次，命中 maxit(40) 15 次，其中 ⑧ 组
        12 帧**全部**命中 = 每帧 40 次重落 = 480 次/次运行。
      · 这 480 次重落是**夹具自己造的物理位移**（不是玩家输入）。它们产生的
        WM_MOUSEMOVE 一旦晚于 settle 返回才被 poll 派发，就会在 CURSOR_DISABLED 下把
        虚拟光标顶偏，而 ⑧ 组把 engine.mouse_rel 当「相机实际拿到的增量」的取值来源 ->
        **夹具副作用被测成被测值**（§5 反模式 3/8）。审核实测签名（连跑 35 次红 1 次）：
          FAIL ⑧ 空白持按第 2 帧 右下移 (540,370)：GL=(134,137) VK=(20,10)
          FAIL ⑧ 空白区松开：GL=(-114,-127)
        两条正好是「顶偏 (+114,+127) 再原样回吐 (-114,-127)」的一对。
      · 收成只看回读后：⑧ 组每帧重落 1~2 次（收敛即停），夹具不再自造位移；
        判据本身没放宽（回读 == 注入点仍是硬前提，排空/静默仍要连续 stable 次确认）。
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
            # ★Q-B7-43-2：判据只看**回读**（见函数注释）。旧写法 (rb == t and mp == t)
            # 在 CURSOR_DISABLED 下永不收敛 -> 每帧空转 40 次重落 -> 夹具自造位移。
            same = (rb == t)
            if not same:
                # 切 CURSOR_DISABLED 后的首个轮询，GLFW 3.4 会把虚拟坐标重置为物理
                # 光标位置；这里再落一次 = 玩家把鼠标又移回注入点，直到回读收敛。
                # **只在回读没到位时才落**：每落一次都是夹具自造的物理位移，越少越好。
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


def pump(n=15, dt=0.02):
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
        print('    %-30s GL=%-46s VK=%s' % (lb, g, v))
    check(title, not bad,
          '；'.join('%s: GL=%s VK=%s' % (lb, g, v) for (lb, g, v) in bad[:3])
          if bad else '%d 步逐项相等' % len(rows))


# ============================ 夹具保真（反模式 8 的牙） ============================
print()
print("=== 夹具保真：两端都是生产 UIManager + 生产派发入口 ===")
p = Pair()
check('GL 的 UI 管理器是生产 loom_ui.UIManager（不是测试自搭的假 UI）',
      type(p.gl.ui) is UIManager, type(p.gl.ui).__name__)
check('VK 的 UI 管理器是生产 loom_ui.UIManager（同一个类，不是 _DriverUI 空壳）',
      type(p.vk.ui) is UIManager, type(p.vk.ui).__name__)
check('两端 UI 树由同一批脚本级 API 搭出：同名同序',
      [e.name for e in p.gl.ui.canvases[0].root.children]
      == [e.name for e in p.vk.ui.canvases[0].root.children],
      ([e.name for e in p.gl.ui.canvases[0].root.children],
       [e.name for e in p.vk.ui.canvases[0].root.children]))
check('桥是生产那个类 vk_ui.UIInputBridge，且按生产构造式包的 ui is driver.ui',
      isinstance(p.bridge, vk_ui.UIInputBridge) and p.bridge.ui is p.vk.ui,
      'bridge=%s bridge.ui id=%r driver.ui id=%r'
      % (type(p.bridge).__name__, id(p.bridge.ui), id(p.vk.ui)))
check('两端 UI 画布尺寸 = 各自窗口尺寸（命中坐标系同源）',
      (p.gl.ui.canvases[0].width, p.gl.ui.canvases[0].height) == (W, H)
      and (p.vk.ui.canvases[0].width, p.vk.ui.canvases[0].height) == (W, H),
      ((p.gl.ui.canvases[0].width, p.gl.ui.canvases[0].height),
       (p.vk.ui.canvases[0].width, p.vk.ui.canvases[0].height)))
check('GL 走的是打包播放器的生产派发（PlayerApp._dispatch_ui_mouse），不是测试自写',
      type(p.gl).__name__ == 'PlayerApp' and callable(getattr(p.gl, '_dispatch_ui_mouse', None)),
      type(p.gl).__name__)


# ============================ ① 点击命中 ============================
print()
print("=== ①. 点击命中：同一光标位置 + 同一 UI 树 → 同一个控件（按钮/空白/重叠/画布外） ===")
rows = []
rows_state = []
rows_abs = []


def step1(label, x, y, press=False, release=False, expect_hit=None):
    p.frame(x, y, press, release)
    g, v = p.ui_state(x, y)
    key = (g['hit'], g['hovered'], g['pressed'], g['focused'])
    rows_state.append((label, key, (v['hit'], v['hovered'], v['pressed'], v['focused'])))
    rows.append((label, key, (v['hit'], v['hovered'], v['pressed'], v['focused'])))
    cc = p.click_counts()
    rows.append((label + ' ·点击回调', cc[0], cc[1]))
    if expect_hit is not None:
        rows_abs.append((label, expect_hit, g['hit'], v['hit']))
    return g, v


step1('悬停空白 (500,350)', 500, 350, expect_hit='root')
step1('悬停按钮 (50,36)', 50, 36, expect_hit='btn')
step1('按下按钮 (50,36)', 50, 36, press=True, expect_hit='btn')
step1('松开按钮 (50,36)', 50, 36, release=True, expect_hit='btn')
step1('悬停重叠 (60,320)', 60, 320, expect_hit='ov_top')
step1('按下重叠 (60,320)', 60, 320, press=True, expect_hit='ov_top')
step1('松开重叠 (60,320)', 60, 320, release=True, expect_hit='ov_top')
step1('悬停下层独有区 (30,305)', 30, 305, expect_hit='ov_bottom')
step1('按下下层 (30,305)', 30, 305, press=True, expect_hit='ov_bottom')
step1('松开下层 (30,305)', 30, 305, release=True, expect_hit='ov_bottom')
step1('滚区空白 (350,150)', 350, 150, expect_hit='sv')
step1('滚区内按钮 (320,120)', 320, 120, expect_hit='inner')
step1('移出画布 (-50,-50)', -50, -50, expect_hit='root')
step1('画布外按下 (-50,-50)', -50, -50, press=True, expect_hit='root')
step1('画布外松开 (-50,-50)', -50, -50, release=True, expect_hit='root')
seq_check('① 点击命中：命中/悬停/按下/焦点 + 点击回调次数，两端逐项相等', rows)
check('① 命中结果与**夹具几何**写死的期望表逐项相等（不取自任何一端）',
      all(e == g == v for (_l, e, g, v) in rows_abs),
      [r for r in rows_abs if not (r[1] == r[2] == r[3])][:3])
check('① 重叠控件「后加者在上」：两端都命中 ov_top（不是 ov_bottom）',
      rows_state[4][1][0] == rows_state[4][2][0] == 'ov_top'
      and rows_state[7][1][0] == rows_state[7][2][0] == 'ov_bottom',
      (rows_state[4][1][0], rows_state[4][2][0],
       rows_state[7][1][0], rows_state[7][2][0]))
check('① 点按钮真的触发一次 on_click（副作用也一致，不是「命中猜对了但没派发」）',
      p.click_counts()[0] == p.click_counts()[1]
      and dict(p.click_counts()[0]).get('btn') == 1
      and dict(p.click_counts()[1]).get('btn') == 1,
      (p.click_counts()[0], p.click_counts()[1]))
check('① 重叠区按下/松开只给上层控件计一次点击（下层 0 次，两端同）',
      dict(p.click_counts()[0]).get('ov_top') == 1
      and dict(p.click_counts()[0]).get('ov_bottom') == 1
      and dict(p.click_counts()[1]).get('ov_top') == 1
      and dict(p.click_counts()[1]).get('ov_bottom') == 1,
      (p.click_counts()[0], p.click_counts()[1]))
check('① 移出画布时两端都不把点击算给任何控件（空白 root 吞事件、无回调）',
      p.ui_state(-50, -50)[0]['pressed'] is None and p.ui_state(-50, -50)[1]['pressed'] is None,
      (p.ui_state(-50, -50)[0]['pressed'], p.ui_state(-50, -50)[1]['pressed']))


# ============================ ② 焦点与键盘 ============================
print()
print("=== ②. 焦点与键盘：点输入框 → 同一个 _focused → 键/文本进同一个控件 ===")
from types import SimpleNamespace


def key_ev(k):
    return SimpleNamespace(type='KEYDOWN', key=k, mod=0, unicode='')


def text_ev(t):
    return SimpleNamespace(type='TEXTINPUT', text=t)


rows = []
step2 = step1
# 焦点：点输入框
step2('按下输入框 (60,85)', 60, 85, press=True, expect_hit='inp')
step2('松开输入框 (60,85)', 60, 85, release=True, expect_hit='inp')
g, v = p.ui_state(60, 85)
check('② 点输入框后两端 _focused 是同一个控件（按 name 比）',
      g['focused'] == v['focused'] == 'inp', (g['focused'], v['focused']))
rows.append(('点输入框后 focused', g['focused'], v['focused']))

# 文本（生产入口：内核 handle_text_input 第①步派发 UI）
r_gl = p.gl.handle_text_input(text_ev('abc'))
r_vk = p.vk.handle_text_input(text_ev('abc'))
check('② 文本经内核入口两端都被 UI 消费（返回 True）', r_gl is True and r_vk is True,
      (r_gl, r_vk))
check('② 同一串文本进同一个控件：内容一致',
      p.elems_gl['inp'].text == p.elems_vk['inp'].text == 'abc',
      (repr(p.elems_gl['inp'].text), repr(p.elems_vk['inp'].text)))
rows.append(('文本 abc 后 text', p.elems_gl['inp'].text, p.elems_vk['inp'].text))

# 键（生产入口：内核 handle_key_event 第③步派发 UI）
r_gl = p.gl.handle_key_event(key_ev(pygame.K_BACKSPACE))
r_vk = p.vk.handle_key_event(key_ev(pygame.K_BACKSPACE))
check('② 退格经内核入口两端都被 UI 消费（返回 True）', r_gl is True and r_vk is True,
      (r_gl, r_vk))
check('② 同一串按键进同一个控件：文本一致',
      p.elems_gl['inp'].text == p.elems_vk['inp'].text == 'ab',
      (repr(p.elems_gl['inp'].text), repr(p.elems_vk['inp'].text)))
rows.append(('退格后 text', p.elems_gl['inp'].text, p.elems_vk['inp'].text))

# 直接调 UIManager.dispatch_key / dispatch_text（任务点名要比的返回值）
d_gl = p.gl.ui.dispatch_key(pygame.K_LEFT)
d_vk = p.vk.ui.dispatch_key(pygame.K_LEFT)
check('② UIManager.dispatch_key 两端返回 True（同一个焦点元素、同一份实现）',
      d_gl is True and d_vk is True, (d_gl, d_vk))
check('② 左移后两端光标位置一致',
      p.elems_gl['inp']._cursor == p.elems_vk['inp']._cursor,
      (p.elems_gl['inp']._cursor, p.elems_vk['inp']._cursor))
rows.append(('左移后 cursor', p.elems_gl['inp']._cursor, p.elems_vk['inp']._cursor))

t_gl = p.gl.ui.dispatch_text('Z')
t_vk = p.vk.ui.dispatch_text('Z')
check('② UIManager.dispatch_text 两端返回 True', t_gl is True and t_vk is True, (t_gl, t_vk))
check('② 直调文本后两端内容一致',
      p.elems_gl['inp'].text == p.elems_vk['inp'].text, 
      (repr(p.elems_gl['inp'].text), repr(p.elems_vk['inp'].text)))
rows.append(('直调文本 Z 后 text', p.elems_gl['inp'].text, p.elems_vk['inp'].text))

# 回车提交（副作用：on_submit 收到同一串文本）
r_gl = p.gl.handle_key_event(key_ev(pygame.K_RETURN))
r_vk = p.vk.handle_key_event(key_ev(pygame.K_RETURN))
check('② 回车经内核入口两端都被 UI 消费（返回 True）', r_gl is True and r_vk is True,
      (r_gl, r_vk))
check('② 提交回调收到同一串文本（两端各 1 次）',
      p.clicks_gl.count('submit:aZb') == 1 and p.clicks_vk.count('submit:aZb') == 1,
      (p.clicks_gl, p.clicks_vk))

# 点别处 -> 两端一起失焦
step2('点空白 → 失焦 (500,350)', 500, 350, press=True, expect_hit='root')
step2('松开空白 (500,350)', 500, 350, release=True, expect_hit='root')
g, v = p.ui_state(500, 350)
check('② 点别处后两端一起失焦（_focused 都是 None）',
      g['focused'] is None and v['focused'] is None, (g['focused'], v['focused']))
rows.append(('点空白后 focused', g['focused'], v['focused']))

# 无焦点时两端都不消费
r_gl = p.gl.handle_key_event(key_ev(pygame.K_BACKSPACE))
r_vk = p.vk.handle_key_event(key_ev(pygame.K_BACKSPACE))
check('② 无焦点时退格两端都不被 UI 消费（返回 False）', r_gl is False and r_vk is False,
      (r_gl, r_vk))
r_gl = p.gl.handle_text_input(text_ev('x'))
r_vk = p.vk.handle_text_input(text_ev('x'))
check('② 无焦点时文本两端都不被 UI 消费（返回 False）', r_gl is False and r_vk is False,
      (r_gl, r_vk))
check('② 无焦点时文本没进输入框（两端都保持提交后的内容）',
      p.elems_gl['inp'].text == p.elems_vk['inp'].text == 'aZb',
      (repr(p.elems_gl['inp'].text), repr(p.elems_vk['inp'].text)))
seq_check('② 焦点与键盘：焦点/文本/光标/提交，两端逐项相等', rows)


# ============================ ③ hover 状态 ============================
print()
print("=== ③. hover 状态：光标移动后「hover 中的控件集合」逐项相等（递归扫整棵树） ===")
p = Pair()
rows = []


def step3(label, x, y, expect=None):
    p.frame(x, y)
    g, v = p.ui_state(x, y)
    rows.append((label, g['hoverset'], v['hoverset']))
    if expect is not None:
        check('③ %s：两端 hover 集合都 = %s（期望取自夹具几何）' % (label, expect),
              g['hoverset'] == v['hoverset'] == expect, (g['hoverset'], v['hoverset']))
    return g, v


step3('光标进按钮 (50,36)', 50, 36, ('btn',))
step3('光标进重叠上层 (60,320)', 60, 320, ('ov_top',))
step3('光标进滚动区子按钮 (320,120)', 320, 120, ('inner',))
step3('光标进滚动区空白 (350,150)', 350, 150, ())
step3('光标回空白 (500,350)', 500, 350, ())
step3('光标出画布 (-50,-50)', -50, -50, ())
seq_check('③ hover 集合：两端逐项相等（含离开时旧控件的 _hover 必须清掉）', rows)
g, v = p.ui_state(500, 350)
check('③ 光标移走后两端都不再有控件处于 hover（不残留）',
      g['hoverset'] == v['hoverset'] == (), (g['hoverset'], v['hoverset']))


# ============================ ④ 滚动消费 ============================
print()
print("=== ④. 滚动消费：ScrollView 上的滚轮被 UI 吃掉、别处不吃（且两端脚本可见值一致） ===")
p = Pair()
rows = []
rows_abs = []


def step4(label, x, y, wheel=0, press=False, release=False, expect_consumed=None):
    g, v = p.frame(x, y, press, release, wheel)
    # 纯滚轮帧：GL 的 ui_consumed 就等于「滚轮被 ScrollView 吃掉」（该帧没有别的消费源）
    rows.append((label + ' ·消费',
                 g['consumed'] if not (press or release) else 'n/a',
                 v['wheel_consumed'] if not (press or release) else 'n/a'))
    rows.append((label + ' ·脚本可见滚轮', g['wheel'], v['wheel']))
    if expect_consumed is not None:
        rows_abs.append((label, expect_consumed, g['consumed'], v['wheel_consumed']))
    return g, v


g, v = step4('可滚 ScrollView 上滚轮(-3)', 350, 150, wheel=-3, expect_consumed=True)
rows.append(('可滚 ScrollView scroll_pos',
             tuple(p.elems_gl['sv'].scroll_pos), tuple(p.elems_vk['sv'].scroll_pos)))
check('④ 可滚 ScrollView 上的滚轮：两端都真滚了（scroll_pos.y < 0，且逐值相等）',
      p.elems_gl['sv'].scroll_pos == p.elems_vk['sv'].scroll_pos
      and p.elems_gl['sv'].scroll_pos[1] < 0,
      (p.elems_gl['sv'].scroll_pos, p.elems_vk['sv'].scroll_pos))
g, v = step4('不可滚 ScrollView 上滚轮(+3)', 350, 300, wheel=3, expect_consumed=False)
rows.append(('不可滚 ScrollView scroll_pos',
             tuple(p.elems_gl['svn'].scroll_pos), tuple(p.elems_vk['svn'].scroll_pos)))
g, v = step4('按钮上滚轮(+3)', 50, 36, wheel=3, expect_consumed=False)
g, v = step4('空白上滚轮(-2)', 500, 350, wheel=-2, expect_consumed=False)
g, v = step4('同帧「点按钮 + 滚轮」(50,36,+3)', 50, 36, wheel=3, press=True)
g, v = step4('松开 (50,36)', 50, 36, release=True)
seq_check('④ 滚动消费：消费位 + 脚本可见滚轮 + scroll_pos，两端逐项相等', rows)
check('④ 「是否被 UI 消费」与夹具几何写死的期望表逐项相等（可滚=True / 其它=False）',
      all(e == g == v for (_l, e, g, v) in rows_abs),
      [r for r in rows_abs if not (r[1] == r[2] == r[3])][:3])
check('④ 不在 ScrollView 上时两端都不消费（滚轮该给相机/脚本）',
      rows_abs[1][2] is False and rows_abs[1][3] is False
      and rows_abs[2][2] is False and rows_abs[2][3] is False
      and rows_abs[3][2] is False and rows_abs[3][3] is False,
      rows_abs[1:4])


# ============================ ⑤ UI 消费对引擎的屏蔽 ============================
print()
print("=== ⑤. UI 消费对引擎的屏蔽：点中按钮 → 两端都不把这次点击交给引擎/脚本 ===")
p = Pair()
rows = []
_g0 = p.gl_frame(500, 350)
_v0 = p.vk_frame(500, 350)
check('⑤ 基线：两端 key_state 里没有任何 True 键（点击前）',
      _g0['keys_true'] == _v0['keys_true'] == (),
      (_g0['keys_true'], _v0['keys_true']))
rows.append(('基线 key_state True 键', _g0['keys_true'], _v0['keys_true']))

g, v = p.frame(50, 36, press=True)
rows.append(('点中按钮 ·GL ui_consumed / VK last_consumed', g['consumed'], v['consumed']))
rows.append(('点中按钮 ·引擎交互屏蔽', g['consumed'], not v['wants_camera']))
rows.append(('点中按钮 ·key_state True 键', g['keys_true'], v['keys_true']))
check('⑤ 点中按钮：两端都判定「这次点击被 UI 消费」（同一口径，逐项相等）',
      g['consumed'] is True and v['consumed'] is True, (g['consumed'], v['consumed']))
check('⑤ 点中按钮：两端都把这次点击从引擎交互路径上屏蔽（GL ui_consumed=True / '
      'VK wants_camera()=False）',
      g['consumed'] is True and v['wants_camera'] is False, (g['consumed'], v['wants_camera']))
check('⑤ 点中按钮时两端 key_state 都不更新（True 键集合仍为空）',
      g['keys_true'] == v['keys_true'] == (), (g['keys_true'], v['keys_true']))
check('⑤ 点中按钮后两端 is_key(w) 都是 False（点击没被当成按键/开火）',
      p.gl.is_key('w') is False and p.vk.is_key('w') is False,
      (p.gl.is_key('w'), p.vk.is_key('w')))

g, v = p.frame(50, 36, release=True)
rows.append(('松开按钮 ·GL ui_consumed / VK last_consumed', g['consumed'], v['consumed']))
rows.append(('松开按钮 ·key_state True 键', g['keys_true'], v['keys_true']))
check('⑤ 松开按钮当帧两端同样算消费（与 GL 同序），key_state 仍不更新',
      g['consumed'] is True and v['consumed'] is True
      and g['keys_true'] == v['keys_true'] == (),
      (g['consumed'], v['consumed'], g['keys_true'], v['keys_true']))

g, v = p.frame(500, 350, press=True)
rows.append(('点空白 ·GL ui_consumed / VK last_consumed', g['consumed'], v['consumed']))
rows.append(('点空白 ·key_state True 键', g['keys_true'], v['keys_true']))
check('⑤ 点空白区：两端都**不**把这次点击算成 UI 消费（3D 拾取/引擎交互仍可用）',
      g['consumed'] is False and v['consumed'] is False, (g['consumed'], v['consumed']))
check('⑤ 点空白后两端 key_state 仍不更新',
      g['keys_true'] == v['keys_true'] == (), (g['keys_true'], v['keys_true']))
g, v = p.frame(500, 350, release=True)
rows.append(('松开空白 ·key_state True 键', g['keys_true'], v['keys_true']))
seq_check('⑤ UI 消费对引擎的屏蔽：消费位 / 屏蔽位 / key_state，两端逐项相等', rows)


# ============================ ⑥ 坐标系一致性 ============================
print()
print("=== ⑥. 坐标系一致性：两端 int 像素 mouse_pos 喂同一 UI 树 → 命中相同 ===")
p = Pair()
rows = []
rows_hit = []
# 期望表由夹具几何写死（不取自任何一端）：Y 轴翻转 / DPI 缩放 / 原点偏移都会当场红
_EXPECT = [
    ('左上角 (0,0)', 0, 0, 'root'),
    ('按钮内左上 (20,20)', 20, 20, 'btn'),
    ('按钮内右下 (139,51)', 139, 51, 'btn'),
    ('按钮右下边界外 (140,52)', 140, 52, 'root'),
    ('按钮左上边界外 (19,19)', 19, 19, 'root'),
    ('按钮竖向镜像位 (50,364)', 50, 364, 'root'),
    ('输入框内 (60,85)', 60, 85, 'inp'),
    ('滚动区子按钮 (320,120)', 320, 120, 'inner'),
    ('右下角 (639,399)', 639, 399, 'root'),
    ('画布外负坐标 (-50,-50)', -50, -50, 'root'),
]


def step6(label, x, y, expect):
    g, v = p.frame(x, y)
    rows.append((label + ' ·mouse_pos', g['pos'], v['pos']))
    _c, eg = p.gl.ui.hit_test(p.gl.mouse_pos)
    _c, ev = p.vk.ui.hit_test(p.vk.mouse_pos)
    rows_hit.append((label, expect, getattr(eg, 'name', None), getattr(ev, 'name', None)))
    return g, v


for (label, x, y, expect) in _EXPECT:
    step6(label, x, y, expect)
seq_check('⑥ mouse_pos：同一串光标输入 → 两端 int 像素坐标逐值相等', rows)
check('⑥ 用两端各自的 mouse_pos 喂各自的 UI 树 → 命中结果与夹具几何期望表逐项相等',
      all(e == g == v for (_l, e, g, v) in rows_hit),
      [r for r in rows_hit if not (r[1] == r[2] == r[3])][:3])
check('⑥ 两端 mouse_pos 都是 2 元 int 元组（int 像素，不是宿主桥的 float pos）',
      all(isinstance(t, tuple) and len(t) == 2
          and all(isinstance(x, int) and not isinstance(x, bool) for x in t)
          for t in (p.gl.mouse_pos, p.vk.mouse_pos)),
      (p.gl.mouse_pos, p.vk.mouse_pos))
check('⑥ 竖向镜像位 (50,364) 两端都**不**命中按钮（Y 轴翻转会命中 → 该断言就是防它）',
      rows_hit[5][2] == rows_hit[5][3] == 'root', (rows_hit[5][2], rows_hit[5][3]))
# float 入参（GLFW 在 Windows 上只给整数，这里额外钉 int 截断语义两端一致）
p.frame(120.7, 63.4)
check('⑥ float 入参 (120.7,63.4)：两端 mouse_pos 都 int 截断成同一值',
      p.gl.mouse_pos == p.vk.mouse_pos == (120, 63), (p.gl.mouse_pos, p.vk.mouse_pos))
_c, eg = p.gl.ui.hit_test(p.gl.mouse_pos)
_c, ev = p.vk.ui.hit_test(p.vk.mouse_pos)
check('⑥ float 入参后两端命中相同（(120,63) 落在按钮/输入框之间的空白）',
      getattr(eg, 'name', None) == getattr(ev, 'name', None) == 'root',
      (getattr(eg, 'name', None), getattr(ev, 'name', None)))


# ============================ ⑦ 窗口 resize：UI 画布跟随 ============================
print()
print("=== ⑦. 窗口 resize：UI 画布尺寸 / anchor 布局 / 画布外判定，两端逐项相等（Q-B7-41-1） ===")
print("    （人类裁决：「判为缺陷，VK 补 ui.resize」——GL 在 _on_resize 里同步画布，VK 原先没有）")
p = Pair()


def _add_anchored(mgr):
    """anchor/pivot 布局夹具：三个锚定控件（几何写死在测试里，不取自任何一端）。

    a_tl anchor=(0,0) pivot=(0,0) rect=(10,10,100,40)   -> 左上角固定
    a_br anchor=(1,1) pivot=(1,1) rect=(-10,-10,100,40) -> 贴右下角（随画布走）
    a_ct anchor=(.5,.5) pivot=(.5,.5) rect=(0,0,120,60) -> 居中（随画布走）
    """
    c = mgr.canvases[0]
    tl = Button(name='a_tl', rect=(10, 10, 100, 40),
                anchor=(0.0, 0.0), pivot=(0.0, 0.0), text='TL')
    br = Button(name='a_br', rect=(-10, -10, 100, 40),
                anchor=(1.0, 1.0), pivot=(1.0, 1.0), text='BR')
    ct = Button(name='a_ct', rect=(0, 0, 120, 60),
                anchor=(0.5, 0.5), pivot=(0.5, 0.5), text='CT')
    for e in (tl, br, ct):
        c.root.add_child(e)
    return {'a_tl': tl, 'a_br': br, 'a_ct': ct}


_anchors = (_add_anchored(p.gl.ui), _add_anchored(p.vk.ui))

# 期望表（夹具几何 + anchor/pivot 公式手算写死；**不取自任何一端**）
_RECT_EXPECT = {
    (640, 400): {'a_tl': (10.0, 10.0, 100.0, 40.0),
                 'a_br': (530.0, 350.0, 100.0, 40.0),
                 'a_ct': (260.0, 170.0, 120.0, 60.0)},
    (800, 500): {'a_tl': (10.0, 10.0, 100.0, 40.0),
                 'a_br': (690.0, 450.0, 100.0, 40.0),
                 'a_ct': (340.0, 220.0, 120.0, 60.0)},
    (320, 240): {'a_tl': (10.0, 10.0, 100.0, 40.0),
                 'a_br': (210.0, 190.0, 100.0, 40.0),
                 'a_ct': (100.0, 90.0, 120.0, 60.0)},
}
_HIT_EXPECT = {
    (640, 400): {(10, 10): 'a_tl', (700, 450): 'root', (530, 350): 'a_br',
                 (340, 220): 'a_ct', (500, 350): 'root'},
    (800, 500): {(10, 10): 'a_tl', (700, 450): 'a_br', (530, 350): 'root',
                 (340, 220): 'a_ct', (500, 350): 'root'},
    (320, 240): {(10, 10): 'a_tl', (700, 450): 'root', (530, 350): 'root',
                 (340, 220): 'root', (500, 350): 'root'},
}
rows = []
_PR = {}


def _canvas_size(mgr):
    c = mgr.canvases[0]
    return (int(c.width), int(c.height))


def _anchored_rects(mgr, elems):
    c = mgr.canvases[0]
    pr = (0.0, 0.0, float(c.width), float(c.height))
    return {n: tuple(float(v) for v in e.screen_rect(pr)) for n, e in elems.items()}


def probe_resize(label, size):
    """比一档画布尺寸下的「画布尺寸 / anchor 矩形 / 同一坐标的命中结果」。"""
    gs, vs = _canvas_size(p.gl.ui), _canvas_size(p.vk.ui)
    rows.append((label + ' ·UI 画布尺寸', gs, vs))
    check('⑦ %s：两端 UI 画布尺寸 = %s（期望表，不取自任何一端）' % (label, size),
          gs == vs == size, (gs, vs))
    gr = _anchored_rects(p.gl.ui, _anchors[0])
    vr = _anchored_rects(p.vk.ui, _anchors[1])
    for n in ('a_tl', 'a_br', 'a_ct'):
        rows.append((label + ' ·%s 矩形' % n, gr[n], vr[n]))
    check('⑦ %s：anchor 布局结果两端逐项相等且 = 期望表' % label,
          gr == vr == _RECT_EXPECT[size], (gr, vr))
    gh, vh = {}, {}
    for pos in _HIT_EXPECT[size]:
        gh[pos] = getattr(p.gl.ui.hit_test(pos)[1], 'name', None)
        vh[pos] = getattr(p.vk.ui.hit_test(pos)[1], 'name', None)
        rows.append((label + ' ·命中 %s' % (pos,), gh[pos], vh[pos]))
    check('⑦ %s：同一坐标的命中结果两端逐项相等且 = 期望表（含「画布外」坐标）' % label,
          gh == vh == _HIT_EXPECT[size], (gh, vh))
    _PR[label] = {'size': size, 'gl_hit': gh, 'vk_hit': vh,
                  'gl_rect': gr, 'vk_rect': vr}
    return gs, vs


probe_resize('起始 640x400', (640, 400))
_w = p.resize_both(800, 500)
check('⑦ 两端窗口真的到了 800x500（否则下面的期望表无意义）',
      _w == ((800, 500), (800, 500)), _w)
probe_resize('resize 到 800x500', (800, 500))
_w = p.resize_both(200, 100)
check('⑦ 两端窗口真的到了 200x100（低于 320x240 下限 -> 触发 GL 的钳制分支）',
      _w == ((200, 100), (200, 100)), _w)
probe_resize('resize 到 200x100（钳到 320x240）', (320, 240))
check('⑦ 「画布外」判定随画布尺寸翻转、两端同步：点 (700,450) 在 640x400 = root（画布外），'
      '800x500 = a_br（画布内锚定控件），320x240 = root（又出画布）',
      (_PR['起始 640x400']['gl_hit'][(700, 450)],
       _PR['起始 640x400']['vk_hit'][(700, 450)]) == ('root', 'root')
      and (_PR['resize 到 800x500']['gl_hit'][(700, 450)],
           _PR['resize 到 800x500']['vk_hit'][(700, 450)]) == ('a_br', 'a_br')
      and (_PR['resize 到 200x100（钳到 320x240）']['gl_hit'][(700, 450)],
           _PR['resize 到 200x100（钳到 320x240）']['vk_hit'][(700, 450)]) == ('root', 'root'),
      {k: (v['gl_hit'][(700, 450)], v['vk_hit'][(700, 450)]) for k, v in _PR.items()})
check('⑦ 锚定控件真的跟着画布走了、两端同步：点 (530,350) 在 640x400 = a_br（右下角原位），'
      '800x500 = root（a_br 已随画布移到 690,450）',
      (_PR['起始 640x400']['gl_hit'][(530, 350)],
       _PR['起始 640x400']['vk_hit'][(530, 350)]) == ('a_br', 'a_br')
      and (_PR['resize 到 800x500']['gl_hit'][(530, 350)],
           _PR['resize 到 800x500']['vk_hit'][(530, 350)]) == ('root', 'root'),
      {k: (v['gl_hit'][(530, 350)], v['vk_hit'][(530, 350)]) for k, v in _PR.items()})
seq_check('⑦ 窗口 resize：画布尺寸 / anchor 矩形 / 命中结果，两端逐项相等', rows)


# ============================ ⑧ 跨帧持按的相机门控 ============================
print()
print("=== ⑧. 跨帧持按：按住控件 / 空白区按下未松开，(ui_consumed, wants_camera, 相机增量) 两端逐项相等 ===")
print("    （人类裁决：「以 GL 为准」——GL 的 ui_consumed 只看**本帧**事件，不看跨帧持按）")
p = Pair()
rows = []
_lk = p.lock_both()
check('⑧ 两端都已上锁（生产脚本 API；mouse_rel 的生产前提，与 GL 的 CURSOR_DISABLED 同源）',
      _lk == (True, True), _lk)


def press_step(label, x, y, press=False, release=False, exp_consumed=None, exp_rel=None):
    """一帧：喂同一串光标/按键 -> 比「消费位 + 相机门控 + 相机实际拿到的增量」。

    口径（写清，防"拿自报数字当证据"；Q-B7-43-2 修后更新）：
      · GL 的相机增量 = ui_consumed 时 (0,0)，否则生产泵结算出的 engine.mouse_rel
        —— 因为 runtime.PlayerApp.move_camera / rotate_camera 在 ui_consumed=True 时
        **早退**（runtime.py:306-316），本帧相机拿到的就是 0；
      · VK 的相机增量 = driver.ui_consumed 时 (0,0)，否则本帧喂进 driver 的物理增量
        —— Q-B7-43-2（2026-11-22 裁决 A）修后：vk_player.draw **无条件**喂
        （mouse_rel = 本帧物理增量，与 GL 同语义），「消费帧相机不转」由相机消费点的
        ui_consumed 早退承担（SceneDriver.apply_editor_camera_mouse，= GL
        editor._update_camera 的 _ui_lock 同语义）。
    两端都取"相机实际拿到的增量"，不是"引擎自报的鼠标值"。
    """
    g, v = p.frame(x, y, press, release)
    g_rel = (0, 0) if g['consumed'] else tuple(g['rel'])
    v_rel = tuple(v['cam_rel'])
    rows.append((label + ' ·GL ui_consumed / VK not wants_camera',
                 g['consumed'], not v['wants_camera']))
    rows.append((label + ' ·相机实际拿到的增量', g_rel, v_rel))
    if exp_consumed is not None:
        check('⑧ %s：两端「这次事件被 UI 消费」判定一致且 = 期望 %s'
              % (label, exp_consumed),
              g['consumed'] == (not v['wants_camera']) == exp_consumed,
              (g['consumed'], not v['wants_camera']))
    if exp_rel is not None:
        check('⑧ %s：两端相机实际拿到的增量一致且 = 期望 %s' % (label, exp_rel),
              g_rel == v_rel == exp_rel, (g_rel, v_rel))
    return g, v


# 吸收帧：上锁后两端基线都已重锚，本帧无增量
press_step('锚帧 悬停按钮 (50,36)', 50, 36, exp_consumed=False, exp_rel=(0, 0))
# ① 按住 UI 控件：按下 -> 持按 2 帧 -> 松开 -> 再移动
press_step('按下按钮 (60,36) 同时右移 10px', 60, 36, press=True,
           exp_consumed=True, exp_rel=(0, 0))
press_step('持按第 1 帧 右移 10px (70,36)', 70, 36,
           exp_consumed=False, exp_rel=(10, 0))
press_step('持按第 2 帧 右移 10px (80,36)', 80, 36,
           exp_consumed=False, exp_rel=(10, 0))
press_step('松开按钮 (80,36)', 80, 36, release=True,
           exp_consumed=True, exp_rel=(0, 0))
press_step('松开后右移 10px (90,36)', 90, 36,
           exp_consumed=False, exp_rel=(10, 0))
# ② 空白区按下未松开（GL: root 的 on_mouse_down 返回 False -> 不消费）
press_step('移到空白 (500,350)', 500, 350, exp_consumed=False, exp_rel=(410, 314))
press_step('空白区按下 (500,350)', 500, 350, press=True,
           exp_consumed=False, exp_rel=(0, 0))
press_step('空白持按第 1 帧 右下移 (520,360)', 520, 360,
           exp_consumed=False, exp_rel=(20, 10))
press_step('空白持按第 2 帧 右下移 (540,370)', 540, 370,
           exp_consumed=False, exp_rel=(20, 10))
press_step('空白区松开 (540,370)', 540, 370, release=True,
           exp_consumed=False, exp_rel=(0, 0))
press_step('松开后右下移 (560,380)', 560, 380,
           exp_consumed=False, exp_rel=(20, 10))
# ③ 拖动滑条：跨帧拖动时两端**都**继续抢相机（本次对齐没把拖动门控弄丢）
_sld = Slider(name='sld', rect=(200, 200, 200, 24), min_value=0.0, max_value=100.0,
              value=0.0)
p.gl.ui.canvases[0].root.add_child(_sld)
p.vk.ui.canvases[0].root.add_child(
    Slider(name='sld', rect=(200, 200, 200, 24), min_value=0.0, max_value=100.0,
           value=0.0))
press_step('移到滑条 (210,210)', 210, 210, exp_consumed=False, exp_rel=(-350, -170))
press_step('滑条上按下 (210,210)', 210, 210, press=True,
           exp_consumed=True, exp_rel=(0, 0))
press_step('拖动第 1 帧 右移 40px (250,210)', 250, 210,
           exp_consumed=True, exp_rel=(0, 0))
press_step('拖动第 2 帧 右移 50px (300,210)', 300, 210,
           exp_consumed=True, exp_rel=(0, 0))
press_step('拖动松开 (300,210)', 300, 210, release=True,
           exp_consumed=True, exp_rel=(0, 0))
seq_check('⑧ 跨帧持按：消费位 / 相机门控 / 相机增量，两端逐项相等', rows)


def _row(label, kind):
    """按标签取一行（不靠下标算，防以后加步骤错位）。"""
    for r in rows:
        if r[0] == label + ' ·' + kind:
            return r[1:]
    return None


_hold_lb = '持按第 1 帧 右移 10px (70,36)'
_blank_lb = '空白持按第 1 帧 右下移 (520,360)'
check('⑧ 持按控件期间两端**都**把增量交给相机（GL ui_consumed=False / VK wants_camera()=True）'
      '—— 这就是 Q-B7-41-2 的修前红点（旧 VK 靠跨帧 _pressed_elem 一直抢相机）',
      _row(_hold_lb, 'GL ui_consumed / VK not wants_camera') == (False, False)
      and _row(_hold_lb, '相机实际拿到的增量') == ((10, 0), (10, 0)),
      (_row(_hold_lb, 'GL ui_consumed / VK not wants_camera'),
       _row(_hold_lb, '相机实际拿到的增量')))
check('⑧ 空白区按下未松开期间两端**都**把增量交给相机（GL ui_consumed=False / '
      'VK wants_camera()=True）—— 旧 VK 靠跨帧 _last_pointer_down 一直抢相机',
      _row(_blank_lb, 'GL ui_consumed / VK not wants_camera') == (False, False)
      and _row(_blank_lb, '相机实际拿到的增量') == ((20, 10), (20, 10)),
      (_row(_blank_lb, 'GL ui_consumed / VK not wants_camera'),
       _row(_blank_lb, '相机实际拿到的增量')))
_drag_rows = [r for r in rows if r[0].startswith('拖动第')]
check('⑧ 拖动滑条时两端**都**抢相机（跨帧拖动的门控没被本次对齐弄丢：drag_to 每帧 '
      'consumed=True，不靠跨帧判据）',
      _drag_rows == [('拖动第 1 帧 右移 40px (250,210) ·GL ui_consumed / VK not wants_camera',
                      True, True),
                     ('拖动第 1 帧 右移 40px (250,210) ·相机实际拿到的增量', (0, 0), (0, 0)),
                     ('拖动第 2 帧 右移 50px (300,210) ·GL ui_consumed / VK not wants_camera',
                      True, True),
                     ('拖动第 2 帧 右移 50px (300,210) ·相机实际拿到的增量', (0, 0), (0, 0))],
      _drag_rows)
check('⑧ 滑条两端都真被拖到同一个值（副作用也一致）',
      abs(p.gl.ui.find('sld').value - p.vk.ui.find('sld').value) < 1e-9
      and p.gl.ui.find('sld').value > 0.0,
      (p.gl.ui.find('sld').value, p.vk.ui.find('sld').value))


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
    except Exception as e:
        cleanup_ok = False
        print('FAIL 收尾第 %d 对失败: %r' % (i + 1, e))
check('收尾：全部对的鼠标都未处于锁定态（不把光标捕获带出进程）', cleanup_ok)

print()
print('总结果: ' + ('ALL PASS' if ok else '有 FAIL'))
sys.exit(0 if ok else 1)
