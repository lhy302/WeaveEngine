# -*- coding: utf-8 -*-
"""一键跑全部回归测试 (无头测试 + 真实窗口集成测试).
用法: py -3.12 tests\\run_all.py  (从项目根任意位置均可)
最后一个 test_integration.py 会开真实窗口并弹原生文件对话框? —— 不会,
对话框已 mock 取消; 但会打开 GPU 窗口渲染数帧."""
import os, sys, subprocess, glob

# 2026-11-06: Windows 控制台/管道默认 GBK, 末尾 "全部测试完成 ✅" 会抛
# UnicodeEncodeError -> 明明全绿却 exit=1 (与各 test_*.py 的 P-02 修复同款).
# 统一 UTF-8(replace): 失败信号重新只由子进程退出码决定。
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# 2026-11-08 (beta3 回补审计 N2): 统一把运行期配置隔离到临时目录。
# 背景: 配置体系改为"用户层 %LOCALAPPDATA%\Loom\…"后, 没有显式隔离的测试会在
# **真实用户目录**里留下 games\tests-<hash>\settings.json / engine\settings.json
# (实测两处)。setdefault 不覆盖测试自己已设的值, 所以各测试的精细隔离仍然优先。
import tempfile as _tf_iso
os.environ.setdefault('LOOM_USER_ROOT', _tf_iso.mkdtemp(prefix='loom_tests_userroot_'))

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
