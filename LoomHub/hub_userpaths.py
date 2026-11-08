# -*- coding: utf-8 -*-
r"""hub_userpaths.py — LoomHub 侧的用户可写目录收口（契约 2026-11-08 §2/§4 的 Hub 等价物）。

为什么 Hub 不自带"复用 Loom/userpaths.py"：
  发布形态里 LoomHub 是独立的 PyInstaller onedir 包，引擎源码不在它的可导入路径上，
  「import userpaths」在安装版里会失败 —— 以前 hub_config._userpaths() 就是这样静默
  退化成"写程序目录"，于是装到 Program Files 后设置改不动（ACL: Users=RX）。

规则必须与契约 §2 完全一致（否则卸载器/备份/迁移会分叉）：
  · 根目录: LOOM_USER_ROOT > %LOCALAPPDATA%\Loom > ~/.loom
  · Hub 的配置文件统一放 <root>/hub/ —— 与 Loom/userpaths.hub_settings() 同一落点，
    这样卸载器里"删除 %LOCALAPPDATA%\Loom\hub"就能覆盖 Hub 的全部配置。
  · 本模块只拼路径 / 建目录 / 算备份名；JSON 读写由 hub_config 负责（tmp + os.replace 原子写）。
"""
import os

APP_DIR_NAME = 'Loom'
HUB_SUBDIR = 'hub'
_FALLBACK_DIR = '.loom'


def user_root():
    r"""用户层根目录: LOOM_USER_ROOT > %LOCALAPPDATA%\Loom > ~/.loom。"""
    d = os.environ.get('LOOM_USER_ROOT')
    if d:
        return os.path.abspath(d)
    base = os.environ.get('LOCALAPPDATA')
    if base:
        return os.path.join(os.path.abspath(base), APP_DIR_NAME)
    home = os.path.expanduser('~') or os.getcwd()
    return os.path.join(os.path.abspath(home), _FALLBACK_DIR)


def hub_dir():
    """Hub 配置目录: <root>/hub。"""
    return os.path.join(user_root(), HUB_SUBDIR)


def hub_settings():
    """Hub 设置（用户层）: <root>/hub/settings.json。"""
    return os.path.join(hub_dir(), 'settings.json')


def interpreters():
    """解释器台账: <root>/hub/interpreters.json。"""
    return os.path.join(hub_dir(), 'interpreters.json')


def projects():
    """项目台账: <root>/hub/projects.json。"""
    return os.path.join(hub_dir(), 'projects.json')


def log_path(app='LoomHub'):
    """日志: <root>/logs/<app>/日志.txt。"""
    return os.path.join(user_root(), 'logs', _safe(app), '日志.txt')


def backup_path(path):
    """备份名: 同目录 <name>.bak-<yyyyMMdd-HHmmss>.json（冲突追加 -N）。"""
    import time
    d, name = os.path.split(os.path.abspath(path))
    stem = name[:-5] if name.lower().endswith('.json') else name
    stamp = time.strftime('%Y%m%d-%H%M%S')
    cand = os.path.join(d, '%s.bak-%s.json' % (stem, stamp))
    n = 1
    while os.path.exists(cand):
        cand = os.path.join(d, '%s.bak-%s-%d.json' % (stem, stamp, n))
        n += 1
    return cand


def ensure_dir(p):
    """建目录（p 是目录）。失败会抛（契约 §7: 写失败必须可判定）。"""
    if p:
        os.makedirs(p, exist_ok=True)


def ensure_parent(path):
    """建 path 的父目录。"""
    ensure_dir(os.path.dirname(os.path.abspath(path)))


def _safe(name):
    import re
    s = re.sub(r'[^0-9A-Za-z._\-\u4e00-\u9fa5]+', '_', str(name or '')).strip('._ ')
    return s or 'default'
