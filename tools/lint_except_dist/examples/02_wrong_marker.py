"""02_wrong_marker.py — 演示标记格式不完整（应报 WARN）

运行: python loom_lint_except.py examples/02_wrong_marker.py
预期: WARN 2（缺理由 / 缺逗号），ERROR 0
"""


def example_a():
    try:
        x = 1 / 0
    except ZeroDivisionError:
        pass  # _ignore_
        # 错误示范：有标记但没写"为什么可以忽略"（缺逗号 + 缺理由）


def example_b():
    try:
        x = int("abc")
    except ValueError:
        pass  # _ignore_,
        # 错误示范：有逗号但理由为空
