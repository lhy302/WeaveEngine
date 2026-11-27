# -*- coding: utf-8 -*-
"""test_editor_vk_fallback_panel.py — 编辑器「VK 装配失败 → 自动改写配置 + 提示 + 本次回退 GL」
门（Q-B7-60-1 终审 P0-1 + 人类 2026-11-24 指令）。

人类指令（本门最高依据，原话）:
  「加编辑器启动时 VK 失败 → 自动改写配置为 opengl + 提示」。
叠加既有裁决: ①重启编辑器生效（不做视口热切换）②一个键全局消费 ③--backend 显式最高
优先级（Q6 先例: 显式选择不改写用户配置）④auto = 先试 VK 失败回退 GL、不改写配置（Q1/Q7）。

★ 本文件 = **父门**（瘦宿主）；真探针在 tests/_editor_vk_fallback_child.py（下划线前缀:
  run_all 只收集 test_*.py，不会把它当门跑）。隔离原因与 test_vk_editor_smoke /
  test_grid_occlusion_parity 同一条: 子进程加载 Qt + 真窗口后，收尾会非确定性卡在驱动
  teardown（进程变僵尸数分钟）—— 父门只认 verdict 文件，轮询到即收口。

两组（各一个子进程，真建 LoomGUI + 真建 GL 视口）:
  A（mode=a）: backend 来自配置（render_api=vulkan）+ VK 装配失败 →
     ① 设置面板仍能创建对话框（P0-1 另一半: 面板可达）② 引擎层 render_api 已自动改写为
     opengl 且走唯一写盘路径 ③ self.viewport 是 GLViewport 且真建出 GL 编辑器（可用）
     ④ 可见提示被发出（文案含原因 / 已改写 / 已回退）。
  B（mode=b）: 显式 --backend vulkan + VK 装配失败 → 配置**不变**（仍 vulkan），
     但仍有可见提示 + 本次回退 GL。
  C（mode=c）: 配置 auto + VK 装配失败 → 配置**不变**（仍 auto，P1-2 与播放器同义：
     auto 没有偏好可持久化）+ 可见提示 + 本次回退 GL。

为什么新建文件而不是扩 test_editor_backend_config_parity.py: 那条门按设计是**纯 python、
不真开窗口**（docstring 原文「真调用生产函数 / 真写配置，不真开窗口」），69 条跑完 ~1s；
本门必须真建 Qt 窗口 + GL 上下文，且必须按仓库既有纪律拆子进程（否则收尾卡死拖 run_all）。
两者运行形态与失败模式不同，混在一起会让无窗口门也背上驱动 teardown 风险。
配置写盘闭环（P1-1）与 auto 语义（P1-2）两组无窗口断言仍在
test_editor_backend_config_parity.py 的 E/F 段（同一份被测实现，不重复起窗口）。

修前红（2026-11-25，HEAD 14e2408 + 本门，实跑原文见交付报告）:
  · A 组（配置来的 vulkan）**0 PASS / 15 FAIL** —— viewport 仍是 VkViewport、配置未改写、
    提示 0 次、面板对话框创建 0 次（editor is None 首行 return）、GL 视口 90s 未就绪；
  · B 组（显式 --backend vulkan）**3 PASS / 12 FAIL** —— 配置不变/未写盘三条修前即绿
    （修前根本没有改写逻辑），其余同 A 组。
修后 A/B/C 各 **16 PASS / 0 FAIL**（父门 6 条 PASS，EXIT 0）。
C 组（配置 auto）是**修后追加的回归锁**，没有单独跑修前态（修前 auto 在编辑器侧被
editor_backend_choice 直接归成 gl、根本不会去试 VK，所以它的修前红由
test_editor_backend_config_parity 的 F2/F3/F5~F8 与 A/B 两组的逐条红承载）；它锁的是
「auto 失败后**不改写配置**」这条与播放器同义的语义，防止以后把 auto 也当成 vulkan 改写。
注: 子探针的 A10b（editor 为 None 时面板改后端真的落盘）是**回归锁**不是修前红证据 ——
修前面板的「写盘」本身是通的，坏的是「面板根本打不开」+「显示值不等于生效值」；
A10b 锁的是「可达之后真的能用」，防止以后把面板做成只有个壳。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHILD = os.path.join(HERE, '_editor_vk_fallback_child.py')

_fails = []
_pass_n = 0

# 每组断言条数（子进程 verdict 里 pass_count 必须 >= 这个数，防止「少跑也绿」）
_MIN_CHECKS = {'a': 16, 'b': 16, 'c': 16}


def check(name, cond, detail=''):
    global _pass_n
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if cond:
        _pass_n += 1
    else:
        _fails.append(name)


def _reap_child(proc, mode):
    """kill + wait(timeout)：保证父门退出时子进程（及其真窗口）已不在了。

    为什么 kill 之后再 wait：子女是直连显示器的真窗口进程，驱动 teardown 可能卡住
    （历史实测：进程变僵尸数分钟），此时 wait 会一起挂住。kill 是尽力而为，wait 有
    界（5s）失败就放弃 —— 但窗口已随 TerminateProcess 进入销毁流程。
    """
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def run_child(mode):
    verdict_path = os.path.join(tempfile.gettempdir(),
                                'editor_vk_fallback_%s_verdict.json' % mode)
    try:
        if os.path.exists(verdict_path):
            os.unlink(verdict_path)
    except OSError:
        pass
    env = dict(os.environ)
    env.setdefault('LOOM_NO_DIALOG', '1')
    env.setdefault('PYTHONUNBUFFERED', '1')
    # 2026-11-26 污染修复：run_all 给全部测试文件共享同一个 LOOM_USER_ROOT
    # （run_all.py:24 mkdtemp 一次），而本门的子探针会把 render_api 改写成 opengl
    # —— 若沿用共享 root，会污染同轮后跑的门（实测 test_entry_backend_parity /
    # test_render_api 假红）。子进程强制用**独立** root，写穿也只写自己的沙箱。
    env['LOOM_USER_ROOT'] = tempfile.mkdtemp(prefix='loom_vkfallback_root_')
    print('---- 子进程 mode=%s: %s ----' % (mode, os.path.basename(CHILD)))
    proc = subprocess.Popen([sys.executable, CHILD, mode, verdict_path],
                            env=env, cwd=ROOT)
    # 2026-11-27 (人类反馈：测试不得留下要人点的窗口): 无论走哪条分支，离开本函数
    # 前都必须 kill + wait —— 子进程的真窗口存活期 = 进程存活期，父门只认 verdict
    # 就收口（不等退出），残留的是**子进程窗口**（实测：驱动 teardown 卡住时窗口
    # 会在桌面上留数秒到数分钟）。kill 后再 wait(timeout) 收尸，超时不再纠缠。
    try:
        deadline = time.monotonic() + 240
        v = None
        while time.monotonic() < deadline:
            try:
                with open(verdict_path, encoding='utf-8') as f:
                    v = json.load(f)
                break
            except (OSError, ValueError):
                if proc.poll() is not None and v is None:
                    break
                time.sleep(1.0)
        child_rc = proc.poll()
        if v is None and time.monotonic() >= deadline:
            print('FAIL mode=%s 子进程超时 240s（无 verdict，已硬杀）' % mode)
    finally:
        _reap_child(proc, mode)
    if v is None:
        try:
            with open(verdict_path, encoding='utf-8') as f:
                v = json.load(f)
        except Exception as e:
            print('FAIL mode=%s verdict 不可读: %r' % (mode, e))
    return v, child_rc


def main():
    for mode, tag in (('a', 'A 组（配置来的 vulkan）'),
                      ('b', 'B 组（显式 --backend vulkan）'),
                      ('c', 'C 组（配置 auto，P1-2 两端同义）')):
        v, rc = run_child(mode)
        fails = (v or {}).get('fails')
        check('%s 真窗口探针 verdict 全绿（判定以 verdict 文件为准；rc/僵尸收尾属已知驱动问题）'
              % tag,
              v is not None and v.get('ok') is True and fails == [],
              'child_rc=%s fails=%r' % (rc, fails))
        check('%s 断言条数完整（>= %d 条全跑）' % (tag, _MIN_CHECKS[mode]),
              v is not None and v.get('pass_count', -1) >= _MIN_CHECKS[mode],
              'pass_count=%s' % ((v or {}).get('pass_count'),))
    print()
    print('总结果:', 'ALL PASS' if not _fails else '有 FAIL: %s' % _fails)
    if _fails:
        print('FAIL test_editor_vk_fallback_panel: %d 条未过' % len(_fails))
        sys.exit(1)
    print('PASS test_editor_vk_fallback_panel: 全部通过 (P0-1 VK 失败自动回退 + 面板可达)')
    sys.exit(0)


main()
