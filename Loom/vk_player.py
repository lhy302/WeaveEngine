# -*- coding: utf-8 -*-
"""
vk_player.py — Vulkan 后端播放器 (wgpu-py + GLFW, 2026-08-29 入口化)

中间层 (scene_driver) = 单一数据来源; 本文件 = Vk 后端 窗口/表面/循环:
  run_vk(scene, ...) 可由文员入口/LoomHub/发布链 (game_player) 复用;
  --mini/--keep/--no-shadow/--frames/--stage 为探针能力 (保留).

用法: py -3.12 Loom\vk_player.py <场景.json> [--frames N] [--keep] [--mini]
"""
import os
import sys
import time

os.environ.setdefault('WGPU_BACKEND_TYPE', 'Vulkan')

import math as _math
import numpy as np
import wgpu
from matlib import mat4_view_yaw_pitch, mat4_perspective  # noqa: F401 (探针兼容)

# 中间层 (scene_driver) 为单一数据来源
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sceneio
from scene_driver import SceneDriver, build_models, build_lights  # noqa: F401

from rendercanvas.glfw import GlfwRenderCanvas
import rendercanvas.glfw

from vk_renderer import VkRenderer
from vk_ui import UIInputBridge      # 2026-11-06 R3: 窗口事件 -> driver.ui
# 2026-11-07 scan_05 P-10 修复: 失败按"段"分类 —— 初始化段失败是**可回退信号**
# (上层 run_player/game_player 据此改走 OpenGL), 渲染循环内失败不可同进程回退,
# 只能打印原因后非零退出 (原来一律 os._exit, 发布链的兜底也只覆盖 init)。
from run_player import VkInitError, VkRunError


# ==================== 2026-11-07: 输入注册/回调链 小工具 ====================

class _InputRetry:
    """输入回调注册的重试预算 (scan_05 P-08).

    旧实现: 窗口句柄验活失败 -> 每帧重试 + 每帧打印一行 (60Hz 日志风暴)。
    这里给一个有限预算: 失败 3 次后进入终态, 不再重试、不再打印。
    """

    def __init__(self, limit=3):
        self.limit = max(1, int(limit))
        self.attempts = 0
        self.given_up = False
        self.last_reason = None
        self.given_up_announced = False

    def can_try(self):
        return not self.given_up

    def failed(self, reason):
        """记一次失败; 返回 True=还可以重试, False=已进入终态."""
        self.last_reason = reason
        if self.given_up:
            return False
        self.attempts += 1
        if self.attempts >= self.limit:
            self.given_up = True
            if not self.given_up_announced:
                self.given_up_announced = True
                print("[vk] 输入不可用 (%s) —— 已重试 %d 次仍失败, 本次运行不再尝试"
                      " (键盘/鼠标/滚轮不会生效)" % (reason, self.attempts))
            return False
        print("[vk] 输入回调注册失败 (%s) —— 重试 %d/%d"
              % (reason, self.attempts, self.limit))
        return True


def _chain_callback(setter, win, our_cb, tag=''):
    """注册 our_cb, 并把**库之前注册的**回调链在它前面一起调用 (scan_05 P-07).

    rendercanvas.GlfwRenderCanvas 在创建窗口时已对这 5 个事件注册了自己的回调
    (submit_event/get_events 事件链); pyGLFW 的 set_*_callback 是 replace 语义,
    直接覆盖会让库的事件 API 静默失活。pyGLFW 的 set_*_callback **返回上一个
    回调**, 这里据此做链式转发: 先库、后自己。库未注册/版本不支持时退化为
    直接注册 (行为与旧实现相同)。

    返回被链上的旧回调 (None = 无旧回调)。
    """
    prev = None
    try:
        prev = setter(win, our_cb)
    except Exception as e:
        print("[vk] 注册 %s 回调失败: %r" % (tag or '?', e))
        return None
    if prev is None:
        return None

    def _chained(*args):
        try:
            prev(*args)
        except Exception as e:          # 库回调出问题不能拖垮自己的输入处理
            print("[vk] 库回调 (%s) 异常: %r" % (tag or '?', e))
        return our_cb(*args)

    try:
        setter(win, _chained)
    except Exception as e:
        print("[vk] 链式转发 %s 回调失败 (保留库回调优先): %r" % (tag or '?', e))
    return prev


def _wheel_taken_by_scrollview(ui, pos):
    """本帧滚轮是否真被 UI 的 ScrollView 吃掉 (滚轮专属判据, scan_05 P-09).

    UIManager.dispatch_mouse 只在"指针下的 ScrollView 可滚动"时消费滚轮; 而
    vk_ui.last_wheel_consumed 记录的是**本帧鼠标事件整体**是否被消费 —— 用它对
    滚轮判一次, 会把"同帧点按钮 + 滚轮"里的滚轮一起丢掉。这里按同一判据复核
    (只读 UI 树, 不改 UI 实现); 判不了时保守认为已被消费 (保持旧行为)。
    """
    if ui is None:
        return False
    if not hasattr(ui, '_hit_scroll_view'):
        return True
    try:
        sv = ui._hit_scroll_view(pos)
    except Exception:
        return True
    if sv is None:
        return False
    try:
        return bool(sv.can_scroll())
    except Exception:
        return True


def run_vk(scene=None, frames_n=None, keep=False, mini=False, no_shadow=False,
           stage='p4', width=1280, height=800, title="Loom (Vulkan)",
           scene_data=None):
    """Vk 播放器 (阻塞至窗口关闭/帧数达成). 返回平均 FPS 或 None.
    scene: 明文场景文件路径 (None 时用 scene_data 字典, 游戏包模式)."""
    if scene_data is not None:
        data = scene_data
    elif mini:
        data = _mini_data()
    else:
        if scene is None or not os.path.exists(scene):
            raise FileNotFoundError("场景不存在: %s" % scene)
        data = sceneio.load_scene_data(scene)
    driver = SceneDriver()
    driver.load_from_data(data)
    # 2026-11-06 R3: UI 输入桥 (GLFW 回调缓存 -> 每帧 dispatch_mouse + 键盘/文本).
    ui_bridge = UIInputBridge(getattr(driver, 'ui', None))
    try:
        from physics_bridge import cv_available as _pb_ok
    except Exception:
        _pb_ok = False
    # 2026-11-06 相机对齐: 打印也用真实玩家相机 (有 active_camera 时不再是轨道参数)
    _cam = driver.active_camera_object()
    if _cam is not None:
        _cam_desc = ("玩家相机 %r (yaw=%.1f° pitch=%.1f° roll=%.1f° fov=%.0f°)"
                     % (_cam.name, _cam.yaw, _cam.pitch, _cam.roll, _cam.fov))
    else:
        _cam_desc = "轨道 target=%s dist=%.1f" % (driver.target, driver.distance)
    print("加载 %s: 物体 %d, 相机 %s | 物理后端: %s" %
          (os.path.basename(scene or '<数据>'), len(driver.models), _cam_desc,
           "Culverin (Jolt)" if _pb_ok else "无 (culverin 缺失, 物理禁用)"))

    # 2026-11-07 scan_05 P-10: 初始化段包成"可回退信号" —— 这一段失败时上层可以
    # 干净地改走 OpenGL (VkInitError); 之前任何异常都直接冒泡, 由 Loom.py 的
    # except Exception 变成"无法启动渲染引擎", 发布链的 auto 回退覆盖不到细节。
    try:
        canvas = GlfwRenderCanvas(size=(width, height), title=title, vsync=False)
        canvas.set_update_mode('fastest')
        adapter = wgpu.gpu.request_adapter_sync(
            canvas=canvas, power_preference='high-performance')
        device = adapter.request_device_sync()
        ctx = canvas.get_wgpu_context()
        fmt = ctx.get_preferred_format(adapter)
    except BaseException as _ie:
        if isinstance(_ie, (KeyboardInterrupt, SystemExit)):
            raise
        raise VkInitError("Vulkan 初始化失败 (%s): %r"
                          % (type(_ie).__name__, _ie)) from _ie
    # 2026-11-06 双后端一致性: 着色器里已经做了 pow(col, 1/2.2) 的手工 gamma
    # (与 GL 路径同一段公式)。若交换链用 *-srgb 格式, GPU 会再做一次线性->sRGB
    # 编码 => 二次伽马, 画面明显发白, 与 GL 不可能逐像素一致。
    # 因此显式请求非 srgb 的 8bit 格式 (与 GL 的默认帧缓冲同为线性采样空间)。
    _usage = wgpu.TextureUsage.RENDER_ATTACHMENT
    try:
        if isinstance(fmt, str) and fmt.endswith("-srgb"):
            # 直接尝试用非 srgb 变体 configure; 不支持则回退原格式 (不静默失败)
            try:
                ctx.configure(device=device, format=fmt[:-5], usage=_usage)
                fmt = fmt[:-5]
            except Exception as _e:
                print("[vk] 非 srgb 交换链不可用 (回退 srgb, 可能出现二次伽马):", _e)
                ctx.configure(device=device, format=fmt, usage=_usage)
        else:
            ctx.configure(device=device, format=fmt, usage=_usage)
        print("设备:", adapter.info['device'], "| format:", fmt)

        renderer = VkRenderer(device, fmt, stage=stage)
    except BaseException as _ie:      # 初始化段 (交换链/shader/pipeline) —— 可回退
        if isinstance(_ie, (KeyboardInterrupt, SystemExit)):
            raise
        raise VkInitError("Vulkan 交换链/渲染器初始化失败 (%s): %r"
                          % (type(_ie).__name__, _ie)) from _ie
    if no_shadow:
        import copy
        driver.lights = [copy.copy(l) for l in driver.lights]
        for l in driver.lights:
            l.shadow = False

    times = []
    t_last = time.perf_counter()
    frame_count = 0
    result = [None]


    # 2026-11-06 输入对齐 (复核 B 的 P0): 此前 vk_player 完全没注册键盘回调,
    # driver.key_state 永远为空 -> 脚本 is_key/get_action 恒 False (WASD 不动)。
    # 这里在首帧拿到 GLFW 窗口后注册回调, 把按键映射回 _KEYMAP 的**键名**
    # (driver.is_key 按名字查), 与 GL 的 script_keys 同语义。
    # 2026-11-06 相机/鼠标对齐: 同一处补鼠标三路回调 (光标增量 / 按键 / 滚轮) ——
    # driver.mouse_rel / mouse_buttons / mouse_wheel 此前无人写, 玩家脚本的
    # 鼠标转视角 (sens 0.002) 与滚轮推拉在 Vk 下永远不生效。
    _keys_registered = [False]
    _prev = [None]          # 上一帧光标位置 (None = 重新起算, 防突跳)
    _input_retry = _InputRetry(limit=3)   # 2026-11-07 P-08: 有限重试, 不刷屏
    _handle_error = [None]                # 句柄验活失败原因 (交给重试预算统一打印)
    _loop_error = [None]                  # 2026-11-07 P-10: 渲染循环内异常占位


    def _resolve_glfw_window(glfw):
        """拿到 rendercanvas 真正创建的那个 GLFW 窗口.

        2026-11-06 修复 (P0, 实测): 原实现用 glfw.get_current_context(), 但
        wgpu/Vulkan 画布上没有 OpenGL current context —— pyGLFW 在这种情况下
        返回一个**无效句柄** (本机实测 glfw.set_key_callback 直接
        OSError: access violation reading 0x340), 被 except 静默吞掉,
        于是 key_state/mouse_rel 永远为空 = 键盘鼠标输入全废。
        正确来源是画布自身持有的 _window (rendercanvas.GlfwRenderCanvas);
        找不到时再退回 get_current_context(), 并用 get_window_size 验活
        (无效句柄会抛) —— 双重兜底, 换 rendercanvas 版本也不至于静默失效。"""
        cand = getattr(canvas, '_window', None)
        if cand is None:
            try:
                cand = glfw.get_current_context()
            except Exception:
                cand = None
        if cand is None:
            return None
        try:
            glfw.get_window_size(cand)       # 句柄验活 (无效指针这里就抛)
        except Exception as e:
            _handle_error[0] = "拿不到有效 GLFW 窗口 (%r)" % (e,)
            return None
        return cand


    def _register_input():
        """首帧注册键鼠回调 (原 _register_keys: 2026-11-06 起键盘+鼠标一起接).

        2026-11-07 P-08: 失败走 _InputRetry 预算 —— 只重试 3 次并最多打印 3 行,
        然后进入"输入不可用"终态 (旧实现每帧重试 + 每帧打印, 60Hz 日志风暴)。
        """
        if _keys_registered[0] or not _input_retry.can_try():
            return
        try:
            import glfw
            from loom_glfw_window import _GLFW_TO_PG
            from loom_input import _KEYMAP
            win = _resolve_glfw_window(glfw)
            if win is None:
                _input_retry.failed(_handle_error[0] or "GLFW 窗口句柄不可用")
                _handle_error[0] = None
                return
            _pg2name = {pg: name for name, pg in _KEYMAP.items()}

            def _on_key(w, key, scancode, action, mods):
                if action == glfw.REPEAT:
                    return
                pg = _GLFW_TO_PG.get(key)
                if pg is None:
                    return
                # 2026-11-06 R3 (与 GL loom_glfw_window._on_key_cb 同序):
                # 按下沿先给 UI 焦点元素; 消费则不写 key_state (输入框里按 W
                # 不应同时驱动角色)。松开沿照旧更新 key_state。
                if action == glfw.PRESS and ui_bridge.on_key(pg, mods):
                    return
                name = _pg2name.get(pg)
                if name is not None:
                    driver.key_state[name] = (action != glfw.RELEASE)

            # 2026-11-07 P-07: 链式转发 —— 先跑 rendercanvas 已注册的回调
            # (它的事件栈 submit_event/get_events 靠这 5 个回调), 再处理自己的。
            _chain_callback(glfw.set_key_callback, win, _on_key, 'key')

            def _on_char(w, codepoint):
                # GLFW 字符回调 = IME 提交的最终文本 (与 GL _on_char_cb 同源);
                # UI InputField 有焦点时消费, 否则无副作用.
                try:
                    ch = chr(codepoint)
                except (ValueError, OverflowError):
                    return
                ui_bridge.on_text(ch)

            _chain_callback(glfw.set_char_callback, win, _on_char, 'char')

            # ---- 鼠标 (与 GL 同语义; 2026-11-06 R3: 先进 UI, 再决定相机) ----
            def _on_cursor(w, x, y):
                # 只记录位置; 光标增量在 draw() 帧首统一结算 —— 这样本帧
                # UI 是否捕获鼠标 (点击/拖动) 能决定是否喂给相机, 与 GL 的
                # ui_consumed 门控同语义。
                ui_bridge.on_cursor(x, y)

            _BTN = {glfw.MOUSE_BUTTON_LEFT: 1, glfw.MOUSE_BUTTON_MIDDLE: 2,
                    glfw.MOUSE_BUTTON_RIGHT: 3}

            def _on_mouse_button(w, button, action, mods):
                btn = _BTN.get(button)
                if btn is None:
                    return
                down = (action != glfw.RELEASE)
                lst = list(driver.mouse_buttons)
                lst[btn - 1] = down
                driver.mouse_buttons = tuple(lst)
                ui_bridge.on_mouse_button(btn, down)

            def _on_scroll(w, xoff, yoff):
                # 与 GL (loom_glfw_window._on_scroll_cb) 同向: 上正下负, 逐格累加.
                # 先缓存给 UI (ScrollView 可能消费); draw() 里未消费才写
                # driver.mouse_wheel.
                ui_bridge.on_scroll(yoff)

            _chain_callback(glfw.set_cursor_pos_callback, win, _on_cursor, 'cursor')
            _chain_callback(glfw.set_mouse_button_callback, win,
                            _on_mouse_button, 'mouse_button')
            _chain_callback(glfw.set_scroll_callback, win, _on_scroll, 'scroll')

            # 鼠标锁定 -> 光标捕获/隐藏 (等价 GL 的 glfw.set_input_mode 分支);
            # 锁定时 _prev 置空, 避免光标被"虚化回中"时产生一帧巨大跳变。
            def _apply_cursor_mode(locked):
                _prev[0] = None
                try:
                    x, y = glfw.get_cursor_pos(win)
                    ui_bridge.on_cursor(x, y)
                except Exception:
                    pass
                try:
                    glfw.set_input_mode(
                        win, glfw.CURSOR,
                        glfw.CURSOR_DISABLED if locked else glfw.CURSOR_NORMAL)
                except Exception:
                    pass

            driver.on_mouse_lock_changed = _apply_cursor_mode
            # 与 runtime.PlayerApp 一致: 播放期默认锁定鼠标 (玩家按 Tab 释放/回锁,
            # Tab 的切换由 first_person/third_person 脚本走 driver.toggle_mouse_locked)。
            driver.set_mouse_locked(True)
            _keys_registered[0] = True
        except Exception as e:
            # 失败原因交给重试预算 (限次 + 限打印), 不再每帧一行
            _input_retry.failed(repr(e))


    # 2026-11-06: 开发者视角鼠标默认关闭 (GL PlayerApp 无此能力)
    try:
        driver.dev_mouse_enabled = (os.environ.get("LOOM_VK_DEVMOUSE") == "1")
    except Exception:
        pass

    def draw():
        nonlocal t_last, frame_count
        _register_input()
        frame_count += 1
        now = time.perf_counter()
        times.append(now - t_last)
        render_dt = now - t_last   # 分离批1: 渲染 dt = 上帧到本帧墙钟
        t_last = now
        if len(times) > 300:
            times.pop(0)
        if not keep and frames_n and frame_count >= frames_n:
            canvas.close()
            return
        try:
            w, h = ctx.physical_size
            # 2026-11-06 R3: 帧首把窗口事件结算给 UI (鼠标按下/松开/滚轮),
            # 再决定光标增量是否喂相机 —— UI 捕获鼠标时不转视角.
            _ui_now = getattr(driver, 'ui', None)
            if _ui_now is not None and _ui_now is not ui_bridge.ui:
                ui_bridge.ui = _ui_now          # 场景切换/重建后重新绑定
            ui_bridge.begin_frame()
            try:
                _x, _y = ui_bridge.pos
                _p = _prev[0]
                if _p is not None and ui_bridge.wants_camera():
                    driver.feed_mouse_rel(_x - _p[0], _y - _p[1])
                _prev[0] = (_x, _y)
                # 滚轮: 只有"滚轮本身"被 UI (ScrollView) 消费才不给脚本/相机。
                # 2026-11-07 P-09: last_wheel_consumed 是本帧鼠标事件**整体**
                # 被消费 (含"点中按钮"), 单用它会把同帧点击的滚轮一起丢掉;
                # 这里与滚轮专属判据合并 (二者都成立才算被 UI 吃掉)。
                _wh = ui_bridge.last_wheel
                if _wh:
                    _taken = (ui_bridge.last_wheel_consumed
                              and _wheel_taken_by_scrollview(_ui_now, ui_bridge.pos))
                    if not _taken:
                        driver.mouse_wheel += _wh
                        ui_bridge.last_wheel_consumed = False
            except Exception as _ie:
                print('[vk] UI 输入结算异常 (跳过本帧):', repr(_ie))
            # 分离批1+2: 时钟推进 (排逻辑+物理步) → alpha 透传插值层 → 渲染段
            driver.advance_logic(render_dt)
            if getattr(driver, '_interp', None) is not None:
                driver._interp.alpha = driver._clock.alpha
            vp, cam_pos = driver.render_pose(aspect=w / h)
            # 2026-11-06 R1: world Canvas billboard 的 right/up 必须与 GL
            # (mat4_view_yaw_pitch 的 V[0]/V[1] 行) 逐位同源; 这里显式传,
            # 避免渲染层从 VP 反解 yaw/pitch 时丢失 roll 信息.
            _cam_basis = None
            try:
                if getattr(driver, 'orbit_mode', True):
                    _yaw, _pitch, _roll = driver.yaw, driver.pitch, 0.0
                else:
                    _yaw = driver.camera_yaw
                    _pitch = driver.camera_pitch
                    _roll = driver.camera_roll
                _V = mat4_view_yaw_pitch(np, tuple(cam_pos), _yaw, _pitch, _roll)
                _cam_basis = ((float(_V[0, 0]), float(_V[0, 1]), float(_V[0, 2])),
                              (float(_V[1, 0]), float(_V[1, 1]), float(_V[1, 2])))
            except Exception:
                _cam_basis = None
            # 2026-11-06: Canvas UI 接线 (GL 的 UIManager.draw_all 同一份元素树)。
            # HUD 默认关闭 —— GL 的 PlayerApp._draw_hud 是 pass (玩家不该看到调试
            # HUD), 无条件打开会**制造**两端差异; 需要时 LOOM_VK_HUD=1。
            _hud = None
            if os.environ.get("LOOM_VK_HUD") == "1":
                try:
                    import vk_ui as _vkui
                    _hud = _vkui.hud_lines_from_driver(driver)
                except Exception:
                    _hud = None
            renderer.draw_frame(ctx, driver.models, driver.lights, vp, cam_pos,
                                interp=getattr(driver, '_interp', None),
                                sky=getattr(driver, 'skybox', None),
                                ui=getattr(driver, 'ui', None),
                                hud_lines=_hud, cam_basis=_cam_basis)
        except BaseException as _e:   # 含 wgpu PanicError (device lost 风暴)
            # 2026-11-07 P-10: 不再 os._exit(1) (发布链看到的是"双击没反应")。
            # 记录成"不可回退的失败信号": 关闭画布结束循环, 打印完整原因后由
            # run_vk 抛 VkRunError 让上层以非零码退出并如实说明。
            import traceback
            traceback.print_exc()
            print("[vk] 渲染循环内异常 (%s: %s) —— Vulkan 已初始化, 无法在本进程内"
                  " 回退 OpenGL; 结束渲染循环并按失败退出"
                  % (type(_e).__name__, _e))
            _loop_error[0] = _e
            try:
                canvas.close()
            except Exception:
                pass
            return
        if len(times) > 30:
            fps = 1.0 / (sum(times[-30:]) / len(times[-30:]))
            canvas.set_title("%s | %.0f FPS" % (title, fps))
            result[0] = fps

    # 2026-11-07: 脚本 request_game_exit() -> driver.request_quit -> 关窗退出
    _orig_draw = draw

    def draw(*a, **k):
        # 2026-11-07 修复: 原 draw 可能是无参签名, 必须原样转发, 不能固定传 dt
        # (旧实现 _orig_draw(dt) -> "takes 0 positional arguments but 1 was given")
        try:
            if getattr(driver, 'request_quit', False):
                canvas.close()
                return
        except Exception:
            pass
        return _orig_draw(*a, **k)

    canvas.request_draw(draw)
    import threading
    last_ok = [time.perf_counter()]


    def _heartbeat():
        while True:
            time.sleep(5)
            if time.perf_counter() - last_ok[0] > 60:
                print("watchdog: 渲染无进展 60s, 强制退出 (防卡死)")
                os._exit(9)
    threading.Thread(target=_heartbeat, daemon=True).start()

    try:
        rendercanvas.glfw.loop.run()
    except KeyboardInterrupt:
        pass
    # 2026-11-07 P-10: 循环内失败 -> 非零退出并说明 (不回退, 也不假装成功)
    if _loop_error[0] is not None:
        _le = _loop_error[0]
        raise VkRunError("Vulkan 渲染循环异常: %s: %s"
                         " (Vulkan 已初始化, 未回退 OpenGL)" % (type(_le).__name__, _le))
    if times:
        # 短跑 (<11 帧, 如 --frames 8) 时 times[10:] 为空 -> 原来的 sum/len 会
        # ZeroDivisionError; 空则回退用全量 (探针/冒烟不应因统计窗口而崩).
        t = times[min(10, len(times)):] or times
        avg = sum(t) / len(t)
        print("\n=== Vk 播放 (物体 %d) | 帧数 %d | %.3f ms/帧 | FPS %.1f ==="
              % (len(driver.models), len(t), avg * 1000, 1.0 / avg))
    return result[0]


def _mini_data():
    """探针最小场景: 1 立方体 + 1 平行光 (shadow=True)."""
    return {
        "version": 10, "materials": [], "cameras": [], "active_camera": None,
        "camera": {"target": [0, 1, 0], "distance": 6.0, "yaw": 0.6,
                   "pitch": -0.35},
        "lights": [{"id": "l1", "name": "太阳", "kind": "directional",
                    "position": [0, 12, 0], "azimuth": 30, "elevation": -55,
                    "roll": 0, "color": [1.0, 1.0, 1.0], "intensity": 1.1,
                    "mode": "full", "shape": "circle", "size": 8.0,
                    "shadow": True}],
        "objects": [{"id": "o1", "name": "立方体", "type": "cube",
                     "params": {"size": 1.0}, "position": [0, 0.5, 0],
                     "rotation": [0.3, 0.6, 0.0], "scale": [1, 1, 1],
                     "color": "#e0804a", "normal_mode": "flat",
                     "saturation": 1.0, "visible": True, "scripts": [],
                     "collider": {"shape": "box", "enabled": True},
                     "rigidbody": None, "audio_source": None,
                     "animator": None}]}


def main():
    args = sys.argv[1:]
    scene = args[0] if args and not args[0].startswith('--') else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     '保存', '压测50球.json')
    frames_n = None
    stage = 'p4'
    w, h = 1280, 800
    for i, a in enumerate(args):
        if a == '--frames' and i + 1 < len(args):
            frames_n = int(args[i + 1])
        if a == '--stage' and i + 1 < len(args):
            stage = args[i + 1]
        if a == '--size' and i + 1 < len(args):
            w, h = (int(x) for x in args[i + 1].split('x'))
    run_vk(scene, frames_n=frames_n, keep='--keep' in args,
           mini='--mini' in args, no_shadow='--no-shadow' in args,
           stage=stage, width=w, height=h)


if __name__ == '__main__':
    main()
