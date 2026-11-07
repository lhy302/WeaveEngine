# -*- coding: utf-8 -*-
"""game_settings.py — 单游戏设置 (与 Unity PlayerPrefs / UE GameUserSettings 同角色)。

落盘位置: **游戏文件夹**（打包后 = MyGame.exe 同级）的 `游戏设置.json`。
  可用环境变量 LOOM_GAME_DIR 覆盖（编辑器/测试用）。

典型用法（脚本里，切换渲染后端后需重启游戏）:
    api = self.engine.get_render_api()          # 当前生效的后端
    self.engine.set_render_api("vulkan")        # 写入配置, 下次启动生效

启动时由 run_player.resolve_backend 读取: 命令行 --backend > 本文件 > 引擎 设置.json > 默认。
"""
import json
import os
import sys

FILE_NAME = "游戏设置.json"


def game_dir():
    """游戏文件夹: LOOM_GAME_DIR > 主程序所在目录 > 当前目录。"""
    d = os.environ.get("LOOM_GAME_DIR")
    if d and os.path.isdir(d):
        return d
    try:
        main = os.path.abspath(sys.argv[0])
        if main:
            return os.path.dirname(main) or os.getcwd()
    except Exception:
        pass
    return os.getcwd()


def path():
    return os.path.join(game_dir(), FILE_NAME)


def load():
    """读整份配置 (不存在/损坏 -> {})。"""
    try:
        with open(path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def read(key, default=None):
    return load().get(key, default)


def set_value(key, value):
    """写单个配置项 (其它项保留)。返回写入后的整份 dict; 失败抛异常。"""
    d = load()
    d[key] = value
    p = path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return d


BACKENDS = ("vulkan", "opengl", "auto")


def normalize(api):
    """归一后端名; 非法值返回 None。"""
    if api is None:
        return None
    a = str(api).strip().lower()
    return a if a in BACKENDS else None


def read_render_api():
    """读游戏设置里的渲染后端 (缺失/非法 -> None)。"""
    return normalize(read("render_api"))


def write_render_api(api):
    """写渲染后端。返回 (ok, 归一值或 None, 错误信息或 None)。"""
    a = normalize(api)
    if a is None:
        return False, None, "render_api 必须是 vulkan / opengl / auto"
    try:
        set_value("render_api", a)
    except Exception as e:
        return False, a, "写入失败: %r" % (e,)
    return True, a, None