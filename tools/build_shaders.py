# -*- coding: utf-8 -*-
"""build_shaders.py — T3 单源 GLSL -> SPIR-V（glslang 固定版本，缺失/校验失败即构建失败）。

用法: py -3.13 tools/build_shaders.py [--check]

设计（2026-11-11 Phase 0 spike）：
  · 着色器源在 Loom/shaders/*.frag|.vert，正文用 loom_shader_compat.glsl 的宏；
  · `#ifdef LOOM_VK` 只允许出现在兼容层；
  · 构建：glslang -V --target-env vulkan1.1 -DLOOM_VK -o <src>.spv；
  · glslang 固定 16.6.0，校验版本与 sha256（TOOLCHAIN 清单），缺失 -> 非 0 退出（不静默回退 WGSL）。
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADERS = os.path.join(ROOT, "Loom", "shaders")
TOOLCHAIN = os.path.join(ROOT, "tools", "shadertools.lock.json")
DEFAULT_GLSLANG = r"C:\loom_build\shadertools\bin\glslang.exe"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_lock():
    with open(TOOLCHAIN, encoding="utf-8") as f:
        return json.load(f)


def _find_glslang(lock):
    exe = os.environ.get("LOOM_GLSLANG") or DEFAULT_GLSLANG
    if not os.path.isfile(exe):
        raise SystemExit("[shaders] 缺少 glslang: %s（T3 单源构建必须用它；不静默回退 WGSL）" % exe)
    out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    ver = ""
    for line in (out.stdout or "").splitlines():
        if "Version:" in line and "16." in line:
            ver = line.strip()
            break
    want = lock["glslang"]["version"]
    if want not in ver:
        raise SystemExit("[shaders] glslang 版本不符: 期望 %s，实测 %r" % (want, ver))
    sha = _sha256(exe)
    if sha.lower() != lock["glslang"]["sha256"].lower():
        raise SystemExit("[shaders] glslang sha256 不符: 期望 %s，实测 %s"
                         % (lock["glslang"]["sha256"], sha))
    return exe


def _expand(src_path):
    """把 //@@COMPAT@@ 行替换成兼容层内容（GL 侧也用同一函数）。"""
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    with open(os.path.join(SHADERS, "loom_shader_compat.glsl"), encoding="utf-8") as f:
        compat = f.read()
    src = src.replace("//@@COMPAT@@", compat)
    # T3c: 绑定号单点表（GL/VK 共用），着色器里只写 B_xxx
    sys.path.insert(0, os.path.join(ROOT, "Loom"))
    import loom_shader_bindings
    import loom_scene_ubo
    src = src.replace("//@@SCENE_UBO@@",
                      loom_scene_ubo.glsl_block())
    return loom_shader_bindings.expand(src)


def _targets():
    out = []
    for name in sorted(os.listdir(SHADERS)):
        if name.endswith((".frag", ".vert")):
            out.append(os.path.join(SHADERS, name))
    return out


def main(argv):
    lock = _load_lock()
    exe = _find_glslang(lock)
    check_only = "--check" in argv
    rc = 0
    for src in _targets():
        spv = src + ".spv"
        # glslang 按扩展名推断 stage（.frag/.vert），无需额外 flag
        tmp = os.path.join(SHADERS, "_tmp_expanded" + os.path.splitext(src)[1])
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_expand(src))
        try:
            cmd = [exe, "-V", "--target-env", "vulkan1.1", "-DLOOM_VK",
                   tmp, "-o", spv]
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if p.returncode != 0:
            print("[shaders] 编译失败 %s\n%s\n%s" % (src, p.stdout, p.stderr))
            rc = 1
            continue
        size = os.path.getsize(spv) if os.path.isfile(spv) else 0
        print("[shaders] %-28s -> %-24s %5d bytes" % (os.path.basename(src),
                                                       os.path.basename(spv), size))
    if rc == 0 and check_only:
        print("[shaders] --check 通过（版本/sha256/编译全部 OK）")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
