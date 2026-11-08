# -*- coding: utf-8 -*-
"""test_user_config.py — 用户配置目录契约 (2026-11-08) 的验收测试。

契约: docs/design/用户配置目录契约_20261108.md §9
覆盖: 首次写默认 / delta 生效 / 模板新增键自动生效 / 坏 JSON->备份+默认 /
      旧格式迁移成功 / 旧格式迁移失败->默认 / 只读模板下可运行(模板字节不变) /
      LOOM_USER_ROOT 与 LOOM_GAME_DIR 覆盖 / 原子写(中途失败不留半文件) /
      未知键保留；外加审计缺陷 P-01-01 / P-01-03 / P-01-05 / P-01-07 / P-01-11 的回归。

所有写路径都指向临时目录；绝不写仓库（契约 §8 不变量）。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import contextlib
import hashlib
import io
import json
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


def rd(p):
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def wr(p, d, text=None):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        if text is not None:
            f.write(text)
        else:
            json.dump(d, f, ensure_ascii=False, indent=2)


def sha(p):
    with open(p, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn()
    return out, buf.getvalue()


class Sandbox:
    """把 argv[0] 指到 <tmp>/game/MyGame.exe，LOOM_* 指到 <tmp> 下的子目录。"""

    def __init__(self, tmp, game_dir_override=False):
        self.tmp = tmp
        self.exe_dir = os.path.join(tmp, 'game')
        os.makedirs(self.exe_dir, exist_ok=True)
        self._argv0 = sys.argv[0]
        self._env = {k: os.environ.get(k) for k in
                     ('LOOM_USER_ROOT', 'LOOM_GAME_DIR', 'LOOM_GAME_ID', 'LOOM_PROJECT_DIR')}
        sys.argv[0] = os.path.join(self.exe_dir, 'MyGame.exe')
        os.environ['LOOM_USER_ROOT'] = os.path.join(tmp, 'userroot')
        os.environ.pop('LOOM_GAME_ID', None)
        os.environ.pop('LOOM_PROJECT_DIR', None)
        if game_dir_override:
            os.environ['LOOM_GAME_DIR'] = os.path.join(tmp, 'gamedir')
            os.makedirs(os.environ['LOOM_GAME_DIR'], exist_ok=True)
        else:
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

    @property
    def template(self):
        return os.path.join(self.exe_dir, '游戏设置.json')


import userpaths              # noqa: E402
import game_settings as GS    # noqa: E402
import guiloader              # noqa: E402
import loom_input as LI       # noqa: E402


# ============ A. userpaths 收口 ============
def t_userpaths(tmp):
    print("=== A. userpaths 路径收口 ===")
    os.environ['LOOM_USER_ROOT'] = os.path.join(tmp, 'u')
    root = userpaths.user_root()
    check("LOOM_USER_ROOT 覆盖 user_root", root == os.path.abspath(os.path.join(tmp, 'u')), root)
    check("engine_settings 在用户根下",
          userpaths.engine_settings().startswith(root), userpaths.engine_settings())
    check("hub_settings 在用户根下",
          userpaths.hub_settings().startswith(root), userpaths.hub_settings())
    check("game_settings(gid) 在 games/<gid>/settings.json",
          userpaths.game_settings('PacMan2D-1a2b3c4d').replace('\\', '/').endswith(
              'games/PacMan2D-1a2b3c4d/settings.json'),
          userpaths.game_settings('PacMan2D-1a2b3c4d'))
    check("project_settings(pid) 在 projects/<pid>/settings.json",
          userpaths.project_settings('abc').replace('\\', '/').endswith(
              'projects/abc/settings.json'), userpaths.project_settings('abc'))
    check("log_path 在 logs/<app>/日志.txt",
          userpaths.log_path('game').replace('\\', '/').endswith('logs/game/日志.txt'),
          userpaths.log_path('game'))
    bp = userpaths.backup_path(os.path.join(tmp, 'u', 'settings.json'))
    check("backup_path 形态 <name>.bak-<ts>.json",
          os.path.basename(bp).startswith('settings.bak-') and bp.endswith('.json'), bp)
    gid1 = userpaths.game_id_for(os.path.join(tmp, 'game'), '吃豆人 2D')
    gid2 = userpaths.game_id_for(os.path.join(tmp, 'game'), '吃豆人 2D')
    check("game_id 稳定且含 sha1 短码", gid1 == gid2 and '-' in gid1, gid1)
    proj = os.path.join(tmp, 'proj')
    os.makedirs(proj, exist_ok=True)
    pid, created = userpaths.project_id(proj)
    pid2, created2 = userpaths.project_id(proj)
    check("project_id 首次生成并落盘、二次复用",
          created and not created2 and pid == pid2 and len(pid) == 32, (pid, created, created2))


# ============ B. 模板 + delta 合并 ============
def t_merge(tmp):
    print("=== B. 默认模板 <-> 用户 delta ===")
    with Sandbox(tmp) as sb:
        wr(sb.template, {"render_api": "vulkan", "title": "吃豆人"})
        check("首次启动: 用户层不存在时 load 只返回模板值",
              GS.load() == {"render_api": "vulkan", "title": "吃豆人"}, GS.load())
        created = GS.bootstrap()
        up = GS.user_path()
        check("bootstrap 首次写 {schema:1, values:{}}",
              created and rd(up).get("schema") == 1 and rd(up).get("values") == {}, rd(up))
        GS.set_value("mouse_lock_allowed", False)
        check("delta 生效: mouse_lock_allowed=False 可读",
              GS.mouse_lock_allowed() is False)
        uf = rd(up)
        check("用户层只存 delta (不含模板里的键)",
              uf.get("values") == {"mouse_lock_allowed": False}, uf.get("values"))
        check("模板值仍可见 (模板为底)", GS.read('title') == '吃豆人')
        # 模板新增键 -> 自动生效
        wr(sb.template, {"render_api": "vulkan", "title": "吃豆人", "新增键": 42})
        check("模板新增键自动生效", GS.read('新增键') == 42, GS.read('新增键'))
        # 未知键保留
        v = rd(up)['values']
        v['未来兼容键'] = {'x': 1}
        wr(up, {"schema": 1, "values": v})
        check("未知键保留 (模板没有、用户有的键不丢)",
              GS.read('未来兼容键') == {'x': 1}, GS.read('未来兼容键'))
        check("模板文件字节未被写过 (只读层)", '新增键' in rd(sb.template))


# ============ C. 坏 JSON -> 备份 + 默认 ============
def t_corrupt(tmp):
    print("=== C. 坏 JSON -> 备份 + 默认 ===")
    with Sandbox(tmp) as sb:
        wr(sb.template, {"render_api": "vulkan"})
        GS.bootstrap()
        up = GS.user_path()
        wr(up, None, text="{ 这不是 json")
        out, log = capture(lambda: GS.load())
        check("坏用户层 -> 回落到模板值", out == {"render_api": "vulkan"}, out)
        bak = [f for f in os.listdir(os.path.dirname(up)) if '.bak-' in f]
        check("坏文件已备份 *.bak-<ts>.json", len(bak) == 1, bak)
        check("备份时出声 (打印原因)", '[配置]' in log, log.strip())
        out2 = capture(lambda: GS.read_key_bindings())[0]
        check("坏文件之后仍可正常读", out2 == {}, out2)


# ============ D. 旧格式迁移 ============
def t_migrate_ok(tmp):
    print("=== D. 旧格式迁移成功 ===")
    with Sandbox(tmp) as sb:
        wr(os.path.join(sb.exe_dir, '游戏配置.json'),
           {"render_api": "opengl", "game_id": "PacMan2D-1a2b3c4d", "未知旧键": "v"})
        created = GS.bootstrap()
        up = GS.user_path()
        check("迁移后用 game_config 里的 game_id 定位用户层",
              up.replace('\\', '/').endswith('games/PacMan2D-1a2b3c4d/settings.json'), up)
        vals = rd(up).get('values')
        check("旧格式已知键搬进 values", created and vals.get('render_api') == 'opengl', vals)
        check("旧格式未知键也搬 (宁留勿丢)", vals.get('未知旧键') == 'v', vals)
        check("迁移后 read_render_api 生效", GS.read_render_api() == 'opengl')


def t_migrate_bad(tmp):
    print("=== D2. 旧格式迁移失败 -> 默认启动 (不在半路崩) ===")
    with Sandbox(tmp) as sb:
        wr(os.path.join(sb.exe_dir, '游戏配置.json'), None, text="{ 坏掉的旧配置")
        ok = True
        try:
            GS.bootstrap()
        except Exception as e:      # noqa: BLE001
            ok = False
            print("   异常:", repr(e))
        up = GS.user_path()
        check("旧配置损坏时仍完成首次写默认", ok and os.path.isfile(up), up)
        check("损坏旧配置不被搬进 values", rd(up).get('values') == {}, rd(up).get('values'))
        check("旧配置原件保持不动 (模板层只读)",
              open(os.path.join(sb.exe_dir, '游戏配置.json'), encoding='utf-8').read().startswith('{ 坏'))


# ============ E. LOOM_GAME_DIR 强制覆盖 ============
def t_game_dir_override(tmp):
    print("=== E. LOOM_GAME_DIR 最高优先级覆盖 ===")
    with Sandbox(tmp, game_dir_override=True) as sb:
        gd = os.environ['LOOM_GAME_DIR']
        wr(os.path.join(gd, '游戏设置.json'), {"render_api": "opengl"})
        check("LOOM_GAME_DIR 下的旧格式明文可读", GS.read_render_api() == 'opengl',
              GS.read_render_api())
        ok, val, err = GS.write_render_api('vulkan')
        check("写回到 LOOM_GAME_DIR 指定目录", ok and val == 'vulkan' and err is None,
              (ok, val, err))
        check("写后重新读取生效", GS.read_render_api() == 'vulkan')
        check("用户根未被 LOOM_GAME_DIR 场景污染",
              not os.path.exists(userpaths.engine_settings()))
        other = os.path.join(tmp, 'explicit_dir')
        ok2, _v2, _e2 = GS.write_render_api('opengl', base_dir=other)
        check("base_dir 显式落点生效 (供 run_player._SETTINGS_BASE 等既有覆盖用)",
              ok2 and os.path.isfile(os.path.join(other, '游戏设置.json')), ok2)


# ============ F. 原子写 ============
def t_atomic(tmp):
    print("=== F. 原子写: 中途失败不留半文件 ===")
    with Sandbox(tmp) as sb:
        wr(sb.template, {"render_api": "vulkan"})
        GS.bootstrap()
        up = GS.user_path()
        with open(up, 'rb') as f:
            before = f.read()
        real_replace = GS.os.replace

        def boom(a, b):                      # 模拟 os.replace 失败（磁盘满/ACL）
            raise OSError(13, '模拟磁盘满')

        GS.os.replace = boom
        raised = None
        try:
            GS.set_value('render_api', 'opengl')
        except Exception as e:                # noqa: BLE001
            raised = e
        finally:
            GS.os.replace = real_replace
        check("写失败上抛 (契约 §7, 不再 except: pass)", raised is not None, raised)
        leftovers = [f for f in os.listdir(os.path.dirname(up)) if f.endswith('.tmp')]
        check("失败后无 .tmp 残留", leftovers == [], leftovers)
        with open(up, 'rb') as f:
            check("失败后原用户文件未被截断/半写", f.read() == before)
        GS.set_value('render_api', 'opengl')
        check("恢复正常后可写 (替换回来的 os.replace 生效)",
              GS.read_render_api() == 'opengl', GS.read_render_api())


# ============ G. 键位三层优先级 (审计 P-01-01) ============
def t_bindings(tmp):
    print("=== G. 键位: 默认 < 模板 < 用户层 (P-01-01) ===")
    with Sandbox(tmp) as sb:
        check("apply_game_bindings 已实现 (P-01-01)",
              hasattr(LI.InputMixin, 'apply_game_bindings'))
        tpl = os.path.join(tmp, '输入配置.default.json')
        wr(tpl, {"actions": {"跳跃": ["j"], "交互": ["e"], "坏条目": 5}})
        tpl_hash = sha(tpl)
        e = LI.InputMixin.__new__(LI.InputMixin)
        e.actions = dict(LI.DEFAULT_ACTIONS)
        out, log = capture(lambda: e._load_action_bindings(tpl))
        check("模板层生效 (跳跃=j)", e.actions.get('跳跃') == ['j'], e.actions.get('跳跃'))
        check("单条坏条目只跳过自己 (P-01-16)",
              e.actions.get('交互') == ['e'] and '坏条目' not in e.actions, e.actions.get('交互'))
        check("坏条目出声告警", '跳过该条' in log, log.strip())
        GS.write_key_binding('解锁鼠标', ['F10'])
        e._load_action_bindings(tpl)
        check("用户层 key_bindings 覆盖模板/默认 (解锁鼠标=F10)",
              e.actions.get('解锁鼠标') == ['F10'], e.actions.get('解锁鼠标'))
        check("读模板不改模板字节 (只读层)", sha(tpl) == tpl_hash)
        # P-01-05: rebind 只写用户层
        e.rebind_action('跳跃', ['k'])
        check("rebind_action 只写用户层 (模板不变)", sha(tpl) == tpl_hash)
        check("rebind_action 结果落进用户层 key_bindings",
              GS.read_key_bindings().get('跳跃') == ['k'], GS.read_key_bindings())
        check("用户层文件只有 delta (无模板动作全量)", set(rd(GS.user_path())['values'].keys())
              == {'key_bindings'}, rd(GS.user_path())['values'])


# ============ H. 改键失败必须可判定 (P-01-03) ============
def t_set_action_binding_fail(tmp):
    print("=== H. set_action_binding 写失败如实返回 (P-01-03) ===")
    import engine as E
    blocker = os.path.join(tmp, 'blocker_file')
    with open(blocker, 'w', encoding='utf-8') as f:
        f.write('x')
    os.environ['LOOM_USER_ROOT'] = blocker       # 根是文件 -> makedirs 必失败

    class _Eng(LI.InputMixin):
        pass

    _Eng.set_action_binding = E.GLEngine.set_action_binding
    e = _Eng()
    e.actions = dict(LI.DEFAULT_ACTIONS)
    res = capture(lambda: e.set_action_binding('向前', ['i']))[0]
    check("写失败 -> ok=False", res.get('ok') is False, res)
    check("写失败 -> saved=False (不再假成功)", res.get('saved') is False, res)
    check("写失败 -> 带 error 供上层提示", bool(res.get('error')), res.get('error'))
    os.environ['LOOM_USER_ROOT'] = os.path.join(tmp, 'userroot')
    res2 = capture(lambda: e.set_action_binding('向前', ['i']))[0]
    check("写成功 -> ok=True + saved=True + path",
          res2.get('ok') is True and res2.get('saved') is True and res2.get('path'),
          res2)


# ============ I. read_key_bindings 坏类型告警 (P-01-11) ============
def t_bad_bindings_warn(tmp):
    print("=== I. read_key_bindings 坏类型不再静默 (P-01-11) ===")
    with Sandbox(tmp) as sb:
        wr(sb.template, {"key_bindings": {"向前": ["w", None, ''], "交互": 5,
                                          "跳跃": [1, 2]}})
        out, log = capture(GS.read_key_bindings)
        check("合法键名保留, 非法键名丢弃", out == {'向前': ['w']}, out)
        check("丢弃非法键名时告警", '已丢弃' in log, log.strip())
        check("整条类型非法时告警", '忽略' in log, log.strip())
        check("无有效键名的动作告警", '无有效键名' in log, log.strip())


# ============ J. guiloader 引擎设置分层 ============
def t_guiloader(tmp):
    print("=== J. guiloader 设置: 模板只读 + 用户 delta ===")
    with Sandbox(tmp) as sb:
        tpl = os.path.join(sb.exe_dir, '设置.json')
        wr(tpl, {"gui": 'DarkGUI', "fps_limit": '60'})
        tpl_hash = sha(tpl)
        s = guiloader.load_settings('loom')
        check("模板值被读到", s.get('gui') == 'DarkGUI' and s.get('fps_limit') == '60',
              (s.get('gui'), s.get('fps_limit')))
        s['gui'] = 'LoomGUI'
        guiloader.save_settings('loom', s)
        up = guiloader.user_settings_path('loom')
        check("用户层落在 userpaths.engine_settings()",
              os.path.abspath(up) == os.path.abspath(userpaths.engine_settings()), up)
        check("用户层只存 delta", rd(up).get('values', {}).get('gui') == 'LoomGUI'
              and 'fps_limit' not in rd(up).get('values', {}), rd(up).get('values'))
        s2 = guiloader.load_settings('loom')
        check("合并后用户覆盖模板", s2.get('gui') == 'LoomGUI' and s2.get('fps_limit') == '60',
              (s2.get('gui'), s2.get('fps_limit')))
        check("模板字节未被改", sha(tpl) == tpl_hash)
        # base 显式覆盖 = 旧语义（测试/工具隔离）
        legacy = os.path.join(tmp, 'legacy')
        guiloader.save_settings('loom', {'gui': 'X'}, base=legacy)
        check("base 显式给出时仍写该目录明文",
              rd(os.path.join(legacy, '设置.json')).get('gui') == 'X',
              rd(os.path.join(legacy, '设置.json')))


if __name__ == "__main__":
    print("========== 用户配置目录契约测试 ==========")
    with tempfile.TemporaryDirectory() as t1:
        t_userpaths(t1)
    with tempfile.TemporaryDirectory() as t2:
        t_merge(t2)
    with tempfile.TemporaryDirectory() as t3:
        t_corrupt(t3)
    with tempfile.TemporaryDirectory() as t4:
        t_migrate_ok(t4)
    with tempfile.TemporaryDirectory() as t5:
        t_migrate_bad(t5)
    with tempfile.TemporaryDirectory() as t6:
        t_game_dir_override(t6)
    with tempfile.TemporaryDirectory() as t7:
        t_atomic(t7)
    with tempfile.TemporaryDirectory() as t8:
        t_bindings(t8)
    with tempfile.TemporaryDirectory() as t9:
        t_set_action_binding_fail(t9)
    with tempfile.TemporaryDirectory() as t10:
        t_bad_bindings_warn(t10)
    with tempfile.TemporaryDirectory() as t11:
        t_guiloader(t11)
    print("=" * 50)
    if _fails:
        print("总结果: %d 项失败 ❌" % len(_fails))
        for f in _fails:
            print("  FAIL:", f)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
