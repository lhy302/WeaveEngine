# -*- coding: utf-8 -*-
"""test_entry_execution_parity.py — B7-55 入口执行面同源门（Q-B7-55-1, 2026-11-22）

人类目标态（本门最高依据）:
  「编译入口和源码入口和打包游戏一样，全部走 run_player.py 后端选择组件」
  + 「四入口零用户可感知差异」。
  B7-54 已统一后端**决策**面（test_entry_backend_parity.py）；本门锁
  **执行**面：同一份 env + argv 下，源码入口 Loom.py 与编译入口 build_entry.py
  必须走同一条执行路径（远程三态 / 编辑器 --ui 装配 / 可见报错 / 退出码）。

本门三组（全部真调用入口函数，不真起窗；唯一例外 B5 是两个入口的
minimal+vulkan 进程级对拍 —— 该组合修后**必须快速可见报错退出**，不会起窗）:

  A. 远程三态决策一致: LOOM_REMOTE_MODE 四态（未设/off/on/auto）× 两入口，
     真调用 hostenv.remote_launch.remote_mode（唯一实现）、Loom.py._remote_mode、
     build_entry._remote_mode，返回值逐位一致；并锁 _launch_player 两入口
     转调同一函数（build_entry 两个播放分支都调它）。
  B. --ui × --backend 执行面一致: qt/minimal × gl/vulkan 四组合，真调用两入口的
     _editor_execution_plan（唯一实现 hostenv.editor_launch）：视图/引擎类、
     是否可见报错、报错文案、退出码逐位一致；minimal+vulkan 再跑两条真实进程，
     比 stdout 关键行 + 退出码 + 是否起窗。
  C. 结构单源: LOOM_REMOTE_MODE 的**取值集合**与**三态判定**全仓唯一实现 =
     hostenv/remote_launch.py；其余出现点全部在白名单里并写明理由（消费者 /
     Hub 设置注入 / 测试夹具 / 文档文案）。

修前红（2026-11-22, HEAD e2709e8, git worktree 临时树 + 本门真跑）:
  48 FAIL / EXIT 1 = A 组 22 + B 组 17 + C 组 9（原文节选见提交报告）。
  同日前置行为真跑（主树 HEAD，未改代码）:
    · Loom.py --ui minimal --backend vulkan --auto-close 6
      -> [VkViewport] VK 编辑器就绪、EXIT 0（起 Qt 窗口）；
    · build_entry.py --ui minimal --backend vulkan
      -> [错误] 无法启动渲染引擎: VkEditorApp 需要 wgpu device 与
         present_format… EXIT 1（不起窗）。
  两条即本门锁的「同一 env+argv 两入口执行面不同」。
修后全绿: 57 条 check 全 PASS / EXIT 0（2026-11-22, agent-75）。

注意（断言措辞纪律）: 本门只锁「两入口对同一输入产生同一可观察结果」与
「唯一实现位置」，不写「某入口没有某能力」这类会把缺陷态固化的断言。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 与 test_entry_backend_parity 同款：失败退出码闸门 + 用户层配置隔离 + 关弹窗
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate
import tempfile as _tempfile_gate

_os_gate.environ.setdefault('LOOM_USER_ROOT',
                            _tempfile_gate.mkdtemp(prefix='loom_test_userroot_b755_'))
_os_gate.environ['LOOM_NO_DIALOG'] = '1'


class _FailGateStream:
    def __init__(self, stream):
        self._stream = stream
        self.failed = False

    def write(self, text):
        if isinstance(text, str) and (text.startswith('FAIL') or '\nFAIL' in text):
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


import ast
import importlib
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # Loom/
REPO = os.path.dirname(ROOT)                 # 仓库根
sys.path.insert(0, ROOT)

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('  ' + str(detail) if detail else ''))
    if not cond:
        _fails.append(name)


def _load_mod(name):
    try:
        return importlib.import_module(name)
    except Exception as e:
        print('[gate] 无法导入 %s: %r' % (name, e))
        return None


def _load_entry(mod_name, file_name):
    """按文件路径装载入口模块（Loom.py 与 'Loom' 目录重名，不能按名 import）。"""
    spec = importlib.util.spec_from_file_location(mod_name,
                                                  os.path.join(ROOT, file_name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


remote_launch = _load_mod('hostenv.remote_launch')
editor_launch = _load_mod('hostenv.editor_launch')
loom = _load_entry('loom_entry_b755', 'Loom.py')
build_entry = _load_entry('build_entry_b755', 'build_entry.py')


def _func_body_src(src, name):
    """按 ast 定位模块顶层函数 name，返回其完整源码行段（含 docstring）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = src.split('\n')
            return '\n'.join(lines[node.lineno - 1:node.end_lineno])
    return None


# ==================== A. 远程三态决策一致 ====================

_REMOTE_CASES = [
    ('未设', None, 'off'),
    ('off', 'off', 'off'),
    ('on', 'on', 'on'),
    ('auto', 'auto', 'auto'),
]


def _set_remote_env(value):
    old = os.environ.get('LOOM_REMOTE_MODE')
    if value is None:
        os.environ.pop('LOOM_REMOTE_MODE', None)
    else:
        os.environ['LOOM_REMOTE_MODE'] = value
    return old


def _restore_remote_env(old):
    if old is None:
        os.environ.pop('LOOM_REMOTE_MODE', None)
    else:
        os.environ['LOOM_REMOTE_MODE'] = old


def _safe_call(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except Exception as e:
        return None, repr(e)


def t_remote_decision():
    for label, env_val, expected in _REMOTE_CASES:
        old = _set_remote_env(env_val)
        try:
            ref, err0 = (_safe_call(remote_launch.remote_mode)
                         if remote_launch is not None else (None, 'hostenv.remote_launch 不存在'))
            loom_v, err1 = (_safe_call(loom._remote_mode)
                            if hasattr(loom, '_remote_mode') else (None, 'Loom.py 无 _remote_mode'))
            be_v, err2 = (_safe_call(build_entry._remote_mode)
                          if hasattr(build_entry, '_remote_mode') else (None, 'build_entry.py 无 _remote_mode'))
        finally:
            _restore_remote_env(old)
        tag = 'LOOM_REMOTE_MODE=%s' % label
        check('A1 唯一实现 remote_mode 判定 %s -> %r' % (tag, expected),
              ref == expected, 'got=%r err=%s' % (ref, err0))
        check('A2 Loom.py._remote_mode 与唯一实现一致 (%s)' % tag,
              ref is not None and loom_v == ref,
              'loom=%r ref=%r err=%s' % (loom_v, ref, err1))
        check('A3 build_entry._remote_mode 与唯一实现一致 (%s)' % tag,
              ref is not None and be_v == ref,
              'be=%r ref=%r err=%s' % (be_v, ref, err2))
        check('A4 两入口远程决策逐位一致 (%s)' % tag,
              loom_v is not None and loom_v == be_v,
              'loom=%r be=%r' % (loom_v, be_v))

    # 取值集合本身：REMOTE_ON_VALUES 每个别名为 on；大小写/空白归一；未知值 off
    vals = getattr(remote_launch, 'REMOTE_ON_VALUES', None) if remote_launch else None
    bad = []
    if not isinstance(vals, tuple):
        bad.append('REMOTE_ON_VALUES 非 tuple / 模块缺失: %r' % (vals,))
    else:
        for v in vals:
            got, e = _safe_call(remote_launch.remote_mode,
                                {'LOOM_REMOTE_MODE': v})
            if got != 'on':
                bad.append('%r->%r(%s)' % (v, got, e))
    check('A5 REMOTE_ON_VALUES 每个取值都归为 on（取值集合唯一实现可枚举）',
          not bad, '; '.join(bad) or 'values=%r' % (vals,))
    got_case = (_safe_call(remote_launch.remote_mode,
                           {'LOOM_REMOTE_MODE': '  ON  '})[0]
                if remote_launch else None)
    got_wat = (_safe_call(remote_launch.remote_mode,
                          {'LOOM_REMOTE_MODE': 'wat'})[0]
               if remote_launch else None)
    check('A6 三态归一：大小写/空白敏感度与未知值 off 语义',
          got_case == 'on' and got_wat == 'off',
          'ON=%r wat=%r' % (got_case, got_wat))


def t_launch_delegation():
    calls = []

    def _fake_launch_player(scene, width=1280, height=800, argv=None):
        calls.append((scene, width, height))

    ok = remote_launch is not None and hasattr(remote_launch, 'launch_player')
    orig = getattr(remote_launch, 'launch_player', None) if ok else None
    try:
        if ok:
            remote_launch.launch_player = _fake_launch_player
        loom_ok = hasattr(loom, '_launch_player')
        if ok and loom_ok:
            loom._launch_player('scene.json')
        be_ok = hasattr(build_entry, '_launch_player')
        if ok and be_ok:
            build_entry._launch_player('scene.json')
    finally:
        if ok:
            remote_launch.launch_player = orig
    check('A7 Loom.py._launch_player 薄转调 hostenv.remote_launch.launch_player',
          loom_ok and calls and calls[0] == ('scene.json', 1280, 800),
          'calls=%r' % (calls,))
    check('A8 build_entry._launch_player 与 Loom.py 调同一函数（播放执行面同源）',
          be_ok and len(calls) >= 2 and calls[1] == ('scene.json', 1280, 800),
          'calls=%r' % (calls,))

    for fname, mod_src_name in (('Loom.py', 'Loom.py'), ('build_entry.py', 'build_entry.py')):
        src = open(os.path.join(ROOT, mod_src_name), encoding='utf-8').read()
        check('A9 %s --run 分支调 _launch_player(run_scene)' % fname,
              '_launch_player(run_scene)' in src)
        check('A10 %s 游戏配置.json 分支调 _launch_player(_scene)' % fname,
              '_launch_player(_scene)' in src)


# ==================== B. --ui × --backend 执行面一致 ====================

# (--ui, 后端标签, 实际 CLI 值)：任务口径的 gl = 引擎的 opengl 后端
# （resolve_backend 只认 vulkan|opengl|auto；--backend gl 是非法值会归一成
# vulkan，不属于本门契约，不能拿它当 "gl" 用例）。
_UI_BACKEND_CASES = [
    ('qt', 'gl', 'opengl'),
    ('qt', 'vulkan', 'vulkan'),
    ('minimal', 'gl', 'opengl'),
    ('minimal', 'vulkan', 'vulkan'),
]


def _expected_plan(ui, backend):
    if ui == 'qt':
        return {'view': 'qt', 'backend': backend, 'engine': 'LoomGUI',
                'error': None, 'exit_code': 0}
    if backend == 'vulkan':
        text = (editor_launch.EDITOR_VK_NON_QT_ERROR % ui
                if editor_launch is not None else None)
        return {'view': ui, 'backend': 'vulkan', 'engine': None,
                'error': text, 'exit_code': 1}
    return {'view': ui, 'backend': 'gl', 'engine': 'EditorApp',
            'error': None, 'exit_code': 0}


def _entry_plan(mod, argv):
    if not hasattr(mod, '_editor_execution_plan'):
        return None
    try:
        return mod._editor_execution_plan(argv)
    except Exception as e:
        print('[gate] %s._editor_execution_plan(%r) 异常: %r' % (mod.__name__, argv, e))
        return None


def t_editor_execution_plan():
    for ui, backend, cli_value in _UI_BACKEND_CASES:
        argv = ['--ui', ui, '--backend', cli_value]
        tag = '--ui %s --backend %s' % (ui, backend)
        expected = _expected_plan(ui, backend)
        loom_plan = _entry_plan(loom, argv)
        be_plan = _entry_plan(build_entry, argv)
        check('B1 %s Loom.py 执行面计划符合统一策略' % tag,
              loom_plan == expected, 'plan=%r expected=%r' % (loom_plan, expected))
        check('B2 %s build_entry 执行面计划符合统一策略' % tag,
              be_plan == expected, 'plan=%r expected=%r' % (be_plan, expected))
        check('B3 %s 两入口执行面计划逐位一致（视图/报错/退出码）' % tag,
              loom_plan is not None and loom_plan == be_plan,
              'loom=%r be=%r' % (loom_plan, be_plan))

    # 非 Qt 视图 + vulkan：同一条可见报错 + 同退出码（不静默降级 GL）
    argv = ['--ui', 'minimal', '--backend', 'vulkan']
    lp, bp = _entry_plan(loom, argv), _entry_plan(build_entry, argv)
    if isinstance(lp, dict) and isinstance(bp, dict):
        check('B4 minimal+vulkan 两入口报错文案非空且逐字一致',
              bool(lp.get('error')) and lp.get('error') == bp.get('error'),
              'loom=%r be=%r' % (lp.get('error'), bp.get('error')))
        check('B5 minimal+vulkan 两入口退出码一致且为 1（可见失败，不静默降级 GL）',
              lp.get('exit_code') == bp.get('exit_code') == 1,
              'loom=%r be=%r' % (lp.get('exit_code'), bp.get('exit_code')))
    else:
        check('B4 minimal+vulkan 两入口报错文案非空且逐字一致', False,
              'plan 缺失 loom=%r be=%r' % (lp, bp))
        check('B5 minimal+vulkan 两入口退出码一致且为 1（可见失败，不静默降级 GL）',
              False, 'plan 缺失 loom=%r be=%r' % (lp, bp))

    # 视图类：两入口对同一 --ui 解析出同一个 IEditorView 实现类
    try:
        lm = loom._make_editor_view('minimal')
        bm = build_entry._make_editor_view('minimal')
        check('B6 --ui minimal 两入口注入同一视图类（MinimalEditorView）',
              type(lm).__name__ == type(bm).__name__ == 'MinimalEditorView',
              'loom=%s be=%s' % (type(lm).__name__, type(bm).__name__))
        ld = loom._make_editor_view('default')
        bd = build_entry._make_editor_view('default')
        check('B7 --ui default 两入口解析结果同类（guiloader 自定义 GUI / None 兜底）',
              type(ld) is type(bd),
              'loom=%r be=%r' % (type(ld).__name__, type(bd).__name__))
    except Exception as e:
        check('B6 --ui minimal 两入口注入同一视图类（MinimalEditorView）', False, repr(e))
        check('B7 --ui default 两入口解析结果同类（guiloader 自定义 GUI / None 兜底）', False, repr(e))

    # 两入口 main 真调用 _editor_execution_plan（门测的就是分支用的那份决策）
    for fname in ('Loom.py', 'build_entry.py'):
        src = open(os.path.join(ROOT, fname), encoding='utf-8').read()
        check('B8 %s main 真调用 _editor_execution_plan（门不是门内复刻）' % fname,
              src.count('_editor_execution_plan(') >= 2)


def _run_entry_process(file_name, args, timeout=60):
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['LOOM_NO_DIALOG'] = '1'
    env['LOOM_USER_ROOT'] = _tempfile_gate.mkdtemp(prefix='loom_b755_sub_')
    try:
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, file_name)] + list(args),
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return e


def t_editor_process_parity():
    """minimal+vulkan 进程级对拍：修后两入口都必须**快速可见报错 exit 1**。

    修前（HEAD e2709e8）实测 Loom.py 起 Qt VK 窗口（--auto-close 5 后 EXIT 0），
    build_entry 直接报 VkEditorApp 参数错 EXIT 1 —— 正是本门要锁的执行面分叉。
    """
    args = ['--ui', 'minimal', '--backend', 'vulkan', '--auto-close', '5']
    lr = _run_entry_process('Loom.py', args)
    br = _run_entry_process('build_entry.py', args)
    text = (editor_launch.EDITOR_VK_NON_QT_ERROR % 'minimal'
            if editor_launch is not None else None)

    l_out = getattr(lr, 'stdout', '') or ''
    b_out = getattr(br, 'stdout', '') or ''
    l_code = getattr(lr, 'returncode', None)
    b_code = getattr(br, 'returncode', None)
    check('B9 minimal+vulkan 进程级：两入口退出码一致且为 1',
          l_code == b_code == 1, 'Loom=%r build_entry=%r' % (l_code, b_code))
    check('B10 minimal+vulkan 进程级：两入口 stdout 含同一条可见报错',
          bool(text) and text in l_out and text in b_out,
          'Loom含=%r be含=%r' % (bool(text and text in l_out),
                                bool(text and text in b_out)))
    check('B11 minimal+vulkan 进程级：两入口都不起窗（无 VK 视口/编辑器就绪行）',
          ('[VkViewport]' not in l_out and '[VkViewport]' not in b_out
           and '渲染后端: Vulkan' not in l_out and '渲染后端: Vulkan' not in b_out),
          'Loom=%r be=%r' % (l_out[-160:], b_out[-160:]))


# ==================== C. 结构单源（取值集合 + 三态判定） ====================

# 允许出现 LOOM_REMOTE_MODE 字面量的文件白名单（每条写理由）。
# 判定口径: 只有「取值集合常量」与「off/on/auto 三态判定函数」必须全仓唯一；
# 下列文件要么是**消费者**（只判 'auto'/'1'，不做归一），要么是 Hub 设置
# 注入（输入是 Hub 设置 dict，不是环境变量），要么是测试夹具/文档文案。
_ALLOWED_FILES = {
    'Loom/hostenv/remote_launch.py':
        '唯一实现：REMOTE_ON_VALUES 取值集合 + remote_mode 三态归一 + 三态执行面',
    'Loom/Loom.py':
        '入口薄转调：_remote_mode/_launch_player 只 import hostenv.remote_launch（注释/docstring 提及变量名）',
    'Loom/build_entry.py':
        '入口薄转调：_remote_mode/_launch_player 只 import hostenv.remote_launch（注释/docstring 提及变量名）',
    'Loom/run_player.py':
        '消费者：_maybe_remote_fallback 只判 == "auto"（VK 上屏失败后的一次性回读请求），不复制取值集合/不归一',
    'Loom/render/vk/player.py':
        '消费者：_remote_auto() 只判 == "auto"（引擎侧上屏健康自检开关），不复制取值集合/不归一',
    'Loom/gui/main_window.py':
        'GUI 既有独立开关：编辑器视口只判 == "1" 启用离屏回读；不参与入口三态（本轮不改语义）',
    'Loom/gui/remote_viewport.py':
        '文档文案：说明编辑器远程视口的启用方式（无判定）',
    'Loom/render/gl/render.py':
        '诊断文案：提示可用 LOOM_REMOTE_MODE=1（无判定）',
    'Loom/tests/test_hub_update.py':
        '测试：Hub 设置 -> 子进程环境变量注入语义（断言注入值为 "1"；不是入口实现）',
    'Loom/tests/test_scene_version_gates.py':
        '测试夹具：真跑入口时设置 LOOM_REMOTE_MODE=on（不是实现）',
    'Loom/tests/test_entry_execution_parity.py':
        '本门自身（结构断言需要枚举变量名/路径；不是生产实现）',
    'LoomHub/hub_config.py':
        'Hub 设置注入：apply_launch_env 把 Hub 设置 remote_mode=on 注入为 "1"（输入=Hub 设置 dict，不是环境变量三态）',
    'LoomHub/hub_commands.py':
        'Hub 注释：说明是否注入 LOOM_REMOTE_MODE（无判定）',
    'LoomHub/hub_controller.py':
        'Hub 注释：说明 H1 不再无条件注入 LOOM_REMOTE_MODE=1（无判定）',
    'tools/package_engine.py':
        '打包启动 bat 模板：生成 set LOOM_REMOTE_MODE=1 的发布脚本（产物脚本，不是入口判定）',
}

_SKIP_DIRS = {'__pycache__', '_tmp', 'archive', 'NVIDIA Corporation', '.git'}


def _iter_repo_py_files():
    for base in (os.path.join(REPO, 'Loom'), os.path.join(REPO, 'LoomHub'),
                 os.path.join(REPO, 'tools')):
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if fn.endswith('.py'):
                    yield os.path.join(dirpath, fn)


def _rel(path):
    return os.path.relpath(path, REPO).replace('\\', '/')


def _remote_collection_hits():
    """收集「疑似远程模式取值集合」的字面量容器：含 'remote' 且 >=3 个 on 值。"""
    on_vals = set('1 on true yes remote'.split())
    hits = []
    for path in _iter_repo_py_files():
        try:
            tree = ast.parse(open(path, encoding='utf-8').read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                vals = [e.value.strip().lower() for e in node.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if 'remote' in vals and len(set(vals) & on_vals) >= 3:
                    hits.append('%s:%d' % (_rel(path), node.lineno))
    return hits


def _three_state_func_hits():
    """收集「疑似三态判定函数」：体内引用 LOOM_REMOTE_MODE/REMOTE_MODE_ENV
    且 return 字符串常量覆盖 >=2 个 off/on/auto。"""
    hits = []
    for path in _iter_repo_py_files():
        try:
            src = open(path, encoding='utf-8').read()
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ''
            if 'LOOM_REMOTE_MODE' not in seg and 'REMOTE_MODE_ENV' not in seg:
                continue
            rets = set()
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Return)
                        and isinstance(sub.value, ast.Constant)
                        and isinstance(sub.value.value, str)):
                    rets.add(sub.value.value)
            if len(rets & {'off', 'on', 'auto'}) >= 2:
                hits.append('%s:%s' % (_rel(path), node.name))
    return hits


def _literal_file_hits():
    """返回 {相对路径: [行号...]}（含 LOOM_REMOTE_MODE 字面量的 .py 文件）。"""
    out = {}
    for path in _iter_repo_py_files():
        try:
            src = open(path, encoding='utf-8').read()
        except Exception:
            continue
        if 'LOOM_REMOTE_MODE' not in src:
            continue
        lines = [i for i, line in enumerate(src.splitlines(), 1)
                 if 'LOOM_REMOTE_MODE' in line]
        out[_rel(path)] = lines
    return out


def t_single_source_structure():
    check('C1 hostenv.remote_launch 定义 REMOTE_ON_VALUES 与 REMOTE_MODES（唯一实现可导入）',
          remote_launch is not None
          and isinstance(getattr(remote_launch, 'REMOTE_ON_VALUES', None), tuple)
          and tuple(getattr(remote_launch, 'REMOTE_MODES', ())) == ('off', 'on', 'auto'),
          'module=%r' % (remote_launch is not None,))

    coll = _remote_collection_hits()
    rl_path = os.path.join(ROOT, 'hostenv', 'remote_launch.py')
    rl_line = None
    if os.path.isfile(rl_path):
        for i, line in enumerate(open(rl_path, encoding='utf-8').read().splitlines(), 1):
            if line.strip().startswith('REMOTE_ON_VALUES'):
                rl_line = i
                break
    expected_coll = (['Loom/hostenv/remote_launch.py:%d' % rl_line]
                     if rl_line else [])
    check('C2 全仓只有 hostenv/remote_launch.py 定义远程模式 on 取值集合',
          coll == expected_coll, 'hits=%r expected=%r' % (coll, expected_coll))

    funcs = _three_state_func_hits()
    check('C3 全仓只有 hostenv/remote_launch.remote_mode 做 off/on/auto 三态判定',
          funcs == ['Loom/hostenv/remote_launch.py:remote_mode'], 'hits=%r' % (funcs,))

    lit = _literal_file_hits()
    unknown = sorted(set(lit) - set(_ALLOWED_FILES))
    detail = '; '.join('%s:%s' % (f, lit[f]) for f in sorted(lit))
    check('C4 LOOM_REMOTE_MODE 字面量出现点全部在白名单内（白名单逐条带理由）',
          not unknown, 'unknown=%r 全部出现点: %s' % (unknown, detail))
    check('C5 白名单每项都有非空理由',
          all(isinstance(v, str) and v.strip() for v in _ALLOWED_FILES.values()),
          'entries=%d' % len(_ALLOWED_FILES))

    # 入口只做薄转调：不再定义取值集合常量，_remote_mode 体内不读环境变量
    for fname in ('Loom.py', 'build_entry.py'):
        src = open(os.path.join(ROOT, fname), encoding='utf-8').read()
        check('C6 %s 不再定义 _REMOTE_ON_VALUES 取值集合（无第二份实现）' % fname,
              '_REMOTE_ON_VALUES' not in src)
        body = _func_body_src(src, '_remote_mode')
        check('C7 %s 的 _remote_mode 体内不直接读 os.environ（薄转调）' % fname,
              body is not None and 'os.environ' not in body,
              'body=%r' % (body,))
        check('C8 %s 转调 hostenv.remote_launch（依赖方向：入口 -> hostenv）' % fname,
              'hostenv.remote_launch' in src)

    rl_path2 = os.path.join(ROOT, 'hostenv', 'remote_launch.py')
    rl_src = open(rl_path2, encoding='utf-8').read() if os.path.isfile(rl_path2) else ''
    imports_loom = False
    if rl_src:
        try:
            _tree = ast.parse(rl_src)
            for _node in ast.walk(_tree):
                if isinstance(_node, ast.Import):
                    imports_loom = imports_loom or any(
                        a.name == 'Loom' or a.name.startswith('Loom.') for a in _node.names)
                elif isinstance(_node, ast.ImportFrom):
                    imports_loom = imports_loom or (
                        _node.module == 'Loom'
                        or (_node.module or '').startswith('Loom.'))
        except SyntaxError:
            pass
    check('C9 hostenv/remote_launch.py 不 import Loom.py（无循环 import）',
          bool(rl_src) and not imports_loom)


t_remote_decision()
t_launch_delegation()
t_editor_execution_plan()
t_editor_process_parity()
t_single_source_structure()

print('=' * 60)
if _fails:
    print('FAIL test_entry_execution_parity: %d 条未过' % len(_fails))
    for f in _fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS test_entry_execution_parity: 全部通过 (B7-55 入口执行面同源)')
sys.exit(0)