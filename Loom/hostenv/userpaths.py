# -*- coding: utf-8 -*-
"""userpaths.py — 用户可写配置目录的**唯一**收口点（2026-11-08 用户配置目录契约 §2）。

契约: docs/design/用户配置目录契约_20261108.md
分层:
  · 默认模板层 = 发布夹/引擎目录里的同名文件（设置.json / 输入配置.default.json /
    游戏设置.json）—— **只读**，运行时永不写；
  · 用户层     = %LOCALAPPDATA%\Loom\…  —— 只存 delta（用户改过的键）；
  · 备份       = 用户层同目录 *.bak-<yyyyMMdd-HHmmss>.json。

环境变量（仅测试/调试）:
  LOOM_USER_ROOT  覆盖 user_root()
  LOOM_GAME_DIR   仍由 game_settings 侧作为"最高优先级强制覆盖"（见该模块）

本模块只拼路径、建目录、算标识与备份名；**不做** JSON 读写（读写在各配置文件
模块内统一走 tmp + os.replace 原子语义）。
"""
import hashlib
import os
import re
import time
import uuid

APP_DIR_NAME = "Loom"        # %LOCALAPPDATA%\Loom
_FALLBACK_DIR = ".loom"      # 无 LOCALAPPDATA 时 ~/.loom


# ---------------- 根目录 ----------------

def user_root():
    """用户层根目录: LOOM_USER_ROOT > %LOCALAPPDATA%\\Loom > ~/.loom."""
    d = os.environ.get("LOOM_USER_ROOT")
    if d:
        return os.path.abspath(d)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return os.path.join(os.path.abspath(base), APP_DIR_NAME)
    home = os.path.expanduser("~") or os.getcwd()
    return os.path.join(os.path.abspath(home), _FALLBACK_DIR)


# ---------------- 固定路径（契约 §2 的 8 个 API） ----------------

def engine_settings():
    """引擎/编辑器设置（设置.json 的用户层）。"""
    return os.path.join(user_root(), "engine", "settings.json")


def hub_settings():
    """LoomHub 设置（第 5 批接入）。"""
    return os.path.join(user_root(), "hub", "settings.json")


def game_settings(game_id):
    """打包游戏的 游戏设置.json 用户层: <root>\\games\\<game_id>\\settings.json."""
    return os.path.join(user_root(), "games", safe_name(game_id), "settings.json")


def project_settings(pid):
    """编辑器工程的 游戏设置.json 用户层: <root>\\projects\\<pid>\\settings.json."""
    return os.path.join(user_root(), "projects", safe_name(pid), "settings.json")


def log_path(app):
    """日志落盘位置: <root>\\logs\\<app>\\日志.txt（game_player / LoomHub 用）。"""
    return os.path.join(user_root(), "logs", safe_name(app), "日志.txt")


def backup_path(path):
    """备份名: <同目录><name>.bak-<yyyyMMdd-HHmmss>.json（冲突时追加 -N）。"""
    d, name = os.path.split(os.path.abspath(path))
    stem = name[:-5] if name.lower().endswith(".json") else name
    stamp = time.strftime("%Y%m%d-%H%M%S")
    cand = os.path.join(d, "%s.bak-%s.json" % (stem, stamp))
    n = 1
    while os.path.exists(cand):
        cand = os.path.join(d, "%s.bak-%s-%d.json" % (stem, stamp, n))
        n += 1
    return cand


def ensure_dir(p):
    """建目录（p 可以是目录或文件路径的所在目录的父目录）。调用方传目录。"""
    if p:
        os.makedirs(p, exist_ok=True)


def ensure_parent(path):
    """建 path 的父目录。"""
    ensure_dir(os.path.dirname(os.path.abspath(path)))


# ---------------- 标识（契约 §3） ----------------

_SAFE_RE = re.compile(r"[^0-9A-Za-z._\-\u4e00-\u9fa5]+")


def safe_name(name, default="default"):
    """清洗成可用作目录名的标识（保留中文/字母/数字/._-，其余替换为 _）。"""
    s = _SAFE_RE.sub("_", str(name or "")).strip("._ ")
    return (s or default)[:64]


def sha1_short(text, n=8):
    return hashlib.sha1(str(text).encode("utf-8", "replace")).hexdigest()[:n]


def game_id_for(dir_path, title=None):
    """打包游戏标识: <清洗后的标题>-<sha1(exe 目录)[:8]>（契约 §3 缺省规则）。"""
    d = os.path.abspath(dir_path or os.getcwd())
    base = title or os.path.basename(d.rstrip("\\/")) or "game"
    return "%s-%s" % (safe_name(base, "game"), sha1_short(d))


def project_id(project_dir):
    """编辑器工程标识: <工程>/.loom/project_id（首次生成 uuid4 并落盘）。

    读取失败/写失败都上抛由调用方处理（契约 §5-3: 写失败必须可判定）。
    返回 (project_id, created)。
    """
    proj = os.path.abspath(project_dir)
    pdir = os.path.join(proj, ".loom")
    pfile = os.path.join(pdir, "project_id")
    try:
        with open(pfile, "r", encoding="utf-8") as f:
            pid = f.read().strip()
        if pid:
            return pid, False
    except FileNotFoundError:
        pass
    except OSError:
        # 目录不可读/权限问题: 上抛交给上层决定（不静默造新 id 导致配置分裂）
        raise
    pid = uuid.uuid4().hex
    ensure_dir(pdir)
    tmp = pfile + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(pid)
    os.replace(tmp, pfile)
    return pid, True
