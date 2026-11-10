"""04_broad_exception.py — 演示过宽异常类型（应报 WARN）

运行: python loom_lint_except.py examples/04_broad_exception.py
预期: WARN 2（宽异常未声明 _broad_），ERROR 0
"""
import json


def parse_a(s):
    try:
        return json.loads(s)
    except Exception:  # ← 过宽，未声明 _broad_
        print("解析失败")


def parse_b(s):
    try:
        return json.loads(s)
    except (ValueError, TypeError):  # 正确：细化了类型
        print("解析失败")


def user_callback(cb):
    try:
        cb()
    except Exception:  # _broad_, 用户回调可能抛任意异常，引擎必须兜住
        print("回调异常")
