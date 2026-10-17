# -*- coding: utf-8 -*-
"""MiniHubGUI 渲染探针 (SDL dummy, 2026-08-14): 主界面 + 设置面板渲染不崩."""
import os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
import sys
sys.path.insert(0, r"D:\my-project\Loom(py源代码)\Loom")
sys.path.insert(0, r"D:\my-project\Loom(py源代码)\LoomHub")
import guiloader


class _Ctl:
    install_root = "C:\\Program Files\\Loom"
    py_ver = "3.12.10"
    msg = ""
    msg_level = 'ok'
    interpreters = [{'name': 'Loom', 'version': '1.0.0', 'kind': 'py',
                     'dir': 'D0', 'default': True},
                    {'name': 'Loom', 'version': '2.0.0', 'kind': 'exe',
                     'dir': 'D1', 'default': False}]
    projects = [{'name': '项目1', 'scene': 'D:\\p1\\场景.json'}]

    def default_interpreter(self):
        return self.interpreters[0]
    def set_msg(self, text, level='ok'):
        self.msg = text; self.msg_level = level


v = guiloader.load_gui('loomhub', 'MiniHubGUI', controller=_Ctl(),
                       base=r"D:\my-project\Loom(py源代码)\LoomHub")
print("加载:", type(v).__name__, " 是 IHubView:", isinstance(v, object))
v._draw()
v._show_settings = True
v._draw()
v._show_settings = False
v._draw()
print("主界面 + 设置面板渲染 OK ✅")
