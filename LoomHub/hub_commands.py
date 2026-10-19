# -*- coding: utf-8 -*-
"""
hub_commands.py — LoomHub Engine Agent 接口 (HUB-EAI, 2026-08-27)
====================================================================
用途 (用户定调): LoomHub 完全命令行化 —— Agent 从项目创建到项目编辑的
全链路工作: 引擎列表/项目列表直接输出 (排查) / 导入·安装·选默认解释器 /
项目创建·导入·打开 / 启动 Loom (复用 build_launch_command, 与 GUI 双击
完全同环境 — 用于复现"LoomHub 启动的 Loom"的环境问题) / 设置读写.
LoomHub 全部为按钮 (非连贯操作), 命令层与 GUI/controller 同一实现.

协议 (与 Loom EAI 同构, LoomHub.py --agent 时启动):
  端口/令牌: <程序目录>/.hub_agent_port.json {"port","token","pid","url"}
  POST /cmd {"cmd","args"} -> {"ok":true,"result"} | {"ok":false,"error"}
  GET  /logs?after=N  -> {"ok":true,"seq","lines"}
  GET  /             -> 命令清单
  鉴权: 请求头 X-Agent-Token (错 token -> 401)
命令在请求线程直接执行 (LoomHub 命令全部 = 文件/配置/子进程操作, 无 UI
一致性需求; 唯一例外 quit -> 停止服务并退出进程).

命令表 (LoomHub 全部按钮面):
  status / interpreter_list / project_list       查询 (列表全量输出)
  interpreter_add {dir} / interpreter_install_zip {zip, root?} /
  interpreter_remove {dir} / interpreter_default {dir}
  project_create {path, name?} / project_import {dir} /
  project_open {name|path} / project_remove {name|path}
  launch_engine {scene?, mode?('open'|'run'), agent?}  启动 Loom 子进程
  engine_stop {pid} (终止上面启动的进程, 排查后清理)
  settings_get {key?} / settings_set {key,value}
  quit
"""
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hub_config as cfg
import hub_install as inst

PORT_FILE = '.hub_agent_port.json'
LOG_RING = deque(maxlen=2000)
_LOG_SEQ = 0
_LOG_LOCK = threading.Lock()
_COMMANDS = {}
_CMDS_DESC = {}


def log(msg):
    global _LOG_SEQ
    with _LOG_LOCK:
        _LOG_SEQ += 1
        LOG_RING.append((_LOG_SEQ, time.strftime('%H:%M:%S'), str(msg)))
    return _LOG_SEQ


def log_since(after):
    with _LOG_LOCK:
        return [r for r in LOG_RING if r[0] > after]


# 命令参数一律可能是字符串 (GUI 控制台 "agent=false" / JSON "false"):
# 裸 bool('false') == True, 必须走 as_bool (与 Loom EAI 同一约定).
_FALSE_WORDS = {'', '0', 'false', 'no', 'off', 'none', '否'}


def as_bool(v, default=False):
    """命令参数布尔化 ('false'/'0'/'no'/'off' 判假)."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() not in _FALSE_WORDS


def coerce_value(v):
    """设置值归一 (settings_set): 控制台只能给字符串, 但 GUI 读设置时
    open_py 要 bool、fps 要数字 —— 直接存字符串会让 GUI 复选框/档位错乱.
    'true'/'false' -> bool, 纯数字 -> int/float, 其余原样字符串."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    low = s.lower()
    if low in ('true', 'yes', 'on'):
        return True
    if low in ('false', 'no', 'off'):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return v


def command(name, desc=""):
    def deco(fn):
        _COMMANDS[name] = fn
        _CMDS_DESC[name] = desc
        return fn
    return deco


def command_names():
    return {k: _CMDS_DESC.get(k, '') for k in _COMMANDS}


def dispatch(cmd, args):
    """执行一条命令 (hub 无 UI 一致性需求, 请求线程直跑).
    args 无则用空 dict; 异常记日志返回错误, 不崩服务."""
    fn = _COMMANDS.get(cmd)
    if fn is None:
        return {'ok': False,
                'error': '未知命令: %s (可用: %s)' % (cmd, ' '.join(sorted(_COMMANDS)))}
    try:
        t0 = time.perf_counter()
        result = fn(args or {})
        ms = (time.perf_counter() - t0) * 1000
        # 契约统一 (2026-08-27, 与 Loom EAI 同): 命令返回 {'error': ...} =
        # 参数/前置条件不对, 外层同步 ok=False (免 Agent 把拒绝当成功).
        if isinstance(result, dict) and result.get('error'):
            log('[命令] %s %s -> 拒绝: %s' % (cmd, args or '', result['error']))
            return {'ok': False, 'error': result['error'], 'result': result}
        log('[命令] %s %s -> ok (%.1fms)' % (cmd, args or '', ms))
        return {'ok': True, 'result': result}
    except Exception as e:
        log('[命令] %s 失败: %r' % (cmd, e))
        return {'ok': False, 'error': repr(e)}


# ====================================================================
# 查询 (列表全量输出, 排查用)
# ====================================================================
@command('status', 'LoomHub 摘要: 默认解释器/数量/设置')
def cmd_status(args):
    its = cfg.load_interpreters()
    prj = cfg.load_projects()
    try:
        import guiloader
        s = guiloader.load_settings('loomhub')
    except Exception:
        s = {}
    return {'default': cfg.default_interpreter(),
            'interpreter_count': len(its),
            'project_count': len(prj),
            'settings': s}


@command('interpreter_list', '引擎列表 (全量, 含 dir/version/kind/default)')
def cmd_interpreter_list(args):
    its = cfg.load_interpreters()
    default = cfg.default_interpreter()
    def_dir = default['dir'] if default else None
    return {'interpreters': [
        {'name': i.get('name'), 'version': i.get('version'),
         'kind': i.get('kind'), 'dir': i.get('dir'),
         'default': (i.get('dir') == def_dir) or i.get('default', False)}
        for i in its]}


@command('project_list', '项目列表 (全量, 含 name/scene/version)')
def cmd_project_list(args):
    return {'projects': list(cfg.load_projects())}


# ====================================================================
# 解释器管理
# ====================================================================
@command('interpreter_add', '导入解释器目录: {dir} (发现元数据+登记)')
def cmd_interpreter_add(args):
    d = args.get('dir')
    if not d or not os.path.isdir(d):
        return {'error': '目录不存在: %s' % d}
    info = cfg.discover_interpreter(d)
    if info is None:
        return {'error': '未发现解释器元数据 (缺 %s 或主程序): %s'
                % (cfg.META_NAME, d)}
    cfg.add_interpreter(info)
    return {'added': info}


@command('interpreter_install_zip', '.zip 安装解释器: {zip, version} (校验+登记; '
         'root 参数已禁用, 固定安装根)')
def cmd_interpreter_install_zip(args):
    """2026-08-28 二轮(高危4): root 参数**不再接受自定义** —— 原实现
    root 完全不校验, 攻击链"恶意 zip + root=任意目录"直接把文件释放进
    Startup 等目录 (路线C 实机 RELEASED)。现在只允许固定的
    cfg.DEFAULT_INSTALL_ROOT (显式传同等值=放行, 其余值=拒绝)。"""
    z = args.get('zip')
    ver = args.get('version')
    if not z or not os.path.isfile(z):
        return {'error': 'zip 不存在: %s' % z}
    if not ver:
        return {'error': '需要 version (x.y.z 或 x.y.z.betaN)'}
    root = args.get('root')
    if root:
        try:
            rn = os.path.abspath(os.path.normpath(root)).rstrip('\\/')
            dn = os.path.abspath(cfg.DEFAULT_INSTALL_ROOT).rstrip('\\/')
            if rn != dn:
                return {'error': '自定义安装根已禁用: %s (只允许 %s)'
                        % (root, cfg.DEFAULT_INSTALL_ROOT)}
        except Exception as e:
            return {'error': 'root 校验失败: %r' % e}
    target = inst.install_from_zip(z, ver, target_root=cfg.DEFAULT_INSTALL_ROOT)
    return {'installed': target}


@command('interpreter_remove', '移除解释器登记: {dir} (不删目录文件)')
def cmd_interpreter_remove(args):
    d = args.get('dir')
    its = cfg.load_interpreters()
    for i in its:
        if i.get('dir') == d or i.get('version') == d:
            cfg.remove_interpreter(i)
            return {'removed': d}
    return {'error': '未登记: %s (先 interpreter_list 查看)' % d}


@command('interpreter_default', '设默认解释器: {dir} (不匹配报列表)')
def cmd_interpreter_default(args):
    d = args.get('dir')
    its = cfg.load_interpreters()
    sel = next((i for i in its if i.get('dir') == d), None)
    if sel is None:
        return {'error': '未登记 (先 interpreter_list): %s' % d}
    cfg.set_default_interpreter(sel)
    return {'default': cfg.default_interpreter()}


# ====================================================================
# 项目管理 (文件式: 项目 = 场景文件; 命令行版 = 直接指定路径)
# ====================================================================
EMPTY_SCENE = {"version": 10, "objects": [], "lights": [], "cameras": [],
               "camera": {"target": [0, 0, 0], "distance": 10.0,
                          "yaw": 0.6, "pitch": -0.35}}


def _hub_write_roots():
    """Hub 侧写路径白名单根: LoomHub 目录 / 默认解释器保存目录 / 用户目录 /
    系统临时目录 (写临时文件/测试场地合法; 病毒投放价值区不在其中)."""
    roots = [os.path.abspath(cfg.HUB_DIR).rstrip('\\/'),
             os.path.expanduser('~').rstrip('\\/')]
    try:
        sd = cfg.interpreter_save_dir()
        if sd:
            roots.append(os.path.abspath(sd).rstrip('\\/'))
    except Exception:
        pass
    try:
        import tempfile
        roots.append(os.path.normpath(tempfile.gettempdir()).rstrip('\\/'))
    except Exception:
        pass
    out, seen = [], set()
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _hub_safe_write_path(path, purpose='写文件'):
    """Hub 侧写路径白名单 (2026-08-28 二轮高危4: project_create 原可任意
    路径建目录+写文件 = 路线C 的目录铺垫原语)。"""
    if not path or not isinstance(path, str):
        return False, '需要非空 path'
    full = os.path.abspath(os.path.normpath(path))
    for r in _hub_write_roots():
        if full == r:
            return False, '路径是目录, 不是文件: %s' % full
        if full.startswith(r + os.sep) or full.startswith(r + '/'):
            return True, full
    return False, ('%s 越域: %s (白名单: LoomHub 目录/解释器保存目录/用户目录)'
                   % (purpose, full))


@command('project_create', '创建项目 (空场景文件): {path} 选填 name (白名单外拒绝)')
def cmd_project_create(args):
    p = args.get('path')
    if not p:
        return {'error': 'project_create 需要 path (完整场景文件路径)'}
    ok, full = _hub_safe_write_path(p, 'project_create')
    if not ok:
        return {'error': full}
    p = full
    if os.path.isdir(p):
        return {'error': 'path 指向目录: %s' % p}
    base = os.path.dirname(p)
    os.makedirs(base, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(EMPTY_SCENE, f, ensure_ascii=False)
    name = args.get('name') or os.path.splitext(os.path.basename(p))[0]
    cfg.add_project(name, p)
    return {'created': p, 'name': name}


@command('project_import', '导入项目目录: {dir} (场景文件式: 目录内查场景.json)')
def cmd_project_import(args):
    d = args.get('dir')
    if not d or not os.path.isdir(d):
        return {'error': '目录不存在: %s' % d}
    info = cfg.discover_project(d)
    if info is None:
        return {'error': '未发现项目场景: %s' % d}
    cfg.add_project(info[0], info[1])
    return {'imported': {'name': info[0], 'scene': info[1]}}


@command('project_open', '打开项目 (启动 Loom 编辑器): {name|path, agent?}')
def cmd_project_open(args):
    key = args.get('path') or args.get('name')
    if not key:
        return {'error': '需要 name 或 path'}
    prj = next((p for p in cfg.load_projects()
                if p.get('scene') == key or p.get('name') == key), None)
    scene = key if prj is None else prj['scene']
    if prj is None and not os.path.isfile(scene):
        # 未登记且不是磁盘上的场景文件: 早报错. (原来直接透传给 launch_engine,
        # 打错项目名会静默启动一个"场景不存在"的编辑器, 排查时极易误判)
        return {'error': '未登记项目且不是场景文件: %s (先 project_list)' % key}
    return cmd_launch_engine({'scene': scene, 'agent': args.get('agent', False)})


@command('project_remove', '移除项目登记: {name|path} (不删场景文件)')
def cmd_project_remove(args):
    key = args.get('name') or args.get('path')
    prj = next((p for p in cfg.load_projects()
                if p.get('scene') == key or p.get('name') == key), None)
    if prj is None:
        return {'error': '未登记: %s (先 project_list)' % key}
    # cfg.remove_project 收的是**场景路径字符串** (按 scene 过滤), 传 dict
    # 会一条都匹配不上 -> 静默什么也没删却回报 removed (2026-08-27 修).
    cfg.remove_project(prj['scene'])
    return {'removed': key, 'scene': prj['scene']}


# ====================================================================
# 启动 Loom (复用 GUI 同款 build_launch_command: 启动环境完全一致)
# ====================================================================
_LAUNCHED = {}     # pid -> (Popen, info) 排查后 engine_stop 清理


def launch_spec(args, info=None):
    """构造启动规格 (cmd/cwd/env/prefer) —— 与 GUI 双击 (hub_controller.
    open_project) **逐字段同构**, 是本命令存在的意义: 用它复现"LoomHub 启动
    的 Loom"环境问题, 任何一处不一致都会让复现结论失真.
    返回 (spec dict, 错误字符串或 None). 无副作用, 可被测试直接断言."""
    info = info or cfg.default_interpreter()
    if info is None:
        return None, '无默认解释器 (先 interpreter_add 或 interpreter_default)'
    # 2026-10-19 启动路径 bug 修复: 相对路径按工作区根解析（与 GUI open_project 同构）
    scene = cfg.resolve_runtime_path(args.get('scene'))
    if scene:
        # GUI 同款校验 (2026-08-20 安全加固: projects.json 被篡改时不打开任意文件)
        if not os.path.isfile(scene):
            return None, '场景文件不存在: %s' % scene
        if not str(scene).lower().endswith('.json'):
            return None, '非场景文件 (.json), 拒绝打开: %s' % scene
    mode = args.get('mode') or ('open' if scene else 'run')
    # 启动器设置 open_py: GUI 走这一条选 .py/.exe, 命令层不读设置就会
    # 在"exe 版解释器 + open_py=True"时启动另一个可执行体 (环境不同).
    prefer = None
    try:
        import guiloader
        prefer = 'py' if guiloader.load_settings('loomhub').get('open_py', True) else 'exe'
    except Exception:
        prefer = None
    cmd_parts = cfg.build_launch_command(info, scene, mode=mode, prefer=prefer)
    if as_bool(args.get('agent')):
        cmd_parts.append('--agent')
    # 2026-10-19 启动路径 bug 修复: cwd 也解析成绝对（与 GUI open_project 同构）
    cwd_resolved = cfg.resolve_runtime_path(info.get('dir')) or cfg.HUB_DIR
    return {'cmd': cmd_parts, 'cwd': cwd_resolved,
            'env': dict(os.environ), 'prefer': prefer, 'mode': mode,
            'interpreter': info}, None


@command('launch_engine', '启动 Loom: {scene?, mode?(open|run), agent?(false)} '
         'agent=true 追加 --agent 并轮询端口文件返回 port/token')
def cmd_launch_engine(args):
    spec, err = launch_spec(args)
    if err:
        return {'error': err}
    info = spec['interpreter']
    cmd_parts = spec['cmd']
    # GUI 同款启动: 无 shell (list 直传, 免 cmd.exe 引号歧义)、
    # cwd=解释器目录、env=当前环境副本、不加 CREATE_NO_WINDOW (窗口可见).
    import subprocess
    t0 = time.time()
    p = subprocess.Popen(cmd_parts, cwd=spec['cwd'], env=spec['env'])
    _LAUNCHED[p.pid] = (p, info)
    out = {'pid': p.pid, 'command': ' '.join(cmd_parts), 'interpreter': info['dir'],
           'cwd': spec['cwd'], 'prefer': spec['prefer'], 'mode': spec['mode']}
    if as_bool(args.get('agent')):
        # 轮询 Loom 的 .agent_port.json (Loom 程序目录).
        # **必须判新鲜度**: 上次运行残留的端口文件会被立刻读到, 拿着已死进程
        # 的 port/token 去发命令, 表现为"启动成功但命令全超时" (2026-08-27 修).
        # 判据 = 文件里的 pid 就是本次子进程, 或写入时间晚于本次启动时刻.
        pf = os.path.join(info['dir'], '.agent_port.json')
        while time.time() - t0 < 15.0:
            try:
                with open(pf, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if d.get('pid') == p.pid or os.path.getmtime(pf) >= t0:
                    out['agent_port'] = d
                    break
            except Exception:
                pass
            time.sleep(0.3)
        if 'agent_port' not in out:
            out['agent_wait'] = '15s 内未发现本次启动的端口文件 (旧文件已忽略)'
    log('[hub] 启动 Loom pid=%s (env=GUI 同款构建命令)' % p.pid)
    return out


@command('engine_stop', '停止 launch_engine 启动的进程: {pid} (缺省=命令自己记住的全部)')
def cmd_engine_stop(args):
    pid = args.get('pid')
    if pid not in (None, ''):
        try:
            pid = int(pid)          # 控制台传来的是字符串
        except (TypeError, ValueError):
            return {'error': 'pid 不是数字: %r' % (pid,)}
    else:
        pid = None
    stopped = []
    for k in list(_LAUNCHED):
        if pid is not None and k != pid:
            continue
        p, info = _LAUNCHED.pop(k)
        try:
            p.terminate()
        except Exception:
            pass
        stopped.append(k)
    return {'stopped': stopped}


# ====================================================================
# 设置 / 退出
# ====================================================================
@command('settings_get', '读 LoomHub 设置: {key?} (缺省=全部)')
def cmd_settings_get(args):
    import guiloader
    s = guiloader.load_settings('loomhub')
    return s if not args.get('key') else {args['key']: s.get(args['key'])}


@command('settings_set', '写 LoomHub 设置: {key,value} (如 gui/open_py)')
def cmd_settings_set(args):
    key = args.get('key')
    val = args.get('value')
    if not key:
        return {'error': '需要 key'}
    import guiloader
    s = guiloader.load_settings('loomhub')
    # 控制台只能给字符串: open_py="false" 存进去后 GUI 读到的是真值字符串,
    # 复选框/档位全错 —— 统一归一成 bool/数字 (coerce_value).
    val = coerce_value(val)
    s[key] = val
    guiloader.save_settings('loomhub', s)
    return {'set': {key: val}, 'type': type(val).__name__}


_QUIT = {'flag': False}
# 退出钩子 (测试可替换): 生产=os._exit 立即杀进程; 测试注入假函数验证
# "quit 确实会退出", 不必真的把测试进程干掉.
_EXIT = os._exit


@command('quit', '退出 LoomHub (停服务+进程)')
def cmd_quit(args):
    _QUIT['flag'] = True
    # tk mainloop 无法跨线程安全打断: 延时退出 (先返回响应).
    # 走模块级 _EXIT 而非直接 os._exit —— 便于自动化测试断言.
    delay = 0.5
    try:
        delay = float(args.get('after', 0.5))
    except (TypeError, ValueError):
        delay = 0.5
    t = threading.Timer(delay, lambda: _EXIT(0))
    t.daemon = True
    t.start()
    return {'quitting': True, 'after': delay}


# ====================================================================
# HTTP 桥 (同 Loom EAI 协议; 服务要 close 由入口驱动)
# ====================================================================
def port_file_path(base=None):
    return os.path.join(base or os.path.dirname(os.path.abspath(sys.argv[0])),
                        PORT_FILE)


class _Handler(BaseHTTPRequestHandler):
    """服务实例只能经 self.server.hub 取 (BaseHTTPRequestHandler 的
    self.server 是 ThreadingHTTPServer 实例, HubService 挂在它的 .hub);
    别在类上放 service/hub 类属性 —— 那会是 None, 用起来直接 500."""

    def log_message(self, fmt, *args):
        pass

    def _auth(self):
        """令牌校验 (2026-08-28 二轮中危2): 常量时间比较 + Host 本机校验."""
        import hmac
        tok = self.headers.get('X-Agent-Token') or ''
        if not hmac.compare_digest(tok.encode('utf-8'),
                                   self.server.hub.token.encode('utf-8')):
            return False
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost', '')

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth():
            return self._json(401, {'ok': False, 'error': 'bad token'})
        if self.path.startswith('/logs'):
            after = 0
            if 'after=' in self.path:
                try:
                    after = int(self.path.split('after=')[1].split('&')[0])
                except Exception:
                    after = 0
            return self._json(200, {'ok': True, 'seq': _LOG_SEQ,
                                    'lines': log_since(after)})
        if self.path.startswith('/status'):
            return self._json(200, {'ok': True, 'pid': os.getpid(),
                                    'mode': 'loomhub-agent'})
        return self._json(200, {'ok': True, 'service': 'loomhub-agent',
                                'commands': list(_COMMANDS)})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {'ok': False, 'error': 'bad token'})
        if not self.path.startswith('/cmd'):
            return self._json(404, {'ok': False, 'error': 'not found'})
        try:
            req = json.loads(self.rfile.read(
                int(self.headers.get('Content-Length', 0)) or 0)
                .decode('utf-8'))
        except Exception as e:
            return self._json(400, {'ok': False, 'error': repr(e)})
        result = dispatch(req.get('cmd'), req.get('args') or {})
        self._json(200, result)


class HubService:
    """HTTP 服务 (请求线程直跑命令). 入口 guard: start() -> 返回端口;
    stop() 结束. quit 命令置 _QUIT 后由入口主循环退出."""

    def __init__(self, base=None):
        self.base = base or os.path.dirname(os.path.abspath(sys.argv[0]))
        self.token = secrets.token_hex(16)
        self.server = None
        self.thread = None
        self.port = 0          # start() 后填真实端口 (未启动时也可安全读)

    def start(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.server.hub = self
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        with open(port_file_path(self.base), 'w', encoding='utf-8') as f:
            json.dump({'port': self.port, 'token': self.token,
                       'pid': os.getpid(),
                       'url': 'http://127.0.0.1:%d' % self.port,
                       'started': time.strftime('%Y-%m-%d %H:%M:%S')},
                      f, ensure_ascii=False)
        print('[hub-agent] HUB-EAI serving on http://127.0.0.1:%d (pid=%d)'
              % (self.port, os.getpid()), flush=True)
        log('[hub-agent] HUB-EAI 启动: %d' % self.port)
        return self.port

    def stop(self):
        _QUIT['flag'] = True
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
        try:
            os.remove(port_file_path(self.base))
        except Exception:
            pass


def load_agent_info(base=None):
    path = port_file_path(base)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
