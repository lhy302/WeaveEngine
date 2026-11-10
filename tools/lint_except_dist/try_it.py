# -*- coding: utf-8 -*-
"""try_it.py -- 一键试用（双击 try_it.bat 或 python try_it.py）

逻辑：
  - 当前目录有 .py 文件 -> 扫当前目录（排除 examples/ tools/ venv 等）
  - 当前目录无 .py 文件 -> 扫 examples/ 演示效果
"""
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # _ignore_, 老版 Python 无 reconfigure  # _broad_, 编码设置失败不影响主流程
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# 扫描时永远排除的目录名
EXCLUDE_DIRS = {"__pycache__", "examples", ".git", "node_modules",
                "venv", ".venv", "env", ".idea", ".vscode", "build", "dist"}


def banner(msg):
    print()
    print("=" * 64)
    print("  " + msg)
    print("=" * 64)
    print()


def collect_py_files(root):
    """收集 root 下的 .py 文件（排除 EXCLUDE_DIRS）。"""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(dirpath, f))
    return out


def main():
    print()
    print("  loom-lint-except 一键试用")
    print("  " + "-" * 28)
    print("  本工具检查 Python 代码里有没有「静默吞错」")
    print("  -- 即 except 分支出错后完全没告诉任何人")

    # 收集当前目录的 .py（排除 examples 等）
    cwd_files = collect_py_files(".")
    use_cwd = len(cwd_files) > 0

    if use_cwd:
        banner("正在扫描当前目录...")
        files = cwd_files
    else:
        banner("当前目录没有 .py 文件，改为演示 examples/ 里的效果")
        ex_dir = os.path.join(HERE, "examples")
        if not os.path.isdir(ex_dir):
            print("找不到 examples/ 目录，无法演示。")
            print("请把 try_it.py + loom_lint_except.py 复制到 Python 项目根目录再运行。")
            return 1
        files = collect_py_files(ex_dir)

    if not files:
        print("没找到任何 .py 文件。")
        return 1

    sys.path.insert(0, HERE)
    try:
        import loom_lint_except as L
    except ImportError:
        print("找不到 loom_lint_except.py，请确保它和本文件在同一目录。")
        return 1

    # 扫描
    errors = []
    warns = []
    for f in files:
        for v in L.check_file(f):
            if v["severity"] == "ERROR":
                errors.append(v)
            elif v["severity"] == "WARN":
                warns.append(v)

    # 结果摘要
    print("-" * 64)
    print("  扫描了 %d 个 .py 文件" % len(files))
    print("-" * 64)
    print()
    print("  ERROR（静默吞错）    : %d 处" % len(errors))
    print("  WARN（标记不全/宽异常）: %d 处" % len(warns))
    print()

    if not errors and not warns:
        print("  [OK] 全部通过！你的代码没有静默吞错问题。")
        print()
        print("  参考 README.md 的「标记协议」，了解以后怎么规范处理 except。")
        return 0

    # 前 5 处 ERROR
    if errors:
        print("  样例（前 5 处 ERROR）：")
        print()
        for v in errors[:5]:
            print("    %s:%d" % (v["file"], v["line"]))
            print("      上下文: %s" % v.get("context", "<无>"))
            print("      %s" % v["message"].replace("\n", " ")[:100])
            print()
        if len(errors) > 5:
            print("    ... 还有 %d 处" % (len(errors) - 5))
            print()

    # 引导
    print("-" * 64)
    print("  想怎么办？")
    print("-" * 64)
    print()
    print("  A. 看完整报告：")
    print("       python loom_lint_except.py .")
    print()
    print("  B. 了解怎么修：")
    print("       打开 README.md 的「标记协议」章节")
    print()
    print("  C. 看示例代码：")
    print("       打开 examples/ 目录（故意写了 5 类典型问题）")
    print()
    if use_cwd:
        print("  提示：这里扫的是你当前目录。想看示例效果，")
        print("        请在一个空目录里运行 try_it.py。")
    else:
        print("  提示：把 try_it.py 复制到你的 Python 项目根目录再运行，")
        print("        就能扫你自己的代码。")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())