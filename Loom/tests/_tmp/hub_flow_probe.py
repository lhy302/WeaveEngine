# -*- coding: utf-8 -*-
"""端到端探针: 真实 LoomHubGUI 初始化 + 模拟点击"新建" (目录框返回临时目录).
验证: 启动自动扫描 + 新建项目建场景+登记 全链路不崩. 临时配置不污染真实."""
import os, sys, tempfile
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_ROOT, 'Loom'))
sys.path.insert(0, os.path.join(_ROOT, 'LoomHub'))

import hub_config as cfg
_tmp = tempfile.mkdtemp()
cfg.INTERPRETERS_FILE = os.path.join(_tmp, "interpreters.json")
cfg.PROJECTS_FILE = os.path.join(_tmp, "projects.json")
cfg.add_interpreter({"name": "Loom", "version": "1.0.0", "kind": "py",
                     "dir": os.path.dirname(os.path.abspath(__file__)),
                     "main": "Loom.py", "path": "x", "default": True})

import LoomHub as pm
import filedialog
scene_path = os.path.join(_tmp, "新游戏.json")
filedialog.save_file = lambda *a, **k: scene_path       # 模拟用户保存文件对话框返回

app = pm.LoomHubGUI(400, 300)    # 真实 init: pygame 窗口 + 自动扫描
print("启动后 projects:", cfg.load_projects())
app._action_new_project()        # 模拟点击"新建"
projs = cfg.load_projects()
print("新建后 projects:", projs)
ok = any(p['name'] == "新游戏" and os.path.isfile(p['scene'])
         and p['scene'] == scene_path for p in projs)
print("RESULT:", "PASS" if ok else "FAIL")
import pygame; pygame.quit()
