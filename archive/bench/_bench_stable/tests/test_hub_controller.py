# -*- coding: utf-8 -*-
"""
test_hub_controller.py — HubController 命令层测试 (UI 无关, 无头).
UI 模块化 (2026-08-13): 业务动作从 LoomHub.py 抽到 hub_controller.py 后,
本文件固化"命令层可无头测、消息/配置效果正确". 不弹窗口 (filedialog 全
不调用, 用直接传路径/ patch 的方式绕过), 全部用临时目录 + monkeypatch.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PM_DIR = os.path.join(os.path.dirname(HERE), '..', 'LoomHub')
sys.path.insert(0, os.path.dirname(HERE))            # Loom\
sys.path.insert(0, PM_DIR)

import hub_config as cfg
import hub_controller as hc
from hub_controller import HubController

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _mk_ctrl():
    """无头构造 HubController (绕过 __init__ 的 python_version subprocess 与自动扫描)."""
    ctrl = HubController.__new__(HubController)
    ctrl.install_root = ""
    ctrl.interpreters = []
    ctrl.projects = []
    ctrl.msg = ""
    ctrl.msg_level = 'ok'
    ctrl.py_ver = None
    return ctrl


def t_scan_interpreters():
    """扫描安装根: 发现 -> 登记 + 消息; 无发现 -> dim 消息."""
    with tempfile.TemporaryDirectory() as tmp:
        ctrl = _mk_ctrl()
        added = []
        old_scan, old_add = hc.cfg.scan_install_root, hc.cfg.add_interpreter
        try:
            hc.cfg.scan_install_root = lambda: [
                {"name": "Loom", "version": "1.0.0", "kind": "py",
                 "dir": os.path.join(tmp, "1.0.0")},
                {"name": "Loom", "version": "2.0.0", "kind": "exe",
                 "dir": os.path.join(tmp, "2.0.0")}]
            hc.cfg.add_interpreter = lambda it: added.append(it)
            ctrl.scan_interpreters()
            check("扫描消息: 扫描到 2 个", "扫描到 2 个" in (ctrl.msg or ""), ctrl.msg)
            check("扫描消息等级 ok", ctrl.msg_level == 'ok')
            check("扫描登记了 2 个解释器", len(added) == 2)
        finally:
            hc.cfg.scan_install_root, hc.cfg.add_interpreter = old_scan, old_add
        # 无发现
        ctrl2 = _mk_ctrl()
        old_scan2 = hc.cfg.scan_install_root
        try:
            hc.cfg.scan_install_root = lambda: []
            ctrl2.scan_interpreters()
            check("无发现 -> dim + 提示", ctrl2.msg_level == 'dim'
                  and "没有找到" in (ctrl2.msg or ""), ctrl2.msg)
        finally:
            hc.cfg.scan_install_root = old_scan2


def t_new_scene_file():
    """new_scene_file: 写入 v8 空场景."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "a_场景.json")
        _mk_ctrl().new_scene_file(p)
        data = cfg.load_json(p)
        check("空场景 v8 + 空对象/光源", data is not None and data.get('version') == 8
              and data.get('objects') == [] and data.get('lights') == [], data)
        check("空场景含 camera", data is not None and 'camera' in data)


def t_new_project_file():
    """do_new_project_file (绕过对话框直接给路径): 建文件 + 登记 + 消息 + 坏路径容错."""
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.PROJECTS_FILE
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        try:
            ctrl = _mk_ctrl()
            scene = os.path.join(tmp, "我的游戏.json")
            ctrl.do_new_project_file(scene)
            check("建空场景文件", os.path.isfile(scene)
                  and cfg.load_json(scene).get('version') == 8)
            check("登记项目", any(p['name'] == "我的游戏" for p in cfg.load_projects()))
            check("成功消息 ok", "已创建项目" in (ctrl.msg or "")
                  and ctrl.msg_level == 'ok', ctrl.msg)
            # 坏路径 (不存在的目录) -> err 不崩
            ctrl2 = _mk_ctrl()
            ctrl2.do_new_project_file(os.path.join(tmp, "无目录", "x.json"))
            check("坏路径 -> err 不崩", ctrl2.msg_level == 'err'
                  and "创建项目失败" in (ctrl2.msg or ""), ctrl2.msg)
        finally:
            cfg.PROJECTS_FILE = old


def t_unique_name():
    """默认场景名唯一递增 (新项目 / 新项目1 / 新项目2 ...)."""
    ctrl = _mk_ctrl()
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "保存")
        os.makedirs(d)
        check("无冲突 -> 新项目", ctrl.unique_scene_name(os.path.join(tmp, "空")) == "新项目")
        open(os.path.join(d, "新项目.json"), 'w').write("{}")
        check("有冲突 -> 新项目1", ctrl.unique_scene_name(d) == "新项目1")
        open(os.path.join(d, "新项目1.json"), 'w').write("{}")
        check("再冲突 -> 新项目2", ctrl.unique_scene_name(d) == "新项目2")


def t_set_install_root():
    ctrl = _mk_ctrl()
    with tempfile.TemporaryDirectory() as tmp:
        check("有效目录 -> True + 消息", ctrl.set_install_root(tmp)
              and "安装根已改为" in (ctrl.msg or ""))
        check("无效目录 -> False + err", (not ctrl.set_install_root(
            os.path.join(tmp, "nope"))) and ctrl.msg_level == 'err')


def t_set_default_remove():
    """设默认/移除解释器: 配置效果 + 消息; 无选中静默."""
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.INTERPRETERS_FILE
        cfg.INTERPRETERS_FILE = os.path.join(tmp, "interpreters.json")
        try:
            a = {"name": "Loom", "version": "1.0.0", "kind": "py", "dir": "D:\\a",
                 "main": "Loom.py", "path": "D:\\a\\Loom.py"}
            b = {"name": "Loom", "version": "2.0.0", "kind": "exe", "dir": "D:\\b",
                 "main": "Loom.exe", "path": "D:\\b\\Loom.exe"}
            cfg.add_interpreter(a)
            cfg.add_interpreter(b)
            ctrl = _mk_ctrl()
            ctrl.set_default(b)
            check("设为默认生效", cfg.default_interpreter()['version'] == "2.0.0")
            check("设为默认消息", "默认解释器已设为" in (ctrl.msg or ""))
            ctrl.remove_interpreter(a)
            check("移除后剩 b", len(cfg.load_interpreters()) == 1
                  and cfg.load_interpreters()[0]['version'] == "2.0.0")
            check("移除消息 dim", ctrl.msg_level == 'dim')
            ctrl2 = _mk_ctrl()
            ctrl2.set_default(None)
            check("set_default(None) 不动作", ctrl2.msg == "")
        finally:
            cfg.INTERPRETERS_FILE = old


def t_open_project_no_interp():
    """打开项目: 无默认解释器 -> err 提示 (不真的 subprocess)."""
    ctrl = _mk_ctrl()
    old = cfg.default_interpreter
    try:
        cfg.default_interpreter = lambda: None
        ctrl.open_project({"name": "x", "scene": "D:\\s\\a.json"})
        check("无解释器 -> err 提示", ctrl.msg_level == 'err'
              and "还没有解释器" in (ctrl.msg or ""), ctrl.msg)
    finally:
        cfg.default_interpreter = old


def t_view_contract():
    """IHubView 契约: LoomHubGUI / TkHubView 均为 IHubView 实现 (UI 可换性保证)."""
    import importlib.util
    for name, path, cls in [("loomhub_py", os.path.join(PM_DIR, "LoomHub.py"),
                             "LoomHubGUI"),
                            ("loomhub_tk", os.path.join(PM_DIR, "hub_view_tk.py"),
                             "TkHubView")]:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            view = getattr(mod, cls).__new__(getattr(mod, cls))
            check("%s 是 IHubView 实现" % cls, isinstance(view, hc.IHubView))
        except Exception as e:
            check("%s 是 IHubView 实现" % cls, False, repr(e))


if __name__ == "__main__":
    print("========== HubController 命令层测试 ==========")
    t_scan_interpreters()
    t_new_scene_file()
    t_new_project_file()
    t_unique_name()
    t_set_install_root()
    t_set_default_remove()
    t_open_project_no_interp()
    t_view_contract()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
