# -*- coding: utf-8 -*-
"""
runtime.py — Player 运行时 (M17: 引擎/编辑器分层)

PlayerApp 只依赖引擎 + sceneio, 不 import 编辑器: 加载场景文件即渲染。
打包版可只带运行时 (编辑器 UI 不打包), exe 更小、无编辑功能。
Loom.py / build_entry.py 的 --run <scene.json> 都从这里启动。
2026-08-22 发布链路 (Unity Build 对齐): 支持 scene_data 直接喂字典
(游戏包.lsc 解包产物, 场景不出明文) + title (玩家窗口标题 = 游戏名).
"""
import json
import os

# 2026-10-18 A2: import pygame 已删（GLFW 窗口剥离；set_caption 改用 glfw）
from engine import GLEngine, gc_play_enter, gc_play_exit, engine_gc_frozen
import sceneio


# ==================== 2026-11-08 鼠标锁定语义重构（人类裁决）====================
# 裁决要点: ①默认**不锁**（没人要求就不锁）; ②**不做**"检测到 UI 就自动解锁"（交给
# 游戏开发者用 set_ui_capture_mouse 显式判断）; ③三件能力齐: 整局是否锁 / 某时刻锁不锁
# / 哪个键解锁（动作 解锁鼠标，默认 Tab，可改、冲突拒绝 —— 后者在 loom_input 侧）。
_LOCK_BACKEND_LAST = {}          # (id(win), locked) -> 已记录，防每次调用刷日志


def read_mouse_lock_policy():
    """读本局鼠标策略 -> (allowed, initial)。

    新默认（人类裁决 2026-11-08）: **未配置 = 不锁**（False/False）。
    显式配置照读；initial 在 allowed=False 时恒为 False（不允许锁就别谈初始锁）。
    """
    try:
        import game_settings as _gs
    except Exception as e:
        print('[鼠标] 读游戏配置失败 (%r) -> 按默认不锁' % (e,))
        return False, False
    allowed = bool(_gs.read_bool('mouse_lock_allowed', False))
    if not allowed:
        return False, False
    return True, bool(_gs.read_bool('mouse_locked', False))


def apply_mouse_lock_backend(win, locked, tag='player'):
    """把"锁定/解锁鼠标"真正落到窗口后端: GLFW 模式 + **回读校验** + Win32 兜底 + 日志。

    2026-11-08 人类裁决（实测病灶）: 旧实现只翻一个 `glfw CURSOR` 模式且包在
    `except: pass` 里 —— 失败没人知道, 玩家表现为"按了键光标出来了但动不了"。
    这里三段式: ①设模式 -> ②回读实际模式校验 -> ③不符/失败用 Win32 兜底并告警。
    返回 True = 已确认生效（GLFW 回读一致, 或 Win32 兜底已执行）。
    """
    locked = bool(locked)
    ok = False
    detail = '无窗口句柄'
    if win is not None:
        try:
            import glfw
            want = glfw.CURSOR_DISABLED if locked else glfw.CURSOR_NORMAL
            glfw.set_input_mode(win, glfw.CURSOR, want)
            got = glfw.get_input_mode(win, glfw.CURSOR)
            ok = (got == want)
            detail = 'glfw 回读=%s' % ('一致' if ok else '不一致(%r)' % (got,),)
        except Exception as e:
            detail = 'glfw 失败 (%r)' % (e,)
    if not ok:
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            if locked:
                hwnd = 0
                try:
                    import glfw
                    hwnd = glfw.get_win32_window(win)
                except Exception:
                    hwnd = 0
                if hwnd:
                    class _R(ctypes.Structure):
                        _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                                    ('right', wintypes.LONG), ('bottom', wintypes.LONG)]
                    r = _R()
                    u.GetClientRect(hwnd, ctypes.byref(r))
                    pt = wintypes.POINT(0, 0)
                    u.ClientToScreen(hwnd, ctypes.byref(pt))
                    r.left += pt.x; r.right += pt.x
                    r.top += pt.y; r.bottom += pt.y
                    u.ClipCursor(ctypes.byref(r))
                u.ShowCursor(False)
                detail += ' | Win32 兜底: ClipCursor+ShowCursor(F)'
            else:
                u.ClipCursor(None)
                u.ShowCursor(True)
                detail += ' | Win32 兜底: ClipCursor(None)+ShowCursor(T)'
            ok = True
        except Exception as e:
            detail += ' | Win32 兜底失败 (%r)' % (e,)
    key = (id(win), locked)
    if _LOCK_BACKEND_LAST.get(key) != ok:
        _LOCK_BACKEND_LAST[key] = ok
        print('[鼠标] %s: %s (%s)' % (tag, '锁定' if locked else '解锁', detail))
    return ok

class PlayerApp(GLEngine):
    """只读场景播放器: 无编辑器 UI, 轨道相机 + 默认引擎键位.

    2026-10-20 P0-1 白屏修复：支持 ctx 参数（外部 GL 上下文）。
    远程/虚拟显示下 GLFW native present 失败时，可用离屏 GL + 外部窗口
    （Qt，见 loom_player_window.py）显示，绕过 GLFW 窗口。
    """

    def __init__(self, scene_path=None, width=1280, height=800,
                 scene_data=None, title=None, ctx=None):
        super().__init__(width, height, ctx=ctx)
        for m in list(self.models):
            self.remove_model(m)                 # 清默认场景
        if title:
            # 2026-10-18 A2: GLFW 窗口标题（原 pygame.display.set_caption）
            # 2026-10-20 P0-1: 外部 ctx 模式无 GLFW 窗口，跳过
            try:
                import glfw
                win = getattr(self, '_glfw_win', None)
                if win is not None:
                    glfw.set_window_title(win, title)
            except Exception:
                pass
        cam_out = {}
        # M38: load_scene_data (明文 JSON 与 LOOMSC 混淆场景自动解密);
        # 2026-08-22: scene_data 为游戏包解包产物时直接使用 (场景不出明文).
        if scene_data is not None:
            data = scene_data
        else:
            data = sceneio.load_scene_data(scene_path) if scene_path else None
        if not isinstance(data, dict):
            raise ValueError("无法加载场景: %s" % scene_path)
        # 2026-11-09 (Q6=A): 场景目录作为 base_dir —— skybox 六面图的**相对路径**按它解析
        # （不传的话播放器按 CWD 解析，换目录启动就找不到图 -> 只能回退默认蓝）。
        _base = (os.path.dirname(os.path.abspath(scene_path))
                 if scene_path else None)
        sceneio.scene_from_dict(self, data, camera_out=cam_out, base_dir=_base)
        if cam_out:
            self.camera_target = cam_out['target']
            # 2026-11-06 R-03: 与 Vk 后端同语义 —— 场景距离在入口钳制
            # (0.5..1000), 否则 distance=5000 会把观察目标顶到 far 之外、整屏裁空。
            from loom_camera import clamp_camera_distance
            self.camera_distance = clamp_camera_distance(cam_out['distance'])
            self.camera_yaw = cam_out['yaw']
            self.camera_pitch = cam_out['pitch']
            # 2026-11-07: 播放器也套用场景相机投影 (ortho/fov), 与编辑器播放一致
            try:
                self.ortho = bool(cam_out.get('ortho', False))
                self.ortho_size = float(cam_out.get('ortho_size', 12.0))
                import math as _m
                if cam_out.get('fov') is not None:
                    self._fov = _m.radians(float(cam_out['fov']))
            except Exception:
                pass
        # 玩家视角: 场景 active_camera (Unity Camera) 优先, 否则默认轨道相机
        cam = self.active_camera_object()
        if cam is not None:
            self.apply_camera(cam)
        else:
            self.orbit_mode = True
            self.apply_orbit_camera()
        # 2026-11-08 鼠标锁定语义重构（人类裁决）:
        #   ① 默认**不锁**（未配置 = allowed False / initial False）—— 打包吃豆人被默认
        #      锁死、Tab 后光标出现但动不了的实测病灶就在旧默认 (True/True);
        #   ② 引擎**不猜**入"弹 UI 就自动解锁"（反例: 界面有常驻可点 UI 但仍需锁鼠标），
        #      解锁时机由游戏脚本显式 set_mouse_locked / set_ui_capture_mouse 决定;
        #   ③ 解锁键归引擎独占 (D6=A): GLEngine._poll_mouse_unlock_key / poll_unlock()
        #      统一处理 解锁鼠标 动作（默认 Tab，可改键，冲突在 loom_input 侧拒绝）。
        self.mouse_lock_allowed, _lock0 = read_mouse_lock_policy()
        print('[鼠标] 策略: allowed=%s initial=%s (来源: 游戏设置.json; 未配置=不锁)'
              % (self.mouse_lock_allowed, _lock0))
        self.set_mouse_locked(_lock0)
        # 分离批2: 首帧快照对齐 (加载位姿=curr, 首渲染帧不插值)
        if getattr(self, '_interp', None) is not None:
            self._interp.advance()
            self._interp.align()
        self._render_world = None
        if hasattr(self, '_prep_sig'):
            self._prep_sig = None           # 批5: prep 缓存强制失效
            self._disp_gen = -1
        clk = getattr(self, '_clock', None)
        if clk is not None:
            clk.reset()
        # GC 生命周期 (2026-09-01 流畅度批): 场景加载完成即冻结长寿命对象
        # (501 Mesh 大 list ≈ 490 万槽永久代化) + 放宽播放阈值 —— 发布玩家=
        # 常驻播放态, gen2 不再全量遍历场景 (1% low 帧尖刺本体治理).
        # 一次性代价: enter 内 collect 在加载尾 ~20-150ms@500球 (加载时刻, 可接受).
        # LOOM_GC_LEGACY=1 秒回退 (A/B 基线用).
        gc_play_enter()

    def load_scene(self, path):
        """M37 运行时切场景 (GC 批包裹): 冻结态下旧场景对象被 freeze 钉死,
        先解冻回收再冻新场景 —— 防脚本切关卡长局内存单调上涨."""
        frozen = engine_gc_frozen()
        if frozen:
            gc_play_exit()               # 解冻旧场景 + 清播放垃圾 + 阈值还原
        try:
            return super().load_scene(path)
        finally:
            if frozen:
                gc_play_enter()          # 冻结新场景 + 播放阈值 (加载失败也重冻)

    # ==================== 2026-11-08 D8=A: GL 播放器补 UI 鼠标派发 ====================
    # 审计 P-06-01: 此前只有编辑器 (editor._dispatch_ui_mouse) 与 VK (vk_ui.UIInputBridge)
    # 会把鼠标事件交给 UIManager, GL 播放器 (PlayerApp / 打包版 opengl) 完全没有派发通道
    # -> Canvas 按钮的声明式事件 (_fire_binding) 在 GL 播放器里永远不触发。
    # 语义与两端对齐: 回调只缓存 -> 帧首一次 dispatch_mouse -> 未被消费再 update_hover_only
    # (UIManager.dispatch_mouse 是唯一入口; 每帧最多一次, pressed/released 由
    #  GlfwWindowMixin._handle_events 每帧清空)。**不引入任何编辑器交互**。
    # ---- 2026-11-08 鼠标锁定语义重构: 播放器侧的 锁不锁 执行点 ----
    def set_mouse_locked(self, locked):
        """锁定/解锁鼠标（播放器语义）.

        与旧实现的差别（人类裁决 2026-11-08）:
          ① `allowed=False` 时**任何**锁请求都不生效（脚本调 set_mouse_locked(True)
             也锁不住玩家），并只报一次原因；
          ② 后端落地统一走 apply_mouse_lock_backend（GLFW 模式 + 回读校验 +
             Win32 兜底 + 一行日志），不再 `except: pass` 静默失败。
        """
        locked = bool(locked)
        if locked and not getattr(self, 'mouse_lock_allowed', False):
            if not getattr(self, '_lock_denied_logged', False):
                self._lock_denied_logged = True
                print('[鼠标] mouse_lock_allowed=False -> 忽略 set_mouse_locked(True) (本局只报一次)')
            self.mouse_locked = False
            return
        self.mouse_locked = locked
        if getattr(self, '_external_ctx', False):
            view = getattr(self, 'view', None)
            if view is not None and hasattr(view, 'set_mouse_locked'):
                try:
                    view.set_mouse_locked(locked)
                except Exception as e:
                    if not getattr(self, '_lock_view_err_logged', False):
                        self._lock_view_err_logged = True
                        print('[鼠标] 宿主视图 set_mouse_locked 失败 (%r), 本局不再报' % (e,))
            return
        apply_mouse_lock_backend(getattr(self, '_glfw_win', None), locked,
                                 tag='GL 播放器')
    def _dispatch_ui_mouse(self):
        """把本帧新按下/松开 + 光标位置 + 滚轮交给 UI。返回 consumed。

        只在**非外部上下文** (自建 GLFW 窗口, 即 --run/打包版 opengl) 调用:
        外部上下文由宿主喂事件, 其 pressed/released 不按帧清空, 在这里重复派发
        会变成"一次点击触发多次"(见 handler 注释)。
        """
        ui = getattr(self, 'ui', None)
        if ui is None:
            self.ui_consumed = False
            return False
        pos = getattr(self, 'mouse_pos', (0, 0))
        pressed = set(getattr(self, 'pressed', ()) or ())
        released = set(getattr(self, 'released', ()) or ())
        try:
            wheel = int(getattr(self, 'mouse_wheel', 0) or 0)
        except (TypeError, ValueError):      # 只有坏值才回落 (不吞其它异常)
            wheel = 0
        consumed = False
        try:
            consumed = bool(ui.dispatch_mouse(pos, pressed, released, wheel))
        except Exception as e:
            # 每帧都可能命中 -> 只报一次 (打包版日志不做 120Hz 刷屏)
            if not getattr(self, '_ui_dispatch_err_logged', False):
                self._ui_dispatch_err_logged = True
                print('[player] UI 鼠标派发异常 (本局只报一次, 之后静默跳过): %r' % (e,))
            consumed = False
        if not consumed:
            try:
                ui.update_hover_only(pos)
            except Exception as e:
                if not getattr(self, '_ui_hover_err_logged', False):
                    self._ui_hover_err_logged = True
                    print('[player] UI hover 更新异常 (本局只报一次): %r' % (e,))
        self.ui_consumed = consumed
        return consumed

    def _handle_events(self):
        """帧首: 先轮转窗口事件 (super), 再把本帧鼠标事件交给 UI。"""
        super()._handle_events()
        if not getattr(self, '_external_ctx', False):
            self._dispatch_ui_mouse()

    def move_camera(self, delta_time):
        """UI 捕获鼠标时本帧不移动相机 (与 editor/ui_consumed 同语义)。"""
        if getattr(self, 'ui_consumed', False):
            return
        return super().move_camera(delta_time)

    def rotate_camera(self, delta_time):
        """UI 捕获鼠标时本帧不旋转相机 (与 editor/ui_consumed 同语义)。"""
        if getattr(self, 'ui_consumed', False):
            return
        return super().rotate_camera(delta_time)

    def _draw_hud(self):
        """M39: 播放器不画引擎调试 HUD (相机坐标/FPS/操作提示等 — 玩家不该看到).
        游戏自己的 UI (脚本 engine.ui.text 等, M33) 照常在 render 里画."""
        pass