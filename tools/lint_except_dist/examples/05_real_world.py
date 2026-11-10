"""05_real_world.py — 真实项目里的典型场景

运行: python loom_lint_except.py examples/05_real_world.py
预期: 至少 3 ERROR（取决于代码风格）
"""
import json
import os
import sys


def load_scene(path):
    """场景加载 —— 典型的静默失败重灾区。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None  # ← ERROR：加载失败静默返回 None，用户不知道是路径错还是文件坏
    return data


def save_state(state_file, state):
    """状态保存 —— 失败后用户以为保存了。"""
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass  # ← ERROR：保存失败静默，用户以为成功


def get_screen_size():
    """探测分辨率 —— 失败有 fallback，是合理的 _ignore_ 场景。"""
    try:
        import ctypes
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass  # _ignore_, 无头/非 Windows 环境探测失败，下方用默认尺寸兜底
    return (1920, 1080)


def dispatch_user_event(handler, event):
    """用户事件派发 —— 用户代码异常不能炸引擎。"""
    try:
        handler(event)
    except Exception as e:  # _broad_, 用户 handler 可能抛任意异常
        print("事件处理异常: %r" % e, file=sys.stderr)  # ← E3 上报
