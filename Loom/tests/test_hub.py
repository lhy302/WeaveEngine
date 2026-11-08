# -*- coding: utf-8 -*-

"""
test_hub.py — LoomHub 项目管理器核心逻辑测试 (hub_config / hub_install), 全无头.
不弹窗口/不启动解释器/不改真实配置 (全部用临时目录 + monkeypatch 模块常量).
"""

# 2026-11-06 P-02 修复: Windows 控制台默认 GBK, 末尾 print 的 ✅/❌/≤ 等字符会抛
# UnicodeEncodeError, 让"测试通过"被记录成 exit=1 的假失败 (48/51 曾被误判)。
# 统一把 stdout/stderr 切到 UTF-8(replace), 失败信号重新只由断言决定。
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-11-06 失败退出码闸门 (复核 A 指出: 54 个测试里仅 18 个有 sys.exit(1),
# 其余 FAIL 也 exit 0 -> run_all 假绿, 失败被静默吞掉)。
# 做法: 包一层 stdout, 出现以 "FAIL" 开头的行就在进程退出时把状态码改成 1。
# 只在真出现 FAIL 时才改码, 全 PASS 的测试行为完全不变。
import atexit as _atexit_gate
import os as _os_gate
import sys as _sys_gate


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


import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PM_DIR = os.path.join(os.path.dirname(HERE), '..', 'LoomHub')   # LoomHub 源码目录
sys.path.insert(0, os.path.dirname(HERE))            # Loom\
sys.path.insert(0, PM_DIR)

import hub_config as cfg
import hub_install as inst

# ---- 2026-08-27 文件级隔离修复 (此前污染事故根因) ----
# 历史版本用例把发现/保存写进了真实 LoomHub\interpreters.json (每次全量
# 回归 +N 条 %TEMP% 引擎条目)。启动即把两个配置文件指针重定向到本测试
# 进程的临时目录 —— 任何用例 (含未逐用例重定向的) 都不会再碰真台账.
_TEST_CFG_DIR = tempfile.mkdtemp(prefix='loomhub_cfg_test_')
cfg.INTERPRETERS_FILE = os.path.join(_TEST_CFG_DIR, 'interpreters.json')
cfg.PROJECTS_FILE = os.path.join(_TEST_CFG_DIR, 'projects.json')
# 2026-11-08 第 5b 批: Hub 设置/台账已迁到用户目录（%LOCALAPPDATA%\Loom\hub），
# 测试必须整体重定向到临时根，否则会把开发机真实用户配置改脏。
os.environ.setdefault('LOOM_USER_ROOT', _TEST_CFG_DIR)

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _make_interp(root, version, kind='py', name="Loom"):
    """在 <root>/<version>/ 造一个解释器 (解释器.json + 主程序), 返回目录."""
    d = os.path.join(root, version)
    os.makedirs(d, exist_ok=True)
    main = "%s.py" % name if kind == 'py' else "%s.exe" % name
    with open(os.path.join(d, cfg.META_NAME), 'w', encoding='utf-8') as f:
        import json
        json.dump({"name": name, "version": version,
                   "main": main if kind == 'py' else None,
                   "main_exe": main if kind == 'exe' else None,
                   "python_version": "3.12.10"}, f, ensure_ascii=False)
    open(os.path.join(d, main), 'w').close()
    return d


# ---------------- 解释器发现 / 扫描 ----------------
def t_discover():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_interp(tmp, "1.2.3", 'py')
        info = cfg.discover_interpreter(d)
        check("发现 .py 解释器 (name/version/kind)", info is not None
              and info['name'] == "Loom" and info['version'] == "1.2.3"
              and info['kind'] == 'py', info)
        check(".py 主程序路径存在", info and os.path.isfile(info['path']))
        d2 = _make_interp(tmp, "2.0.0", 'exe')
        info2 = cfg.discover_interpreter(d2)
        check("发现 .exe 解释器 (kind=exe)", info2 is not None and info2['kind'] == 'exe',
              info2)
        # 无元数据目录
        empty = os.path.join(tmp, "no_meta")
        os.makedirs(empty)
        check("无元数据目录返回 None", cfg.discover_interpreter(empty) is None)
        # 元数据在但主程序缺失
        d3 = os.path.join(tmp, "3.0.0")
        os.makedirs(d3)
        import json
        with open(os.path.join(d3, cfg.META_NAME), 'w', encoding='utf-8') as f:
            json.dump({"name": "Loom", "version": "3.0.0", "main": "Loom.py"}, f)
        check("主程序缺失视为未完成安装 (None)", cfg.discover_interpreter(d3) is None)
        # 2026-08-20 加固 (Qoder 报告低危5): 主程序名/版本号格式白名单
        d4 = os.path.join(tmp, "4.0.0")
        os.makedirs(d4)
        with open(os.path.join(d4, cfg.META_NAME), 'w', encoding='utf-8') as f:
            json.dump({"name": "Loom", "version": "4.0.0",
                       "main": "..\\..\\evil.py", "main_exe": ""}, f)
        check("恶意 main 名 (路径穿越) 拒绝登记",
              cfg.discover_interpreter(d4) is None)
        d5 = os.path.join(tmp, "5.0.0")
        os.makedirs(d5)
        with open(os.path.join(d5, cfg.META_NAME), 'w', encoding='utf-8') as f:
            json.dump({"name": "Loom", "version": "not-a-version",
                       "main": "Loom.py"}, f)
        with open(os.path.join(d5, "Loom.py"), 'w', encoding='utf-8') as f:
            f.write("print('x')")
        check("非法版本号拒绝登记", cfg.discover_interpreter(d5) is None)
        # 2026-08-22 元数据合同 (第九节): validate_meta 发版自检独立入口,
        # 与导入/扫描同判. 关键: 版本号白名单只查格式不查大小, 大版本兼容.
        check("validate_meta 合法元数据 -> None",
              cfg.validate_meta({"name": "Loom", "version": "1.0.0",
                                 "main": "Loom.py"}) is None)
        check("validate_meta 超大版本号 (9999.9999.9999) 合法",
              cfg.validate_meta({"name": "Loom", "version": "9999.9999.9999",
                                 "main_exe": "Loom.exe"}) is None)
        check("validate_meta 版本号 2.5 (缺第三段) 拒绝",
              isinstance(cfg.validate_meta({"version": "2.5",
                                            "main": "Loom.py"}), str))
        check("validate_meta 版本号 '编译版' 拒绝 (2026-08-22 事故回归)",
              isinstance(cfg.validate_meta({"version": "编译版",
                                            "main": "Loom.py"}), str))
        check("validate_meta 恶意 main (路径穿越) 拒绝",
              isinstance(cfg.validate_meta({"version": "1.0.0",
                                            "main": "..\\evil.py"}), str))
        check("validate_meta main/main_exe 双空拒绝",
              isinstance(cfg.validate_meta({"version": "1.0.0"}), str))
        check("validate_meta 非 dict 拒绝",
              isinstance(cfg.validate_meta("{}"), str))
        # 版本数值巨大 + 排序 (用户"旧 hub 用新版引擎"场景端到端)
        d_big = _make_interp(tmp, "10.20.30", 'exe')
        check("大版本号 discover 正常",
              cfg.discover_interpreter(d_big) is not None
              and cfg.discover_interpreter(d_big)['version'] == "10.20.30")


def t_scan_install_root():
    with tempfile.TemporaryDirectory() as tmp:
        _make_interp(tmp, "1.0.0", 'py')
        _make_interp(tmp, "2.0.0", 'exe')
        os.makedirs(os.path.join(tmp, "not_a_version"))   # 无元数据目录, 应跳过
        found = cfg.scan_install_root(tmp)
        check("扫描到 2 个解释器版本", len(found) == 2, found)
        check("版本升序 (1.0.0 < 2.0.0)",
              [x['version'] for x in found] == ["1.0.0", "2.0.0"],
              [x['version'] for x in found])
        check("版本排序数值正确", [x['version'] for x in found][-1] == "2.0.0")
    check("空安装根返回 []", cfg.scan_install_root(os.path.join(
        tempfile.gettempdir(), "_loom_no_such_dir_xyz")) == [])


def t_beta_version():
    """2026-08-22 合同第九节: 解释器 beta 版本 (x.y.z.betaN) 支持:
    校验放行 / 排序 beta<正式、betaN 递进 / discover / zip 安装放行."""
    check("beta 版本 validate_meta 放行",
          cfg.validate_meta({"version": "1.0.0.beta1", "main": "Loom.py"}) is None)
    check("beta 号多位数合法 (1.0.0.beta10)",
          cfg.validate_meta({"version": "1.0.0.beta10", "main": "Loom.py"}) is None)
    check("beta 缺数字拒 (1.0.0.beta)",
          isinstance(cfg.validate_meta({"version": "1.0.0.beta",
                                        "main": "Loom.py"}), str))
    check("beta 粘连拒 (1.0.0beta1)",
          isinstance(cfg.validate_meta({"version": "1.0.0beta1",
                                        "main": "Loom.py"}), str))
    check("排序 beta1 < beta2 < 正式版",
          cfg._version_key("1.0.0.beta1") < cfg._version_key("1.0.0.beta2")
          < cfg._version_key("1.0.0"),
          str((cfg._version_key("1.0.0.beta1"), cfg._version_key("1.0.0"))))
    check("排序 1.1.0.beta1 < 1.2.0 (主版本段优先)",
          cfg._version_key("1.1.0.beta1") < cfg._version_key("1.2.0"))
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_interp(tmp, "1.0.0.beta1", 'exe')
        info = cfg.discover_interpreter(d)
        check("beta 解释器 discover 正常 (kind=exe)",
              info is not None and info['version'] == "1.0.0.beta1"
              and info['kind'] == 'exe', info)
        # 排序端到端: beta1 < 正式 1.0.0
        _make_interp(tmp, "1.0.0", 'exe')
        found = cfg.scan_install_root(tmp)
        check("scan 排序 beta1 在 1.0.0 前",
              [x['version'] for x in found] == ["1.0.0.beta1", "1.0.0"],
              [x['version'] for x in found])
        # zip 安装 beta 放行
        import zipfile as zf
        import hub_install
        zip_p = os.path.join(tmp, "beta.zip")
        with zf.ZipFile(zip_p, 'w') as z:
            z.writestr(cfg.META_NAME, '{"name": "Loom", "version": "1.0.0.beta1",'
                                     ' "main_exe": "Loom.exe"}')
            z.writestr("Loom.exe", "x")
        try:
            tgt = hub_install.install_from_zip(zip_p, "1.0.0.beta1",
                                               os.path.join(tmp, "root"))
            check("zip 安装 beta 版本成功", os.path.isdir(tgt), tgt)
        except hub_install.InstallError as e:
            check("zip 安装 beta 版本成功", False, str(e))
        # zip 安装非法版本仍拒
        try:
            hub_install.install_from_zip(zip_p, "1.2.3（中文）",
                                         os.path.join(tmp, "root2"))
            check("zip 安装非法版本拒绝", False)
        except hub_install.InstallError as e:
            check("zip 安装非法版本拒绝", True, str(e))


# ---------------- 配置读写 (interpreters / projects) ----------------
def t_config_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cfg.INTERPRETERS_FILE = os.path.join(tmp, "interpreters.json")
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        cfg.save_interpreters([{"name": "Loom", "version": "1.0.0", "kind": "py",
                                "dir": "D:\\x", "main": "Loom.py", "path": "D:\\x\\Loom.py"}])
        lst = cfg.load_interpreters()
        check("interpreters round-trip", len(lst) == 1 and lst[0]['version'] == "1.0.0")
        cfg.save_projects([{"name": "我的游戏", "scene": "D:\\s\\a.json"}])
        prj = cfg.load_projects()
        check("projects round-trip", len(prj) == 1 and prj[0]['name'] == "我的游戏")
        # 损坏文件容错
        with open(cfg.INTERPRETERS_FILE, 'w') as f:
            f.write("{broken")
        check("坏配置容错返回 []", cfg.load_interpreters() == [])
        # 恢复文件级隔离指针 (防止后续用例把全局指向已删除的 tmp)
        cfg.INTERPRETERS_FILE = os.path.join(_TEST_CFG_DIR, 'interpreters.json')
        cfg.PROJECTS_FILE = os.path.join(_TEST_CFG_DIR, 'projects.json')


def t_add_default_remove():
    with tempfile.TemporaryDirectory() as tmp:
        cfg.INTERPRETERS_FILE = os.path.join(tmp, "interpreters.json")
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        a = {"name": "Loom", "version": "1.0.0", "kind": "py", "dir": "D:\\a",
             "main": "Loom.py", "path": "D:\\a\\Loom.py"}
        b = {"name": "Loom", "version": "2.0.0", "kind": "exe", "dir": "D:\\b",
             "main": "Loom.exe", "path": "D:\\b\\Loom.exe"}
        cfg.add_interpreter(a)
        cfg.add_interpreter(b)
        cfg.set_default_interpreter(b)
        check("默认解释器 = b (2.0.0)", cfg.default_interpreter()['version'] == "2.0.0",
              cfg.default_interpreter())
        check("同 dir 覆盖不重复", len(cfg.load_interpreters()) == 2)
        cfg.add_interpreter(dict(a))   # 同 dir 再加
        check("同 dir 再登记仍 2 条", len(cfg.load_interpreters()) == 2)
        cfg.remove_interpreter(a)
        check("移除 a 后剩 1 条", len(cfg.load_interpreters()) == 1)
        check("移除的是 b", cfg.load_interpreters()[0]['version'] == "2.0.0")
        cfg.set_default_interpreter(None)   # 清空默认标记
        d = cfg.default_interpreter()
        check("无显式默认时取列表第一个", d is not None and d['version'] == "2.0.0", d)


def t_projects_crud():
    with tempfile.TemporaryDirectory() as tmp:
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        cfg.add_project("游戏A", "D:\\s\\a.json")
        cfg.add_project("游戏B", "D:\\s\\b.json", version="1.0.0")
        cfg.add_project("游戏A", "D:\\s\\a.json")   # 同 scene 覆盖
        lst = cfg.load_projects()
        check("项目登记 (覆盖不重复)", len(lst) == 2)
        cfg.remove_project("D:\\s\\a.json")
        check("移除项目后剩 1", len(cfg.load_projects()) == 1
              and cfg.load_projects()[0]['name'] == "游戏B")


# ---------------- 启动命令 ----------------
def _open_project_cmd(interp_info, scene):
    """把 HubController.open_project 的命令构造真跑一遍（Popen 换成捕获桩）。

    D3=A 之后 "--agent" 由调用方追加，这条断言盯的就是调用方那一步：恰好一个。
    """
    import hub_controller as hc
    captured = {}
    old_pop = hc.subprocess.Popen
    old_interp = cfg.default_interpreter
    hc.subprocess.Popen = lambda cmd, **kw: captured.setdefault('cmd', list(cmd))
    cfg.default_interpreter = lambda: interp_info
    try:
        ctrl = hc.HubController.__new__(hc.HubController)
        ctrl.msg = ""
        ctrl.msg_level = 'ok'
        ctrl.set_msg = lambda m, lvl='ok': setattr(ctrl, 'msg', m)
        ctrl.open_project({'scene': scene})
    finally:
        hc.subprocess.Popen = old_pop
        cfg.default_interpreter = old_interp
    return captured.get('cmd') or []


def t_launch_command(monkey_env=None):
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.default_python
        # P-08c 修复 (2026-11-06): hub_config.default_python 现签名
        # (engine_dir=None), 桩 lambda 必须接受该关键字参数
        cfg.default_python = lambda engine_dir=None: "python"
        try:
            py = {"name": "Loom", "version": "1.0.0", "kind": "py",
                  "path": os.path.join(tmp, "Loom.py")}
            exe = {"name": "Loom", "version": "1.0.0", "kind": "exe",
                   "path": os.path.join(tmp, "Loom.exe")}
            scene_file = os.path.join(tmp, "a.json")
            open(scene_file, 'w', encoding='utf-8').write("{}")
            scene = scene_file
            # 2026-11-08 D3=A 人类裁决: build_launch_command 恢复**纯拼装**，
            # --agent 由调用方(hub_controller.open_project)追加。因此这里仍断言
            # "命令里没有 --agent"，同时下面单独断言调用方恰好加一次。
            check(".py 用系统默认 python + --open",
                  cfg.build_launch_command(py, scene, 'open') ==
                  ["python", py['path'], "--open", scene])
            check(".py 播放模式 --run",
                  cfg.build_launch_command(py, scene, 'run') ==
                  ["python", py['path'], "--run", scene])
            check(".py 纯启动无场景参数",
                  cfg.build_launch_command(py, None) == ["python", py['path']])
            check(".exe 直接运行 + --open",
                  cfg.build_launch_command(exe, scene, 'open') ==
                  [exe['path'], "--open", scene])
            check("纯拼装: 任何 mode 都不自带 --agent",
                  all('--agent' not in cmd for cmd in (
                      cfg.build_launch_command(py, scene, 'open'),
                      cfg.build_launch_command(py, scene, 'run'),
                      cfg.build_launch_command(py, None),
                      cfg.build_launch_command(exe, scene, 'open'))),
                  [cfg.build_launch_command(py, scene, 'open')])
            check("打开项目: 调用方恰好追加一个 --agent (D3=A)",
                  _open_project_cmd(py, scene).count('--agent') == 1,
                  _open_project_cmd(py, scene))
            check("default_python 返回字符串",
                  isinstance(cfg.default_python(), str))
        finally:
            cfg.default_python = old


def t_hub_settings_userdir():
    """契约 2026-11-08 §2/§4/§7: Hub 设置落用户目录、只存 delta、模板只读。"""
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get('LOOM_USER_ROOT')
        os.environ['LOOM_USER_ROOT'] = tmp
        try:
            tpl = cfg.hub_settings_template()
            tpl_before = open(tpl, 'rb').read() if os.path.isfile(tpl) else None
            p = cfg.hub_settings_file()
            check("hub 设置路径落在用户根下（不再写安装目录）",
                  os.path.abspath(p).startswith(os.path.abspath(tmp)), p)
            merged = cfg.load_hub_settings()
            check("读设置 = 默认+模板合并（gui/open_py 都有）",
                  'gui' in merged and 'open_py' in merged, merged)
            cfg.save_hub_settings(dict(merged, open_py=False))
            raw = _json.load(open(p, encoding='utf-8'))
            check("用户层是新格式 {schema,values}",
                  raw.get('schema') == 1 and isinstance(raw.get('values'), dict), raw)
            check("只写 delta: 改过的键进 values",
                  raw['values'].get('open_py') is False, raw.get('values'))
            check("模板层负责的键不进 delta",
                  'gui' not in raw['values'], raw.get('values'))
            check("读回: 用户 delta 覆盖模板层",
                  cfg.load_hub_settings().get('open_py') is False)
            tpl_after = open(tpl, 'rb').read() if os.path.isfile(tpl) else None
            check("模板文件字节未变（运行时永不写模板）", tpl_before == tpl_after)
        finally:
            if old is None:
                os.environ.pop('LOOM_USER_ROOT', None)
            else:
                os.environ['LOOM_USER_ROOT'] = old
        check("撤掉 LOOM_USER_ROOT 后路径回到系统用户目录",
              not os.path.abspath(cfg.hub_settings_file()).startswith(
                  os.path.abspath(tmp)), cfg.hub_settings_file())


# ---------------- 用户目录（2026-11-08 契约 §2/§4/§7；第 5b 批） ----------------
def t_hub_settings_readonly_program_dir():
    """验收 1: 程序目录（模板层）不可写时，Hub 仍能把设置存进用户层。"""
    import stat
    with tempfile.TemporaryDirectory() as prog, tempfile.TemporaryDirectory() as user:
        tpl = os.path.join(prog, '设置.json')
        with open(tpl, 'w', encoding='utf-8') as f:
            f.write('{"gui": "TkHubView", "open_py": true}')
        os.chmod(tpl, stat.S_IREAD)          # 模拟"程序目录只读"
        old_tpl = cfg.hub_settings_template
        old_root = os.environ.get('LOOM_USER_ROOT')
        cfg.hub_settings_template = lambda: tpl
        os.environ['LOOM_USER_ROOT'] = user
        try:
            before = sorted(os.listdir(prog))
            cfg.save_hub_settings({'gui': 'TkHubView', 'open_py': False})
            upath = cfg.hub_settings_file()
            check("程序目录只读时保存不抛异常且落用户层", os.path.isfile(upath), upath)
            check("用户层路径在用户根下",
                  os.path.abspath(upath).startswith(os.path.abspath(user)), upath)
            raw = json.load(open(upath, encoding='utf-8'))
            check("只写 delta（只有改过的 open_py）",
                  raw.get('values') == {'open_py': False}, raw.get('values'))
            check("只读模板内容未被改写",
                  open(tpl, encoding='utf-8').read() == '{"gui": "TkHubView", "open_py": true}')
            check("程序目录没有多出/少掉文件",
                  sorted(os.listdir(prog)) == before, os.listdir(prog))
            check("读回生效（用户 delta 覆盖模板）",
                  cfg.load_hub_settings().get('open_py') is False)
        finally:
            cfg.hub_settings_template = old_tpl
            if old_root is None:
                os.environ.pop('LOOM_USER_ROOT', None)
            else:
                os.environ['LOOM_USER_ROOT'] = old_root
            try:
                os.chmod(tpl, stat.S_IWRITE)
            except OSError:
                pass


def t_hub_settings_write_failure_raises():
    """契约 §7: 用户层写失败必须上抛，不得静默丢设置。"""
    import hub_userpaths
    with tempfile.TemporaryDirectory() as tmp:
        blocker = os.path.join(tmp, 'blocker')
        open(blocker, 'w').close()           # 用"文件"占住路径 -> makedirs 必失败
        old_root_fn = hub_userpaths.user_root
        old_root = os.environ.get('LOOM_USER_ROOT')
        os.environ.pop('LOOM_USER_ROOT', None)
        hub_userpaths.user_root = lambda: os.path.join(blocker, 'root')
        try:
            raised = False
            try:
                cfg.save_hub_settings({'open_py': False})
            except Exception:
                raised = True
            check("用户层写失败 -> 上抛（不静默）", raised)
        finally:
            hub_userpaths.user_root = old_root_fn
            if old_root is not None:
                os.environ['LOOM_USER_ROOT'] = old_root


def t_hub_ledger_migration():
    """验收 2: 程序目录旧台账首次运行迁移进用户目录（条目数一致、旧文件不动）。"""
    with tempfile.TemporaryDirectory() as prog, tempfile.TemporaryDirectory() as user:
        leg_i = os.path.join(prog, 'interpreters.json')
        leg_p = os.path.join(prog, 'projects.json')
        interps = [{"name": "Loom", "version": "0.1.0.beta4", "kind": "py",
                    "dir": "D:/a", "main": "Loom.py", "path": "D:/a/Loom.py"},
                   {"name": "Loom", "version": "0.1.0.beta3", "kind": "py",
                    "dir": "D:/b", "main": "Loom.py", "path": "D:/b/Loom.py"}]
        projects = [{"name": "游戏A", "scene": "D:/s/a.json"}]
        with open(leg_i, 'w', encoding='utf-8') as f:
            json.dump({"interpreters": interps}, f, ensure_ascii=False)
        with open(leg_p, 'w', encoding='utf-8') as f:
            json.dump({"projects": projects}, f, ensure_ascii=False)
        before_i = open(leg_i, 'rb').read()
        before_p = open(leg_p, 'rb').read()
        old = (cfg.INTERPRETERS_FILE, cfg.PROJECTS_FILE,
               cfg.LEGACY_INTERPRETERS_FILE, cfg.LEGACY_PROJECTS_FILE,
               os.environ.get('LOOM_USER_ROOT'))
        os.environ['LOOM_USER_ROOT'] = user
        cfg.LEGACY_INTERPRETERS_FILE = leg_i
        cfg.LEGACY_PROJECTS_FILE = leg_p
        cfg.INTERPRETERS_FILE = cfg.default_interpreters_file()
        cfg.PROJECTS_FILE = cfg.default_projects_file()
        try:
            check("解释器台账默认落点改到用户目录",
                  os.path.abspath(cfg.INTERPRETERS_FILE).startswith(os.path.abspath(user)),
                  cfg.INTERPRETERS_FILE)
            lst = cfg.load_interpreters()
            check("首次运行迁移解释器台账（条目数一致）", len(lst) == 2, lst)
            check("用户层台账文件已创建", os.path.isfile(cfg.INTERPRETERS_FILE),
                  cfg.INTERPRETERS_FILE)
            prj = cfg.load_projects()
            check("首次运行迁移项目台账（条目数一致）", len(prj) == 1, prj)
            check("旧台账文件保持不动（不删用户文件）",
                  open(leg_i, 'rb').read() == before_i
                  and open(leg_p, 'rb').read() == before_p)
            cfg.add_interpreter({"name": "Loom", "version": "0.1.0.beta9", "kind": "py",
                                 "dir": "D:/n", "main": "Loom.py", "path": "D:/n/Loom.py"})
            check("迁移后可继续登记且不丢已迁移条目",
                  len(cfg.load_interpreters()) == 3, cfg.load_interpreters())
            check("用户层文件是完整台账（不是 delta）",
                  len(json.load(open(cfg.INTERPRETERS_FILE,
                                     encoding='utf-8'))['interpreters']) == 3)
        finally:
            (cfg.INTERPRETERS_FILE, cfg.PROJECTS_FILE,
             cfg.LEGACY_INTERPRETERS_FILE, cfg.LEGACY_PROJECTS_FILE,
             old_root) = old
            if old_root is None:
                os.environ.pop('LOOM_USER_ROOT', None)
            else:
                os.environ['LOOM_USER_ROOT'] = old_root


def t_guiloader_hub_layer():
    """LoomHub/guiloader 对 loomhub 已委派到用户层；base= 保持旧语义（测试隔离）。"""
    import guiloader
    with tempfile.TemporaryDirectory() as user, tempfile.TemporaryDirectory() as base_dir:
        old_root = os.environ.get('LOOM_USER_ROOT')
        os.environ['LOOM_USER_ROOT'] = user
        try:
            s = guiloader.load_settings('loomhub')
            check("guiloader 读 Hub 设置带回默认键",
                  bool(s.get('gui')) and 'open_py' in s, s)
            guiloader.save_settings('loomhub', dict(s, open_py=False))
            upath = os.path.join(user, 'hub', 'settings.json')
            check("guiloader 写 Hub 设置落用户层（不再写程序目录）",
                  os.path.isfile(upath), upath)
            check("guiloader 读回用户 delta 生效",
                  guiloader.load_settings('loomhub').get('open_py') is False)
            guiloader.save_settings('loomhub', {'gui': 'TkHubView', 'open_py': False},
                                    base=base_dir)
            check("base= 保持旧语义（整份写该目录）",
                  os.path.isfile(os.path.join(base_dir, '设置.json')))
            check("base= 读回一致",
                  guiloader.load_settings('loomhub', base=base_dir).get('open_py') is False)
        finally:
            if old_root is None:
                os.environ.pop('LOOM_USER_ROOT', None)
            else:
                os.environ['LOOM_USER_ROOT'] = old_root


def t_python_version_error():
    check("python_version 对无效命令返回 None", cfg.python_version("__no_such_py__.exe") is None)


# ---------------- zip 安装 ----------------
def _make_zip(zip_path, files, slip=False):
    """files: [(相对路径, 内容)]. slip=True 时加一个 ../ 越界项."""
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for rel, content in files:
            zf.writestr(rel, content)
        if slip:
            zf.writestr("../evil.txt", "boom")


def t_install_zip():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "install_root")
        zip_path = os.path.join(tmp, "Loom.zip")
        meta = json.dumps({"name": "Loom", "version": "0.9.0", "main": "Loom.py"})
        _make_zip(zip_path, [("Loom.py", "print('hi')"), (cfg.META_NAME, meta)])
        cfg.INTERPRETERS_FILE = os.path.join(tmp, "interpreters.json")
        target = inst.install_from_zip(zip_path, "0.9.0", root)
        check("zip 安装到 <根>/<版本号>", os.path.isdir(target)
              and target == os.path.join(root, "0.9.0"), target)
        check("安装后主程序存在", os.path.isfile(os.path.join(target, "Loom.py")))
        check("安装后已登记到配置", any(x['version'] == "0.9.0"
                                        for x in cfg.load_interpreters()))

        # zip 顶层包一层子目录
        zip2 = os.path.join(tmp, "Loom2.zip")
        _make_zip(zip2, [("inner/Loom.py", "print('hi')"),
                         ("inner/" + cfg.META_NAME, meta)])
        target2 = inst.install_from_zip(zip2, "0.9.1", root)
        check("zip 包内多一层目录也能识别", os.path.isfile(
            os.path.join(target2, cfg.META_NAME)))
        # 2026-08-20 加固 (Qoder 报告低危4): 版本号格式白名单 (防路径拼接越权)
        try:
            inst.install_from_zip(zip_path, "..\\..\\Desktop\\evil", root)
            check("非法版本号应被拒绝", False)
        except inst.InstallError:
            check("非法版本号抛 InstallError (x.y.z 白名单)", True)


def t_install_errors():
    with tempfile.TemporaryDirectory() as tmp:
        # 缺元数据
        zip_bad = os.path.join(tmp, "bad.zip")
        _make_zip(zip_bad, [("random.txt", "x")])
        try:
            inst.install_from_zip(zip_bad, "1.0.0", os.path.join(tmp, "r1"))
            check("缺元数据 zip 应抛错", False)
        except inst.InstallError:
            check("缺元数据 zip 抛 InstallError", True)
        # Zip Slip 防护
        zip_slip = os.path.join(tmp, "slip.zip")
        _make_zip(zip_slip, [("Loom.py", "x"), (cfg.META_NAME, "{}")], slip=True)
        try:
            inst.install_from_zip(zip_slip, "1.0.0", os.path.join(tmp, "r2"))
            check("Zip Slip 应被拒绝", False)
        except inst.InstallError:
            check("Zip Slip 抛 InstallError (越界路径拒绝)", True)
        # 2026-08-20 安全加固 (Qoder 报告低危2): 兄弟目录前缀边界
        # "../1.0.0evil/evil.py" 归一化后 startswith(".../1.0.0") 为 True,
        # 旧实现误放行写入 target 外相邻目录; 新实现按分隔符边界拒绝.
        zip_bro = os.path.join(tmp, "bro.zip")
        _make_zip(zip_bro, [("Loom.py", "x"), (cfg.META_NAME, "{}")])
        with zipfile.ZipFile(zip_bro, 'a') as zf:
            zf.writestr("../1.0.0evil/evil.py", "boom")
        try:
            inst.install_from_zip(zip_bro, "1.0.0", os.path.join(tmp, "r3"))
            check("兄弟目录前缀越界应被拒绝", False)
        except inst.InstallError:
            check("兄弟目录前缀越界抛 InstallError (分隔符边界)", True)
        # 不存在 zip
        try:
            inst.install_from_zip(os.path.join(tmp, "no.zip"), "1.0.0", os.path.join(tmp, "r3"))
            check("不存在 zip 应抛错", False)
        except inst.InstallError:
            check("不存在 zip 抛 InstallError", True)


def t_remote_interface():
    try:
        inst.RemoteDownloader().download("http://x", "D:\\x")
        check("远程下载接口目前不可用", False)
    except NotImplementedError:
        check("远程下载接口留空 (NotImplementedError)", True)


def t_new_project_scene():
    """新建项目: 生成 v8 空场景 (controller) + LoomHub GUI/tk 视图模块可导入 (冒烟)."""
    import importlib.util
    import hub_controller
    ctrl = hub_controller.HubController.__new__(hub_controller.HubController)
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "新项目_场景.json")
        ctrl.new_scene_file(p)
        data = cfg.load_json(p)
        check("新建项目生成 v8 空场景", data is not None and data.get('version') == 8
              and data.get('objects') == [] and data.get('lights') == [], data)
        check("空场景含 camera 字段", data is not None and 'camera' in data)
    for name, path in [("loomhub_gui", os.path.join(PM_DIR, "LoomHub.py")),
                       ("loomhub_tk", os.path.join(PM_DIR, "hub_view_tk.py"))]:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            check("%s 模块可导入" % name, True)
        except Exception as e:
            check("%s 模块可导入" % name, False, repr(e))


def t_save_dir_discover():
    """解释器保存目录 / 目录项目发现 (2026-08-12 文件夹式流程)."""
    with tempfile.TemporaryDirectory() as tmp:
        # interpreter_save_dir: 有解释器 -> <dir>/Projects; 无解释器 -> None
        # 2026-11-06 契约同步: 2026-10-19 用户拍板 B2 把默认项目目录从
        # "保存" 改名为 "Projects" (Unity 习惯), 旧目录仅作扫描兼容。
        # 原断言写死 "保存" 已随契约演化过期。
        interp = {"name": "Loom", "version": "1.0.0", "kind": "py",
                  "dir": os.path.join(tmp, "LoomI")}
        check("interpreter_save_dir = <dir>/Projects",
              cfg.interpreter_save_dir(interp) == os.path.join(tmp, "LoomI", "Projects"))
        check("interpreter_legacy_save_dir = <dir>/保存 (兼容旧场景)",
              cfg.interpreter_legacy_save_dir(interp) == os.path.join(tmp, "LoomI", "保存"))
        old_projects = cfg.PROJECTS_FILE
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        try:
            check("无默认解释器 interpreter_save_dir None",
                  cfg.interpreter_save_dir() is None)
        finally:
            cfg.PROJECTS_FILE = old_projects

        # discover_project
        d = os.path.join(tmp, "MyProject")
        os.makedirs(d)
        check("discover 无场景目录 -> None", cfg.discover_project(d) is None)
        scene = os.path.join(d, "MyProject_场景.json")
        open(scene, 'w').write("{}")
        check("discover 命中 <目录名>_场景.json",
              cfg.discover_project(d) == ("MyProject", scene))
        d2 = os.path.join(tmp, "Other")
        os.makedirs(d2)
        open(os.path.join(d2, "b.json"), 'w').write("{}")
        check("discover 无命名场景取第一个 json",
              cfg.discover_project(d2) == ("b", os.path.join(d2, "b.json")))
        check("discover 不存在目录 None",
              cfg.discover_project(os.path.join(tmp, "nope")) is None)


def t_scan_save_dir():
    """扫描解释器保存目录: 场景文件登记为项目, <名>_场景 命名去后缀."""
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.PROJECTS_FILE
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        try:
            save = os.path.join(tmp, "保存")
            os.makedirs(save)
            open(os.path.join(save, "游戏A_场景.json"), 'w').write("{}")
            open(os.path.join(save, "游戏B.json"), 'w').write("{}")
            open(os.path.join(save, "note.txt"), 'w').write("x")   # 非 json 忽略
            found = cfg.scan_save_dir_projects(save)
            check("扫描登记 2 个场景", len(found) == 2, found)
            names = {n for n, _ in found}
            check("扫描项目名正确 (去 _场景 后缀)", names == {"游戏A", "游戏B"}, names)
            check("扫描已写入 projects.json", len(cfg.load_projects()) == 2)
            # 幂等: 再扫不重复
            cfg.scan_save_dir_projects(save)
            check("扫描幂等不重复", len(cfg.load_projects()) == 2)
            # 目录不存在 -> []
            check("扫描不存在目录 -> []",
                  cfg.scan_save_dir_projects(os.path.join(tmp, "nope")) == [])
        finally:
            cfg.PROJECTS_FILE = old


def t_new_project_flow():
    """新建项目完整流程 (controller, 文件式, 2026-08-12): 创建 <名>.json 场景文件 + 登记.
    不再输入项目名 (规避输入法问题), 项目名 = 场景文件名去扩展名."""
    import hub_controller
    ctrl = hub_controller.HubController.__new__(hub_controller.HubController)
    ctrl.msg = ""
    ctrl.msg_level = 'ok'
    ctrl.interpreters = []
    ctrl.projects = []
    ctrl.install_root = ""
    with tempfile.TemporaryDirectory() as tmp:
        old = cfg.PROJECTS_FILE
        cfg.PROJECTS_FILE = os.path.join(tmp, "projects.json")
        try:
            scene = os.path.join(tmp, "我的游戏.json")
            ctrl.do_new_project_file(scene)
            check("新建流程: 创建场景文件",
                  os.path.isfile(scene) and cfg.load_json(scene).get('version') == 8)
            check("新建流程: 登记到 projects.json",
                  any(p['name'] == "我的游戏" for p in cfg.load_projects()))
            check("新建流程: 登记场景路径正确",
                  any(p['scene'] == scene for p in cfg.load_projects()))
            check("新建流程: 消息更新", "已创建项目" in (ctrl.msg or ""))
            # 第二项目 (不同文件)
            scene2 = os.path.join(tmp, "Game2.json")
            ctrl.do_new_project_file(scene2)
            check("新建流程: 第二项目登记",
                  any(p['name'] == "Game2" and p['scene'] == scene2
                      for p in cfg.load_projects()))
            check("新建流程: 共 2 项目", len(cfg.load_projects()) == 2,
                  cfg.load_projects())
            # 默认场景名唯一 (保存目录已有 新项目.json 时递增)
            d = os.path.join(tmp, "保存")
            os.makedirs(d)
            open(os.path.join(d, "新项目.json"), 'w').write("{}")
            check("默认场景名: 空目录/不存在 -> 新项目",
                  ctrl.unique_scene_name(os.path.join(tmp, "空目录")) == "新项目")
            check("默认场景名: 有冲突 -> 新项目1",
                  ctrl.unique_scene_name(d) == "新项目1",
                  ctrl.unique_scene_name(d))
            # 导入 (文件夹式) 的核心发现逻辑: 未含场景的目录不可导入
            found = cfg.discover_project(os.path.join(tmp, "EmptyDir"))
            check("导入: 无场景目录不可导入", found is None)
        finally:
            cfg.PROJECTS_FILE = old


if __name__ == "__main__":
    print("========== LoomHub (hub_config / hub_install) 测试 ==========")
    t_discover()
    t_scan_install_root()
    t_beta_version()
    t_config_roundtrip()
    t_add_default_remove()
    t_projects_crud()
    t_launch_command()
    t_hub_settings_userdir()
    t_hub_settings_readonly_program_dir()
    t_hub_settings_write_failure_raises()
    t_hub_ledger_migration()
    t_guiloader_hub_layer()
    t_python_version_error()
    t_install_zip()
    t_install_errors()
    t_remote_interface()
    t_new_project_scene()
    t_save_dir_discover()
    t_scan_save_dir()
    t_new_project_flow()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
