# -*- coding: utf-8 -*-
"""test_unlock_key.py — 解锁键归属 (D6=A) 与键位冲突拒绝 (审计 P-01-02) 的定向断言。

白盒契约:
  · 2026-11-08 人类裁决 D6=A: 引擎**独占**解锁键; 内置 first/third_person 删掉
    硬编码 Tab 分支(只读 mouse_locked, 不再 toggle)。
  · Script 基类增加 keys_used 声明 ('Tab' 或 'action:向前');
    设置解锁键时若与任何脚本声明冲突 -> **拒绝保存**并提示"…已被脚本 X 使用,
    请先定义解锁键"。
  · 加载时冲突(用户配置里已存着冲突键) -> 告警并回退默认 Tab(见 loom_input
    resolve_unlock_key_conflict 的 docstring 说明理由)。

覆盖: 一帧恰好翻转一次 / 冲突拒绝保存 / action: 展开 / 自冲突排除 /
      加载时冲突回退 / poll_unlock(暂停态入口) / 无冲突改键可用。
所有写路径指向临时目录(LOOM_USER_ROOT)。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contextlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('LOOM_NO_PARALLEL', '1')

_fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        _fails.append(name)


def capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn()
    return out, buf.getvalue()


import engine as E            # noqa: E402
import game_settings as GS    # noqa: E402
import loom_input as LI       # noqa: E402
import scripts as SC          # noqa: E402


class Stub(LI.InputMixin):
    """最小桩: 只实现脚本/引擎接口里本文件用到的那几项。"""

    def __init__(self):
        self.actions = dict(LI.DEFAULT_ACTIONS)
        self.script_keys = {}
        # 2026-11-08 裁决: 引擎默认不允许锁鼠标；本文件测"允许锁"的游戏
        self.mouse_lock_allowed = True
        self.mouse_locked = True
        self.mouse_unlock_requested = False
        self._ui_capture_mouse = False
        self.mouse_rel = (0, 0)
        self.camera_yaw = 0.0
        self.camera_pitch = 0.0
        self.camera = E.Point3D(0, 0, 0)
        self.camera_target = None
        self.orbit_mode = True
        self._external_ctx = True
        self.view = None
        self._unlock_key_prev = False
        self.moved = 0.0

    # 脚本依赖的最小面
    def is_key(self, name):
        return bool(self.script_keys.get(name, False))

    def get_action(self, name):
        for k in self.actions.get(name, (name,)):
            if self.script_keys.get(k, False):
                return True
        return False

    def world_position(self, m):
        return m.position

    def move_with_collision(self, m, dx, dy, dz):
        self.moved += abs(dx) + abs(dz)
        return False

    def player_pitch_limits(self):
        return None


Stub.set_action_binding = E.GLEngine.set_action_binding
Stub._poll_mouse_unlock_key = E.GLEngine._poll_mouse_unlock_key
Stub.poll_unlock = E.GLEngine.poll_unlock


class FakeObj:
    def __init__(self):
        self.position = E.Point3D(0, 0, 0)
        self.rotation = E.Point3D(0, 0, 0)
        self.rigidbody = None


class Sandbox:
    def __init__(self, tmp):
        self._argv0 = sys.argv[0]
        self._env = {k: os.environ.get(k) for k in ('LOOM_USER_ROOT', 'LOOM_GAME_DIR')}
        exe = os.path.join(tmp, 'game')
        os.makedirs(exe, exist_ok=True)
        sys.argv[0] = os.path.join(exe, 'MyGame.exe')
        os.environ['LOOM_USER_ROOT'] = os.path.join(tmp, 'userroot')
        os.environ.pop('LOOM_GAME_DIR', None)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        sys.argv[0] = self._argv0
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def _temp_script(sid, keys_used):
    """临时注册一个声明 keys_used 的脚本（用完删除）。"""
    cls = type('TmpUnlockProbe', (SC.Script,), {
        'script_id': sid, 'name': '占位脚本', 'params': (),
        'keys_used': tuple(keys_used)})
    SC.SCRIPTS[sid] = cls
    return cls


# ============ A. 声明与内置脚本语义 ============
def t_declared():
    print("=== A. keys_used 声明 / 内置脚本不再占 Tab ===")
    check("Script 基类有 keys_used 声明位", hasattr(SC.Script, 'keys_used'))
    uses = SC.script_key_uses()
    check("first_person 已声明消费动作", 'first_person' in uses
          and 'action:向前' in uses['first_person'], uses.get('first_person'))
    check("first_person 不再声明/占用 Tab",
          'Tab' not in uses.get('first_person', ()) and
          'Tab' not in uses.get('third_person', ()),
          (uses.get('first_person'), uses.get('third_person')))
    src = open(os.path.join(ROOT, 'scripts.py'), encoding='utf-8').read()
    check("内置播放器脚本源码里不再 toggle 鼠标锁定",
          src.count('toggle_mouse_locked') == 0, src.count('toggle_mouse_locked'))
    fp = SC.get_script('first_person')()
    fp.obj = FakeObj()
    fp.engine = Stub()
    check("first_person 实例无 _tab_was 状态 (旧 Tab 分支已删)",
          not hasattr(fp, '_tab_was'))


# ============ B. 一帧恰好翻转一次 (P-01-02 直证) ============
def t_one_toggle_per_frame():
    print("=== B. 同一帧 poll + 玩家脚本 -> 只翻转一次 (P-01-02) ===")
    e = Stub()
    e.script_keys = {'Tab': True}
    s = SC.get_script('first_person')()
    s.obj = FakeObj()
    s.engine = e
    s.on_start()                                  # 脚本 on_start 锁定鼠标
    check("on_start 后锁定", e.mouse_locked is True)
    toggled = e._poll_mouse_unlock_key()          # engine.update_scripts 的第 1 步
    s.update(0.0)                                 # 第 2 步: 脚本只读状态
    check("引擎 poll 报告发生翻转", toggled is True)
    check("按一次 Tab 净效果 = 解锁 (不再被脚本翻回去)",
          e.mouse_locked is False and e.mouse_unlock_requested is True,
          (e.mouse_locked, e.mouse_unlock_requested))
    check("解锁状态鼠标不转视角 (脚本只读)", abs(s.yaw) < 1e-9, "yaw=%.3f" % s.yaw)


# ============ C. 冲突拒绝保存 ============
def t_conflict_reject(tmp):
    print("=== C. 设置解锁键与脚本声明冲突 -> 拒绝保存 ===")
    with Sandbox(tmp):
        _temp_script('_probe_tab_user', ('Tab',))
        try:
            e = Stub()
            ok, reason = e.validate_action_binding(LI.UNLOCK_ACTION, ['Tab'])
            check("validate_action_binding 判定冲突", ok is False, (ok, reason))
            check("提示指名脚本", '占位脚本(_probe_tab_user)' in reason, reason)
            check("提示含'请先定义解锁键'", '请先定义解锁键' in reason, reason)

            raised = None
            try:
                e.rebind_action(LI.UNLOCK_ACTION, ['Tab'])
            except ValueError as exc:
                raised = exc
            check("rebind_action 直接拒绝 (抛 ValueError)", raised is not None, raised)
            check("拒绝后内存绑定未变",
                  e.actions.get(LI.UNLOCK_ACTION) == ['Tab'], e.actions.get(LI.UNLOCK_ACTION))
            check("拒绝后**未写用户层**",
                  LI.UNLOCK_ACTION not in GS.read_key_bindings(), GS.read_key_bindings())

            res = capture(lambda: e.set_action_binding(LI.UNLOCK_ACTION, ['Tab']))[0]
            check("set_action_binding 如实返回 ok=False / saved=False",
                  res.get('ok') is False and res.get('saved') is False, res)
            check("set_action_binding 的 error 带冲突原因",
                  '已被脚本' in str(res.get('error')), res.get('error'))
        finally:
            SC.SCRIPTS.pop('_probe_tab_user', None)


# ============ D. action: 展开 与 自冲突排除 ============
def t_action_expand(tmp):
    print("=== D. action: 展开 / 自冲突排除 ===")
    with Sandbox(tmp):
        e = Stub()      # first_person 声明 action:向前, 向前 当前绑定 w/Up
        ok, reason = e.validate_action_binding(LI.UNLOCK_ACTION, ['w'])
        check("解锁键绑到'向前'的键 -> 冲突", ok is False and '已被脚本' in reason, reason)
        ok2, reason2 = e.validate_action_binding('向前', ['w'])
        check("把 向前 再绑回 w -> 不算自冲突 (允许)",
              ok2 is True, reason2)
        raised = None
        try:
            e.rebind_action(LI.UNLOCK_ACTION, ['w'])
        except ValueError as exc:
            raised = exc
        check("rebind 解锁键=w 被拒绝", raised is not None, raised)


# ============ E. 加载时冲突 -> 告警 + 回退默认 ============
def t_load_conflict(tmp):
    print("=== E. 加载时冲突 -> 告警并回退默认 Tab ===")
    with Sandbox(tmp):
        GS.write_key_binding(LI.UNLOCK_ACTION, ['w'])     # 用户层存了冲突键
        e = Stub()
        _out, log = capture(lambda: e._load_action_bindings())
        check("加载后回退到默认 Tab",
              e.actions.get(LI.UNLOCK_ACTION) == ['Tab'], e.actions.get(LI.UNLOCK_ACTION))
        check("回退时明确告警 (不静默)", '已回退默认解锁键' in log, log.strip())


# ============ F. poll_unlock: 暂停态入口 ============
def t_poll_unlock_api():
    print("=== F. poll_unlock() 供暂停态调用 ===")
    e = Stub()
    check("poll_unlock 是公开 API", hasattr(e, 'poll_unlock'))
    e.script_keys = {'Tab': True}
    e.mouse_locked = True
    first = e.poll_unlock()
    second = e.poll_unlock()          # 未松开 -> 不应再翻
    check("按下帧返回 True (发生翻转)", first is True)
    check("持续按住不重复翻转", second is False and e.mouse_locked is False,
          (second, e.mouse_locked))
    e.script_keys = {}
    e.poll_unlock()
    e.script_keys = {'Tab': True}
    check("松开后再按 -> 回锁", e.poll_unlock() is True and e.mouse_locked is True)
    e2 = Stub()
    e2.mouse_lock_allowed = False
    e2.mouse_locked = True
    e2.script_keys = {'Tab': True}
    check("不允许锁定时永远不锁且不翻转",
          e2.poll_unlock() is False and e2.mouse_locked is False)


# ============ G. 无冲突改键照常可用 ============
def t_rebind_ok(tmp):
    print("=== G. 无冲突改键：立即生效 + 落用户层 ===")
    with Sandbox(tmp):
        e = Stub()
        res = capture(lambda: e.set_action_binding(LI.UNLOCK_ACTION, ['F10']))[0]
        check("改键成功", res.get('ok') is True and res.get('saved') is True, res)
        check("写入用户层 key_bindings",
              GS.read_key_bindings().get(LI.UNLOCK_ACTION) == ['F10'],
              GS.read_key_bindings())
        e.script_keys = {'F10': True}
        check("新键立即生效 (get_action)", e.get_action(LI.UNLOCK_ACTION) is True)


# ============ H. N3: 桩缺 actions -> 恰好一条告警; 补齐后轮询真的翻转 ============
def t_n3_missing_actions_once():
    print("=== H. N3: 轮询跑不起来时恰好一条告警, 补齐后真的翻转 ===")

    class _NoActionsStub(LI.InputMixin):
        """刻意不给 actions/script_keys —— 复刻"桩缺属性"的假绿现场。"""

        def __init__(self):
            # 允许锁 + **缺 actions/script_keys** —— 复刻 N3"轮询其实没跑"的假绿现场
            self.mouse_lock_allowed = True
            self.mouse_locked = True
            self.mouse_unlock_requested = False
            self._ui_capture_mouse = False
            self._external_ctx = True
            self.view = None

    _NoActionsStub._warn_unlock_poll_unavailable = E.GLEngine._warn_unlock_poll_unavailable
    _NoActionsStub._poll_mouse_unlock_key = E.GLEngine._poll_mouse_unlock_key
    _NoActionsStub.poll_unlock = E.GLEngine.poll_unlock

    e = _NoActionsStub()
    outs, log = capture(lambda: [e.poll_unlock() for _ in range(50)])
    n = log.count('解锁键轮询未执行')
    check("缺 actions/script_keys 时 poll 全返回 False (不假装翻转)",
          outs == [False] * 50, outs[:3])
    check("50 帧只告警 1 条 (不刷屏; 修前: 每帧一条)", n == 1, n)
    check("告警带引擎类名 + 缺失属性",
          '_NoActionsStub' in log and 'actions' in log, log.strip()[:140])
    check("实例留下已告警标记", getattr(e, '_unlock_poll_warned', False) is True)

    # 补齐最小输入状态后, 轮询真的要跑起来（这也是本批给 4 个桩补属性的依据）
    e2 = _NoActionsStub()
    e2.actions = dict(LI.DEFAULT_ACTIONS)
    e2.script_keys = {'Tab': True}
    e2.mouse_locked = True
    out2, log2 = capture(e2.poll_unlock)
    check("补齐 actions/script_keys 后 poll_unlock 真的翻转",
          out2 is True and e2.mouse_locked is False,
          (out2, e2.mouse_locked))
    check("补齐后不再产生'轮询未执行'告警", '解锁键轮询未执行' not in log2,
          log2.strip()[:120])


# ============ I. 默认不锁 + allowed=False 彻底不锁（2026-11-08 人类裁决） ============
def t_default_no_lock(tmp):
    print("=== I. 默认不锁 / allowed=False 彻底不锁 / set_mouse_lock_allowed ===")
    with Sandbox(tmp):
        check("game_settings 默认 allowed=False", GS.mouse_lock_allowed() is False,
              GS.mouse_lock_allowed())
        check("game_settings 默认 initial=False", GS.mouse_lock_initial() is False,
              GS.mouse_lock_initial())

        class _LockStub(LI.InputMixin):
            """默认态引擎桩（不读配置 -> 走代码默认值）。"""

            def __init__(self):
                self.mouse_locked = False
                self.mouse_unlock_requested = False
                self._ui_capture_mouse = False
                self._external_ctx = True
                self.view = None
                self.actions = dict(LI.DEFAULT_ACTIONS)
                self.script_keys = {}

            def is_key(self, name):
                return bool(self.script_keys.get(name, False))

            def get_action(self, name):
                for k in self.actions.get(name, (name,)):
                    if self.script_keys.get(k, False):
                        return True
                return False

        _LockStub._poll_mouse_unlock_key = E.GLEngine._poll_mouse_unlock_key
        _LockStub.poll_unlock = E.GLEngine.poll_unlock

        e = _LockStub()
        check("引擎默认 mouse_lock_allowed=False (类属性)",
              LI.InputMixin.mouse_lock_allowed is False)
        out, log = capture(lambda: e.set_mouse_locked(True))
        check("allowed=False: set_mouse_locked(True) 无效",
              e.mouse_locked is False and out is False, (e.mouse_locked, out))
        check("allowed=False: 明确告警(说明本游戏不允许锁鼠标)",
              '不允许锁鼠标' in log, log.strip()[:110])
        _o2, log2 = capture(lambda: e.set_mouse_locked(True))
        check("再次请求锁定不刷屏 (每进程一次)",
              '不允许锁鼠标' not in log2, log2.strip()[:80])

        e.script_keys = {'Tab': True}
        toggled = capture(lambda: e.poll_unlock())[0]
        check("allowed=False: 按 Tab 不翻转",
              toggled is False and e.mouse_locked is False, (toggled, e.mouse_locked))
        _o3, log3 = capture(lambda: e.poll_unlock())
        check("allowed=False: 按 Tab 不打印'切换鼠标锁定'",
              '切换鼠标锁定' not in log3, log3.strip()[:80])
        tog = capture(lambda: e.toggle_mouse_locked())[0]
        check("allowed=False: toggle_mouse_locked 完全不响应",
              tog is False and e.mouse_unlock_requested is False)
        e.set_ui_capture_mouse(True)
        check("allowed=False: 特殊场景 API 也不会把锁打开",
              e.mouse_locked is False, e.mouse_locked)
        e.set_ui_capture_mouse(False)

        # 打开 allowed -> 立即按意图应用；Tab 随之生效
        e.set_mouse_lock_allowed(True)
        check("set_mouse_lock_allowed(True) 后立即锁定",
              e.mouse_locked is True, e.mouse_locked)
        e.script_keys = {}
        e.poll_unlock()                      # 松开帧
        e.script_keys = {'Tab': True}
        check("打开 allowed 后按 Tab 生效(解锁)",
              e.poll_unlock() is True and e.mouse_locked is False,
              e.mouse_locked)

        # 关掉 allowed -> 立刻释放（锁不能被脚本留着）
        e.mouse_unlock_requested = False
        e.set_mouse_locked(True)             # 此时 allowed=True, 可以锁
        check("回锁成功(前置)", e.mouse_locked is True, e.mouse_locked)
        e.set_mouse_lock_allowed(False)
        check("set_mouse_lock_allowed(False) 立即释放",
              e.mouse_locked is False and e.mouse_unlock_requested is False,
              e.mouse_locked)


if __name__ == "__main__":
    print("========== 解锁键归属 / 冲突拒绝 定向测试 ==========")
    t_declared()
    t_one_toggle_per_frame()
    with tempfile.TemporaryDirectory() as t1:
        t_conflict_reject(t1)
    with tempfile.TemporaryDirectory() as t2:
        t_action_expand(t2)
    with tempfile.TemporaryDirectory() as t3:
        t_load_conflict(t3)
    t_poll_unlock_api()
    with tempfile.TemporaryDirectory() as t4:
        t_rebind_ok(t4)
    t_n3_missing_actions_once()
    with tempfile.TemporaryDirectory() as t5:
        t_default_no_lock(t5)
    print("=" * 50)
    if _fails:
        print("总结果: %d 项失败 ❌" % len(_fails))
        for f in _fails:
            print("  FAIL:", f)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
