# -*- coding: utf-8 -*-
"""test_editor_backend_config_parity.py — Q-B7-60-1 编辑器渲染后端「配置驱动」语义门
（2026-11-23 人类裁决 / 2026-11-24 agent-85 落地）

人类裁决（本门最高依据，原话）:
  「设置里可以选择的只有编辑器当前播放用的啥 API（和播放器一样的存储方式，和播放器
   保持一致，只不过可以在编辑器里直接修改）……编辑器只是在播放模式下只是多一层编辑器
   的外部 UI，其他部分完全一致，编辑模式下只保留编辑场景之类的必要的显示，不带任何
   逻辑帧执行功能（纯编辑场景）……编辑器里的后端只取决于文件里的后端是啥……设置里
   展示的是当前项目正在使用的渲染后端（以配置文件为准）」
  追加裁决: ①重启编辑器生效（不做视口热切换）②一个键全局消费（--backend 命令行仍是
  显式最高优先级）。

修前现状（HEAD af49677）: _editor_backend_choice 只认命令行显式 --backend vulkan，
其余一律 gl —— 配置里的 render_api 对编辑器视口完全无效，同一键在编辑器里只是
「替播放器设的」（违反「一个键全局消费」）。

本门四组（真调用生产函数 / 真写配置，不真开窗口；唯一进程内副作用是 LOOM_USER_ROOT
隔离的临时用户配置目录）:

  A. 配置驱动: 引擎层 设置.json 的 render_api 三态（vulkan/opengl/auto）× 无显式
     argv → 两入口 _editor_backend_choice 决策一致且 = 期望（vulkan→vk /
     opengl→gl / auto→gl）。配置写入走**真实 settings_set 命令壳**（与设置面板
     同一份写盘路径）—— 证明「设置面板写的那个键」就是「编辑器视口读的那个键」
     （一个键全局消费，不是两条链）。
  B. 显式覆盖: argv --backend 仍是显式最高优先级（配置 opengl + argv vulkan →
     vulkan；argv 缺省 → 配置生效）。
  C. 编辑态零逻辑回归锁: 真调用 GLEngine.advance_logic / SceneDriver.advance_logic
     （编辑器形状）跑 N 帧 → 时钟逻辑步 0、插值 alpha == 0、脚本 update 触发点 0；
     每组都带 is_playing=True 对照组证明时钟本身是活的（断言不空转）。
     本组锁的是**既有已满足行为**（任务书: 编辑态零逻辑代码一行不改，C 组只是加锁）
     → 修前即绿，属回归锁，不作为修前红证据。
  D. 结构单源 + 设置面板: 编辑器后端决策实现全仓唯一
     （hostenv/editor_launch.editor_backend_choice）；两入口只薄转调且**真调用同一
     实现**（monkeypatch 计数，不是门内复刻）；设置面板标签/tooltip/写盘命令壳就位。

2026-11-25 终审（agent-89）追加两段（P1-1 / P1-2），并把 auto 期望从 gl 改为 vulkan:

  E. 写盘闭环（P1-1 单层化）: 目标不变量 = 面板显示值 == 重启后生效值 ==
     editor_backend_choice([])。面板写盘走**唯一写盘路径**
     editor_launch.write_render_api_choice（引擎层 settings_set 命令壳 + 清游戏层覆盖键 +
     复核生效值）；面板显示值取 editor_launch.effective_render_api（= 解析链最终结果）。
     反例组: 先在游戏层写 opengl（= 播放器 VK 失败回退 _persist_backend 同款），断言
     面板如实显示 opengl（来源层 game），再在面板改回 vulkan -> 生效值真为 vulkan
     （修前: 游戏层覆盖键把引擎层压住，改了无效）。
  F. auto 语义两端同义（P1-2）: 播放器 resolve_backend(None)=='auto' 原样透传；编辑器
     决策 = 'vulkan'（先试 VK，失败由启动期回退 GL）；失败写盘策略单源
     editor_launch.should_rewrite_config_on_vk_failure —— auto 不改写配置（与播放器
     Q1/Q7=A 同义）、显式 --backend 不改写（Q6 先例）、配置来的 vulkan 改写 opengl
     （人类 2026-11-24 指令）。

修前红（2026-11-25，HEAD 14e2408 + 本门，实跑原文见交付报告）: **29 FAIL / EXIT 1**
  = A5/A6（auto 期望升级后两入口仍返回 gl）+ B1/B2（显式 auto）+ D12/D12b/D15/D16/D17
  （唯一写盘路径 / 失败处理 / 面板显示生效值 / 面板可达段落尚不存在）+ E1~E9（写盘
  闭环全组）+ F2~F8（auto 同义与失败策略）。
修后 **101 checks** 全 PASS / EXIT 0（原 69 条中 68 条原样 + 旧 D12 迁移改写为唯一写盘路径判据（同 docstring 披露；新增 D12b），覆盖面严格增强
路径并**新增** D12b 锁「唯一实现体内真的走 settings_set 命令壳」，强度不降）。

修前红（2026-11-24，HEAD af49677 + 本门，git worktree 临时树真跑）: **17 FAIL / EXIT 1**
  = A 组 3（A5/A6/A8，决策不读配置）+ B 组 3（B1/B2/B4，配置不生效、显式优先无从体现）
  + D 组 11（D1/D2/D5×2/D7 决策非单源、D9~D14 设置面板旧文案与直写）。C 组 13 条修前
  即绿（编辑态零逻辑是**既有已满足行为**，本组只加回归锁，不作为修前红证据）。
修后 **69 checks** 全 PASS / EXIT 0（2026-11-24，agent-85）。

断言措辞纪律: 只锁「同一输入 → 同一可观察决策」与「唯一实现位置」，不写「某入口没有
某能力」这类会把缺陷态固化的断言。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 与 test_entry_backend_parity 同款：失败退出码闸门 + 用户层配置隔离 + 关弹窗
# 本门真写引擎层 render_api（settings_set 命令壳 -> guiloader 用户层 delta）,
# 必须隔离 —— 契约 §8: 跑测试不得污染 %LOCALAPPDATA%，也不得在仓库里留文件。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate
import tempfile as _tempfile_gate

_os_gate.environ.setdefault('LOOM_USER_ROOT',
                            _tempfile_gate.mkdtemp(prefix='loom_test_userroot_b760_'))
_os_gate.environ.setdefault('LOOM_NO_DIALOG', '1')

# D 组要 ast.parse 全仓 .py（含历史文件里的非法转义序列）：SyntaxWarning 属噪音，
# 不改变 AST 结论，这里静音以免污染门输出。
import warnings as _warnings
_warnings.filterwarnings('ignore', category=SyntaxWarning)


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


def _func_body_src(src, name):
    """按 ast 定位函数 name（顶层或类方法均可），返回其完整源码行段（含 docstring）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            _lines = src.split('\n')
            return '\n'.join(_lines[node.lineno - 1:node.end_lineno])
    return None


run_player = _load_mod('run_player')
guiloader = _load_mod('guiloader')
game_settings = _load_mod('game_settings')
editor_launch = _load_mod('hostenv.editor_launch')
loom = _load_entry('loom_entry_b760', 'Loom.py')
build_entry = _load_entry('build_entry_b760', 'build_entry.py')


# ============ 配置写入/清除（走真实 settings_set 命令壳） ============

def _cmd_settings_set(key, value):
    """真调用 EAI settings_set 命令（设置面板写盘的同一个命令壳）。
    命令体 = guiloader load/save 同一入口；win=None 时无 GUI 即时生效分支。"""
    import agent_commands as ac
    return ac.cmd_settings_set(None, {'key': key, 'value': value})


def _engine_settings_path():
    """引擎层用户 设置.json 路径（settings_set 的落点）。"""
    return guiloader.user_settings_path('loom')


def _clear_engine_settings():
    """清空引擎层用户 delta（回到「配置未写」态）。"""
    p = _engine_settings_path()
    try:
        if os.path.isfile(p):
            os.remove(p)
    except Exception as e:
        print('[gate] 清理引擎层设置失败 (%r): %s' % (e, p))


def _entry_edit_choice(mod, argv):
    """真调用入口的编辑器后端决策函数；缺函数/异常 -> (None, 原因)。"""
    fn = getattr(mod, '_editor_backend_choice', None)
    if not callable(fn):
        return None, '%s 无 _editor_backend_choice' % getattr(mod, '__name__', mod)
    try:
        return fn(list(argv)), None
    except Exception as e:
        return None, repr(e)


# ============ A. 配置驱动（引擎层 render_api 三态 × 无显式 argv） ============

# (配置写入值, 期望的编辑器后端, 理由)
_CONFIG_CASES = [
    ('vulkan', 'vulkan', '配置 vulkan -> VK 视口'),
    ('opengl', 'gl', '配置 opengl -> GL 视口'),
    ('auto', 'vulkan', 'P1-2 后 auto 两端同义：先试 VK，失败由编辑器启动期回退 GL（不改写配置）'),
]


def t_config_driven():
    for written, expected, why in _CONFIG_CASES:
        _clear_engine_settings()
        tag = 'render_api=%s（%s）' % (written, why)
        # ① 真写：设置面板同一个命令壳
        try:
            res = _cmd_settings_set('render_api', written)
            wrote_ok = isinstance(res, dict) and res.get('set', {}).get('render_api') == written
            err = None
        except Exception as e:
            wrote_ok, err = False, repr(e)
        check('A1 settings_set 命令壳把 render_api=%s 写进引擎层' % written,
              wrote_ok, 'err=%s' % (err,))
        # ② 回读：引擎层真的存了这个值（下拉框选中项读的就是它）
        got_cfg = guiloader.load_settings('loom').get('render_api')
        check('A2 引擎层回读 render_api == %s（下拉框选中项以配置文件为准）' % written,
              got_cfg == written, 'got=%r' % (got_cfg,))
        # ③ 游戏层未配置（本组只写引擎层 -> 证明决策真的读了引擎层那个键）
        game_api = None
        try:
            game_api = game_settings.read_render_api()
        except Exception as e:
            print('[gate] 读游戏层失败 (%r)' % (e,))
        check('A3 游戏层 render_api 未配置（决策只可能来自引擎层那个键）',
              game_api is None, 'game=%r' % (game_api,))
        # ④ 同一事实源：run_player.resolve_backend(None) 归一结果
        try:
            api = run_player.resolve_backend(None)
            api_err = None
        except Exception as e:
            api, api_err = None, repr(e)
        check('A4 run_player.resolve_backend(None) 解析出 %s（唯一事实源）' % written,
              api == written, 'got=%r err=%s' % (api, api_err))
        # ⑤ 两入口真调用决策函数，逐位一致且 = 期望
        loom_v, err_l = _entry_edit_choice(loom, [])
        be_v, err_b = _entry_edit_choice(build_entry, [])
        check('A5 Loom.py._editor_backend_choice(无 argv) == %r  [%s]' % (expected, tag),
              loom_v == expected, 'got=%r err=%s' % (loom_v, err_l))
        check('A6 build_entry._editor_backend_choice(无 argv) == %r  [%s]' % (expected, tag),
              be_v == expected, 'got=%r err=%s' % (be_v, err_b))
        check('A7 两入口编辑器后端决策逐位一致  [%s]' % tag,
              loom_v is not None and loom_v == be_v, 'loom=%r be=%r' % (loom_v, be_v))
    _clear_engine_settings()
    # 配置未写 -> 默认（guiloader 默认 render_api=vulkan -> 与播放器默认一致）
    try:
        api = run_player.resolve_backend(None)
    except Exception as e:
        api = repr(e)
    loom_v, _ = _entry_edit_choice(loom, [])
    be_v, _ = _entry_edit_choice(build_entry, [])
    check('A8 配置未写时编辑器后端 == 播放器默认解析结果（同一事实源）',
          api == 'vulkan' and loom_v == 'vulkan' and be_v == 'vulkan',
          'resolve=%r loom=%r be=%r' % (api, loom_v, be_v))


# ============ B. 显式 --backend 覆盖配置 ============

def t_explicit_override():
    cases = [
        ('opengl', ['--backend', 'vulkan'], 'vulkan', '显式 vulkan 压过配置 opengl'),
        ('vulkan', ['--backend', 'opengl'], 'gl', '显式 opengl 压过配置 vulkan'),
        ('vulkan', ['--backend', 'auto'], 'vulkan',
         'P1-2 后显式 auto 也先试 VK（失败由启动期回退 GL，不改写配置）'),
        ('vulkan', [], 'vulkan', '无显式 -> 配置生效'),
        ('opengl', [], 'gl', '无显式 -> 配置生效（另一向）'),
    ]
    for written, argv, expected, why in cases:
        _clear_engine_settings()
        try:
            _cmd_settings_set('render_api', written)
        except Exception as e:
            print('[gate] 写配置失败 (%r)' % (e,))
        tag = 'render_api=%s × argv=%s（%s）' % (written, (' '.join(argv) or '<缺省>'), why)
        loom_v, err_l = _entry_edit_choice(loom, argv)
        be_v, err_b = _entry_edit_choice(build_entry, argv)
        check('B1 Loom.py 决策 == %r  [%s]' % (expected, tag),
              loom_v == expected, 'got=%r err=%s' % (loom_v, err_l))
        check('B2 build_entry 决策 == %r  [%s]' % (expected, tag),
              be_v == expected, 'got=%r err=%s' % (be_v, err_b))
        check('B3 两入口逐位一致  [%s]' % tag,
              loom_v is not None and loom_v == be_v, 'loom=%r be=%r' % (loom_v, be_v))
    # 显式优先的结构判据：同一份配置下两种 argv 决策必须不同（否则「显式优先」是空话）
    _clear_engine_settings()
    try:
        _cmd_settings_set('render_api', 'vulkan')
    except Exception as e:
        print('[gate] 写配置失败 (%r)' % (e,))
    cfg_only, _ = _entry_edit_choice(loom, [])
    forced, _ = _entry_edit_choice(loom, ['--backend', 'opengl'])
    check('B4 同一配置 vulkan 下：无 argv 与 --backend opengl 决策不同（显式真优先）',
          cfg_only == 'vulkan' and forced == 'gl',
          'cfg_only=%r forced=%r' % (cfg_only, forced))
    _clear_engine_settings()


# ============ C. 编辑态零逻辑回归锁（代码一行不改，只加锁） ============

EDIT_FRAMES = 8
FRAME_DT = 1.0 / 60.0


def _gl_edit_stub(is_playing):
    """无 GL 桩（与 test_clock_pause_restart.make_engine 同款口径）: 只装
    advance_logic 所需字段 + 真 FixedStepClock + 真 InterpState。"""
    import engine as E
    from core.clock import clock_from_settings
    from core.interp import InterpState
    e = E.GLEngine.__new__(E.GLEngine)
    e.is_playing = bool(is_playing)
    e._split_enable = True
    e._clock = clock_from_settings({'logic_fps': 30, 'physics_fps': 60})
    e._logic_steps_seen = []
    e._clock.on_logic_step.append(lambda dt: e._logic_steps_seen.append(dt))
    e._interp = InterpState([])          # 真插值态（alpha 承载对象）
    e._interp.alpha = 0.7
    e._logic_async = False               # 无头直驱 -> 同步路径
    e._external_ctx = False
    e._logic_paused = False
    e._advanced_this_frame = False
    e._logic_wall_last = None
    # 逻辑帧机制入口计数：编辑态必须 0 次（= 零逻辑帧）
    e._ensure_split_calls = [0]
    _clock = e._clock

    def _rec_ensure_split():
        e._ensure_split_calls[0] += 1
        return _clock

    e._ensure_split = _rec_ensure_split
    return e


def _vk_edit_stub(is_playing):
    """真 SceneDriver（生产 VK 播放内核类）+ 编辑器形状开关。
    _editor_shape 只由 _EditorCore 提供（VkEditorApp 继承），SceneDriver 本身没有 ——
    这里显式置位以镜像 VkEditorApp 的生产形状（D 组另有一条断言锁住该前提）。"""
    import render.vk.driver as SD
    from core.interp import InterpState
    d = SD.SceneDriver()
    d._clock.set_fps(logic_fps=30)
    d._interp = InterpState([])
    d._interp.alpha = 0.7
    d._logic_steps_seen = []
    d._clock.on_logic_step.append(lambda dt: d._logic_steps_seen.append(dt))
    d._editor_shape = True
    d.is_playing = bool(is_playing)
    return d


def t_editor_zero_logic():
    # ---- GL：编辑态（is_playing=False）----
    try:
        e = _gl_edit_stub(False)
        for _ in range(EDIT_FRAMES):
            e._advanced_this_frame = False
            e.advance_logic(FRAME_DT)
        gl_err = None
    except Exception as exc:
        e, gl_err = None, repr(exc)
    check('C1 GL 编辑态 advance_logic 可跑（真调用 GLEngine.advance_logic）',
          e is not None, gl_err)
    if e is not None:
        check('C2 GL 编辑态 %d 帧 -> 逻辑步 0（时钟 steps 不变）' % EDIT_FRAMES,
              e._clock.steps == 0 and len(e._logic_steps_seen) == 0,
              'clock.steps=%r on_logic_step=%r' % (e._clock.steps, len(e._logic_steps_seen)))
        check('C3 GL 编辑态 -> 插值 alpha == 0',
              float(e._interp.alpha) == 0.0, e._interp.alpha)
        check('C4 GL 编辑态 -> 脚本 update 触发点 0 次（on_logic_step 未派发）',
              len(e._logic_steps_seen) == 0, len(e._logic_steps_seen))
        check('C5 GL 编辑态 -> 逻辑帧机制入口（_ensure_split）0 次调用',
              e._ensure_split_calls[0] == 0, e._ensure_split_calls[0])
        check('C6 GL 编辑态 -> 渲染帧仍记账（_advanced_this_frame=True，render 不再推进）',
              e._advanced_this_frame is True, e._advanced_this_frame)
    # ---- GL 对照：播放态时钟是活的（否则 C2 是空转断言）----
    try:
        e2 = _gl_edit_stub(True)
        for _ in range(4):
            e2._advanced_this_frame = False
            e2.advance_logic(FRAME_DT)
        gl_ctl = len(e2._logic_steps_seen)
        gl_ctl_err = None
    except Exception as exc:
        gl_ctl, gl_ctl_err = -1, repr(exc)
    check('C7 对照组 GL 播放态 4 帧 -> 逻辑步 > 0（时钟是活的）',
          gl_ctl > 0, 'steps=%r err=%s' % (gl_ctl, gl_ctl_err))

    # ---- VK：编辑器形状 + 编辑态 ----
    try:
        d = _vk_edit_stub(False)
        rets = [d.advance_logic(FRAME_DT) for _ in range(EDIT_FRAMES)]
        vk_err = None
    except Exception as exc:
        d, rets, vk_err = None, [], repr(exc)
    check('C8 VK 编辑态 advance_logic 可跑（真调用 SceneDriver.advance_logic）',
          d is not None, vk_err)
    if d is not None:
        check('C9 VK 编辑态 %d 帧 -> 逻辑步 0（时钟 steps 不变）' % EDIT_FRAMES,
              d._clock.steps == 0 and len(d._logic_steps_seen) == 0,
              'clock.steps=%r on_logic_step=%r' % (d._clock.steps, len(d._logic_steps_seen)))
        check('C10 VK 编辑态 -> 插值 alpha == 0',
              float(d._interp.alpha) == 0.0, d._interp.alpha)
        check('C11 VK 编辑态 -> 脚本 update 触发点 0 次（on_logic_step 未派发）',
              len(d._logic_steps_seen) == 0, len(d._logic_steps_seen))
        check('C12 VK 编辑态 -> 每帧返回 (0, 0)（零逻辑步/零物理步）',
              rets == [(0, 0)] * EDIT_FRAMES, rets[:3])
    # ---- VK 对照：播放态时钟是活的 ----
    try:
        d2 = _vk_edit_stub(True)
        for _ in range(6):
            d2.advance_logic(FRAME_DT)
        vk_ctl = len(d2._logic_steps_seen)
        vk_ctl_err = None
    except Exception as exc:
        vk_ctl, vk_ctl_err = -1, repr(exc)
    check('C13 对照组 VK 播放态 6 帧 -> 逻辑步 > 0（时钟是活的）',
          vk_ctl > 0, 'steps=%r err=%s' % (vk_ctl, vk_ctl_err))


# ============ D. 结构单源 + 设置面板 ============

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


def _decision_def_sites():
    """全仓「编辑器后端决策实现」定义点：函数名含 editor_backend_choice 且体内
    引用 resolve_backend（= 真做后端归一决策，不是薄转调）。返回 ['rel:func', ...]。"""
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
            if 'editor_backend_choice' not in node.name:
                continue
            seg = ast.get_source_segment(src, node) or ''
            if 'resolve_backend' in seg:
                hits.append('%s:%s' % (_rel(path), node.name))
    return sorted(hits)


def t_single_source():
    fn = getattr(editor_launch, 'editor_backend_choice', None) if editor_launch else None
    check('D1 hostenv.editor_launch.editor_backend_choice 存在（唯一实现可导入）',
          callable(fn), 'module=%r' % (editor_launch is not None,))
    sites = _decision_def_sites()
    check('D2 全仓编辑器后端决策实现恰 1 份（hostenv/editor_launch.py）',
          sites == ['Loom/hostenv/editor_launch.py:editor_backend_choice'],
          'sites=%r' % (sites,))

    # 两入口只薄转调：体内含 editor_backend_choice 转调、不含 resolve_backend
    for fname in ('Loom.py', 'build_entry.py'):
        src = open(os.path.join(ROOT, fname), encoding='utf-8').read()
        body = _func_body_src(src, '_editor_backend_choice')
        check('D3 %s 定义 _editor_backend_choice（入口薄转调可被门真调用）' % fname,
              body is not None)
        check('D4 %s 的 _editor_backend_choice 体内转调 hostenv.editor_launch' % fname,
              bool(body) and 'editor_backend_choice' in body,
              'body=%r' % ((body or '')[:200],))
        check('D5 %s 的 _editor_backend_choice 体内不再自己读配置/归一（无第二份决策）' % fname,
              bool(body) and 'resolve_backend' not in body,
              'body=%r' % ((body or '')[:200],))
        check('D6 %s main 编辑器分支真调用 _editor_backend_choice(sys.argv)' % fname,
              '_editor_backend_choice(sys.argv)' in src)

    # 两入口真调用**同一实现**（monkeypatch 计数，不是门内复刻）
    if editor_launch is not None and callable(fn):
        orig = editor_launch.editor_backend_choice
        seen = []

        def _fake(argv):
            seen.append(tuple(argv))
            return 'SENTINEL'

        try:
            editor_launch.editor_backend_choice = _fake
            lv, _le = _entry_edit_choice(loom, [])
            bv, _be = _entry_edit_choice(build_entry, [])
        finally:
            editor_launch.editor_backend_choice = orig
        check('D7 两入口都真调用 hostenv.editor_launch.editor_backend_choice（同一实现）',
              lv == 'SENTINEL' and bv == 'SENTINEL' and len(seen) == 2,
              'loom=%r be=%r calls=%r' % (lv, bv, seen))
    else:
        check('D7 两入口都真调用 hostenv.editor_launch.editor_backend_choice（同一实现）',
              False, 'hostenv.editor_launch.editor_backend_choice 不存在')

    # 编辑器形状前提（C 组 VK 桩显式置 _editor_shape 的依据）
    try:
        import editor
        from editor.core import _EditorCore
        import render.vk.driver as _sd
        shape_ok = (_EditorCore._editor_shape is True
                    and getattr(editor.VkEditorApp, '_editor_shape', None) is True
                    and issubclass(editor.VkEditorApp, _sd.SceneDriver))
        shape_detail = 'VkEditorApp._editor_shape=%r' % (
            getattr(editor.VkEditorApp, '_editor_shape', 'MISSING'),)
    except Exception as e:
        shape_ok, shape_detail = False, repr(e)
    check('D8 VK 编辑器形状前提：VkEditorApp 继承 SceneDriver 且 _editor_shape=True',
          shape_ok, shape_detail)

    # ---- 设置面板（T2）----
    # Q-B7-38-1 第 8 批（2026-11-26）：设置段已按面板域纯搬迁到
    # gui/panels/settings_mixin.py（LoomGUI mixin 装配）。D9~D17 判据一字不动，
    # 仅读取源改为 main_window.py + settings_mixin.py 两文件合并文本（路径跟随，
    # 断言强度不降：找不到标签/出现旧文案仍然照常判红）。
    mw_text = (open(os.path.join(ROOT, 'gui', 'main_window.py'), encoding='utf-8').read()
                + '\n'                + open(os.path.join(ROOT, 'gui', 'panels', 'settings_mixin.py'),
                       encoding='utf-8').read())
    check('D9 设置面板标签改为「渲染后端（编辑器与播放共用，重启生效）」',
          '渲染后端（编辑器与播放共用，重启生效）' in mw_text
          and '播放器渲染 API（默认）' not in mw_text)
    check('D10 tooltip 说明「以配置文件为准 / 编辑器与播放打包共用 / 重启生效 / --backend 可临时覆盖」',
          '设置当前项目的渲染后端（以配置文件为准）' in mw_text
          and '修改后重启编辑器/播放器生效' in mw_text
          and '--backend 命令行参数可临时覆盖本次启动' in mw_text)
    check('D11 旧文案「编辑器固定 OpenGL」已从设置面板移除',
          '编辑器固定 OpenGL' not in mw_text)
    # P1-1 单层化（2026-11-25）后：写盘实现搬到唯一写盘路径 write_render_api_choice
    # （hostenv/editor_launch.py），面板只转调它。D12 判据随之迁移，强度不降反升 ——
    # 原来只锁「面板函数体里有 settings_set 字样」，现在同时锁「面板真转调唯一实现」+
    # 「唯一实现体内确实走 settings_set 命令壳与 render_api 键」。
    body = _func_body_src(mw_text, '_cmd_set_render_api')
    check('D12 下拉框写盘转调唯一写盘路径（write_render_api_choice，面板与 VK 失败回退同一份）',
          bool(body) and 'write_render_api_choice' in body,
          'body=%r' % ((body or '')[:200],))
    _el_src = open(os.path.join(ROOT, 'hostenv', 'editor_launch.py'), encoding='utf-8').read()
    _wbody = _func_body_src(_el_src, 'write_render_api_choice')
    check('D12b 唯一写盘路径体内走 settings_set 命令壳 + render_api 键（与设置面板同一条写盘）',
          bool(_wbody) and 'settings_set' in _wbody and 'render_api' in _wbody,
          'body=%r' % ((_wbody or '')[:200],))
    check('D13 下拉框 currentIndexChanged 接到 _cmd_set_render_api（不再直写 guiloader）',
          'currentIndexChanged.connect(self._cmd_set_render_api)' in mw_text)
    check('D14 旧直写 lambda（s.__setitem__(\'render_api\'）已删',
          "s.__setitem__('render_api'" not in mw_text)
    # ---- VK 装配失败处理（P0-1）的单源结构：写盘走同一份、失败策略走同一份 ----
    hbody = _func_body_src(mw_text, '_handle_vk_init_failure')
    check('D15 VK 装配失败处理（P0-1）唯一实现在 gui/main_window._handle_vk_init_failure，'
          '且转调唯一写盘路径 + 唯一失败策略（不另起第三处写盘）',
          bool(hbody) and 'write_render_api_choice' in hbody
          and 'should_rewrite_config_on_vk_failure' in hbody,
          'body=%r' % ((hbody or '')[:240],))
    check('D16 设置面板渲染后端下拉显示**生效值**（editor_launch.effective_render_api）',
          'effective_render_api' in mw_text)
    check('D17 设置面板的「不依赖 editor」段落无条件渲染（P0-1 另一半：editor 为 None 也可达）',
          'if e is None:' in mw_text and '编辑器未就绪' in mw_text)


# ============ E. 写盘闭环（P1-1 单层化） ============
#
# 目标不变量（本组逐条钉死）: 面板显示值 == 重启后实际生效值 == editor_backend_choice([])。
# 修前缺陷（终审 agent-87 实测）: 面板写**引擎层**、脚本 API 写**游戏层**，而优先级是
# 游戏层 > 引擎层 -> 面板显示引擎层值、生效值却是游戏层的值（面板显示 X 生效 Y），
# 且播放器 VK 失败回退把游戏层写成 opengl 后面板永久显示 vulkan、改回无效。

def _panel_write(api):
    """设置面板写盘的**同一个**函数（_cmd_set_render_api 转调的唯一实现）。"""
    fn = getattr(editor_launch, 'write_render_api_choice', None)
    if not callable(fn):
        return {'ok': False, 'error': 'hostenv.editor_launch.write_render_api_choice 不存在'}
    try:
        return fn(api) or {}
    except Exception as e:
        return {'ok': False, 'error': repr(e)}


def _panel_shows():
    """设置面板显示值 = 生效值（与面板同一个调用 effective_render_api）。"""
    fn = getattr(editor_launch, 'effective_render_api', None)
    if not callable(fn):
        return None, None
    try:
        return fn()
    except Exception as e:
        print('[gate] 读生效值失败 (%r)' % (e,))
        return None, None


def _reset_layers():
    """清两层 render_api（引擎层 delta + 游戏层用户文件），回到「都没写」态。"""
    _clear_engine_settings()
    try:
        import game_settings
        clear = getattr(game_settings, 'clear_value', None)
        if callable(clear):
            clear('render_api')
        p = game_settings.user_path()
        if os.path.isfile(p):
            os.remove(p)
    except Exception as e:
        print('[gate] 清游戏层失败 (%r)' % (e,))


def t_write_closure():
    # 生效值 -> 编辑器二元决策的**独立硬编码**期望表（不复用被测实现表达式）
    for written, expected_choice in (('opengl', 'gl'), ('vulkan', 'vulkan'), ('auto', 'vulkan')):
        _reset_layers()
        res = _panel_write(written)
        check('E1 面板写 render_api=%s 走唯一写盘路径并返回 ok' % written,
              bool(res.get('ok')), res)
        eff, src = _panel_shows()
        check('E2 面板显示值 == %s（显示的是生效值，不是引擎层单层值）' % written,
              eff == written, 'eff=%r src=%r' % (eff, src))
        got = guiloader.load_settings('loom').get('render_api')
        check('E3 引擎层回读 == %s（设置面板写的就是这个键）' % written, got == written, got)
        try:
            api = run_player.resolve_backend(None)
        except Exception as e:
            api = repr(e)
        check('E4 模拟重启后生效值（resolve_backend(None)）== %s' % written,
              api == written, api)
        check('E5 生效值 -> 编辑器决策 == %r（与 editor_backend_choice([]) 一致）'
              % expected_choice,
              editor_launch.editor_backend_choice([]) == expected_choice,
              editor_launch.editor_backend_choice([]))
    # ---- 闭环反例：游戏层覆盖键（播放器 VK 失败回退写的）不得让面板撒谎 ----
    _reset_layers()
    _cmd_settings_set('render_api', 'vulkan')       # 引擎层 vulkan（= 面板上次写的）
    import game_settings
    game_settings.write_render_api('opengl')        # 游戏层 opengl（run_player._persist_backend 同款）
    eff, src = _panel_shows()
    check('E6 游戏层有覆盖时面板显示生效值 opengl，且标注来源层 game',
          eff == 'opengl' and src == 'game', 'eff=%r src=%r' % (eff, src))
    res = _panel_write('vulkan')                    # 用户在面板改回 vulkan
    eff2, src2 = _panel_shows()
    check('E7 面板改回 vulkan 后生效值真为 vulkan（游戏层影子键被单层化写盘清掉）',
          bool(res.get('ok')) and eff2 == 'vulkan',
          'ok=%r err=%r eff=%r src=%r' % (res.get('ok'), res.get('error'), eff2, src2))
    check('E8 游戏层覆盖键已不存在（不存在「面板显示 X、生效 Y」的组合）',
          game_settings.read_render_api() is None,
          'game=%r' % (game_settings.read_render_api(),))
    check('E9 面板显示值 == 生效值 == 决策 三者闭环（同一输入同一可观察结果）',
          eff2 == 'vulkan' and run_player.resolve_backend(None) == 'vulkan'
          and editor_launch.editor_backend_choice([]) == 'vulkan',
          'show=%r resolve=%r choice=%r'
          % (eff2, run_player.resolve_backend(None), editor_launch.editor_backend_choice([])))
    _reset_layers()


# ============ F. auto 语义两端同义（P1-2） ============
#
# 播放器: resolve_backend(None)=='auto' -> run_backend 先试 VK, VkInitError 回退 GL, 不改写配置
# 编辑器: T1 的启动期回退机制就位后同义 —— 先试 VK（backend='vulkan'），失败回退 GL 视口，
#         同样不改写配置（Q1/Q7: auto 没有偏好可持久化）。

def t_auto_semantics():
    _reset_layers()
    _cmd_settings_set('render_api', 'auto')
    try:
        player_api = run_player.resolve_backend(None)
    except Exception as e:
        player_api = repr(e)
    check('F1 播放器侧：配置 auto 原样透传（resolve_backend(None) == "auto"）',
          player_api == 'auto', player_api)
    check('F2 编辑器侧：配置 auto -> 先试 VK（决策 vulkan），不再直接取保底 gl',
          editor_launch.editor_backend_choice([]) == 'vulkan',
          editor_launch.editor_backend_choice([]))
    check('F3 两入口与唯一实现一致（auto -> vulkan）',
          loom._editor_backend_choice([]) == 'vulkan'
          and build_entry._editor_backend_choice([]) == 'vulkan',
          (loom._editor_backend_choice([]), build_entry._editor_backend_choice([])))
    pol = getattr(editor_launch, 'should_rewrite_config_on_vk_failure', None)
    check('F4 VK 失败写盘策略单源存在（editor_launch.should_rewrite_config_on_vk_failure）',
          callable(pol))
    if callable(pol):
        check('F5 auto 失败不改写配置（与播放器 Q1/Q7 同义：没有偏好可持久化）',
              pol(False, 'auto') is False, pol(False, 'auto'))
        check('F6 配置来的 vulkan 失败 -> 改写为 opengl（人类 2026-11-24 指令）',
              pol(False, 'vulkan') is True, pol(False, 'vulkan'))
        check('F7 显式 --backend vulkan 失败不改写（Q6 先例：显式选择不动用户配置）',
              pol(True, 'vulkan') is False, pol(True, 'vulkan'))
        check('F8 本来就是 opengl 的启动不会走到 VK 失败改写（策略对 opengl 恒 False）',
              pol(False, 'opengl') is False, pol(False, 'opengl'))
    else:
        for _n in ('F5', 'F6', 'F7', 'F8'):
            check('%s 失败写盘策略缺失（无法判定）' % _n, False)
    _reset_layers()


t_config_driven()
t_explicit_override()
t_editor_zero_logic()
t_single_source()
t_write_closure()
t_auto_semantics()

print('=' * 60)
if _fails:
    print('FAIL test_editor_backend_config_parity: %d 条未过' % len(_fails))
    for f in _fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS test_editor_backend_config_parity: 全部通过 (Q-B7-60-1 编辑器后端配置驱动)')
sys.exit(0)
