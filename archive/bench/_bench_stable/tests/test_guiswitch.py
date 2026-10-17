# -*- coding: utf-8 -*-
"""
test_guiswitch.py — 可插拔 GUI 系统测试 (2026-08-14, 全无头).
guiloader: 扫描(GUI/ 文件夹 + 文件名后缀 + 前部标识, 只显示标识合法的避免导入坏文件) /
  加载(官方懒 import + 自定义 importlib+build_gui) / 设置(设置.json 原子写, 坏文件回默认) /
  resolve(加载失败回退官方 + 写回设置).
自定义 GUI 用临时文件测试 (2026-08-16 起: 原演示 GUI OrangeGUI/MiniHubGUI 已删除,
GUI 大改后废弃, 官方 LoomGUI/LoomHubGUI 之外的自定义界面靠外部投放).
"""
import os
import sys
import tempfile

os.environ['SDL_VIDEODRIVER'] = 'dummy'   # 官方 LoomHubGUI / MiniHubGUI 需 pygame (不弹窗)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # Loom\ (guiloader / ui / editor ...)
HUB_DIR = os.path.join(os.path.dirname(HERE), '..', 'LoomHub')
sys.path.insert(0, HUB_DIR)                          # LoomHub\ (hub_controller)

import guiloader
from ui.editor_ui import IEditorView
from hub_controller import IHubView

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# ---------------- 测试用 GUI 文件内容 ----------------
LOOM_VALID = """# -*- coding: utf-8 -*-
# gui: loom
# gui-name: 深色界面
# gui-desc: 测试用自定义 Loom 界面
from ui.editor_ui import IEditorView

class DarkGUI(IEditorView):
    def __init__(self, controller=None):
        self.ctl = controller
    def attach(self, c):
        self.ctl = c
    def input_state(self):
        return {'mouse_pos': (0, 0), 'buttons': (0, 0, 0), 'pressed': set(),
                'released': set(), 'wheel': 0, 'click_captured': False, 'focus_id': None}
    def handle_key_event(self, ev):
        return False
    def reset_interaction(self):
        pass
    def draw(self, c, dt):
        pass

def build_gui(controller=None):
    return DarkGUI(controller)
"""

LOOM_BROKEN_IMPORT = """# gui: loom
raise RuntimeError("boom 坏文件")
"""

LOOM_NO_FACTORY = """# gui: loom
class NoFactoryGUI(object):
    pass
"""

LOOM_WRONG_MARKER = """# gui: loomhub
def build_gui(controller=None):
    return None
"""

LOOM_NO_MARKER = """class NoMarkGUI(object):
    pass
"""

HUB_VALID = """# -*- coding: utf-8 -*-
# gui: loomhub
# gui-name: 测试Hub界面
from hub_controller import IHubView

class TestHubGUI(IHubView):
    def __init__(self, controller=None):
        self.ctrl = controller
    def attach(self, c):
        self.ctrl = c
    def run(self):
        pass

def build_gui(controller=None):
    return TestHubGUI(controller)
"""

HUB_WRONG_SUFFIX = """# gui: loomhub
def build_gui(controller=None):
    return None
"""


def make_loom_base():
    tmp = tempfile.mkdtemp()
    _write(os.path.join(tmp, 'GUI', 'DarkGUI.py'), LOOM_VALID)
    _write(os.path.join(tmp, 'GUI', 'BrokenGUI.py'), LOOM_BROKEN_IMPORT)
    _write(os.path.join(tmp, 'GUI', 'NoFactoryGUI.py'), LOOM_NO_FACTORY)
    _write(os.path.join(tmp, 'GUI', 'WrongGUI.py'), LOOM_WRONG_MARKER)
    _write(os.path.join(tmp, 'GUI', 'NoMarkGUI.py'), LOOM_NO_MARKER)
    _write(os.path.join(tmp, 'GUI', 'FooHubGUI.py'), LOOM_VALID)   # HubGUI 后缀, Loom 不收
    _write(os.path.join(tmp, 'GUI', 'notgui.txt'), "x")
    return tmp


def make_hub_base():
    tmp = tempfile.mkdtemp()
    _write(os.path.join(tmp, 'GUI', 'TestHubGUI.py'), HUB_VALID)
    _write(os.path.join(tmp, 'GUI', 'PlainGUI.py'), HUB_WRONG_SUFFIX)   # GUI.py 后缀, LoomHub 不收
    _write(os.path.join(tmp, 'GUI', 'notes.txt'), "x")
    return tmp


# ============ 扫描过滤 ============
def t_scan_filter():
    tmp = make_loom_base()
    ids = [g['id'] for g in guiloader.scan_guis('loom', base=tmp)]
    check("scan 含官方 LoomGUI", 'LoomGUI' in ids, ids)
    check("scan 含合法自定义 DarkGUI", 'DarkGUI' in ids, ids)
    check("scan 含 BrokenGUI(有标识, 加载失败由 resolve 回退)", 'BrokenGUI' in ids)
    check("scan 含 NoFactoryGUI(有标识但缺工厂)", 'NoFactoryGUI' in ids)
    check("scan 不含错程序标识 WrongGUI", 'WrongGUI' not in ids, ids)
    check("scan 不含无标识 NoMarkGUI", 'NoMarkGUI' not in ids)
    check("scan 不收 HubGUI 后缀 FooHubGUI (Loom 只收 GUI.py)", 'FooHubGUI' not in ids)
    # LoomHub 后缀相反: 只收 HubGUI.py
    tmp2 = make_hub_base()
    ids2 = [g['id'] for g in guiloader.scan_guis('loomhub', base=tmp2)]
    check("scan(LoomHub) 含 TestHubGUI", 'TestHubGUI' in ids2, ids2)
    check("scan(LoomHub) 不收 GUI.py 后缀 PlainGUI", 'PlainGUI' not in ids2)


# ============ 加载 ============
def t_load():
    tmp = make_loom_base()
    v = guiloader.load_gui('loom', 'DarkGUI', controller=None, base=tmp)
    check("load 自定义 DarkGUI 成 IEditorView", isinstance(v, IEditorView), v)
    for bad, label in (('BrokenGUI', '坏文件(import 抛错)'),
                       ('NoFactoryGUI', '缺 build_gui 工厂'),
                       ('NoSuchGUI', '不存在')):
        try:
            guiloader.load_gui('loom', bad, controller=None, base=tmp)
            check("load %s 抛异常" % label, False)
        except Exception:
            check("load %s 抛异常" % label, True)


# ============ 设置 round-trip ============
def t_settings():
    tmp = tempfile.mkdtemp()
    guiloader.save_settings('loom', {'gui': 'DarkGUI', 'save_dir': 'D:/x'}, base=tmp)
    s = guiloader.load_settings('loom', base=tmp)
    check("设置 round-trip (gui/save_dir)", s.get('gui') == 'DarkGUI'
          and s.get('save_dir') == 'D:/x', s)
    check("缺设置文件回默认", guiloader.load_settings('loom',
          base=tempfile.mkdtemp()).get('gui') == 'LoomGUI')
    bad = tempfile.mkdtemp()
    _write(os.path.join(bad, '设置.json'), "{not json")
    check("坏设置文件回默认", guiloader.load_settings('loom', base=bad).get('gui') == 'LoomGUI')


# ============ resolve: 回退 / 自定义 / 官方 ============
def t_resolve():
    tmp = make_loom_base()
    # 坏自定义 -> 回退官方(None) + 写回设置
    guiloader.save_settings('loom', {'gui': 'BrokenGUI'}, base=tmp)
    v = guiloader.resolve_gui('loom', controller=None, base=tmp)
    check("坏自定义 resolve 回退官方(None)", v is None)
    s = guiloader.load_settings('loom', base=tmp)
    check("回退后设置.gui 改回官方", s.get('gui') == 'LoomGUI', s)
    # 合法自定义 -> 返回视图
    guiloader.save_settings('loom', {'gui': 'DarkGUI'}, base=tmp)
    v2 = guiloader.resolve_gui('loom', controller=None, base=tmp)
    check("合法自定义 resolve 返回 IEditorView", isinstance(v2, IEditorView), v2)
    # 官方默认 -> None
    guiloader.save_settings('loom', {'gui': 'LoomGUI'}, base=tmp)
    check("官方 resolve 返回 None", guiloader.resolve_gui('loom', base=tmp) is None)


# ============ LoomHub 官方 ============
def t_hub_guis():
    # 2026-08-17 起官方默认 = TkHubView (tkinter; pygame LoomHubGUI 因 IME 污染弃用).
    # 旧设置值 'LoomHubGUI' 已非官方 id -> 走自定义加载失败 -> 回退官方 + 写回设置
    # (等效"旧配置自动迁移").
    tmp = tempfile.mkdtemp()
    guiloader.save_settings('loomhub', {'gui': 'LoomHubGUI'}, base=tmp)   # 旧值
    v = guiloader.resolve_gui('loomhub', controller=None, base=tmp)
    check("LoomHub 旧 LoomHubGUI 设置回退官方 TkHubView", v is not None
          and type(v).__name__ == 'TkHubView', v)
    s = guiloader.load_settings('loomhub', base=tmp)
    check("回退后设置.gui 改回官方", s.get('gui') == 'TkHubView', s)
    # 官方默认
    guiloader.save_settings('loomhub', {'gui': 'TkHubView'}, base=tmp)
    v2 = guiloader.resolve_gui('loomhub', controller=None, base=tmp)
    check("LoomHub 官方 resolve 返回 TkHubView", v2 is not None
          and type(v2).__name__ == 'TkHubView', v2)
    # 坏自定义 -> 回退官方
    guiloader.save_settings('loomhub', {'gui': '不存在GUI'}, base=tmp)
    v3 = guiloader.resolve_gui('loomhub', controller=None, base=tmp)
    check("LoomHub 坏自定义回退官方", v3 is not None
          and type(v3).__name__ == 'TkHubView', v3)


# ============ 入口 _make_editor_view ============
def t_entry():
    import Loom
    from ui.minimal_editor_view import MinimalEditorView
    tmp = make_loom_base()
    guiloader.save_settings('loom', {'gui': 'DarkGUI'}, base=tmp)
    v = Loom._make_editor_view('default', base=tmp)
    check("_make_editor_view(default,自定义) 返回自定义视图", isinstance(v, IEditorView), v)
    check("_make_editor_view(minimal) 仍 Minimal",
          isinstance(Loom._make_editor_view('minimal'), MinimalEditorView))
    check("_make_editor_view(default, 空目录) 官方返回 None",
          Loom._make_editor_view('default', base=tempfile.mkdtemp()) is None)


if __name__ == "__main__":
    print("========== Loom/LoomHub 可插拔 GUI 测试 ==========")
    t_scan_filter()
    t_load()
    t_settings()
    t_resolve()
    t_hub_guis()
    t_entry()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
