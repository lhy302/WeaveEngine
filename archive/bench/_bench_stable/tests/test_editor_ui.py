# -*- coding: utf-8 -*-
"""
test_editor_ui.py — Loom 编辑器 UI 模块化测试 (2026-08-13, 全无头).
UI 模块化三层:
  - UI 实现层: ui/LoomGUI.py (LoomGUI 默认) / ui/minimal_editor_view.py
  - UI 接口层: ui/editor_ui.py (IEditorView)
  - 控制器层: editor.py EditorApp (命令层, UI 无关)
验证: 命令层 (edit_*/commit_*/rename_* 等自动撤销) / IEditorView 契约 /
视图可注入 (换 UI 只换实现) / 入口 --ui 切换.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine as E
import editor
from mesh import create_cube
from undo import UndoManager
from editor import EditorApp
from ui.editor_ui import IEditorView
from ui.loom_gui import LoomGUI
from ui.minimal_editor_view import MinimalEditorView

E.GLEngine._build_gpu = lambda self, m: None   # 无头桩

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


class _ViewStub:
    """极简 IEditorView 桩 (弹保存框时 view.reset_interaction 需要)."""
    def reset_interaction(self):
        pass
    def handle_key_event(self, ev):
        return False
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False,
                'focus_id': None}


def new_ed():
    """无头 EditorApp 桩: 引擎数据 + 撤销 + 命令层所需字段."""
    ed = EditorApp.__new__(EditorApp)
    ed.models = []; ed.materials = []; ed.lights = []; ed.cameras = []
    ed.current_model_index = 0
    ed.script_keys = {}
    ed.undo = UndoManager()
    ed.is_playing = False
    ed.active_camera = None
    ed.camera_target = (0, 0, 0)
    ed.camera_distance = 10.0
    ed.camera_yaw = 0.6
    ed.camera_pitch = -0.35
    ed._scene_path = None   # 保存/另存为逻辑需要
    ed.last_dir = None
    ed.scene_name = '场景'
    ed.selected_index = -1
    ed.selected_light_index = -1
    ed.selected_camera_index = -1
    ed.msg = ""
    ed.msg_color = (220, 222, 228)
    ed._msg_until = 0.0
    ed.prefab_count = 0
    ed.gizmo_mode = 'translate'
    ed.gizmo_drag = None
    ed.gizmo_axis = None
    ed._insp_undo_start = {}
    ed._light_undo_start = {}
    ed._cam_undo_start = {}
    ed.view = _ViewStub()   # 弹保存框会调 view.reset_interaction
    ed._confirm_callback = None   # 防丢询问回调 (UI 注入; 桩里默认无 -> 直接丢弃继续)
    m = ed.add_model(create_cube(1.5), E.Point3D(0, 0, 0), E.Point3D(0, 0, 0), name='立方体')
    return ed, m


# ============ 命令层: 拖拽式字段命令 (edit_model) ============
def t_edit_model():
    ed, m = new_ed()
    ed.edit_model(m, "位置X", True, 'k.posX',
                  lambda: setattr(m, 'position', E.Point3D(3.0, 0, 0)))
    check("edit_model 拖拽中改值", abs(m.position.x - 3.0) < 1e-9, m.position)
    check("edit_model 拖拽中未压栈", not ed.undo.can_undo)
    ed.edit_model(m, "位置X", False, 'k.posX',
                  lambda: setattr(m, 'position', E.Point3D(5.0, 0, 0)))
    check("edit_model 结束改值", abs(m.position.x - 5.0) < 1e-9)
    check("edit_model 结束压栈", ed.undo.can_undo)
    ed.undo.undo()
    check("edit_model undo 还原起点", abs(m.position.x - 0.0) < 1e-9,
          m.position)


# ============ 命令层: 单次命令 (commit_model) ============
def t_commit_model():
    ed, m = new_ed()
    ed.commit_model(m, "换名", lambda: setattr(m, 'name', '新名'))
    check("commit_model 生效", m.name == '新名')
    check("commit_model 压栈", ed.undo.can_undo)
    ed.undo.undo()
    check("commit_model undo 还原", m.name == '立方体')


# ============ 命令层: 名称失焦 (rename) ============
def t_rename():
    ed, m = new_ed()
    ed.rename(m, '甲', '立方体')
    check("rename 生效", m.name == '甲')
    ed.undo.undo()
    check("rename undo 还原旧名", m.name == '立方体')
    ed.rename(m, '立方体', '立方体')
    check("同名 rename 不压栈", not ed.undo.can_undo)


# ============ 命名合法性 (2026-08-17: 空名/重名 + 共用名字池) ============
def t_rename_validation():
    ed, m = new_ed()
    # ① 空名 (全空白也算空) 拒绝, 不改名、不压栈、提示
    u0 = len(ed.undo.undo_stack)
    ed.rename(m, '   ', '立方体')
    check("空名拒绝", m.name == '立方体'
          and len(ed.undo.undo_stack) == u0 and ed.msg == '名称不能为空')
    # ② 模型重名拒绝 (共用名字池: 模型之间). 直接追加第二个模型避免 add_model 压撤销
    m2 = ed.add_model(create_cube(1.5), E.Point3D(2, 0, 0), E.Point3D(0, 0, 0), name='方块')
    u1 = len(ed.undo.undo_stack)
    ed.rename(m, '方块', '立方体')
    check("模型重名拒绝", m.name == '立方体'
          and len(ed.undo.undo_stack) == u1 and ed.msg == '名称已存在: 方块')
    # ③ 与光源/摄像机共用一个名字池: 同名校验跨类型
    ed.lights.append(E.LightState(kind='directional', name='主光'))
    u2 = len(ed.undo.undo_stack)
    ed.rename(m, '主光', '立方体')
    check("与光源重名拒绝", m.name == '立方体'
          and len(ed.undo.undo_stack) == u2)
    ed.cameras.append(E.CameraState(name='主摄像机'))
    u3 = len(ed.undo.undo_stack)
    ed.rename(m, '主摄像机', '立方体')
    check("与摄像机重名拒绝", m.name == '立方体'
          and len(ed.undo.undo_stack) == u3)
    # ④ 重命名为自己当前名字 (仅去空白) 合法 -> 不压栈 (等同 no-op)
    u4 = len(ed.undo.undo_stack)
    ed.rename(m, ' 立方体 ', '立方体')
    check("去空白后同名 = no-op", m.name == '立方体'
          and len(ed.undo.undo_stack) == u4)
    # ⑤ 合法新名生效并压栈
    u5 = len(ed.undo.undo_stack)
    ed.rename(m, '新名字', '立方体')
    check("合法改名生效", m.name == '新名字'
          and len(ed.undo.undo_stack) == u5 + 1)


def t_rename_light_camera_validation():
    ed, m = new_ed()
    ed.lights = [E.LightState(kind='directional', name='主光')]
    ed.cameras = [E.CameraState(name='主摄像机')]
    light = ed.lights[0]
    cam = ed.cameras[0]
    # 光源空名拒绝
    ed.rename_light(light, '', '主光')
    check("光源空名拒绝", light.name == '主光' and ed.msg == '名称不能为空')
    # 摄像机空名拒绝
    ed.rename_camera(cam, '   ', '主摄像机')
    check("摄像机空名拒绝", cam.name == '主摄像机' and ed.msg == '名称不能为空')
    # 光源与物体/摄像机重名拒绝 (共用名字池)
    ed.rename_light(light, m.name, '主光')   # m.name == '立方体'
    check("光源与物体重名拒绝", light.name == '主光')
    ed.rename_light(light, '主摄像机', '主光')
    check("光源与摄像机重名拒绝", light.name == '主光')
    # 摄像机与物体/光源重名拒绝
    ed.rename_camera(cam, m.name, '主摄像机')
    check("摄像机与物体重名拒绝", cam.name == '主摄像机')
    ed.rename_camera(cam, '主光', '主摄像机')
    check("摄像机与光源重名拒绝", cam.name == '主摄像机')
    # 合法改名生效并压栈
    ed.rename_camera(cam, '跟随相机', '主摄像机')
    check("摄像机合法改名", cam.name == '跟随相机' and ed.undo.can_undo)


def t_text_input_routing():
    """IME 合成文本 (pygame.TEXTINPUT) -> 命名框缓冲 (2026-08-17)."""
    import pygame
    from gui import GUI
    g = GUI.__new__(GUI)
    g._focus = 'insp.name'
    g._input = {'insp.name': ''}
    g._num_focus = set()
    g._submit = {}
    g.notice = None
    g._widget_rects = []
    ev = pygame.event.Event(pygame.TEXTINPUT, {'text': '中'})
    check("TEXTINPUT 追加中文", g.handle_key_event(ev) is True
          and g._input['insp.name'] == '中')
    g.handle_key_event(pygame.event.Event(pygame.TEXTINPUT, {'text': '文'}))
    check("TEXTINPUT 连续追加", g._input['insp.name'] == '中文')
    # 数值框不接收 IME 合成文本
    g._num_focus.add('insp.name')
    g.handle_key_event(pygame.event.Event(pygame.TEXTINPUT, {'text': '1'}))
    check("数值框不收 TEXTINPUT", g._input['insp.name'] == '中文')
    # 无焦点时不消费
    g._focus = None
    check("无焦点 TEXTINPUT 不消费",
          g.handle_key_event(pygame.event.Event(pygame.TEXTINPUT, {'text': 'x'})) is False)


# ============ 命令层: gizmo 模式 / 显隐 / 组件 ============
def t_gizmo_mode():
    ed, m = new_ed()
    ed.gizmo_drag = ('X', None, None)
    ed.set_gizmo_mode('rotate')
    check("set_gizmo_mode 切换且清拖拽", ed.gizmo_mode == 'rotate'
          and ed.gizmo_drag is None)


def t_toggle_visible():
    ed, m = new_ed()
    ed.toggle_visible(m)
    check("toggle_visible 生效", m.visible is False and ed.undo.can_undo)
    ed.undo.undo()
    check("toggle_visible undo", m.visible is True)


def t_rigidbody():
    ed, m = new_ed()
    ed.add_rigidbody(m)
    check("add_rigidbody 生效", m.rigidbody is not None)
    ed.undo.undo()
    check("add_rigidbody undo 移除", m.rigidbody is None)


def t_script():
    ed, m = new_ed()
    ed.add_script(m, 'rotate')
    check("add_script 生效", len(m.scripts) == 1
          and m.scripts[0].script_id == 'rotate')
    ed.undo.undo()
    check("add_script undo 移除", len(m.scripts) == 0)


# ============ 光源命令 ============
def t_light_cmd():
    ed, m = new_ed()
    ed.lights = []
    light = ed.add_light('directional')   # 需 _build_gpu 桩已置 (光源无 GPU)
    ed.edit_light(light, "强度", True, 'k.int', lambda: setattr(light, 'intensity', 3.0))
    check("edit_light 拖拽中", abs(light.intensity - 3.0) < 1e-9)
    ed.edit_light(light, "强度", False, 'k.int', lambda: setattr(light, 'intensity', 4.0))
    check("edit_light 结束压栈", ed.undo.can_undo)
    ed.undo.undo()
    check("edit_light undo", abs(light.intensity - 1.0) < 1e-9, light.intensity)


# ============ 场景改动跟踪 (新建前询问是否保存, 2026-08-13) ============
def t_dirty_tracking():
    ed, m = new_ed()
    ed.mark_saved()
    check("mark_saved 后不脏", not ed.scene_is_dirty())
    ed.edit_model(m, "位置", False, 'k.pos',
                  lambda: setattr(m, 'position', E.Point3D(1, 0, 0)))
    check("改场景后变脏", ed.scene_is_dirty())
    ed.mark_saved()
    check("再 mark 不脏", not ed.scene_is_dirty())
    # 旋转编辑器相机不算场景改动 (digest 排除轨道相机)
    ed.camera_yaw = 1.2
    check("转相机视角不算脏", not ed.scene_is_dirty())


# ============ 保存 / 另存为 / 防丢 (2026-08-13) ============
def t_save_scene():
    """保存: 有文件直接存(不弹框), 无文件=弹框; 另存为: 总是弹框."""
    import filedialog as FD
    import tempfile
    ed, m = new_ed()
    _sv = FD.save_file
    _sf = editor.STATE_FILE
    editor.STATE_FILE = os.path.join(tempfile.mkdtemp(), "state.json")
    try:
        # 另存为: 总是弹框, 取消 -> False
        ed._scene_path = None
        FD.save_file = lambda *a, **k: None
        check("另存为(取消) -> False", ed.save_scene_as() is False)
        # 另存为: 选路径 -> True + 保存到该路径
        ed._scene_path = None
        _p = os.path.join(tempfile.mkdtemp(), "as.json")
        FD.save_file = lambda *a, **k: _p
        check("另存为(选路径) -> True", ed.save_scene_as() is True
              and os.path.isfile(_p))
        # 保存: 无文件 + 对话框取消 -> False (与另存为一致)
        ed._scene_path = None
        FD.save_file = lambda *a, **k: None
        check("保存(无文件+取消) -> False", ed.save_scene() is False)
        # 保存: 有文件直接存 -> True + 文件存在 (不弹框)
        ed._scene_path = os.path.join(tempfile.mkdtemp(), "s.json")
        check("保存(有文件直接存) -> True", ed.save_scene() is True
              and os.path.isfile(ed._scene_path))
    finally:
        FD.save_file = _sv
        editor.STATE_FILE = _sf


def t_guard_unsaved():
    """防丢统一入口 (controller._confirm_unsaved, UI 注入询问回调):
    未改动直接过; 改动点"不保存"=丢弃继续(True); 点"保存"=先存再继续;
    取消(含弹框 X) = 中止(False) 返回编辑界面. 兼容旧 bool 回调."""
    import tempfile
    ed, m = new_ed()
    ed.mark_saved()
    ed._confirm_callback = lambda: False    # 兼容旧 bool: False=不保存
    check("未改动 guard 通过", ed._confirm_unsaved() is True)
    ed.edit_model(m, "位置", False, 'k.pos', lambda: setattr(m, 'position', E.Point3D(1, 0, 0)))
    check("改动点'否' -> 丢弃继续 (True)", ed._confirm_unsaved() is True)
    ed._confirm_callback = lambda: 'cancel'     # 2026-08-22 三态: 取消 (弹框 X)
    check("改动点X/取消 -> 中止 (False, 回编辑界面)",
          ed._confirm_unsaved() is False)
    check("取消后场景未被保存 (仍脏)", ed.scene_is_dirty() is True)
    ed._confirm_callback = lambda: 'discard'    # 三态: 不保存
    check("改动返回'discard' -> 丢弃继续 (True)", ed._confirm_unsaved() is True)
    ed._confirm_callback = lambda: True     # 兼容旧 bool: True=保存
    ed._scene_path = os.path.join(tempfile.mkdtemp(), "g.json")
    check("改动点'是'(有文件直接存) -> 通过", ed._confirm_unsaved() is True)
    ed.mark_saved()
    ed.edit_model(m, "位置", False, 'k.pos', lambda: setattr(m, 'position', E.Point3D(2, 0, 0)))
    ed._confirm_callback = lambda: 'save'       # 三态: 保存
    check("改动返回'save'(有文件直接存) -> 通过", ed._confirm_unsaved() is True)


# ============ 视图契约 + 注入 ============
class _GuiStub:
    mouse_pos = (0, 0); buttons = (0, 0, 0); pressed = set()
    released = set(); wheel = 0; click_captured = False; _focus = None


def t_view_contract():
    # LoomGUI (Qt 原生视图) 是鸭子协议实现 (QMainWindow+契约方法), 不继承 ABC
    _CONTRACT = ('attach', 'input_state', 'handle_key_event',
                 'reset_interaction', 'draw')
    check("LoomGUI 满足 IEditorView 契约 (鸭子方法齐)",
          all(hasattr(LoomGUI, m) for m in _CONTRACT))
    check("MinimalEditorView 实现 IEditorView",
          issubclass(MinimalEditorView, IEditorView))
    v = MinimalEditorView.__new__(MinimalEditorView)
    v.gui = _GuiStub()
    st = v.input_state()
    check("Minimal input_state 字段齐全",
          {'click_captured', 'focus_id', 'mouse_pos'} <= set(st), st)
    check("Minimal 吞掉全部按键", v.handle_key_event(None) is True)
    v.reset_interaction()
    check("Minimal reset_interaction 不崩", True)


def t_inject_view():
    """换 UI = 注入另一个 IEditorView 实现, 控制器零改动.
    无头桩: 不建真实 GUI (需要 GL ctx), 手工绑 controller 后走 IEditorView 接口."""
    ed, m = new_ed()
    v = MinimalEditorView.__new__(MinimalEditorView)
    v.gui = _GuiStub()
    v.ctl = ed
    ed.view = v
    st = ed.view.input_state()
    check("注入后 input_state 可用", isinstance(st, dict)
          and st['click_captured'] is True)
    check("注入后 handle_key_event 可用", ed.view.handle_key_event(None) is True)


# ============ 入口 --ui ============
def t_entry_ui():
    import Loom
    check("--ui minimal -> MinimalEditorView",
          isinstance(Loom._make_editor_view('minimal'), MinimalEditorView))
    check("--ui default -> None (用默认 LoomGUI)",
          Loom._make_editor_view('default') is None)
    _, _, _, _, _, _, ui = Loom._parse_args(['--ui', 'minimal'])
    check("_parse_args 解析 --ui", ui == 'minimal')
    _, _, _, _, _, _, ui2 = Loom._parse_args([])
    check("无 --ui 默认 qt (2026-08-18 起 Qt 编辑器为默认)", ui2 == 'qt')


if __name__ == "__main__":
    print("========== Loom 编辑器 UI 模块化测试 ==========")
    t_edit_model()
    t_commit_model()
    t_rename()
    t_rename_validation()
    t_rename_light_camera_validation()
    t_text_input_routing()
    t_gizmo_mode()
    t_toggle_visible()
    t_rigidbody()
    t_script()
    t_light_cmd()
    t_view_contract()
    t_inject_view()
    t_dirty_tracking()
    t_save_scene()
    t_guard_unsaved()
    t_entry_ui()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
