# -*- coding: utf-8 -*-
r"""组装两套完整编译引擎 (2026-09-02, 手动测试用):
   Loom(工作区编译版)\ = 工作区引擎 dist + 工作区投放目录 + LoomHub (复用)
   Loom(稳定区编译版)\ = 稳定区引擎 dist + 稳定区投放目录 + LoomHub (复用)

引擎 dist 直接搬 _bench_ws/_bench_stable 现有成果 (不重编);
LoomHub dist 编译一次拷两份 (两侧源码 MD5 核对一致)。
部署全部 copytree/copy2, 不用 Move。"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))
from guiloader import DEFAULT_SETTINGS  # noqa: E402

ROOT = r"D:\my-project"
SRC_WS = os.path.join(ROOT, "Loom(py源代码-工作区)")
SRC_ST = os.path.join(ROOT, "Loom(py源代码-稳定版本备份区)")
DIST_WS = os.path.join(ROOT, "_bench_ws", "ws_build2", "build_entry.dist")
DIST_ST = os.path.join(ROOT, "_bench_stable", "bench_build6", "build_entry.dist")
DIST_HUB = os.path.join(SRC_WS, "LoomHub", "LoomHub", "LoomHub.dist")
SITE_PKG = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "Programs", "Python", "Python312",
                        "Lib", "site-packages")


def merge_tree(src_dir, dst_dir):
    """合并复制 (不清空目标, 同名覆盖)."""
    if not os.path.isdir(src_dir):
        print("   ⚠ 源不存在, 跳过: %s" % src_dir)
        return
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


def assemble(tag, src_root, engine_dist):
    dst = os.path.join(ROOT, "Loom(%s编译版)" % tag)
    print("=" * 60)
    print("[%s] -> %s" % (tag, dst))

    print("  1) 引擎 dist 搬运 (copytree) ...")
    loom_dst = os.path.join(dst, "Loom")
    if os.path.isdir(loom_dst):
        shutil.rmtree(loom_dst)
    shutil.copytree(engine_dist, loom_dst)

    print("  2) 投放目录: GUI/plugins/core_plugins/scripts/assets/保存 ...")
    for sub in ("GUI", "plugins", "core_plugins", "scripts"):
        merge_tree(os.path.join(src_root, "Loom", sub),
                   os.path.join(loom_dst, sub))
    # assets dist 里已带 (bench 冒烟时补拷过), 但以源码区为准再 merge 一次
    merge_tree(os.path.join(src_root, "Loom", "assets"),
               os.path.join(loom_dst, "assets"))
    # 保存夹 = 手动测试场景入口 (压测50/500球 + 场景.json)
    merge_tree(os.path.join(src_root, "Loom", "保存"),
               os.path.join(loom_dst, "保存"))

    print("  3) PySide6 Qt 平台插件 (QUIET 大坑: 缺 qwindows.dll 启动即崩) ...")
    qp = os.path.join(SITE_PKG, "PySide6", "plugins")
    if os.path.isdir(qp):
        merge_tree(qp, os.path.join(loom_dst, "PySide6", "plugins"))
    else:
        print("   ⚠ 未找到 PySide6 plugins: %s" % qp)

    print("  4) 设置.json / 解释器.json (exe 封装版) ...")
    # P1-3 防复发 (2026-09-02): 设置必须全键生成, 否则 fps_limit 落默认
    # '120'(8ms QTimer) 造成编译版编辑器态帧率腰斩 (60→33).
    # 规则: DEFAULT_SETTINGS['loom'] 全键打底 + 源码 设置.json 覆盖
    # (源码缺的键回落默认, 保证键集永远完整).
    loom_defaults = dict(DEFAULT_SETTINGS["loom"])
    try:
        src_settings = json.load(
            open(os.path.join(src_root, "Loom", "设置.json"),
                 encoding="utf-8"))
        loom_defaults.update(src_settings)
        print("     源码设置键: %s" % sorted(src_settings))
    except Exception as exc:
        print("   ⚠ 源码设置.json 读取失败(%s), 用纯默认值" % exc)
    json.dump(loom_defaults,
              open(os.path.join(loom_dst, "设置.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    # 键集自检: 生成结果必须覆盖 DEFAULT_SETTINGS 全键, 否则组装失败
    missing = set(DEFAULT_SETTINGS["loom"]) - set(loom_defaults)
    if missing:
        raise SystemExit("设置.json 键集自检失败, 缺: %s" % sorted(missing))
    print("     设置键集自检 PASS (%d 键, fps_limit=%s)"
          % (len(loom_defaults), loom_defaults.get("fps_limit")))
    meta = {}
    try:
        meta = json.load(open(os.path.join(src_root, "Loom", "解释器.json"),
                              encoding="utf-8"))
    except Exception:
        pass
    json.dump({"name": "Loom", "version": meta.get("version", "1.0.0"),
               "main": None, "main_exe": "Loom.exe",
               "python_version": "3.12.10",
               "description": "编译版封装 (Loom.exe, %s)" % tag},
              open(os.path.join(loom_dst, "解释器.json"), "w",
                   encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print("  5) LoomHub (编译一次两夹复用, 拷贝) ...")
    hub_dst = os.path.join(dst, "LoomHub")
    if os.path.isdir(hub_dst):
        shutil.rmtree(hub_dst)
    shutil.copytree(DIST_HUB, hub_dst)
    merge_tree(os.path.join(SRC_WS, "LoomHub", "GUI"),
               os.path.join(hub_dst, "GUI"))
    json.dump({"gui": "LoomHubGUI", "open_py": True},
              open(os.path.join(hub_dst, "设置.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    n_loom = sum(len(fs) for _, _, fs in os.walk(loom_dst))
    n_hub = sum(len(fs) for _, _, fs in os.walk(hub_dst))
    print("  完成: Loom %d 文件 / LoomHub %d 文件" % (n_loom, n_hub))


assert os.path.isdir(DIST_WS), DIST_WS
assert os.path.isdir(DIST_ST), DIST_ST
assert os.path.isdir(DIST_HUB), "LoomHub dist 未就绪: " + DIST_HUB
assemble("工作区", SRC_WS, DIST_WS)
assemble("稳定区", SRC_ST, DIST_ST)
print("=" * 60)
print("两套完整编译引擎组装完成")
