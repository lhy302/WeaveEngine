# -*- coding: utf-8 -*-
"""组装编译版本 (2026-08-14): 三个 Nuitka dist -> Loom(编译版本)
   (Loom / LoomHub / 示例游戏) + GUI 文件夹 + 设置.json + 解释器.json(exe版)
   + 保存/场景.json + 根文档 + scripts/coin_game.py + make_demo_game 加密场景.
   部署必须用复制(copytree/copy2) 不用 Move (防丢 numpy/pygame 目录)."""
import os
import shutil
import json

SRC = r"D:\my-project\Loom(py源代码-工作区)"
DST = r"D:\my-project\Loom(编译版本)"


def copy_tree_contents(src_dir, dst_dir):
    """清空并复制 src_dir 内容到 dst_dir (逐项 copytree/copy2).
    2026-08-22 事故修复: 必须先校验 src 存在再清 dst —— 旧实现"先 rmtree
    再 listdir", dist 缺失时抛出异常后 dst 已被清空 (编译版 Loom\ 整目录
    被清空事故, 用户目测元数据缺失才发现)."""
    if not os.path.isdir(src_dir):
        raise SystemExit("源目录不存在, 拒绝清空目标: %s" % src_dir)
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        s = os.path.join(src_dir, name)
        d = os.path.join(dst_dir, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def merge_tree(src_dir, dst_dir):
    """合并复制 (不清空目标): 复用 build_game/玩家运行时 dist 进 Loom 目录
    (与 Loom.exe 共享运行库目标; 08-22 编译版即同目录共存, 经验证可行)."""
    if not os.path.isdir(src_dir):
        raise SystemExit("源目录不存在: %s" % src_dir)
    os.makedirs(dst_dir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        s = os.path.join(src_dir, name)
        d = os.path.join(dst_dir, name)
        if os.path.isdir(s):
            merge_tree(s, d)
        else:
            if os.path.isfile(d):
                os.remove(d)
            shutil.copy2(s, d)


print("0) 清根目录旧残留 (老版本干净重建, 用户要求 2026-08-22): 除 Loom/LoomHub 全删 ...")
os.makedirs(DST, exist_ok=True)
for name in list(os.listdir(DST)):
    if name not in ('Loom', 'LoomHub'):
        p = os.path.join(DST, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

print("1) 复制 dist (示例游戏 2026-08-20 起废弃不再组装) ...")
copy_tree_contents(os.path.join(SRC, "Loom", "Loom", "build_entry.dist"),
                   os.path.join(DST, "Loom"))
copy_tree_contents(os.path.join(SRC, "LoomHub", "LoomHub", "LoomHub.dist"),
                   os.path.join(DST, "LoomHub"))
if os.path.isdir(os.path.join(DST, "示例游戏")):
    shutil.rmtree(os.path.join(DST, "示例游戏"))   # 历史残留清理

print("1b) 合并 build_game.exe + 玩家运行时 (2026-08-28 补: 发布链路工具三件套) ...")
_src_bg = os.path.join(SRC, "Loom", "build_game", "build_game.dist")
if os.path.isdir(_src_bg):
    merge_tree(_src_bg, os.path.join(DST, "Loom"))
    print("   build_game.dist -> 编译版 Loom\\ (与 Loom.exe 同目录)")
_src_rt = os.path.join(SRC, "Loom", "player_runtime", "game_player.dist")
if os.path.isdir(_src_rt):
    merge_tree(_src_rt, os.path.join(DST, "Loom", "player_runtime"))
    print("   player_runtime -> 编译版 Loom\\player_runtime\\")

print("2) GUI/ + 插件目录 (自定义界面 / 插件系统投放点, 2026-08-28 补) ...")
shutil.copytree(os.path.join(SRC, "Loom", "GUI"),
                os.path.join(DST, "Loom", "GUI"), dirs_exist_ok=True)
shutil.copytree(os.path.join(SRC, "LoomHub", "GUI"),
                os.path.join(DST, "LoomHub", "GUI"), dirs_exist_ok=True)
# 插件系统: plugins/editor|player + core_plugins (含 README) —— Nuitka 只打包
# 代码/数据, 投放点目录必须显式拷, 否则"插件"菜单/封装收集全部失效
for _sub in ("plugins", "core_plugins"):
    _s = os.path.join(SRC, "Loom", _sub)
    if os.path.isdir(_s):
        shutil.copytree(_s, os.path.join(DST, "Loom", _sub), dirs_exist_ok=True)
        print("   Loom/%s -> 编译版" % _sub)

print("2b) PySide6 Qt 平台插件 (2026-08-28 QUIET 大坑修复: Nuitka 不收 \
PySide6\\plugins, 缺失=编译版 Loom.exe 启动即崩无窗无报错; 从已装环境拷入) ...")
try:
    import sys
    import sysconfig
    _sp = sysconfig.get_paths().get('purelib') or os.path.join(
        os.path.dirname(sys.executable), 'Lib', 'site-packages')
    _src_qp = os.path.join(_sp, 'PySide6', 'plugins')
    if os.path.isdir(_src_qp):
        shutil.copytree(_src_qp, os.path.join(DST, 'Loom', 'PySide6', 'plugins'),
                        dirs_exist_ok=True)
        print("   PySide6/plugins -> 编译版 Loom\\ (含 platforms/qwindows.dll)")
    else:
        print("   ⚠ 未找到 PySide6 plugins: %s" % _src_qp)
except Exception as e:
    print("   ⚠ PySide6 plugins 拷贝失败:", e)

print("3) 设置.json 默认 ...")
json.dump({"gui": "LoomGUI", "save_dir": ""},
          open(os.path.join(DST, "Loom", "设置.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
json.dump({"gui": "LoomHubGUI", "open_py": True},
          open(os.path.join(DST, "LoomHub", "设置.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

print("4) Loom 解释器.json (exe 封装版, 供 LoomHub 识别) ...")
# 2026-08-22: version 从源码元数据取 —— 旧写死"编译版"会被版本号白名单
# (^\d+\.\d+\.\d+$, 08-20 安全审查) 拒绝 -> LoomHub 导入报"不是有效的解释器"
_src_meta = {}
try:
    _src_meta = json.load(open(os.path.join(SRC, "Loom", "解释器.json"),
                               encoding="utf-8"))
except Exception:
    _src_meta = {}
json.dump({"name": "Loom", "version": _src_meta.get("version", "1.0.0"),
           "main": None, "main_exe": "Loom.exe", "python_version": "3.12.10",
           "description": "编译版封装 (Loom.exe)"},
          open(os.path.join(DST, "Loom", "解释器.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

print("5) 示例场景 保存\\场景.json ...")
os.makedirs(os.path.join(DST, "Loom", "保存"), exist_ok=True)
shutil.copy2(os.path.join(SRC, "Loom", "保存", "场景.json"),
             os.path.join(DST, "Loom", "保存", "场景.json"))

print("6) 根文档 (先清旧文档再拷, 用户要求 2026-08-22: 老版本文档清理干净) ...")
for f in list(os.listdir(DST)):
    if f.endswith(".txt") or f == "requirements.txt":
        os.remove(os.path.join(DST, f))
for f in sorted(os.listdir(SRC)):
    if f.endswith(".txt") and f != "Unity使用速学笔记.txt":
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))
for f in ("requirements.txt",):
    if os.path.isfile(os.path.join(SRC, f)):
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))

print("7) (示例游戏 2026-08-20 起废弃: scripts 不复制, make_demo_game 不生成)")

print("组装完成:", DST)
for sub in ("Loom", "LoomHub"):
    n = sum(len(fs) for _, _, fs in os.walk(os.path.join(DST, sub)))
    print("  %-6s 文件数: %d" % (sub, n))
