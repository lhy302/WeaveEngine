import json
import os
import shutil
import subprocess
import sys

def merge_tree(src_dir, dst_dir):
    if not os.path.isdir(src_dir):
        print("   ! 源不存在, 跳过: %s" % src_dir)
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

def main():
    assert os.path.isdir(DIST_LOOM), "Loom dist 未就绪: " + DIST_LOOM
    loom_dst = os.path.join(DST, "Loom")
    if os.path.isdir(loom_dst):
        shutil.rmtree(loom_dst)
    print("1) Loom dist -> Loom(编译版)\\Loom (删旧放新) ...")
    shutil.copytree(DIST_LOOM, loom_dst)
    print("2) 投放目录 ...")
    for sub in ("GUI", "plugins", "core_plugins", "scripts", "assets", "保存"):
        merge_tree(os.path.join(SRC_WS, "Loom", sub),
                   os.path.join(loom_dst, sub))
    print("2b) ckernels DLL (2026-09-07 C 内核; fastpath 冻结路径按 exe 同级找) ...")
    ck_src = os.path.join(SRC_WS, "Loom", "ckernels", "loom_kernels.dll")
    ck_dst = os.path.join(loom_dst, "ckernels")
    if not os.path.isfile(ck_src):
        raise SystemExit("ckernels DLL 缺失: " + ck_src)
    os.makedirs(ck_dst, exist_ok=True)
    shutil.copy2(ck_src, os.path.join(ck_dst, "loom_kernels.dll"))
    print("   loom_kernels.dll -> ckernels\\ (%d B)"
          % os.path.getsize(os.path.join(ck_dst, "loom_kernels.dll")))
    print("2c) core_components 白名单投放 (2026-09-08 M2b; ★绝不整目录递归,"
          " 见调研 §2.3) ...")
    # 白名单 = 引擎运行必需; 显式排除探针靶 badvector.dll / ambiguous.dll
    CC_WHITELIST = (
        os.path.join("pipeline", "pipeline.dll"),
        "module_ref.dll",
        "registry.json",
        "module_loader.py",
        "module_registry.py",
    )
    CC_FORBIDDEN = ("badvector.dll", "ambiguous.dll")
    cc_src = os.path.join(SRC_WS, "Loom", "core_components")
    cc_dst = os.path.join(loom_dst, "core_components")
    for rel in CC_WHITELIST:
        base = os.path.basename(rel).lower()
        if base in CC_FORBIDDEN:
            raise SystemExit("白名单自检失败: 禁止投放 %s" % rel)
        s = os.path.join(cc_src, rel)
        d = os.path.join(cc_dst, rel)
        if not os.path.isfile(s):
            raise SystemExit("core_components 白名单文件缺失: " + s)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if os.path.isfile(d):
            os.remove(d)
        shutil.copy2(s, d)
        print("   %-32s -> core_components\\ (%d B)"
              % (rel.replace(os.sep, "/"), os.path.getsize(d)))
    # 2d) pipeline_glue.py 投放 (源码根; engine.py 函数内 import 的兜底副本)
    _pg_src = os.path.join(SRC_WS, "Loom", "pipeline_glue.py")
    if os.path.isfile(_pg_src):
        _pg_dst = os.path.join(loom_dst, "pipeline_glue.py")
        if os.path.isfile(_pg_dst):
            os.remove(_pg_dst)
        shutil.copy2(_pg_src, _pg_dst)
        print("   pipeline_glue.py                 -> Loom\\ (%d B)"
              % os.path.getsize(_pg_dst))
    # 收口自检: 目标目录内不得出现任何靶文件
    leaked = []
    for dirpath, _dirnames, filenames in os.walk(cc_dst):
        for fn in filenames:
            if fn.lower() in CC_FORBIDDEN:
                leaked.append(os.path.join(dirpath, fn))
    if leaked:
        raise SystemExit("core_components 误带靶文件: %s" % leaked)
    print("   白名单自检 PASS (%d 文件, 无 badvector/ambiguous)"
          % len(CC_WHITELIST))
    print("3) PySide6 plugins (QUIET 大坑) ...")
    qp = os.path.join(SITE_PKG, "PySide6", "plugins")
    if os.path.isdir(qp):
        merge_tree(qp, os.path.join(loom_dst, "PySide6", "plugins"))
    else:
        raise SystemExit("PySide6 plugins 缺失: " + qp)
    print("4) 设置.json = 源码版同设置 (用户指令; 全键打底防腰斩) ...")
    sys.path.insert(0, os.path.join(SRC_WS, "Loom"))
    from guiloader import DEFAULT_SETTINGS  # noqa: E402
    loom_defaults = dict(DEFAULT_SETTINGS["loom"])
    src_settings = json.load(open(os.path.join(SRC_WS, "Loom", "设置.json"),
                                  encoding="utf-8"))
    loom_defaults.update(src_settings)
    json.dump(loom_defaults,
              open(os.path.join(loom_dst, "设置.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=2)
    missing = set(DEFAULT_SETTINGS["loom"]) - set(loom_defaults)
    if missing:
        raise SystemExit("设置键集自检失败, 缺: %s" % sorted(missing))
    print("   键集自检 PASS (%d 键, fps_limit=%s logic_fps=%s)"
          % (len(loom_defaults), loom_defaults.get("fps_limit"),
             loom_defaults.get("logic_fps")))
    print("5) 解释器.json (exe 封装版) ...")
    meta = json.load(open(os.path.join(SRC_WS, "Loom", "解释器.json"),
                          encoding="utf-8"))
    json.dump({"name": "Loom", "version": meta.get("version", "1.0.0"),
               "main": None, "main_exe": "Loom.exe",
               "python_version": "3.12.10",
               "description": "编译版封装 (Loom.exe)"},
              open(os.path.join(loom_dst, "解释器.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=2)
    print("6) LoomHub — 增量流程: 编译版现有 LoomHub 原样保留 (用户指令:"
          "没修改不重编, 不拷不删) ...")
    hub_dst = os.path.join(DST, "LoomHub")
    if not os.path.isdir(hub_dst):
        raise SystemExit("编译版缺 LoomHub (首次组装需先备好): " + hub_dst)
    n_hub = sum(len(fs) for _, _, fs in os.walk(hub_dst))
    print("   保留现有 LoomHub (%d 文件)" % n_hub)
    print("7) 根文档 ...")
    for d in DOCS:
        p = os.path.join(SRC_WS, d)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(DST, d))
    n_loom = sum(len(fs) for _, _, fs in os.walk(loom_dst))
    print("完成: Loom %d 文件 / LoomHub 保留 %d 文件" % (n_loom, n_hub))
    # ---- 8) M2b 新增: 编译版 registry.json sha256 回填 (审计 P13 完整性钉扎) ----
    # 让编译版 registry.json 与其自身 DLL 自洽 (源侧 registry.json 由
    # build_all.bat 的 refresh 步骤钉源侧哈希, 两侧哈希因 PE 时间戳而不同,
    # 故投放后必须对编译版再钉一次)。脚本失败即硬停, 绝不投出未钉扎的副本。
    _tmp_dir = os.path.join(SRC_WS, "Loom", "tests", "_tmp")
    print("8) 编译版 registry.json sha256 回填 (refresh_registry_sha.py) ...")
    _rf = os.path.join(_tmp_dir, "refresh_registry_sha.py")
    _rc = subprocess.call([sys.executable, _rf, "--root", loom_dst])
    if _rc != 0:
        raise SystemExit("编译版 registry.json sha256 回填失败 (rc=%d): %s" % (_rc, _rf))
    print("   编译版 registry.json 已与其 DLL 自洽")
    # ---- 9) M2b 新增: 投放校验 (硬判据 = 存在性 + 大小 + 导出符号 + module_id) ----
    # 见 M2b投放校验设计_20260908.txt §5.2; DLL 的 SHA256 为软信息。
    # 退出码 != 0 -> raise SystemExit, 组装流程在发布前硬停 (fail-fast)。
    print("9) 投放校验 (verify_release.py: 导出符号 + 关键字符串 + 大小) ...")
    _vr = os.path.join(_tmp_dir, "verify_release.py")
    _rc = subprocess.call([sys.executable, _vr,
                           "--src", os.path.join(SRC_WS, "Loom"),
                           "--dst", loom_dst,
                           "--snapshot"])
    if _rc != 0:
        raise SystemExit("投放校验 FAIL (rc=%d): 见上方明细; 禁止发布" % _rc)
    print("   投放校验 PASS (硬判据全过; DLL SHA256 差异为 PE 时间戳, 预期)")

if __name__ == "__main__":
    main()
