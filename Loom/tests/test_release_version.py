# -*- coding: utf-8 -*-
"""
test_release_version.py — 打包/发布链的"版本一致性"定向断言 (2026-11-08 第 5 批 D1=A)

锁定的人类裁决: 正式发包前内部开发名**一律 0.1.0.beta4，不得改名**；
包名 = 包内元数据 = tag = Loom/解释器.json = release_github 缺省；
LoomHub 一律 0.1.2（版本.json = installer.iss = release_github 缺省；2026-11-08 因 Hub 配置体系改动而升版）。

对应审计项: P-05-06（--version 无白名单）、P-05-07（两个工具缺省版本互相矛盾）、
P-05-13/P-05-14（无版本单一事实源：源码元数据 / Hub 版本.json 从不被回写）。
本文件只读文件与常量，不打包、不联网、不写任何配置。
"""
import sys as _sys_utf8
try:
    _sys_utf8.stdout.reconfigure(encoding='utf-8', errors='replace')
    _sys_utf8.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 失败退出码闸门（与其余 test_*.py 同款，供 run_all 判定）
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)              # Loom/
REPO = os.path.dirname(ROOT)              # 仓库根
for _p in (REPO, os.path.join(REPO, 'tools'), os.path.join(REPO, 'LoomHub'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 断言"缺省值"，所以先把环境变量清掉（CI/本机可能设过）
for _k in ('LOOM_ENGINE_VERSION', 'LOOM_HUB_VERSION'):
    os.environ.pop(_k, None)

import package_engine as pe       # noqa: E402
import release_github as rg       # noqa: E402
import hub_config as hcfg         # noqa: E402
import package_hub as ph          # noqa: E402   (tools/package_hub.py: LoomHub 打包器)

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def t_engine_version_consistency():
    """Loom/解释器.json（打包工具缺省来源）== release_github 缺省 == 包名/tag 派生值。"""
    meta = _read_json(os.path.join(ROOT, '解释器.json'))
    src = str(meta.get('version'))
    check("源码元数据版本 = 0.1.0.beta4（D1 锁定，不得改名）",
          src == '0.1.0.beta4', src)
    check("package_engine.load_version() 缺省 = 源码元数据版本",
          pe.load_version() == src, pe.load_version())
    check("release_github 缺省引擎版本 = 源码元数据版本",
          rg.ENGINE_VERSION == src, rg.ENGINE_VERSION)
    check("zip 包名 = Loom-<version>.zip",
          os.path.basename(rg.engine_zip()) == 'Loom-%s.zip' % src,
          os.path.basename(rg.engine_zip()))
    check("release tag 由同一版本派生 (engine-v<version>)",
          'engine-v%s' % rg.ENGINE_VERSION == 'engine-v%s' % src,
          'engine-v%s' % rg.ENGINE_VERSION)
    check("包内元数据能过 LoomHub 判据 (validate_meta)",
          hcfg.validate_meta(meta, meta.get('version')) is None,
          hcfg.validate_meta(meta, meta.get('version')))


def t_hub_version_consistency():
    """LoomHub/版本.json == release_github 缺省 == installer.iss 的 #define。"""
    hub_ver = str(_read_json(os.path.join(REPO, 'LoomHub', '版本.json')).get('version'))
    check("LoomHub 版本.json = 0.1.2", hub_ver == '0.1.2', hub_ver)
    check("release_github 缺省 Hub 版本 = 版本.json",
          rg.HUB_VERSION == hub_ver, rg.HUB_VERSION)
    check("安装包名 = LoomHub-<version>-Setup.exe",
          os.path.basename(rg.hub_setup()) == 'LoomHub-%s-Setup.exe' % hub_ver,
          os.path.basename(rg.hub_setup()))
    iss = open(os.path.join(REPO, 'tools', 'installer.iss'), encoding='utf-8').read()
    line = [l for l in iss.splitlines() if l.strip().startswith('#define MyAppVersion')]
    check("installer.iss 里有 MyAppVersion 定义", len(line) == 1, line)
    if line:
        got = line[0].split('"')[1] if '"' in line[0] else ''
        check("installer.iss 版本 = 版本.json（否则安装器与发布物脱节）",
              got == hub_ver, got)


def t_version_env_crosscheck():
    """版本只有一个真源：环境变量只能"确认"，与真源不一致必须报错退出。

    独立验收实测过的漏洞：以前 LOOM_HUB_VERSION=9.9.9 时 release_github 用 9.9.9，
    而 package_hub 仍是 0.1.2，两条链静默分叉且无交叉校验。
    """
    import subprocess
    src_hub = ph.load_version()
    src_engine = pe.load_version()
    check("缺省: HUB_VERSION == LoomHub/版本.json",
          rg.HUB_VERSION == src_hub, (rg.HUB_VERSION, src_hub))
    check("缺省: ENGINE_VERSION == Loom/解释器.json",
          rg.ENGINE_VERSION == src_engine, (rg.ENGINE_VERSION, src_engine))
    old_h = os.environ.pop('LOOM_HUB_VERSION', None)
    old_e = os.environ.pop('LOOM_ENGINE_VERSION', None)
    try:
        check("无环境变量 -> resolve_version 返回真源",
              rg.resolve_version('LOOM_HUB_VERSION', src_hub, 'hub') == src_hub)
        os.environ['LOOM_HUB_VERSION'] = src_hub
        check("环境变量 == 真源 -> 通过（仅确认）",
              rg.resolve_version('LOOM_HUB_VERSION', src_hub, 'hub') == src_hub)
        os.environ['LOOM_HUB_VERSION'] = '9.9.9'
        raised = ''
        try:
            rg.resolve_version('LOOM_HUB_VERSION', src_hub, 'hub')
        except SystemExit as e:
            raised = str(e)
        check("LOOM_HUB_VERSION=9.9.9 != 真源 -> 报错退出（不再静默分叉）",
              '分叉' in raised, raised.splitlines()[0] if raised else '')
        os.environ['LOOM_ENGINE_VERSION'] = '9.9.9.beta1'
        raised2 = ''
        try:
            rg.resolve_version('LOOM_ENGINE_VERSION', src_engine, 'engine')
        except SystemExit as e:
            raised2 = str(e)
        check("引擎侧同理: LOOM_ENGINE_VERSION 分叉 -> 报错",
              '分叉' in raised2, raised2.splitlines()[0] if raised2 else '')
    finally:
        os.environ.pop('LOOM_HUB_VERSION', None)
        os.environ.pop('LOOM_ENGINE_VERSION', None)
        if old_h is not None:
            os.environ['LOOM_HUB_VERSION'] = old_h
        if old_e is not None:
            os.environ['LOOM_ENGINE_VERSION'] = old_e
    # 端到端: 子进程 import 时就因分叉退出非 0（"设 9.9.9 不会静默通过"的硬证据）
    env = dict(os.environ)
    env.pop('LOOM_ENGINE_VERSION', None)
    env['LOOM_HUB_VERSION'] = '9.9.9'
    r = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, "tools"); import release_github'],
        cwd=REPO, env=env, capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    check("子进程 import: LOOM_HUB_VERSION=9.9.9 -> 非 0 退出",
          r.returncode != 0,
          (r.returncode, (r.stderr or '').strip().splitlines()[:1]))
    env.pop('LOOM_HUB_VERSION', None)
    env['LOOM_ENGINE_VERSION'] = '9.9.9.beta1'
    r2 = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, "tools"); import release_github'],
        cwd=REPO, env=env, capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    check("子进程 import: LOOM_ENGINE_VERSION=9.9.9.beta1 -> 非 0 退出",
          r2.returncode != 0,
          (r2.returncode, (r2.stderr or '').strip().splitlines()[:1]))
    # 一致时子进程应正常导入
    env.pop('LOOM_ENGINE_VERSION', None)
    r3 = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, "tools"); import release_github as rg; '
         'print(rg.ENGINE_VERSION, rg.HUB_VERSION)'],
        cwd=REPO, env=env, capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    check("子进程 import（无环境变量）-> 正常且两版本都来自真源",
          r3.returncode == 0
          and (r3.stdout or '').split() == [src_engine, src_hub],
          (r3.returncode, (r3.stdout or '').strip(), (r3.stderr or '')[:80]))


def t_hub_version_single_source():
    """N5=A: LoomHub 版本号只有 LoomHub/版本.json 一个真源。

    - 读出来的值 = 版本.json = release_github 缺省（三处一致）；
    - 版本.json 缺失 -> 明确报错退出（exit 非 0），**不回落、不回写**；
    - 打包器里不再存在任何硬编码默认版本（AST 级断言，不看注释）。
    """
    import ast
    vfile = os.path.join(REPO, 'LoomHub', '版本.json')
    check("版本真源文件存在", os.path.isfile(vfile), vfile)
    before = open(vfile, 'rb').read()
    mtime_before = os.path.getmtime(vfile)
    got = ph.load_version()
    check("package_hub.load_version() = 版本.json",
          got == _read_json(vfile).get('version'), got)
    check("load_version() 不写回版本文件（打包不得隐式改源码）",
          open(vfile, 'rb').read() == before
          and os.path.getmtime(vfile) == mtime_before)
    check("--version 覆盖仍然生效", ph.load_version('9.9.9') == '9.9.9')

    # 缺失 -> 报错退出，且不把文件"补"出来
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, '版本.json')
        old = ph.VERSION_FILE
        ph.VERSION_FILE = missing
        try:
            raised = False
            try:
                ph.load_version()
            except SystemExit as e:
                raised = str(e) != ''
            check("版本真源缺失 -> SystemExit 且带原因", raised)
            check("版本真源缺失时不会被自动创建（无静默回写）",
                  not os.path.exists(missing))
        finally:
            ph.VERSION_FILE = old

    # 坏 JSON / 缺字段 -> 同样报错，不猜
    with tempfile.TemporaryDirectory() as tmp:
        bad = os.path.join(tmp, '版本.json')
        old = ph.VERSION_FILE
        ph.VERSION_FILE = bad
        try:
            open(bad, 'w', encoding='utf-8').write('{broken')
            try:
                ph.load_version()
                ok1 = False
            except SystemExit:
                ok1 = True
            check("版本真源坏 JSON -> SystemExit", ok1)
            open(bad, 'w', encoding='utf-8').write('{"x": 1}')
            try:
                ph.load_version()
                ok2 = False
            except SystemExit:
                ok2 = True
            check("版本真源缺 version 字段 -> SystemExit", ok2)
        finally:
            ph.VERSION_FILE = old

    # AST: 不再有 DEFAULT_VERSION 这个名字（注释里出现不算）
    src = open(os.path.join(REPO, 'tools', 'package_hub.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    check("package_hub 不再有硬编码 DEFAULT_VERSION（常量/引用都没有）",
          'DEFAULT_VERSION' not in names and 'DEFAULT_VERSION' not in attrs)


def t_version_whitelist():
    """P-05-06: 非法 --version 必须在打包/发布前被拒，绝不写进包内元数据。"""
    check("合法版本号通过白名单", pe.check_version('0.1.0.beta4') == '0.1.0.beta4')
    for bad in ('0.1.0-beta4', 'v0.1.0.beta4', '0.1', 'beta4'):
        try:
            pe.check_version(bad)
            ok = False
        except SystemExit:
            ok = True
        check("非法版本号被拒: %r" % bad, ok)


def t_release_preflight():
    """P-05-07/P-05-08: 资产缺失时前置检查必须失败（= 不产生任何远端写操作）。"""
    check("存在资产 -> 前置检查通过",
          rg.require_assets([('engine', os.path.join(ROOT, 'Loom.py'))]) is True)
    check("缺资产 -> 前置检查失败（调用方据此零远端写退出）",
          rg.require_assets([('engine',
                              os.path.join(REPO, 'tools', 'dist', '_不存在_.zip'))]) is False)
    # Q10=A（2026-11-08 人类裁决）：发布回归闸门**默认开启**，--no-require-tests 才跳过
    check("发布回归闸门默认开启", rg.want_test_gate([]) is True)
    check("显式 --no-require-tests 才关闭闸门", rg.want_test_gate(['--no-require-tests']) is False)
    check("旧写法 --require-tests 仍然开启（向后兼容）", rg.want_test_gate(['--require-tests']) is True)
    check("闸门函数存在", callable(getattr(rg, 'run_test_gate', None)))


if __name__ == "__main__":
    print("========== 打包/发布链 版本一致性断言 ==========")
    t_engine_version_consistency()
    t_hub_version_consistency()
    t_hub_version_single_source()
    t_version_env_crosscheck()
    t_version_whitelist()
    t_release_preflight()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅")
