# -*- coding: utf-8 -*-
"""
test_hub_eai.py — LoomHub Agent 接口 (HUB-EAI) 测试 (2026-08-27, 全无头).
覆盖: 引擎/项目列表输出 / 导入·默认·移除 / 项目创建(空场景文件)·导入·移除 /
未知命令 / HTTP 端到端 (鉴权 401/清单/日志) / launch_engine 命令构造
(mock Popen; 验证复用 build_launch_command 与 GUI 同款) / engine_stop.
⚠ 开篇即重定向 cfg 配置文件指针到本进程临时目录 —— 2026-08-27 污染事故
根治 (历史测试曾把 %TEMP% 引擎写入真实 LoomHub\interpreters.json).
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest.mock as mock
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), '..', 'LoomHub'))

import hub_config as cfg
import hub_commands as hc

_USED = set()          # 覆盖率闸门: 命令表每条都要真的执行过


def _patch_dispatch(_hc):
    """包一层 dispatch 记录命令名 (覆盖率闸门用; 单一入口, 无路径遗漏)."""
    _orig = _hc.dispatch

    def wrapped(cmd, args):
        if cmd in _hc._COMMANDS:      # 只记合法命令 (『不存在』是用来测未知命令的)
            _USED.add(cmd)
        return _orig(cmd, args)
    _hc.dispatch = wrapped
    return _hc


# ---- 文件级隔离: 本测试任何写入都不落真实台账 ----
_TEST_CFG_DIR = tempfile.mkdtemp(prefix='hub_eai_cfg_')
cfg.INTERPRETERS_FILE = os.path.join(_TEST_CFG_DIR, 'interpreters.json')
cfg.PROJECTS_FILE = os.path.join(_TEST_CFG_DIR, 'projects.json')
_patch_dispatch(hc)

_FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        _FAILS.append(name)


def _make_interp(root, version='1.0.0', kind='py', name="Loom"):
    d = os.path.join(root, version)
    os.makedirs(d, exist_ok=True)
    main = "%s.py" % name if kind == 'py' else "%s.exe" % name
    with open(os.path.join(d, cfg.META_NAME), 'w', encoding='utf-8') as f:
        json.dump({"name": name, "version": version,
                   "main": main if kind == 'py' else None,
                   "main_exe": main if kind == 'exe' else None,
                   "python_version": "3.12.10"}, f, ensure_ascii=False)
    open(os.path.join(d, main), 'w').close()
    return d


def _r(cmd, args=None):
    return hc.dispatch(cmd, args or {})


# ============ 1. 空台账列表 ============
def t_empty_lists():
    r = _r('interpreter_list')
    check("interpreter_list 初始空", r['ok'] and r['result']['interpreters'] == [], r)
    r = _r('project_list')
    check("project_list 初始空", r['ok'] and r['result']['projects'] == [], r)


# ============ 2. 解释器: 导入/默认/移除 ============
def t_interpreter_crud():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_interp(tmp)
        r = _r('interpreter_add', {'dir': d})
        check("interpreter_add 导入 (discover+登记)", r['ok']
              and r['result']['added']['kind'] == 'py', r)
        r = _r('interpreter_list')
        its = r['result']['interpreters']
        check("interpreter_list 1 条含 dir/version/default", len(its) == 1
              and its[0]['dir'] == d and its[0]['version'] == '1.0.0'
              and (its[0]['default'] or its[0].get('default') is not None), its)
        r = _r('status')
        check("status 默认解释器= 导入的", r['ok']
              and r['result']['interpreter_count'] == 1
              and r['result']['default']['dir'] == d, r['result'])
        r = _r('interpreter_remove', {'dir': d})
        check("interpreter_remove 移除登记", r['ok'])
        r = _r('interpreter_list')
        check("移除后列表空", r['result']['interpreters'] == [])
        r = _r('interpreter_remove', {'dir': 'D:\\none'})
        check("移除不存在的提示", not r['ok'] and '未登记' in r['error'], r)


# ============ 3. 项目: 创建空场景/列表/移除 (文件落盘可被场景系统读) ============
def t_project_crud():
    with tempfile.TemporaryDirectory() as tmp:
        scene = os.path.join(tmp, '我的空场景.json')
        r = _r('project_create', {'path': scene, 'name': '空工程'})
        check("project_create 建空场景+登记", r['ok'] and os.path.isfile(scene)
              and r['result']['name'] == '空工程', r)
        import sceneio
        data = sceneio.load_scene_data(scene)
        check("空场景可被 sceneio 读 (v10)", data is not None
              and data.get('version') == 10 and data.get('objects') == [], data)
        r = _r('project_list')
        check("project_list 1 条", r['ok'] and len(r['result']['projects']) == 1
              and r['result']['projects'][0]['scene'] == scene, r)
        r = _r('project_remove', {'name': '空工程'})
        check("project_remove", r['ok'])
        r = _r('project_open', {'path': 'x'})
        check("项目不存在且无默认解释器 -> 仍先报未登记/非场景文件 (早拦截)",
              not r['ok'] and '未登记项目' in r['error'], r)


# ============ 3b. 项目导入 (目录扫描式, discover_project 同款) ============
def t_project_import():
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, '我的场景工程')
        os.makedirs(d)
        # discover_project 优先 <目录名>_场景.json (编辑器默认命名规则)
        scene = os.path.join(d, '我的场景工程_场景.json')
        json.dump({'version': 10, 'objects': [], 'lights': [], 'cameras': []},
                  open(scene, 'w', encoding='utf-8'), ensure_ascii=False)
        r = _r('project_import', {'dir': d})
        check("project_import 发现并登记 (name/scene 落黄账)",
              r['ok'] and r['result']['imported']['name'] == '我的场景工程'
              and r['result']['imported']['scene'] == scene, r)
        r = _r('project_import', {'dir': os.path.join(tmp, '不存在')})
        check("project_import 目录不存在 -> 拒绝", not r['ok'], r)
        # 空目录 (无场景文件) -> 拒绝
        d2 = os.path.join(tmp, '空目录')
        os.makedirs(d2)
        r = _r('project_import', {'dir': d2})
        check("project_import 无场景文件 -> 拒绝", not r['ok']
              and '未发现项目场景' in r['error'], r)


# ============ 4. 未知命令 ============
def t_unknown():
    r = _r('不存在的')
    check("未知命令 -> ok=False 含清单", not r['ok'] and '未知命令' in r['error'], r)


# ============ 5. launch_engine: 命令构造同 GUI + mock Popen ============
def t_launch_mocked():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_interp(tmp)
        _r('interpreter_add', {'dir': d})
        # 2026-08-28 加场景存在性校验 (GUI 同款, 防篡改台账启动任意文件):
        # 测真实启动前先造一个真场景文件, 不再拿占位路径蒙混
        scene_a = os.path.join(tmp, 'A.json')
        __import__('json').dump({'version': 10, 'objects': [], 'lights': [],
                                 'cameras': []}, open(scene_a, 'w', encoding='utf-8'),
                                ensure_ascii=False)
        scene_b = os.path.join(tmp, 'B.json')
        __import__('json').dump({'version': 10, 'objects': [], 'lights': [],
                                 'cameras': []}, open(scene_b, 'w', encoding='utf-8'),
                                ensure_ascii=False)
        fake = mock.MagicMock()
        fake.pid = 4242
        with mock.patch('subprocess.Popen', return_value=fake) as m:
            r = _r('launch_engine', {'scene': scene_a})
            check("launch_engine 返回 pid/command", r['ok']
                  and r['result']['pid'] == 4242, r)
            cmd = ' '.join(m.call_args[0][0])
            check("启动命令含 --open A.json (GUI 同款 build_launch_command)",
                  '--open' in cmd and 'A.json' in cmd, cmd)
            r = _r('launch_engine', {'scene': scene_b, 'mode': 'run'})
            cmd2 = ' '.join(m.call_args_list[-1][0][0])
            check("mode=run 时含 --run", '--run' in cmd2 and 'B.json' in cmd2, cmd2)
            r = _r('engine_stop', {'pid': 4242})
            check("engine_stop 终止记录进程", r['ok'] and 4242 in r['result']['stopped'])


# ============ 6. HTTP 端到端 ============
def t_http():
    with tempfile.TemporaryDirectory() as tmp:
        base = tmp
        svc = hc.HubService(base=tmp)
        port = svc.start()
        info = hc.load_agent_info(tmp)
        check("端口文件写入 (.hub_agent_port.json)", info and info['port'] == port
              and info['token'] == svc.token, info)
        url = 'http://127.0.0.1:%d' % port

        def post(cmd, args, token):
            req = urllib.request.Request(
                url + '/cmd',
                data=json.dumps({'cmd': cmd, 'args': args}).encode('utf-8'),
                headers={'Content-Type': 'application/json',
                         'X-Agent-Token': token})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    return r.status, json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode('utf-8'))

        code, body = post('interpreter_list', {}, 'wrong')
        check("HTTP 鉴权错 token -> 401", code == 401, body)
        code, body = post('interpreter_list', {}, svc.token)
        check("HTTP POST /cmd 200 列表 ok", code == 200 and body['ok']
              and isinstance(body['result']['interpreters'], list), body)
        req = urllib.request.Request(
            url + '/logs?after=0', headers={'X-Agent-Token': svc.token})
        with urllib.request.urlopen(req, timeout=15) as r:
            ldata = json.loads(r.read().decode('utf-8'))
        check("GET /logs 有行", ldata['ok'] and len(ldata['lines']) > 0, ldata['lines'][-2:])
        svc.stop()
        check("stop 后端口文件删除", hc.load_agent_info(tmp) is None)


# ============ 7. 2026-08-28 修复回归: settings 归一 / quit / 契约 ============
def t_settings_and_contract():
    # settings_set 值归一: 控制台只能传字符串, 存储必须还原成 bool/数字
    r = _r('settings_set', {'key': 'open_py', 'value': 'false'})
    check("settings_set 'false' 归一成 bool False",
          r['ok'] and r['result']['set']['open_py'] is False
          and r['result']['type'] == 'bool', r)
    r = _r('settings_set', {'key': '_test_num', 'value': '120'})
    check("settings_set '120' 归一成 int (GUI 档位才不串)",
          r['ok'] and r['result']['set']['_test_num'] == 120, r)
    r = _r('settings_get', {'key': 'open_py'})
    check("settings_get 读回归一后的值 (bool False)",
          r['ok'] and r['result']['open_py'] is False, r)
    # 清理测试键
    import guiloader
    s = guiloader.load_settings('loomhub')
    s.pop('_test_num', None)
    guiloader.save_settings('loomhub', s)
    # settings_get key 缺省 = 全部
    r = _r('settings_get')
    check("settings_get 缺省返回全部", r['ok'] and isinstance(r['result'], dict))
    r = _r('settings_set', {})
    check("settings_set 缺 key -> 拒绝 (外层 ok=False)", not r['ok']
          and 'key' in r['error'], r)

    # quit: 走模块级 _EXIT 钩子 (测试注入假退出, 不必真杀进程)
    exit_called = {}
    _orig = hc._EXIT
    hc._EXIT = lambda code: exit_called.update(code=code)
    try:
        t0 = time.time()
        r = _r('quit', {'after': 0.05})
        time.sleep(0.3)
        check("quit 置 _QUIT 并通过 _EXIT 钩子退出 (不直接 os._exit)",
              r['ok'] and r['result']['quitting'] is True
              and exit_called.get('code') == 0 and time.time() - t0 < 5, (r, exit_called))
    finally:
        hc._EXIT = _orig
        hc._QUIT['flag'] = False

    # 契约: 各命令非法输入 -> 外层 ok=False (不能藏在 result.error 里)
    r = _r('interpreter_install_zip', {'zip': 'D:\\none'})
    check("interpreter_install_zip 文件不存在 -> 外层 ok=False",
          not r['ok'] and 'zip 不存在' in r['error'], r)
    r = _r('interpreter_default', {'dir': 'D:\\none'})
    check("interpreter_default 未登记 -> 外层 ok=False", not r['ok'], r)
    r = _r('engine_stop', {'pid': 'abc'})
    check("engine_stop pid 非数字 -> 外层 ok=False 不抛异常", not r['ok']
          and 'pid' in r['error'], r)


# ============ 7b. 写路径白名单 / root 固定 (2026-08-28 二轮高危3/4) ============
def t_hub_write_whitelist():
    # project_create 越权 (不在 Hub 目录/用户目录/解释器保存目录/系统临时)
    r = _r('project_create', {'path': r'C:\Windows\Temp\evil.json'})
    check("project_create 越权 -> 外层拒绝 (白名单外)", not r['ok']
          and '越域' in r['error'], r)
    r = _r('project_create', {'path': r'D:\flagpoc\evil_project.json'})
    check("project_create 非用户目录 -> 拒绝", not r['ok'], r)
    # 白名单内 (系统临时) 放行
    import tempfile
    p = os.path.join(tempfile.gettempdir(), 'hub_wl_ok.json')
    r = _r('project_create', {'path': p, 'name': '白名单ok'})
    check("project_create 白名单内 (系统临时) 正常建", r['ok']
          and os.path.isfile(p), r)
    os.remove(p)
    # interpreter_install_zip: 自定义 root = 拒绝 (真实 zip + mock 安装器)
    import hub_commands as hc
    from unittest import mock
    import zipfile
    z = os.path.join(tempfile.gettempdir(), 'hub_wl_zip.zip')
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr('1.0.0/flag.txt', 'dummy')
    try:
        with mock.patch.object(hc.inst, 'install_from_zip',
                               return_value='dummy') as m:
            r = _r('interpreter_install_zip', {'zip': z, 'version': '1.0.0'})
            check("无 root 参数 -> 默认安装根放行", r['ok']
                  and m.call_args[1]['target_root'] == cfg.DEFAULT_INSTALL_ROOT, r)
            r = _r('interpreter_install_zip',
                   {'zip': z, 'version': '1.0.0',
                    'root': cfg.DEFAULT_INSTALL_ROOT})
            check("root=默认安装根同值 -> 放行", r['ok'], r)
            r = _r('interpreter_install_zip',
                   {'zip': z, 'version': '1.0.0',
                    'root': r'C:\Windows\Temp'})
            check("root=自定义目录 -> 拒绝 (安装根已固定)", not r['ok']
                  and '已禁用' in r['error'], r)
    finally:
        os.remove(z)


# ============ 8. 2026-08-28: launch_spec 与 GUI 同构断言 ============
def t_launch_spec_gui_align():
    """launch_spec 是本轮修的核心: 命令层启动条件必须与 GUI 双击逐字段一致.
    用源码比对 GUI 路径 (hub_controller.open_project) 的四个要素:
    prefer(读 open_py) / build_launch_command / cwd=解释器目录 / env=环境副本."""
    import re
    ctrl_src = open(os.path.join(os.path.dirname(HERE), '..', 'LoomHub',
                                 'hub_controller.py'), encoding='utf-8').read()
    gui_has = {
        'prefer 读 open_py 设置': 'load_settings' in ctrl_src
        and "open_py" in ctrl_src,
        'build_launch_command': 'build_launch_command' in ctrl_src,
        'cwd=解释器目录': "cwd = interp.get('dir')" in ctrl_src
        or "cwd=interp" in ctrl_src,
        'env=环境副本': 'dict(os.environ)' in ctrl_src,
    }
    for label, cond in gui_has.items():
        check("GUI 源码含 %s (同构基准)" % label, cond)
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_interp(tmp)
        _r('interpreter_add', {'dir': d})
        # 真场景文件 (launch_spec 校验存在性)
        scene = os.path.join(tmp, 's.json')
        json.dump({'version': 10}, open(scene, 'w', encoding='utf-8'),
                  ensure_ascii=False)
        spec, err = hc.launch_spec({'scene': scene, 'mode': 'open'})
        check("launch_spec 返回 spec 无错误", spec is not None and err is None, err)
        if spec:
            check("command 复用 build_launch_command (含 --open 场景)",
                  '--open' in ' '.join(spec['cmd']) and scene in spec['cmd'],
                  spec['cmd'])
            spec_d = spec['interpreter'].get('dir')
            info_d = cfg.load_interpreters()[0].get('dir')
            check("cwd = 解释器目录 (GUI 同款, 取登记的那份)",
                  spec['cwd'] == spec_d == info_d,
                  (spec['cwd'], spec_d, info_d))
            check("env = 环境副本 (非 None)", isinstance(spec['env'], dict)
                  and 'PATH' in spec['env'])
            check("prefer 读的是 open_py 设置 (默认为 py)", spec['prefer'] in ('py', 'exe'))
            spec2, _ = hc.launch_spec({}, info=spec['interpreter'])
            if spec2:
                check("纯启动 (无 scene): mode=run 且无 --open/--run 参数",
                      spec2['mode'] == 'run' and '--open' not in ' '.join(spec2['cmd'])
                      and '--run' not in ' '.join(spec2['cmd']), spec2['cmd'])
        # 校验拒绝路径 (对标 GUI 场景文件校验)
        spec_n, err_n = hc.launch_spec({'scene': os.path.join(tmp, '不存在.json')},
                                       info=cfg.load_interpreters()[0])
        check("launch_spec 场景不存在 -> 错误提示 (GUI 同款拦截)",
              spec_n is None and '不存在' in err_n, err_n)
        # 非 .json 且**存在**的文件: 后端要有真文件才测得到扩展名分支
        exe = os.path.join(tmp, 'a.exe')
        open(exe, 'w').close()
        spec_x, err_x = hc.launch_spec({'scene': exe}, info=cfg.load_interpreters()[0])
        check("launch_spec 非 .json 场景 -> 拒绝 (防台账篡改打开任意文件)",
              spec_x is None and '.json' in err_x, err_x)
        # 无默认解释器 -> 错误
        lst = cfg.load_interpreters()
        for i in lst:
            cfg.remove_interpreter(i)
        spec_none, err_none = hc.launch_spec({})
        check("launch_spec 无默认解释器 -> 错误提示", spec_none is None and '解释器' in err_none)


# ============ 9. 2026-08-28: 陈旧端口文件不误取 ============
def t_port_freshness():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_interp(tmp)
        _r('interpreter_add', {'dir': d})
        scene = os.path.join(tmp, 'f.json')
        json.dump({'version': 10}, open(scene, 'w', encoding='utf-8'),
                  ensure_ascii=False)
        # 预埋"陈旧端口文件": pid=1 (不可能是本测试要启动的 pid) + mtime 改到
        # 1990 年 —— 新鲜度两条判据都该判它陈旧, 命令轮询满 15s 报告 agent_wait.
        # (不做 time 假时钟: mock time.time/sleep 测 loop 会因"两次调用之间
        # 的 15s 窗口永远不前进"而真死循环 —— 假时钟会骗过它自己.)
        pf = os.path.join(d, '.agent_port.json')
        json.dump({'port': 1, 'token': 'stale', 'pid': 1,
                   'url': 'http://127.0.0.1:1'}, open(pf, 'w', encoding='utf-8'))
        old = 631152000.0                       # 1990-01-01 UTC
        os.utime(pf, (old, old))
        fake = mock.MagicMock()
        fake.pid = 424242
        with mock.patch('subprocess.Popen', return_value=fake) as m:
            r = _r('launch_engine', {'scene': scene, 'agent': 'true'})
        check("agent=true 且残留陈旧端口文件 -> 不误取 (pid/mtime 双重判定, 明确报告等待)",
              r['ok'] and 'agent_port' not in r['result']
              and 'agent_wait' in r['result'], r)
        check("启动命令含 --agent 参数", '--agent' in r['result']['command'], r)


# ============ 10. 覆盖率闸门 ============
def t_coverage():
    table = set(hc.command_names())
    untested = sorted(table - _USED)
    check("HUB-EAI 命令表全部被真实执行过 (共 %d 条)" % len(table),
          not untested, untested)
    ghost = sorted(_USED - table)
    check("测试没有调用已下线的命令", not ghost, ghost)


if __name__ == "__main__":
    print("========== LoomHub Agent 接口 (HUB-EAI) 测试 ==========")
    t_empty_lists()
    t_interpreter_crud()
    t_project_crud()
    t_project_import()
    t_unknown()
    t_launch_mocked()
    t_http()
    t_settings_and_contract()
    t_hub_write_whitelist()
    t_launch_spec_gui_align()
    t_port_freshness()
    t_coverage()
    if _FAILS:
        print("总结果: FAIL ❌", _FAILS)
        sys.exit(1)
    print("总结果: ALL PASS ✅  (命令 %d 条全部覆盖)" % len(hc.command_names()))
    print("全部通过")
