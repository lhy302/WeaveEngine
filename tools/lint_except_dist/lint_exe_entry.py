# -*- coding: utf-8 -*-
"""lint_exe_entry.py — PyInstaller exe 入口（打包成 loom-lint-except.exe）

行为：
  - 扫当前工作目录（用户从哪里启动就扫哪）
  - 当前目录没有 .py 时，扫 exe 自带的 examples/ 演示效果
  - 结束后 pause（双击时窗口不秒关）
"""
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # _ignore_, 老版 Python 无 reconfigure  # _broad_, 编码设置失败不影响主流程
    pass


# PyInstaller frozen 环境：资源在 sys._MEIPASS 里
def resource_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules",
                "venv", ".venv", "env", ".idea", ".vscode", "build", "dist"}


def banner(msg):
    print()
    print("=" * 64)
    print("  " + msg)
    print("=" * 64)
    print()


def collect_py_files(root):
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(dirpath, f))
    return out


def pretty_path(fp):
    """frozen 环境下把 PyInstaller 的临时解压目录替换成相对路径，
    否则报告里显示 C:/Users/xxx/AppData/Local/Temp/_MEIxxxx/examples/... 会让用户困惑。
    """
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        mp_fwd = mp.replace("\\", "/").rstrip("/") + "/"
        fp_fwd = fp.replace("\\", "/")
        if fp_fwd.startswith(mp_fwd):
            return fp_fwd[len(mp_fwd):]
    return fp


def main():
    print()
    print("  loom-lint-except")
    print("  " + "-" * 28)
    print("  检查 Python 代码里有没有「静默吞错」")
    print("  -- 即 except 分支出错后完全没告诉任何人")

    # 1) 扫当前工作目录
    cwd = os.getcwd()
    cwd_files = collect_py_files(cwd)
    use_cwd = len(cwd_files) > 0

    if use_cwd:
        banner("正在扫描当前目录: " + cwd)
        files = cwd_files
    else:
        # 2) 空目录 → 扫 exe 自带的 examples/
        banner("当前目录没有 .py 文件，改为演示 examples/")
        res = resource_dir()
        ex_dir = os.path.join(res, "examples")
        if not os.path.isdir(ex_dir):
            print("找不到 examples/ 目录，无法演示。")
            print("请把 loom-lint-except.exe 复制到 Python 项目根目录再运行。")
            return 1
        files = collect_py_files(ex_dir)

    if not files:
        print("没找到任何 .py 文件。")
        return 1

    # 3) 导入工具
    sys.path.insert(0, resource_dir())
    try:
        import loom_lint_except as L
    except ImportError:
        print("内部错误: 找不到 loom_lint_except 模块。")
        print("这通常意味着 exe 打包不完整，请重新下载。")
        return 1

    # 4) 扫描
    errors = []
    warns = []
    for f in files:
        for v in L.check_file(f):
            if v["severity"] == "ERROR":
                errors.append(v)
            elif v["severity"] == "WARN":
                warns.append(v)

    # 5) 输出
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
        print("  参考 如何使用.md 的「标记速查表」，了解以后怎么规范处理 except。")
        return 0

    # 前 10 处 ERROR
    if errors:
        print("  样例（前 10 处 ERROR）：")
        print()
        for v in errors[:10]:
            print("    %s:%d" % (pretty_path(v["file"]), v["line"]))
            print("      上下文: %s" % v.get("context", "<无>"))
            print("      %s" % v["message"].replace("\n", " ")[:100])
            print()
        if len(errors) > 10:
            print("    ... 还有 %d 处 ERROR" % (len(errors) - 10))
            print()

    # 引导
    print("-" * 64)
    print("  怎么办？")
    print("-" * 64)
    print()
    print("  看到 ERROR，二选一：")
    print()
    print("    A. 确实出错了 → 加日志/上报")
    print("       比如 print('失败: %r' % e) / raise / 返回错误字典")
    print()
    print("    B. 确实无所谓 → 加标记 + 写理由")
    print("       比如 pass  # _ignore_, GL 未就绪时设置视口无效")
    print()
    print("  详细说明见 如何使用.md")
    print()

    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    # 双击运行时 pause（有控制台父进程时不 pause）
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        print()
        try:
            input("按回车键退出...")
        except Exception:  # _ignore_, 用户直接关窗口  # _broad_, input 在非交互环境会抛 EOFError
            pass
    sys.exit(rc)