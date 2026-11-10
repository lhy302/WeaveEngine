"""01_silent_pass.py — 演示静默吞错（应报 ERROR）

运行: python loom_lint_except.py examples/01_silent_pass.py
预期: ERROR 4，WARN 0
"""
import json


def load_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass  # 错误示范：配置文件不存在，用默认值，但完全没告知用户
    return {}


def parse_int(s):
    try:
        return int(s)
    except ValueError:
        pass  # 错误示范：解析失败静默返回 None


def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return 0  # 错误示范：return 了值，但没告知调用方"这是失败而非真结果"


def cleanup(conn):
    try:
        conn.close()
    except Exception:
        pass  # 错误示范：清理失败静默（即使是清理，也应声明 _ignore_）
