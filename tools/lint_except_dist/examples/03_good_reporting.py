"""03_good_reporting.py — 演示正确的上报方式（应全部 PASS）

运行: python loom_lint_except.py examples/03_good_reporting.py
预期: ERROR 0，WARN 0
"""
import json
import logging
import sys

logger = logging.getLogger(__name__)


def load_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as e:
        print("配置缺失，用默认值: %r" % e)          # E2 上报
        return {}


def parse_int(s, default=0):
    try:
        return int(s)
    except ValueError as e:
        logger.warning("解析失败 %r: %r", s, e)    # E4 上报
        return default


def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        raise  # E1 重抛给调用方


def handle_user_input(raw):
    try:
        return json.loads(raw)
    except Exception as e:  # _broad_, 用户输入可能触发任意解析异常
        print("输入无效: %r" % e, file=sys.stderr)  # E3 错误流
        return {"ok": False, "error": str(e)}       # E10 返回错误字典


def release_resource(res):
    try:
        res.release()
    except OSError:
        pass  # _ignore_, 资源释放失败视为已释放，不影响后续流程
