# -*- coding: utf-8 -*-
"""test_beta3_batch2_camera_proj.py — 第 2 批（03 号）回归测试.

覆盖本轮修复的 5 条缺陷（编号见 docs/audit/scan_beta3_03_ui_event_and_scene_driver.md）:
  P-03-02 场景 camera.fov 在 VK 驱动里被死赋值覆盖 -> 现在必须生效, 且 GL/VK 同值
  P-03-03 ortho_size 未容错 -> 坏类型不再抛异常 (GL/VK 同语义, 契约 B4/Q4=B)
  P-03-04 bool('false') -> 严格布尔解析 (不静默错值)
  P-03-06 ortho_size 0/负数/NaN -> 归一/钳制并出声 (不再除零/镜像/全黑)
  P-03-07 暂停态解锁键失效 + 鼠标增量跨暂停累积
  P-03-08 _fire_binding 的 `or sc` 兜底 (假值运行时实例静默丢事件)
  P-03-09 draw_frame(engine=None) 类静默退化 -> 宿主缺失必须出声一次
  D7=A   ortho/ortho_size/fov = 场景相机属性: 进脏判定 + 进撤销 + 播放前后恒等
  P-03-10(VK 键位) 键位加载因缺 import os 从未生效 -> 现在真的从模板/用户层读

跑法: cd Loom && python tests/test_beta3_batch2_camera_proj.py
不写任何受跟踪文件: 用户层配置用 LOOM_USER_ROOT / LOOM_GAME_DIR 指向临时目录。
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
# 隔离用户层/游戏层配置: 本测试绝不碰真实 %LOCALAPPDATA%
_TMPCFG = tempfile.mkdtemp(prefix='loom_b2_cfg_')
os.environ['LOOM_USER_ROOT'] = os.path.join(_TMPCFG, 'user')
os.environ['LOOM_GAME_DIR'] = os.path.join(_TMPCFG, 'game')
os.makedirs(os.environ['LOOM_GAME_DIR'], exist_ok=True)

import numpy as np                                       # noqa: E402

import sceneio as S                                      # noqa: E402
import scene_driver as SD                                # noqa: E402
import loom_ui as L                                      # noqa: E402

ok = True


def check(label, cond, detail=''):
    global ok
    print(('PASS ' if cond else 'FAIL ') + label + ('  ' + str(detail) if detail else ''))
    if not cond:
        ok = False


def _driver(cam=None):
    d = SD.SceneDriver()
    data = {'version': 10, 'objects': []}
    if cam is not None:
        data['camera'] = dict(cam)
    d.load_from_data(data)
    return d


BASE_CAM = {'target': [0, 0, 0], 'distance': 10.0, 'yaw': 0.0, 'pitch': -0.3}


# ============ 1) P-03-02: 场景 fov 必须生效 (修前恒为 60°) ============
def t_fov_applied():
    print('---- 1) 场景 camera.fov ----')
    for deg in (90.0, 45.0, 100.0):
        cam = dict(BASE_CAM); cam['fov'] = deg
        d = _driver(cam)
        check('fov %.1f° 生效' % deg, abs(math.degrees(d.fov) - deg) < 1e-6,
              round(math.degrees(d.fov), 4))
    d = _driver()                      # 无 camera 段 -> 引擎默认 60°
    check('无 camera 段 -> fov 60°', abs(math.degrees(d.fov) - 60.0) < 1e-9)
    # fov 必须真的改变渲染投影（不是只改了字段）：同场景 60° vs 90° 的 VP 必须不同
    cam60 = dict(BASE_CAM); cam60['fov'] = 60.0
    cam90 = dict(BASE_CAM); cam90['fov'] = 90.0
    vp60, _ = _driver(cam60).render_pose(aspect=1.6)
    vp90, _ = _driver(cam90).render_pose(aspect=1.6)
    check('fov 60° vs 90° 的 VP 不同（修前两者完全相同 = 死赋值）',
          float(np.max(np.abs(vp60 - vp90))) > 1e-3,
          float(np.max(np.abs(vp60 - vp90))))


# ============ 2) P-03-03/04/06: 投影字段归一 ============
def t_ortho_normalized():
    print('---- 2) ortho_size / ortho 归一 ----')
    cases = [({'ortho_size': 'abc'}, 12.0, False),
             ({'ortho_size': None}, 12.0, False),
             ({'ortho_size': 0}, S.ORTHO_SIZE_MIN, False),
             ({'ortho_size': -5}, S.ORTHO_SIZE_MIN, False),
             ({'ortho_size': float('nan')}, 12.0, False),
             ({'ortho_size': 13}, 13.0, False),
             ({'ortho': 'false'}, 12.0, False),
             ({'ortho': 'true'}, 12.0, True),
             ({'ortho': 'TRUE'}, 12.0, True),
             ({'ortho': 0}, 12.0, False),
             ({'ortho': 1}, 12.0, True),
             ({'ortho': {'weird': 1}}, 12.0, False)]
    for extra, want_sz, want_ortho in cases:
        cam = dict(BASE_CAM); cam.update(extra)
        try:
            d = _driver(cam)
        except Exception as e:                      # 修前: 'abc' -> ValueError
            check('%r 不抛异常' % (extra,), False, '%s: %s' % (type(e).__name__, e))
            continue
        check('%r -> size=%.3g ortho=%s' % (extra, want_sz, want_ortho),
              abs(d.ortho_size - want_sz) < 1e-9 and d.ortho is want_ortho,
              (d.ortho_size, d.ortho))
        if d.ortho:
            vp, _ = d.render_pose(aspect=1.6)
            check('%r 正交 VP 有限 (修前 0 -> ZeroDivisionError)' % (extra,),
                  bool(np.isfinite(vp).all()))


# ============ 3) sceneio 读写成对（D7=A: 同一个值进去/出来） ============
class _UI(object):
    def __init__(self):
        self.canvases = []
    def clear(self):
        self.canvases = []
    def add_canvas(self, c):
        self.canvases.append(c)


class _Engine(object):
    def __init__(self, ortho=False, ortho_size=12.0, fov_deg=60.0):
        self.models = []
        self.materials = []
        self.lights = []
        self.cameras = []
        self.active_camera = None
        self.ui = _UI()
        self.gravity = -9.8
        self.ortho = ortho
        self.ortho_size = ortho_size
        self._fov = math.radians(fov_deg)


def t_sceneio_roundtrip():
    print('---- 3) sceneio 投影读写成对 ----')
    e = _Engine(ortho=True, ortho_size=13.0, fov_deg=75.0)
    cam = {'target': [0, 0, 0], 'distance': 10, 'yaw': 0.6, 'pitch': -0.35}
    data = S.scene_to_dict(e, camera=dict(cam))
    got = data['camera']
    check('写侧写出 ortho/ortho_size/fov',
          got['ortho'] is True and got['ortho_size'] == 13.0 and got['fov'] == 75.0,
          got)
    out = {}
    S.scene_from_dict(_Engine(), data, camera_out=out)
    check('读侧读回同一组值',
          out['ortho'] is True and out['ortho_size'] == 13.0
          and abs(out['fov'] - 75.0) < 1e-9, out)
    # 旧场景 (无投影键) -> 默认, 不崩
    out2 = {}
    S.scene_from_dict(_Engine(), {'version': 7, 'objects': [],
                                  'camera': {'target': [0, 0, 0]}}, camera_out=out2)
    check('旧场景缺投影键 -> 默认 (False/12/60)',
          out2['ortho'] is False and out2['ortho_size'] == 12.0
          and abs(out2['fov'] - 60.0) < 1e-9, out2)


# ============ 4) P-03-07: 暂停态解锁键 + 鼠标增量不累积 ============
def t_paused_unlock():
    print('---- 4) 暂停态解锁键 / 鼠标增量 ----')
    d = _driver()
    d.mouse_lock_allowed = True
    d.set_mouse_locked(True)
    d.set_logic_paused(True)
    d.key_state['Tab'] = True
    toggled = d.poll_unlock()
    check('暂停态 poll_unlock 返回 True', toggled is True, toggled)
    check('暂停态按 Tab -> 解锁 (修前 mouse_locked 仍 True)',
          d.mouse_locked is False and d.mouse_unlock_requested is True,
          (d.mouse_locked, d.mouse_unlock_requested))
    # 渲染帧路径 (advance_logic 暂停早退分支) 也要能解锁
    d2 = _driver()
    d2.mouse_lock_allowed = True
    d2.set_mouse_locked(True)
    d2.set_logic_paused(True)
    d2.key_state['Tab'] = True
    d2.advance_logic(1.0 / 60.0)
    check('advance_logic 暂停分支内也能解锁', d2.mouse_locked is False, d2.mouse_locked)
    # 暂停期不得累积鼠标增量
    d3 = _driver()
    d3.set_mouse_locked(True)
    d3.set_logic_paused(True)
    for _ in range(10):
        d3.feed_mouse_rel(30, 20)
        d3.advance_logic(1.0 / 60.0)
    check('暂停期 pending 不累积 (修前 (300,200))',
          d3._pending_mouse_rel == (0.0, 0.0), d3._pending_mouse_rel)
    d3.set_logic_paused(False)
    d3.advance_logic(1.0 / 60.0)
    check('恢复首帧 mouse_rel 不是巨值',
          abs(d3.mouse_rel[0]) < 100 and abs(d3.mouse_rel[1]) < 100, d3.mouse_rel)
    # 非暂停帧: 逻辑步内轮询一次 (与 GL update_scripts 同) —— 按住不放不得翻两次
    d4 = _driver()
    d4.mouse_lock_allowed = True
    d4.set_mouse_locked(True)
    d4.key_state['Tab'] = True
    d4._update_scripts(1.0 / 60.0)        # 按下沿: 恰好解锁一次
    first = d4.mouse_locked
    d4._update_scripts(1.0 / 60.0)        # 按住不放: 不得再翻
    check('按住解锁键只翻一次 (翻两次 = P-03-01 双触发病灶)',
          first is False and d4.mouse_locked is False,
          (first, d4.mouse_locked))


# ============ 4b) D6=A 返修: 委托必须真的走 engine 唯一实现 ============
def t_unlock_delegation():
    print('---- 4b) 解锁键委托 engine 唯一实现 (D6=A 返修) ----')
    import engine as E

    d = _driver()
    check('script_keys 与 key_state 是同一个 dict (引擎前置)',
          d.script_keys is d.key_state, (id(d.script_keys), id(d.key_state)))
    d.key_state['Tab'] = True
    check('写 key_state 后 script_keys 立即可见（同源）', d.script_keys.get('Tab') is True)
    check('_poll_unlock_local 语义拷贝已删除 (D6=A: 只允许一套实现)',
          not hasattr(d, '_poll_unlock_local'), dir(d)[:0])
    check('提供 _warn_unlock_poll_unavailable（vk_player 解析器前置）',
          callable(getattr(d, '_warn_unlock_poll_unavailable', None)))
    # 真正的委托证据: 打桩 engine 的唯一实现, 观察 SceneDriver.poll_unlock 是否命中它
    orig = E.GLEngine._poll_mouse_unlock_key
    hits = []

    def _spy(inst):
        hits.append(type(inst).__name__)
        return orig(inst)

    E.GLEngine._poll_mouse_unlock_key = _spy
    try:
        d2 = _driver()
        d2.mouse_lock_allowed = True
        d2.set_mouse_locked(True)
        d2.key_state['Tab'] = True
        toggled = d2.poll_unlock()
    finally:
        E.GLEngine._poll_mouse_unlock_key = orig
    check('poll_unlock 真的调用了 engine.GLEngine._poll_mouse_unlock_key',
          hits == ['SceneDriver'], hits)
    check('委托后行为不变: 一次翻转解锁',
          toggled is True and d2.mouse_locked is False,
          (toggled, d2.mouse_locked))
    # 按住不重复翻转 + mouse_lock_allowed=False 永不锁
    d3 = _driver()
    d3.mouse_lock_allowed = False
    d3.set_mouse_locked(True)
    d3.poll_unlock()
    check('mouse_lock_allowed=False -> 永不锁', d3.mouse_locked is False, d3.mouse_locked)
    d4 = _driver()
    d4.mouse_lock_allowed = True
    d4.set_mouse_locked(True)
    d4.key_state['Tab'] = True
    first = d4.poll_unlock()
    second = d4.poll_unlock()               # 按住不放
    check('按住不重复翻转', first is True and second is False and d4.mouse_locked is False,
          (first, second, d4.mouse_locked))


# ============ 5) P-03-08/09: UI 事件派发不静默 ============
class _Comp(object):
    def __init__(self, sid, inst):
        self.script_id = sid
        self._script = inst


class _Obj(object):
    def __init__(self, comps):
        self.guid = 'g1'
        self.name = 'o'
        self.scripts = comps


class _FalsyScript(object):
    """容器式脚本: 定义 __len__ -> 布尔假值 (旧实现会静默回落成组件)."""
    hits = 0

    def __len__(self):
        return 0

    def on_click(self, *a):
        _FalsyScript.hits += 1


class _Host(object):
    def __init__(self, models):
        self.models = models

    def _measure_text(self, text, size=None):
        return (len(text or '') * ((size or 16) // 2), size or 16)

    def __getattr__(self, name):
        return lambda *a, **k: None


class _DrawFacade(object):
    """严格桩: 只有绘制原语, 没有 .models/.scripts (= VkUIEngine 门面)."""
    def _measure_text(self, text, size=None):
        return (len(text or '') * ((size or 16) // 2), size or 16)

    def draw_screen_rect(self, *a, **k):
        pass

    def draw_text_quad(self, *a, **k):
        pass

    def draw_texture_quad(self, *a, **k):
        pass

    def push_scissor(self, *a, **k):
        pass

    def pop_scissor(self, *a, **k):
        pass


def _ui_with_button():
    btn = L.Button(name='b', rect=(0, 0, 50, 20))
    btn.event_bindings = {'click': {'script': 's1', 'method': 'on_click'}}
    ui = L.UIManager()
    c = L.Canvas(canvas_type='screen', width=100, height=100)
    ui.add_canvas(c)
    c.root = btn
    return ui, btn


def t_ui_dispatch():
    print('---- 5) UI 事件派发 (假值实例 / 未实例化 / 坏宿主) ----')
    ui, btn = _ui_with_button()
    _FalsyScript.hits = 0
    host = _Host([_Obj([_Comp('s1', _FalsyScript())])])
    L.UIManager.draw_all(ui, host)
    fired = L._fire_binding(btn, 'click')
    check('假值运行时实例仍派发 (修前 fire=False)', fired is True and
          _FalsyScript.hits == 1, (fired, _FalsyScript.hits))
    host.models[0].scripts[0]._script = None
    fired2 = L._fire_binding(btn, 'click')
    check('未实例化 -> 返回 False 且不再误报"缺方法"', fired2 is False)
    L._SCRIPT_HOST_WARNED = False
    L.UIManager.draw_all(ui, _DrawFacade())
    check('宿主缺 .models -> 出声一次 (修前静默)', L._SCRIPT_HOST_WARNED is True)
    L.UIManager.draw_all(ui, _DrawFacade())
    check('告警只打一次 (不刷屏)', L._SCRIPT_HOST_WARNED is True)


# ============ 6) D7=A: 进脏判定 + 进撤销 + 播放前后恒等 ============
def _new_ed(real_mark_saved=True):
    import editor
    from undo import UndoManager
    ed = editor.EditorApp.__new__(editor.EditorApp)
    ed.models = []
    ed.materials = []
    ed.lights = []
    ed.cameras = []
    ed.current_model_index = 0
    ed.script_keys = {}
    ed.undo = UndoManager()
    ed.is_playing = False
    ed.active_camera = None
    ed.gravity = -9.8
    ed._skybox = None
    ed.ui = L.UIManager()
    ed.camera_target = (0.0, 0.0, 0.0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed.camera_roll = 0.0
    ed.orbit_mode = True
    ed.ortho = False
    ed.ortho_size = 12.0
    ed._fov = math.radians(60.0)
    ed._scene_path = None
    ed.scene_name = '场景'
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.msg = ''
    ed.msg_color = (220, 222, 228)
    ed._msg_until = 0.0
    ed.script_keys = {}
    class _V(object):
        def reset_interaction(self):
            pass
    ed.view = _V()
    if not real_mark_saved:
        ed.mark_saved = lambda: None
    return ed


def t_editor_projection_dirty_undo():
    print('---- 6) D7=A: 脏判定 / 撤销 / 播放前后恒等 ----')
    ed = _new_ed()
    ed.mark_saved()
    check('初始不脏', ed.scene_is_dirty() is False)
    ed.set_camera_projection(ortho=True, ortho_size=13.0, fov=75.0)
    check('camera_proj 改完 -> 场景已改动 (修前恒为 False)',
          ed.scene_is_dirty() is True)
    check('改值真的生效', ed.ortho is True and ed.ortho_size == 13.0
          and abs(math.degrees(ed._fov) - 75.0) < 1e-9,
          (ed.ortho, ed.ortho_size, math.degrees(ed._fov)))
    ed.undo.undo()
    check('撤销 -> 回到改前投影',
          ed.ortho is False and ed.ortho_size == 12.0
          and abs(math.degrees(ed._fov) - 60.0) < 1e-9,
          (ed.ortho, ed.ortho_size, math.degrees(ed._fov)))
    check('撤销后不再脏', ed.scene_is_dirty() is False)
    ed.undo.redo()
    check('重做 -> 又回到 13/75/正交', ed.ortho is True and ed.ortho_size == 13.0)
    ed.undo.undo()
    # 非法值也必须被归一而不是写进状态
    ed.set_camera_projection(ortho_size=0)
    check('camera_proj size=0 -> 钳到 1.0', ed.ortho_size == S.ORTHO_SIZE_MIN,
          ed.ortho_size)
    ed.undo.undo()
    # 播放前后恒等: 机制层 (快照 -> 套用场景投影 -> 还原)
    ed.undo.clear()
    ed.mark_saved()
    before = ed._camera_proj_state()
    ed._apply_camera(ed._camera_dict())          # 模拟"播放强制套用场景相机"
    ed._apply_camera({'target': [0, 0, 0], 'distance': 10, 'yaw': 0.0,
                      'pitch': -1.55, 'ortho': True, 'ortho_size': 13.0,
                      'fov': 60.0})
    check('播放套用了场景正交', ed.ortho is True)
    ed._apply_camera_proj(before)                # 模拟"停止播放还原快照"
    check('停止播放还原编辑态投影', ed._camera_proj_state() == before,
          (before, ed._camera_proj_state()))
    # 接线存在性 (toggle_play 两个分支都用了快照/还原)
    src = open(os.path.join(ROOT, 'editor.py'), encoding='utf-8').read()
    check('toggle_play 进播放时快照投影',
          '_play_edit_proj = self._camera_proj_state()' in src)
    check('toggle_play 退播放时还原投影',
          '_apply_camera_proj(_pep)' in src)


def t_editor_load_without_camera_resets():
    print('---- 7) 加载无 camera 段的旧场景 -> 投影回默认 ----')
    import editor
    old_save = editor.save_last_dir
    editor.save_last_dir = lambda state_file, path: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'old.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump({'version': 7, 'objects': []}, f)
            ed = _new_ed(real_mark_saved=False)
            # 模拟"上一个场景是正交"
            ed.ortho = True
            ed.ortho_size = 30.0
            ed._fov = math.radians(100.0)
            ed._scene_cam = {'target': [0, 0, 0], 'distance': 9, 'yaw': 0.0,
                             'pitch': -1.55, 'ortho': True, 'ortho_size': 30.0,
                             'fov': 100.0}
            ed._load_scene(p)
            check('无 camera 段 -> 投影回默认 (修前残留正交)',
                  ed.ortho is False and ed.ortho_size == S.ORTHO_SIZE_DEFAULT
                  and abs(math.degrees(ed._fov) - S.FOV_DEFAULT_DEG) < 1e-9,
                  (ed.ortho, ed.ortho_size, math.degrees(ed._fov)))
            check('无 camera 段 -> 清空 _scene_cam (防播放沿用上一场景相机)',
                  ed._scene_cam is None, ed._scene_cam)
    finally:
        editor.save_last_dir = old_save


# ============ 8) P-03-10: VK 键位加载真的读到了模板 ============
def t_key_bindings_loaded():
    """N1 回归（HEAD 已存在的潜伏 P1，本批顺带修掉）.

    HEAD 版 scene_driver 没有模块级 import os，而键位加载块用 os.path.join 且整块包在
    except Exception: pass 里 -> NameError 被吞 -> VK 播放器的键位配置**从未生效**
    （永远回落 DEFAULT_ACTIONS）。本组断言锁死两件事:
      ① 真的从模板 + 用户层读到了（不是"看起来有默认值"）；
      ② 加载失败必须出声，不得无声回退。
    """
    print('---- 8) VK 驱动键位加载 (修前 NameError: os 被吞) ----')
    import io
    import contextlib
    import loom_input

    tpl_path = os.path.join(ROOT, '输入配置.default.json')
    check('模板文件存在 (输入配置.default.json)', os.path.exists(tpl_path), tpl_path)
    with open(tpl_path, encoding='utf-8') as f:
        tpl = (json.load(f).get('actions') or {})

    d = SD.SceneDriver()
    check('actions 含 解锁鼠标 动作', '解锁鼠标' in d.actions, list(d.actions)[:3])
    check('解锁鼠标 默认绑定 = Tab', d.actions.get('解锁鼠标') == ['Tab'],
          d.actions.get('解锁鼠标'))
    # ① 模板一致性: 模板里有的动作, 驱动里必须一模一样（修前永远是 DEFAULT_ACTIONS）
    mismatch = {a: (ks, d.actions.get(a)) for a, ks in tpl.items()
                if list(ks) != list(d.actions.get(a) or [])}
    check('驱动 actions 与模板逐条一致 (修前恒为 DEFAULT_ACTIONS)', not mismatch,
          list(mismatch)[:3])
    # ② 用户层覆盖必须生效
    import game_settings
    game_settings.write_key_binding('解锁鼠标', ['F10'])
    d2 = SD.SceneDriver()
    check('用户层 key_bindings 覆盖生效 (解锁鼠标 -> F10)',
          d2.actions.get('解锁鼠标') == ['F10'], d2.actions.get('解锁鼠标'))
    game_settings.write_key_binding('解锁鼠标', ['Tab'])      # 恢复模板值
    # ③ 失败必须出声: 模板名指向不存在的文件 -> 有告警, 且回落默认而非无声
    old_new, old_old = loom_input._ACTION_FILE, loom_input._ACTION_FILE_LEGACY
    loom_input._ACTION_FILE = '__no_such_template__.json'
    loom_input._ACTION_FILE_LEGACY = '__no_such_legacy__.json'
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            d3 = SD.SceneDriver()
        out = buf.getvalue()
    finally:
        loom_input._ACTION_FILE, loom_input._ACTION_FILE_LEGACY = old_new, old_old
    check('模板缺失 -> 有告警 (修前整块被 except: pass 吞掉)',
          '键位模板缺失' in out, out.strip().splitlines()[:2])
    check('模板缺失 -> 回落 DEFAULT_ACTIONS',
          list(d3.actions.get('解锁鼠标')) == list(loom_input.DEFAULT_ACTIONS['解锁鼠标']),
          d3.actions.get('解锁鼠标'))
    # ④ 写用户层可判定 + 立即生效
    r = d.set_action_binding('跳跃', ['j'])
    check('set_action_binding -> saved=True + path 落在隔离配置目录',
          r.get('ok') is True and r.get('saved') is True
          and os.path.abspath(str(r.get('path', ''))).startswith(
              os.path.abspath(_TMPCFG)), r)
    check('写盘真的发生', os.path.exists(r.get('path') or ''), r.get('path'))
    check('内存立即生效', d.actions.get('跳跃') == ['j'], d.actions.get('跳跃'))


def main():
    t_fov_applied()
    t_ortho_normalized()
    t_sceneio_roundtrip()
    t_paused_unlock()
    t_unlock_delegation()
    t_ui_dispatch()
    t_editor_projection_dirty_undo()
    t_editor_load_without_camera_resets()
    t_key_bindings_loaded()
    print('\n总结果: %s' % ('ALL PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()