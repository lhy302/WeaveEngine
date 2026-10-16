# -*- coding: utf-8 -*-
"""一键跑全部回归测试 (无头测试 + 真实窗口集成测试).
用法: py -3.12 tests\\run_all.py  (从项目根任意位置均可)
最后一个 test_integration.py 会开真实窗口并弹原生文件对话框? —— 不会,
对话框已 mock 取消; 但会打开 GPU 窗口渲染数帧."""
import os, sys, subprocess, glob

HERE = os.path.dirname(os.path.abspath(__file__))
files = [f for f in sorted(glob.glob(os.path.join(HERE, "test_*.py")))
         if os.path.basename(f) != "test_integration.py"]
files.append(os.path.join(HERE, "test_integration.py"))  # 真实窗口放最后
failed = []
for f in files:
    print("=" * 60)
    print("运行:", os.path.basename(f))
    print("=" * 60)
    r = subprocess.run([sys.executable, f])
    if r.returncode != 0:
        failed.append(os.path.basename(f))
print("=" * 60)
if failed:
    print("有失败:", failed)
    sys.exit(1)
print("全部测试完成 ✅")
