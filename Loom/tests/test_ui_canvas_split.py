# -*- coding: utf-8 -*-
"""test_ui_canvas_split.py — loom_ui -> ui/canvas/ 拆分结构门 (Q-B7-38-1 第 7 批, 2026-11-26)

拆分: Loom/loom_ui.py 原 1728 行 / 15 类按域+按层纯搬进 ui/canvas/ 包,
loom_ui.py 留薄 shim (sys.modules 替换, 照 agent_commands.py -> eai/ 先例 e72b96c),
16 处旧式 import (from loom_ui import Canvas / import loom_ui / loom_ui.X) 一行不改。

本门验四件事 (纯搬迁零行为变化的结构件):
  A. loom_ui.py 是薄 shim (< 40 行 / 零 class 定义 / sys.modules 换成 ui.canvas);
  B. 15 个 UI class 双路导入同一对象 (loom_ui.X is ui.canvas.X);
  C. 各子文件行数防回潮 (不许再长成单巨文件; 阈值 = 拆分当时行数 + 余量);
  D. 模块级可变状态经 shim 猴补丁语义不变 (loom_ui._SCRIPT_HOST_WARNED = False
     这类赋值要落到真身 ui.canvas.manager, 照 test_beta3_batch2_camera_proj.py:404 的用法)。

修前红证据 (拆分前 HEAD 99d2349 实测, 见交付报告): 拆分前 loom_ui.py 1728 行 /
15 个 class 定义 / 无 sys.modules 替换 -> A 组全红; ui.canvas 不存在 -> B/D 组 ImportError。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ['LOOM_NO_DIALOG'] = '1'

ok = True

def check(label, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False

def nlines(rel):
    return len(io.open(os.path.join(ROOT, rel), encoding="utf-8").read().splitlines())

CLASSES = ("UIElement", "Canvas", "UIManager", "Shape", "Panel", "Text",
           "Image", "Button", "Slider", "Toggle", "ProgressBar",
           "ScrollView", "InputField", "Dropdown", "GridLayout")

MAX_LINES = {
    "loom_ui.py": 40,
    "ui/canvas/__init__.py": 90,
    "ui/canvas/element.py": 300,
    "ui/canvas/canvas.py": 90,
    "ui/canvas/manager.py": 620,
    "ui/canvas/widgets_basic.py": 280,
    "ui/canvas/widgets_input.py": 570,
    "ui/canvas/widgets_layout.py": 210,
}

print("=== A. loom_ui.py 薄 shim ===")
shim_src = io.open(os.path.join(ROOT, "loom_ui.py"), encoding="utf-8").read()
shim_lines = len(shim_src.splitlines())
shim_classes = [l for l in shim_src.splitlines() if l.startswith("class ")]
check("A1 loom_ui.py < 40 行", shim_lines < 40, "实际 %d 行" % shim_lines)
check("A2 loom_ui.py 零 class 定义", not shim_classes, shim_classes)
check("A3 loom_ui.py 用 sys.modules 换成 ui.canvas",
      "sys.modules[__name__] = _canvas" in shim_src and "import ui.canvas" in shim_src)

print()
print("=== B. 15 class 双路导入同一对象 ===")
import loom_ui
import ui.canvas
check("B1 loom_ui is ui.canvas (同一模块对象)", loom_ui is ui.canvas)
bad = [n for n in CLASSES if getattr(loom_ui, n) is not getattr(ui.canvas, n)]
check("B2 15 个 class 双路取到同一对象", not bad, bad)
homes = sorted({getattr(loom_ui, n).__module__ for n in CLASSES})
check("B3 全部 class 实现都住在 ui/canvas/ 包内", all(h.startswith("ui.canvas") for h in homes), homes)

print()
print("=== C. 各子文件行数防回潮 ===")
for rel in sorted(MAX_LINES):
    n = nlines(rel)
    check("C %s <= %d 行" % (rel, MAX_LINES[rel]), n <= MAX_LINES[rel], "实际 %d 行" % n)

print()
print("=== D. 模块级可变状态经 shim 的猴补丁语义 ===")
import ui.canvas.manager as _mgr
check("D1 shim 可见 _fire_binding 等助手",
      callable(loom_ui._fire_binding) and callable(loom_ui._find_script_instances)
      and callable(loom_ui._warn_script_host_once))
loom_ui._SCRIPT_HOST_WARNED = True
check("D2 写 shim 落到真身 manager (赋值转发)", _mgr._SCRIPT_HOST_WARNED is True)
_mgr._SCRIPT_HOST_WARNED = False
check("D3 读 shim 拿到真身活值 (读转发, 无陈旧副本)", loom_ui._SCRIPT_HOST_WARNED is False)
_SENT = object()
loom_ui._ACTIVE_ENGINE = _SENT
check("D4 _ACTIVE_ENGINE 赋值转发到真身", _mgr._ACTIVE_ENGINE is _SENT)
check("D5 键码表可读 (惰性 pygame 初始化过)", isinstance(_mgr._KEY_CODE_TO_NAME, dict))

print()
print("总结果:", "ALL PASS" if ok else "有 FAIL")
sys.exit(0 if ok else 1)
