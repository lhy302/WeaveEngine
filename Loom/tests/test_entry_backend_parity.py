# -*- coding: utf-8 -*-
"""test_entry_backend_parity.py — B7-54 四入口后端选择同源门 (2026-11-21)

人类裁定（本门最高依据）:
  「编译入口和源码入口和打包游戏一样，全部走 run_player.py 后端选择组件」
  + 「编译的时候两边自己各带上一次打包」
  = Loom.py / build_entry.py / game_player.py / run_player.py 四个入口对
  同一份 argv + 配置必须产生**同一后端决策**；--backend 的 argv 解析 +
  resolve_backend 只允许存在**一份**实现（开发要求 规则 5.5）；
  编译产物经编译期（Nuitka 静态 import 跟随）各带一份 run_player 副本。

本门锁三条不变量（决策函数级真调用，不真开窗口）:
  A. 四入口决策一致: --backend 四态 × 配置 render_api 三态下，
     Loom.py(_cli_backend 链) / build_entry(_player_backend_choice) /
     game_player(_pick_backend) 的后端决策与 run_player.resolve_backend
     的结果完全一致；Loom.py 与 build_entry 的**编辑器面**决策（S4 规则：
     仅显式 --backend 且解析为 vulkan 才走 VK）也逐位一致。
  B. 解析单源（grep 级）: 除 run_player.py 外，Loom.py / build_entry.py /
     game_player.py 不得再出现 --backend 的内联解析逻辑。判定口径：
     内联解析只可能是三种代码形状 —— ①与字面量 '--backend' 做相等比较、
     ②list.index('--backend')、③'"--backend" in ...' 成员测试。
     注释/docstring 提及 --backend、转调 parse_backend_arg / 透传均允许。
  C. build_entry 决策可达: '--backend vulkan' → VK 分支（qt:
     run_loom_gui backend='vulkan'；default/minimal: VkEditorApp）；
     缺省 → GL 分支（与修前逐位一致）；播放分支不再有硬编码 GL 的
     PlayerApp 直连；build_entry 静态 import run_player
     （Nuitka 编进 build_entry.dist = 编译产物自带同源副本）。

修前红（2026-11-21, HEAD 089677f 真跑留痕）: 终审 agent-60 复核实测 38 条
FAIL = A 组 24 + B 组 7 + C 组 7（本文件头初稿误记「B8+C4」，2026-11-22
B7-54 终审 F-3 更正；C2 的静态 import 断言修前即 PASS，不属红证据）。
修后全绿。git 停靠点见该文件所在提交。

2026-11-22 B7-54 终审 F-2 补牙（agent-61）:
  旧 A④ 的期望是门内复刻的「S4 规则」，不触达 Loom.py 真分支源码
  （:500-507 的编辑器分支决策在门内没有对应物）→ 解析层两端同步坏仍绿；
  A①/A①b 两侧同走 run_player.parse_backend_arg（_cli_backend 是薄转调），
  解析层两端同步坏也仍绿。修法:
  · Loom.py 把 S4 编辑器分支决策抽成可独立调用的纯函数
    _editor_backend_choice（main 分支真调用它，决策语义逐位不变）;
  · A④ 改为「双方真调用 + S4 独立期望」三判据（A④ = Loom.py 决策 vs
    独立期望；A④b = build_entry 决策 vs Loom.py 决策，逐位）;
  · B 组新增源码结构断言: _cli_backend 体内含 parse_backend_arg 转调
    且不含 --backend 内联比较；main 的 S4 分支真调用 _editor_backend_choice；
    旧内联 `as _resolve_backend` 已删。
  修前红（新断言就位、Loom.py 尚未抽函数时真跑留痕）: 27 条 FAIL =
  A④ 12 + A④b 12 + B 组结构断言 3（_editor_backend_choice 未定义 /
  main 未真调用 / 旧内联 as _resolve_backend 仍在）。修后全绿。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 与 test_render_api 同款：失败退出码闸门 + 用户层配置隔离 + 关弹窗
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate
import tempfile as _tempfile_gate

# 本门真调 resolve_backend（会触达 game_settings 用户层），必须隔离 ——
# 契约 §8: 跑测试不得污染 %LOCALAPPDATA%，也不得在仓库里留文件。
_os_gate.environ.setdefault('LOOM_USER_ROOT',
                            _tempfile_gate.mkdtemp(prefix='loom_test_userroot_b754_'))
_os_gate.environ.setdefault('LOOM_NO_DIALOG', '1')


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith("FAIL") or "\nFAIL" in text):
            self.failed = True
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


_fail_gate = _FailGateStream(_sys_gate.stdout)
_sys_gate.stdout = _fail_gate


@_atexit_gate.register
def _enforce_fail_exit_code():
    if not _fail_gate.failed:
        return
    try:
        _sys_gate.stdout.flush()
        _sys_gate.stderr.flush()
    except Exception:
        pass
    _os_gate._exit(1)


import os
import sys
import re
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import run_player
import game_player

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def _load_entry(mod_name, file_name):
    """按文件路径装载入口模块（Loom.py 与 'Loom' 目录重名，不能按名 import）。
    三个入口的模块级代码均无副作用（只有 def + __main__ 守卫），可安全装载。"""
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(ROOT, file_name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


loom = _load_entry('loom_entry_b754', 'Loom.py')
build_entry = _load_entry('build_entry_b754', 'build_entry.py')

# ============ A. 四入口决策一致 (--backend 四态 × 配置 render_api 三态) ============

ARGV_CASES = [
    [],                              # 缺省（无 --backend）
    ['--backend', 'vulkan'],
    ['--backend', 'opengl'],
    ['--backend', 'auto'],
]
# 配置三态：未配置 / opengl / vulkan（经 game_settings 用户层真写真读，非打桩）
CONFIG_STATES = [('未配置', None), ('render_api=opengl', 'opengl'), ('render_api=vulkan', 'vulkan')]


def _set_render_api(v):
    import game_settings
    game_settings.set_value('render_api', v)


def _ref_cli(argv):
    """门内参考解析：给出"逻辑上的 --backend 值"。单源性由 B 组锁死 ——
    run_player.parse_backend_arg 存在时优先真调它；修前（未抽出）才用
    门内同语义复刻，保证本门在修前能拿到**真红**而不是 crash。"""
    if hasattr(run_player, 'parse_backend_arg'):
        return run_player.parse_backend_arg(list(argv))
    for i, a in enumerate(argv):
        if a == '--backend' and i + 1 < len(argv):
            return argv[i + 1]
    return None


def t_parity():
    import game_settings
    for state_name, state_val in CONFIG_STATES:
        _set_render_api(state_val)
        for argv in ARGV_CASES:
            tag = 'argv=%s × %s' % (('\x20'.join(argv) or '<缺省>'), state_name)
            # 参考实现（唯一事实源）：run_player 的解析 + resolve_backend
            cli_ref = _ref_cli(argv)
            ref = run_player.resolve_backend(cli_ref)
            # ① Loom.py 源码入口（_launch_native 链: _cli_backend -> resolve_backend）
            try:
                loom_cli = loom._cli_backend(list(argv))
                loom_api = run_player.resolve_backend(loom_cli)
                check('A① Loom.py 播放决策与 run_player 一致 (%s)' % tag,
                      loom_api == ref, 'loom=%r ref=%r' % (loom_api, ref))
                check('A①b Loom.py 解析结果与 run_player.parse_backend_arg 一致 (%s)' % tag,
                      loom_cli == cli_ref, 'loom=%r ref=%r' % (loom_cli, cli_ref))
            except AttributeError as e:
                check('A① Loom.py 播放决策与 run_player 一致 (%s)' % tag, False, e)
            # ② build_entry 编译入口（播放分支决策函数）
            try:
                be_api, be_explicit = build_entry._player_backend_choice(list(argv))
                check('A② build_entry 播放决策与 run_player 一致 (%s)' % tag,
                      be_api == ref, 'be=%r ref=%r' % (be_api, ref))
                check('A②b build_entry explicit 语义一致 (%s)' % tag,
                      be_explicit == (cli_ref is not None), be_explicit)
            except AttributeError as e:
                check('A② build_entry 播放决策与 run_player 一致 (%s)' % tag, False, e)
            # ③ game_player 打包游戏入口（_pick_backend -> resolve_backend）
            try:
                gp_api = game_player._pick_backend(cli_ref)
                check('A③ game_player 决策与 run_player 一致 (%s)' % tag,
                      gp_api == ref, 'gp=%r ref=%r' % (gp_api, ref))
            except AttributeError as e:
                check('A③ game_player 决策与 run_player 一致 (%s)' % tag, False, e)
            # ④ 编辑器面（2026-11-22 终审 F-2 补牙）：旧版期望是门内复刻的
            #    「S4 规则」，不触达 Loom.py 真分支源码 → 两端同步坏仍绿。
            #    现在 Loom.py 侧真调用 loom._editor_backend_choice（main S4 分支
            #    用的同一份决策函数），build_entry 侧真调用其同名纯函数；
            #    expected_edit 仅作独立第三判据（防两边决策函数一起坏）。
            expected_edit = 'vulkan' if (cli_ref is not None
                                         and run_player.resolve_backend(cli_ref) == 'vulkan') else 'gl'
            loom_edit = None
            try:
                loom_edit = loom._editor_backend_choice(list(argv))
                check('A④ Loom.py 编辑器决策（真调用 _editor_backend_choice）与 S4 独立期望一致 (%s)' % tag,
                      loom_edit == expected_edit, 'loom=%r expected=%r' % (loom_edit, expected_edit))
            except AttributeError as e:
                check('A④ Loom.py 编辑器决策（真调用 _editor_backend_choice）与 S4 独立期望一致 (%s)' % tag, False, e)
            try:
                be_edit = build_entry._editor_backend_choice(list(argv))
                check('A④b build_entry 编辑器决策与 Loom.py 决策逐位一致（双方真调用）(%s)' % tag,
                      be_edit == loom_edit, 'be=%r loom=%r' % (be_edit, loom_edit))
            except AttributeError as e:
                check('A④b build_entry 编辑器决策与 Loom.py 决策逐位一致（双方真调用）(%s)' % tag, False, e)
    # 恢复未配置，避免影响同批其它测试（用户层已隔离，双保险）
    _set_render_api(None)


# ============ B. 解析单源（grep 级） ============

# 内联解析只可能是这三种代码形状；命中即违规（注释/docstring 不命中）。
_INLINE_PARSE_PATTERNS = [
    (r'==\s*["\']--backend["\']', '与字面量 --backend 相等比较（内联解析）'),
    (r'\.index\(\s*["\']--backend', 'list.index 内联找 --backend'),
    (r'["\']--backend["\']\s+in\s', '成员测试内联找 --backend'),
]


def t_single_source():
    check('B run_player.parse_backend_arg 存在（全仓唯一解析实现）',
          hasattr(run_player, 'parse_backend_arg'))
    for fname in ('Loom.py', 'build_entry.py', 'game_player.py'):
        src = open(os.path.join(ROOT, fname), encoding='utf-8').read()
        bad = []
        for pat, why in _INLINE_PARSE_PATTERNS:
            for m in re.finditer(pat, src):
                ln = src.count('\n', 0, m.start()) + 1
                line = src.splitlines()[ln - 1].strip()
                bad.append('%s:%d (%s): %s' % (fname, ln, why, line[:80]))
        check('B %s 不含 --backend 内联解析（解析已收敛 run_player.parse_backend_arg）'
              % fname, not bad, '; '.join(bad) or '-')
        check('B %s 转调 parse_backend_arg（单一事实）' % fname,
              'parse_backend_arg' in src)
    rp_src = open(os.path.join(ROOT, 'run_player.py'), encoding='utf-8').read()
    n = len(re.findall(_INLINE_PARSE_PATTERNS[0][0], rp_src))
    check('B run_player.py 是唯一内联解析点（恰 1 处，位于 parse_backend_arg 体内）',
          n == 1 and hasattr(run_player, 'parse_backend_arg'), '比较次数=%d' % n)


# ============ B+. Loom.py 源码结构（2026-11-22 终审 F-2 补牙） ============

def _func_body_src(src, name):
    """按 ast 定位模块顶层函数 name，返回其完整源码行段（含 docstring）。"""
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = src.split('\n')
            return '\n'.join(lines[node.lineno - 1:node.end_lineno])
    return None


def t_loom_source_structure():
    """A① 的 _cli_backend 是薄转调、A④ 旧期望是门内复刻 —— 解析/决策层
    两端同步坏仍绿。本组用源码结构把 Loom.py 钉死在单一解析与真决策函数上:
    _cli_backend 体内必须含 parse_backend_arg 转调且不含 --backend 内联
    比较；main 的 S4 分支必须真调用 _editor_backend_choice（门测的就是
    分支用的那份决策，不是复刻）。"""
    src = open(os.path.join(ROOT, 'Loom.py'), encoding='utf-8').read()
    body = _func_body_src(src, '_cli_backend')
    check('B Loom.py _cli_backend 可定位（结构断言前提）', body is not None)
    if body:
        check('B Loom.py _cli_backend 体内含 parse_backend_arg 转调（解析单一事实）',
              'parse_backend_arg' in body)
        bad = [why for pat, why in _INLINE_PARSE_PATTERNS if re.search(pat, body)]
        check('B Loom.py _cli_backend 体内不含 --backend 内联比较/查找（不得长出第二份解析）',
              not bad, '; '.join(bad) or '-')
    check('B Loom.py 定义 _editor_backend_choice（编辑器决策可被门真调用）',
          _func_body_src(src, '_editor_backend_choice') is not None)
    check('B Loom.py main 的 S4 分支真调用 _editor_backend_choice（门测的就是分支用的那份决策）',
          re.search(r'_editor_backend_choice\(sys\.argv\)', src) is not None)
    check('B Loom.py main 不再内联编辑器后端决策（旧 as _resolve_backend 内联已删）',
          'as _resolve_backend' not in src)


# ============ C. build_entry 分支决策可达 ============

def t_build_entry_branches():
    # -- C1: 决策函数级（真调用，不真开窗口）--
    try:
        api, explicit = build_entry._player_backend_choice(['--backend', 'vulkan'])
        check('C1 build_entry 播放分支决策: --backend vulkan → (vulkan, explicit)',
              api == 'vulkan' and explicit is True, (api, explicit))
        api2, explicit2 = build_entry._player_backend_choice(['--backend', 'opengl'])
        check('C1 build_entry 播放分支决策: --backend opengl → (opengl, explicit)',
              api2 == 'opengl' and explicit2 is True, (api2, explicit2))
        api3, explicit3 = build_entry._player_backend_choice([])
        check('C1 build_entry 播放分支决策: 缺省 → 与 resolve_backend(None) 一致、非显式',
              api3 == run_player.resolve_backend(None) and explicit3 is False,
              (api3, explicit3))
        check('C1 build_entry 编辑器分支决策: --backend vulkan → vulkan（qt=VK 视口 / default=VkEditorApp）',
              build_entry._editor_backend_choice(['--backend', 'vulkan']) == 'vulkan')
        check('C1 build_entry 编辑器分支决策: --backend opengl → gl（与修前逐位一致）',
              build_entry._editor_backend_choice(['--backend', 'opengl']) == 'gl')
        check('C1 build_entry 编辑器分支决策: 缺省 → gl（与修前逐位一致）',
              build_entry._editor_backend_choice([]) == 'gl')
    except AttributeError as e:
        check('C1 build_entry 决策函数存在且可达', False, e)

    # -- C2: 源码结构（四处分支全部过 run_player 后端选择）--
    src = open(os.path.join(ROOT, 'build_entry.py'), encoding='utf-8').read()
    check('C2 build_entry --run 分支不再硬编码 GL 直连 PlayerApp(run_scene)',
          'PlayerApp(run_scene, 1280, 800)' not in src)
    check('C2 build_entry 游戏配置双击分支不再硬编码 GL 直连 PlayerApp(_scene)',
          'PlayerApp(_scene, 1280, 800)' not in src)
    check('C2 build_entry 播放分支走 run_player.run_backend 链路（两处）',
          src.count('run_player.run_backend') >= 2)
    check('C2 build_entry --ui qt 分支把后端决策传给 run_loom_gui（不再恒缺省 gl）',
          re.search(r'run_loom_gui\([^\)]*backend\s*=', src) is not None)
    check('C2 build_entry default/minimal 分支 VK 决策可达（VkEditorApp 装配在分支内）',
          'from editor import VkEditorApp' in src)
    check('C2 build_entry 播放/编辑决策函数存在（对拍门可独立调用）',
          callable(getattr(build_entry, '_player_backend_choice', None))
          and callable(getattr(build_entry, '_editor_backend_choice', None)))
    # 编译产物自带 run_player 副本：Nuitka 静态 import 跟随 —— build_entry.py
    # 直接 import run_player 即可保证 run_player 被编进 build_entry.dist（同源）。
    check('C2 build_entry 静态 import run_player（Nuitka 编译期把 run_player 编进 dist）',
          re.search(r'^import run_player', src, re.M) is not None
          or re.search(r'^\s+import run_player', src, re.M) is not None)


t_parity()
t_single_source()
t_loom_source_structure()
t_build_entry_branches()

print('=' * 60)
if _fails:
    print('FAIL test_entry_backend_parity: %d 条未过' % len(_fails))
    for f in _fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS test_entry_backend_parity: 全部通过 (B7-54 四入口后端选择同源)')
sys.exit(0)
