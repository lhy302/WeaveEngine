# -*- coding: utf-8 -*-
"""同步 + 精简开源版本 (2026-08-14, 2026-08-16, 2026-08-20 更新):
拷贝源码 -> Loom(开源处理版本)\ 删 tests/test_ime.py/__pycache__/保存/
editor_state.json/LoomHub 配置;
2026-08-16: 演示 GUI (OrangeGUI/MiniHubGUI) 已删, 保留 GUI/ 供外部投放;
2026-08-20: 示例游戏废弃 (coin_game.py 已从源码删, 同步自然不带);
            ColorHubGUI.py (LoomHub 绿色换肤) 保留 (自定义 GUI 示例)."""
import os
import shutil

SRC = r"D:\my-project\Loom(py源代码-工作区)"
DST = r"D:\my-project\Loom(开源处理版本)"

# 'Loom' = Nuitka 中间产物目录 (Loom\Loom\build_entry.dist, 2026-08-22 踩坑:
# 打包进行中跑同步会把 ~48MB dist 复制进开源版)
# 2026-08-23 用户发现 (开源版 917MB 泄漏) 根因: Loom 根目录的
# build_entry.dist/build_entry.build/player_runtime 等打包中间目录未列入删除
# 清单被整体同步 —— 全名单补全 (打包后清理 + 防呆双保险)
LOOM_DELETE = {'tests', 'test_ime.py', '__pycache__', '保存', 'editor_state.json',
               'Loom', 'build_entry.dist', 'build_entry.build', 'player_runtime',
               '玩家运行时', 'rt2', 'tk_build', 'hub_out', 'hub_diag',
               'hub_final', 'hub_final2', '构建器测试',
               'build_game',                     # 2026-08-28: build_game.exe 打包中间
               'nuitka-crash-report.xml'}   # Nuitka 打包自动生成的崩溃分析数据(垃圾)
# 'LoomHub' = Nuitka 中间产物目录 (LoomHub\LoomHub\LoomHub.dist, 2026-08-22
# 同 Loom dist 泄漏事故: 同步须在打包完成后跑, 且目录名列入删除清单)
HUB_DELETE = {'__pycache__', 'interpreters.json', 'projects.json', 'LoomHub',
              'hub_out', 'hub_diag', 'hub_final', 'hub_final2',
              'interpreters.json.bak_polluted'}   # 2026-08-30: 本机配置残留漏网补录


def copy_tree(src_dir, dst_dir, delete_names):
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        if name in delete_names:
            print("  跳过:", os.path.join(src_dir, name))
            continue
        s = os.path.join(src_dir, name)
        d = os.path.join(dst_dir, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


print("1) 同步 Loom ...")
copy_tree(os.path.join(SRC, "Loom"), os.path.join(DST, "Loom"), LOOM_DELETE)
print("2) 同步 LoomHub ...")
copy_tree(os.path.join(SRC, "LoomHub"), os.path.join(DST, "LoomHub"), HUB_DELETE)
print("3) 同步根文档 (先清旧文档再拷贝, 用户要求 2026-08-22 老版本清理干净) ...")
for f in list(os.listdir(DST)):
    if f.endswith(".txt") or f == "requirements.txt":
        os.remove(os.path.join(DST, f))
for f in sorted(os.listdir(SRC)):
    if f.endswith(".txt") or f == "requirements.txt":
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))
print("4) 递归清残留 __pycache__ ...")
n = 0
for base in ("Loom", "LoomHub"):
    for dp, dn, fn in os.walk(os.path.join(DST, base)):
        if "__pycache__" in dp:
            shutil.rmtree(dp)
            n += 1
print("  清了", n, "个 __pycache__")
print("完成:", DST)
for sub in ("Loom", "LoomHub"):
    nf = sum(len(fs) for _, _, fs in os.walk(os.path.join(DST, sub)))
    print("  %-6s 文件数: %d" % (sub, nf))
