"""selftest.py — 工具自检（确保工具在自己和示例上都按预期工作）

用法:
    python selftest.py

退出码: 0 = 全部通过；1 = 有失败
"""
import io
import os
import sys

# 让 Windows 控制台安全输出中文
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # _ignore_, 老版 Python 无 reconfigure  # _broad_, 编码设置失败不影响主流程
    pass

# 把工具路径加入搜索路径
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import loom_lint_except as L


def count(rel_path):
    """返回 (errors, warns)。"""
    path = os.path.join(HERE, rel_path)
    vs = L.check_file(path)
    e = sum(1 for v in vs if v["severity"] == "ERROR")
    w = sum(1 for v in vs if v["severity"] == "WARN")
    return e, w


def main():
    fails = []
    def check(label, actual, expected):
        ok = (actual == expected)
        print(("PASS" if ok else "FAIL"), label,
              "实际=%r 期望=%r" % (actual, expected))
        if not ok:
            fails.append(label)

    # 1) 工具自己必须通过自己
    e, w = count("loom_lint_except.py")
    check("工具自身 0 ERROR", e, 0)
    check("工具自身 0 WARN", w, 0)

    # 2) 示例 01：静默吞错应全报 ERROR
    e, w = count("examples/01_silent_pass.py")
    check("01 应报 4 ERROR", e, 4)

    # 3) 示例 03：正确上报应全 PASS
    e, w = count("examples/03_good_reporting.py")
    check("03 应 0 ERROR", e, 0)
    check("03 应 0 WARN", w, 0)

    # 4) 示例 02：标记不完整应报 WARN
    e, w = count("examples/02_wrong_marker.py")
    check("02 应 0 ERROR", e, 0)
    check("02 应 2 WARN", w, 2)

    # 5) 示例 04：宽异常应报 WARN
    # （parse_a 无 _broad_ = 1 WARN；parse_b 精确异常 = PASS；user_callback 有 _broad_ = PASS）
    e, w = count("examples/04_broad_exception.py")
    check("04 应 0 ERROR", e, 0)
    check("04 应 1 WARN", w, 1)

    # 6) 示例 05：真实场景应报 ERROR
    # load_scene 的 return None（静默默认值）+ save_state 的 pass = 2 ERROR
    e, w = count("examples/05_real_world.py")
    check("05 应至少 2 ERROR", e >= 2, True)

    print()
    if fails:
        print("失败 %d 项:" % len(fails))
        for f in fails:
            print("  -", f)
        return 1
    print("全部通过 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())