# -*- coding: utf-8 -*-
"""一次性清理: 删除 py源代码 里的 Nuitka 打包中间目录 + 所有 __pycache__.
只清源码目录 Loom(py源代码) 下的, 不碰 Loom(编译版本).
用法: py -3.12 "Loom\tests\_tmp\cleanup_build.py" [--incl-hub]
--incl-hub: 一并删除 LoomHub 的打包中间目录 (等 LoomHub 打包完成后才可删)."""
import os
import shutil
import sys

ROOT = r"D:\my-project\Loom(py源代码)"
incl_hub = "--incl-hub" in sys.argv


def rm(p):
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
        print("已删:", p)
    elif os.path.exists(p):
        os.remove(p)
        print("已删:", p)


removed = 0
# 1. Loom 的 Nuitka 中间目录 (build/dist, 产物已移走)
rm(os.path.join(ROOT, "Loom", "Loom"))
# 2. LoomHub 的 Nuitka 中间目录 (等打包完成后加 --incl-hub)
if incl_hub:
    rm(os.path.join(ROOT, "LoomHub", "LoomHub"))
# 3. 所有 __pycache__ (递归)
for root, dirs, files in os.walk(ROOT):
    if "__pycache__" in dirs:
        rm(os.path.join(root, "__pycache__"))
        dirs.remove("__pycache__")
    for f in list(files):
        if f.endswith(".pyc") or f.endswith(".pyo"):
            rm(os.path.join(root, f))
print("清理完成")
