# -*- coding: utf-8 -*-
"""test_vk_editor_smoke.py — S4 门：VK 编辑器视口（「编辑器支持 VK」五阶段·阶段 4）。

★ 本文件 = **父门**（瘦宿主）；真探针在 tests/_vk_smoke_child.py（子进程，下划线前缀：run_all 只收集 test_*.py，不会把它当门跑）。
  为什么隔离：子进程加载 Qt + wgpu + Vulkan 真窗口后，进程收尾（ExitProcess /
  TerminateProcess 都一样）会非确定性卡在图形驱动的内核态 teardown 里（进程变
  僵尸数分钟，本机 GTX 1050 Ti 实测）—— run_all 若直接跑子进程体会被拖死。
  父门本身零 Qt/wgpu 依赖：spawn 子进程（超时 180s 硬杀）→ 读 verdict → 落
  PASS/FAIL 与退出码，自己干净退出。子进程的 PASS/FAIL 明细原样透传（下方）。

门内容（与修前红同口径，见子脚本 docstring）：
  A. 结构：VkEditorApp/VkViewport 存在、MRO、编辑器方法唯一实现、事件桥 11 方法；
  B. 真窗口：VK 编辑器 60 帧无异常 + grab() 非背景像素 + 编辑态 选中/拖 gizmo/加物体。

修前必红：VkViewport / VkEditorApp 不存在时子脚本 import 段即红（历史证据：
  FAIL A1 + ModuleNotFoundError ui.vk_viewport，EXIT 1）。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHILD = os.path.join(HERE, '_vk_smoke_child.py')

_fails = []
_pass_n = 0


def check(name, cond, detail=""):
    global _pass_n
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


def main():
    verdict_path = os.path.join(tempfile.gettempdir(), 's4_smoke_verdict.json')
    try:
        if os.path.exists(verdict_path):
            os.unlink(verdict_path)
    except OSError:
        pass
    env = dict(os.environ)
    env.setdefault('LOOM_NO_DIALOG', '1')
    env.setdefault('WGPU_BACKEND_TYPE', 'Vulkan')
    # 2026-11-27 人类反馈：测试不得留下要人点的窗口 —— 弹窗自动关闭兜底（见 run_all 注释）
    env.setdefault('LOOM_DIALOG_AUTO_CLOSE_MS', '8000')
    env.setdefault('PYTHONUNBUFFERED', '1')
    # 父门透传子进程 stdout（PASS/FAIL 明细进 run_all 日志）。
    # ★不等子进程退出：Qt+wgpu 真窗口进程的收尾会卡在驱动 teardown（僵尸数分钟，
    # 本机实测）—— 父门只认 **verdict 文件**（子进程判定完成后立即落盘），轮询到
    # 即收口；轮询不到（真卡死）才硬杀并判红。僵尸进程由 OS 自行回收，不拖 run_all。
    import time as _time
    proc = subprocess.Popen([sys.executable, CHILD, verdict_path],
                            env=env, cwd=ROOT)
    # 2026-11-27 (人类反馈：漏窗): 父门只认 verdict 就收口，但**离开前必须收掉子进程**
    # —— 否则驱动 teardown 卡住期间，子进程的真窗口会留在桌面上等人点。
    # kill 是尽力而为（TerminateProcess 触发窗口销毁），wait 有界 5s（卡住就放弃）。
    try:
        _deadline = _time.monotonic() + 180
        v = None
        while _time.monotonic() < _deadline:
            try:
                with open(verdict_path, encoding='utf-8') as f:
                    v = json.load(f)
                break                  # 子进程判定已落盘（进程本身可能仍在僵尸收尾）
            except (OSError, ValueError):
                if proc.poll() is not None and v is None:
                    break              # 子进程先退了且无 verdict -> 按 FAIL 走
                _time.sleep(1.0)
        child_rc = proc.poll()
        if v is None and _time.monotonic() >= _deadline:
            print('FAIL 冒烟子进程超时 180s（无 verdict，已硬杀）')
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    v = None
    try:
        with open(verdict_path, encoding='utf-8') as f:
            v = json.load(f)
    except Exception as e:
        print('FAIL 冒烟 verdict 不可读: %r' % (e,))
    check('S4 冒烟子进程 verdict 全绿（判定以 verdict 文件为准；rc/僵尸收尾属已知驱动问题）',
          v is not None and v.get('ok') is True and v.get('fails') == [],
          'child_rc=%s verdict=%r' % (child_rc, v))
    check('S4 冒烟断言计数完整（A 结构 6 + B 真窗口 8 = 14 条全跑）',
          v is not None and v.get('pass_count', -1) >= 14,
          'pass_count=%s' % (v.get('pass_count') if v else '?'))
    print()
    print('总结果:', 'ALL PASS' if not _fails else '有 FAIL: %s' % _fails)
    sys.exit(0 if not _fails else 1)


main()
