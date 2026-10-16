# -*- coding: utf-8 -*-
"""ColorHubGUI 加载链路验证探针 (2026-08-20): guiloader 扫描 + import + 实例化."""
import sys
sys.path.insert(0, r"D:\my-project\Loom(py源代码)\Loom")
sys.path.insert(0, r"D:\my-project\Loom(py源代码)\LoomHub")
# 模拟真实 LoomHub 启动 (guiloader 按程序目录 = sys.argv[0] 目录扫描 GUI\)
sys.argv[0] = r"D:\my-project\Loom(py源代码)\LoomHub\LoomHub.py"
import guiloader

guis = guiloader.scan_guis('loomhub')
print("scan:", [(g['id'], g['name'], g.get('official')) for g in guis])

import importlib.util
p = r"D:\my-project\Loom(py源代码)\LoomHub\GUI\ColorHubGUI.py"
spec = importlib.util.spec_from_file_location("ColorHubGUI", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

import hub_view_tk
v = m.build_gui()
print("view class:", type(v).__name__, "| inherits TkHubView:", isinstance(v, hub_view_tk.TkHubView))
print("build_gui ok, title:", v.root.title())
v.root.destroy()
print("ALL OK")
