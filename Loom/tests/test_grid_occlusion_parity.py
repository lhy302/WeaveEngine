# -*- coding: utf-8 -*-
"""test_grid_occlusion_parity.py — 编辑器网格「被物体正确遮挡」两端门（Q-B7-53-1）。

★ 本文件 = **父门**（瘦宿主）；真探针在 tests/_grid_occlusion_child.py（子进程，下划线
  前缀：run_all 只收集 test_*.py，不会把它当门跑）。隔离原因与 test_vk_editor_smoke
  同一条：子进程加载 Qt + 真窗口后，收尾会非确定性卡在驱动 teardown（进程变僵尸数
  分钟）—— 父门只认 verdict 文件，轮询到即收口。

## 这条门钉的是什么（2026-11-22 真窗口取证）

人类裁决原话是「A 网格被物体遮挡，修 GL：让网格走深度测试」。审核 1/3 查出前提与
代码不符（GL 网格本来就是 DEPTH_TEST|BLEND，全仓没有 overlay_scope(enable_only=0)
画网格的调用点）。真窗口取证后是**两个**独立缺陷，本门逐条钉死：

  ① 粗线四边形的角点 z 互换了（commit 68e4998 已修）——a/e 在 p0 却把 b 取了 z0、
     e 取了 z1，四边形被拧成两块深度不连续；网格线是 ±60 世界的长线段，一端常在
     相机背后（近平面裁剪 -> w≈0 -> 屏幕坐标上万像素、z=0），被拧的那半个三角形
     在屏幕空间横跨整个视口，插值深度远小于地面真实深度 -> **网格穿到物体里面**。
     门：tests/test_line_depth_plane.py（插值深度 == 地面真实深度）。
  ② GL 的网格原本由视图层在 plan **之后**画进屏幕 FBO，而后处理开启（默认）时主
     pass 把颜色和深度都写在 color.hdr 上 —— 屏幕 FBO 的深度从没被主 pass 写过，
     于是网格的深度测试**恒失败**：实测 GL 编辑器网格 0 像素（整块不可见）。
     修法：GL 由帧执行器在**最后一个 3D pass 之后**把网格画进**当前场景目标**
     （render/gl/render.py::_draw_grid_in_scene），深度附件 = 刚写完的场景深度；
     视图层读 grid_in_scene_pass 后不再重复画。VK 侧叠加层本来就挂主 pass 深度
     视图，不动。

## 断言（措辞为状态描述）

  ① 网格线在物体前方区域不被画：物体剪影（腐蚀 3px）内 开/关网格的像素差 == 0；
  ② 物体后方的网格照常可见：剪影外像素差 > 1000；
  ③ GL 与 VK 两端一致：同一份取法下两端的 ① 同为 0、②/网格可见量同量级（<= 5%）；
  ④ 网格在编辑态可见（不许为了遮挡把网格修没了）：无物体时开/关网格像素差 > 1000；
  另有 B 段（无窗口）：网格绘制归属、播放态两端都不画网格、编辑态不重复画。

## 修前红（实跑原文见交付报告）

  · 在 68e4998 之前（角点 z 互换）：`FAIL gl A3 物体遮住的地方没有网格（剪影内网格
    像素 == 0）  10240` —— 网格整片画在物体上（穿物体）。
  · 在 ② 未修（HEAD = 253454a 那棵树，只有 68e4998 的 z 修复）：GL
    `FAIL gl A2 网格本身可见（无物体时开/关网格差 > 1000 像素）` 与
    `FAIL gl A4 物体外网格照常可见（剪影外 > 1000 像素）`（两项都是 0 像素：网格
    整块不可见）；同一次运行的 VK 侧全绿 -> 两端不一致。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHILD = os.path.join(HERE, "_grid_occlusion_child.py")

_fails = []
_pass_n = 0


def check(name, cond, detail=""):
    global _pass_n
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


def run_child(backend):
    """拉起一个后端的真窗口探针，只认 verdict 文件（僵尸收尾不拖父门）。"""
    verdict_path = os.path.join(tempfile.gettempdir(),
                                "grid_occlusion_%s_verdict.json" % backend)
    try:
        if os.path.exists(verdict_path):
            os.unlink(verdict_path)
    except OSError:
        pass
    env = dict(os.environ)
    env.setdefault("LOOM_NO_DIALOG", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    print("---- 子进程 %s: %s ----" % (backend, os.path.basename(CHILD)))
    proc = subprocess.Popen([sys.executable, CHILD, backend, verdict_path],
                            env=env, cwd=ROOT)
    deadline = time.monotonic() + 240
    v = None
    while time.monotonic() < deadline:
        try:
            with open(verdict_path, encoding="utf-8") as f:
                v = json.load(f)
            break
        except (OSError, ValueError):
            if proc.poll() is not None and v is None:
                break
            time.sleep(1.0)
    child_rc = proc.poll()
    if v is None and time.monotonic() >= deadline:
        try:
            proc.kill()
        except Exception:
            pass
        print("FAIL %s 子进程超时 240s（无 verdict，已硬杀）" % backend)
    if v is None:
        try:
            with open(verdict_path, encoding="utf-8") as f:
                v = json.load(f)
        except Exception as e:
            print("FAIL %s verdict 不可读: %r" % (backend, e))
    return v, child_rc


def main():
    res = {}
    for backend in ("gl", "vk"):
        v, rc = run_child(backend)
        res[backend] = v
        check("%s 真窗口遮挡探针 verdict 全绿（判定以 verdict 文件为准；rc/僵尸收尾属已知驱动问题）"
              % backend,
              v is not None and v.get("ok") is True and v.get("fails") == [],
              "child_rc=%s fails=%r" % (rc, (v or {}).get("fails")))
        check("%s 断言条数完整（B 段 3 条 + A 段 5 条 = 8 条全跑）" % backend,
              v is not None and v.get("pass_count", -1) >= 8,
              "pass_count=%s" % ((v or {}).get("pass_count", "?"),))

    gl = (res.get("gl") or {}).get("metrics") or {}
    vk = (res.get("vk") or {}).get("metrics") or {}

    # ① 网格线在物体前方区域不被画（两端各自）
    for name, m in (("gl", gl), ("vk", vk)):
        check("%s ① 网格线在物体前方区域不被画（物体剪影内 开/关网格像素差 == 0）" % name,
              m.get("grid_over_object") == 0, m.get("grid_over_object"))

    # ② 物体后方的网格照常可见（两端各自）
    for name, m in (("gl", gl), ("vk", vk)):
        check("%s ② 物体后方的网格照常可见（剪影外像素差 > 1000）" % name,
              int(m.get("grid_outside_object") or 0) > 1000, m.get("grid_outside_object"))

    # ④ 网格在编辑态可见（不许为了遮挡把网格修没了）
    for name, m in (("gl", gl), ("vk", vk)):
        check("%s ④ 网格在编辑态可见（无物体时开/关网格像素差 > 1000）" % name,
              int(m.get("grid_no_object") or 0) > 1000, m.get("grid_no_object"))

    # ③ 两端一致：同一份取法、同一量级（光栅化差异只允许 5% 以内）
    def _close(a, b, tol=0.05):
        # 两端都得真的量到数（metrics 缺失 = 子进程没跑到判据，不能算一致）
        if not isinstance(a, int) or not isinstance(b, int):
            return False
        if a == 0 and b == 0:
            return True
        return abs(a - b) <= tol * max(a, b)

    check("③ 两端一致：物体剪影内网格像素同为 0（GL %r / VK %r）"
          % (gl.get("grid_over_object"), vk.get("grid_over_object")),
          gl.get("grid_over_object") == 0 and vk.get("grid_over_object") == 0)
    check("③ 两端一致：物体外网格像素同量级（差 <= 5%%，GL %r / VK %r）"
          % (gl.get("grid_outside_object"), vk.get("grid_outside_object")),
          _close(gl.get("grid_outside_object"), vk.get("grid_outside_object")))
    check("③ 两端一致：无物体时网格可见量同量级（差 <= 5%%，GL %r / VK %r）"
          % (gl.get("grid_no_object"), vk.get("grid_no_object")),
          _close(gl.get("grid_no_object"), vk.get("grid_no_object")))

    print()
    print("总结果:", "ALL PASS" if not _fails else "有 FAIL: %s" % _fails)
    sys.exit(0 if not _fails else 1)


main()
