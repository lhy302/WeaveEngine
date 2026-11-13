# -*- coding: utf-8 -*-
r"""
hub_config.py — LoomHub 项目管理器核心逻辑 (无 GUI 依赖, 可无头测试)

软件命名 (2026-08-11 定):
   解释器名   = Loom       (解释器默认安装根 = C:\Program Files\Loom\<版本号>)
   项目管理器 = LoomHub    (解释器名 + "Hub", 类似 Unity -> Unity Hub)

配置文件 (放 LoomHub 源码目录旁):
   interpreters.json   已登记的解释器列表 {name,version,kind,dir,main,path,default}
   projects.json       项目列表 {name, scene, version}

解释器元数据: 每个版本目录里有 解释器.json {name,version,main,main_exe,python_version},
   主程序 .py/.exe 双兼容: main 为源码名 / main_exe 为封装名 (封装后改名只需更新此字段).
   多版本共存: 按版本号子目录安装 (类似 Python 的 python3.x 目录), 一台机可装多版本.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

APP_NAME = "Loom"          # 解释器名 = 项目名
HUB_NAME = "LoomHub"       # 项目管理器名 = 解释器名 + "Hub"
HUB_DIR = os.path.dirname(os.path.abspath(__file__))
# 2026-10-19 启动路径 bug 修复：interpreters.json / projects.json 里用相对路径
# (dir="Loom" / path="Loom/Loom.py" / scene="Loom/保存/x.json") 时，Popen(cwd="Loom")
# + argv[1]="Loom/Loom.py" 会在子进程里找 "Loom/Loom/Loom.py" -> 必败。
# 修复：相对路径一律按"LoomHub 的父目录 = 工作区根"解析。
# 用户从任何 cwd 启动 LoomHub 都一致（不受双击/命令行 cwd 影响）。
WORKSPACE = os.path.dirname(HUB_DIR)


def resolve_runtime_path(p):
    """把配置里的路径解析成运行时绝对路径.

    规则（2026-10-19 修 LoomHub 启动路径 bug）：
      - None / 空串 -> 原样返回（保持语义）
      - 绝对路径   -> 原样返回
      - 相对路径   -> 按 WORKSPACE（LoomHub 的父目录 = 工作区根）解析
    调用方拿到绝对路径后可以放心 Popen(cwd=...) / isfile(...)。
    """
    if not p:
        return p
    try:
        if os.path.isabs(p):
            return p
        return os.path.normpath(os.path.join(WORKSPACE, p))
    except Exception:
        return p


def _hub_userpaths():
    """Hub 侧用户目录收口（2026-11-08 契约 §2）。

    hub_userpaths 优先：它在 Hub 自己的目录里，安装版（PyInstaller onedir）一定能导入；
    Loom 的 userpaths 只在源码工作区可用，所以在安装版里它救不了场（以前就是这样
    静默退化成"写程序目录"）。两个都拿不到才返回 None（极端降级，保持旧行为）。
    """
    try:
        import hub_userpaths
        return hub_userpaths
    except Exception:
        pass
    try:
        import userpaths
        return userpaths
    except Exception:
        return None


def default_interpreters_file():
    """解释器台账的用户层落点（拿不到 userpaths 时退回程序目录旧语义）。"""
    up = _hub_userpaths()
    try:
        if up is not None and hasattr(up, 'interpreters'):
            return up.interpreters()
    except Exception:
        pass
    return os.path.join(HUB_DIR, "interpreters.json")


def default_projects_file():
    """项目台账的用户层落点（同上）。"""
    up = _hub_userpaths()
    try:
        if up is not None and hasattr(up, 'projects'):
            return up.projects()
    except Exception:
        pass
    return os.path.join(HUB_DIR, "projects.json")


# 用户层路径（可写）。测试仍可直接改这两个模块常量做隔离。
INTERPRETERS_FILE = default_interpreters_file()
PROJECTS_FILE = default_projects_file()
# 旧位置（程序目录）。首次运行会把它们迁移进用户层，但**不删用户的文件**。
LEGACY_INTERPRETERS_FILE = os.path.join(HUB_DIR, "interpreters.json")
LEGACY_PROJECTS_FILE = os.path.join(HUB_DIR, "projects.json")
# 旧设置文件（程序目录里的 设置.json = 既当"随版本下发的默认模板"又当旧用户设置）
LEGACY_SETTINGS_FILE = os.path.join(HUB_DIR, "设置.json")
PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")
DEFAULT_INSTALL_ROOT = os.path.join(PROGRAM_FILES, APP_NAME)   # C:\Program Files\Loom
META_NAME = "解释器.json"   # 解释器元数据文件名 (每个版本目录内)


# ---------------- 通用 JSON 读写 ----------------
def save_json_atomic(path, data):
    """原子写 JSON: 先写临时文件再 os.replace, 防中途断电损坏.

    写失败**不吞**（契约 §7）: 磁盘满/权限不足一律上抛给调用方。
    注意: 本函数**不**替你建父目录（保持"父目录不存在即失败"的旧语义，
    Loom/tests/test_hub_controller.py 的"坏路径 -> err 不崩"就是靠这条）。
    需要建目录的调用方（各级台账）自己先 ensure_parent。
    """
    tmp = path + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path):
    """读 JSON, 坏文件/缺失返回 None (容错不崩)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _version_key(v):
    """版本排序键 (2026-08-22 支持 beta): '1.0.0' -> (1,0,0,1,0);
    '1.0.0.beta5' -> (1,0,0,0,5) —— beta < 正式版, betaN 越大越新
    (1.0.0.beta1 < 1.0.0.beta2 < 1.0.0). 其余格式解析失败补 0."""
    s = str(v)
    m = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:\.beta(\d+))?', s)
    if m:
        maj, minr, pat = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4) is not None:
            return (maj, minr, pat, 0, int(m.group(4)))
        return (maj, minr, pat, 1, 0)
    parts = []
    for seg in s.split('.'):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2], 1, 0)


# ---------------- 解释器发现 / 扫描 ----------------
_MAIN_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]+\.(py|exe)$')  # 2026-08-20: 主程序名白名单
# 2026-08-22: 解释器版本号格式白名单 —— x.y.z 正式版 / x.y.z.betaN 内测版
# (合同第九节: 只查格式不查大小; 排序见 _version_key, beta < 正式版)
_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(\.beta\d+)?$')


def validate_meta(meta, version=None):
    """解释器元数据合同 (2026-08-22, 见《Loom模块化插件化分析》第九节):
    返回 None = 合法, 字符串 = 拒绝原因. 发版自检 (打 zip 前) 与
    导入/扫描 (discover_interpreter) 共用同一判据 —— 两边平行线唯一
    接缝, 变化须同时知会. version 可传归一化后的值 (discover 用目录名
    兜底), 不传则用 meta['version']."""
    if not isinstance(meta, dict):
        return "元数据不是 JSON 对象"
    v = version if version is not None else (meta.get('version') or "")
    main = meta.get('main') or ""
    main_exe = meta.get('main_exe') or ""
    # 2026-08-20 安全加固 (Qoder 报告低危5): 主程序名/版本号格式白名单 ——
    # main/main_exe 直接拼启动命令 (打开项目即执行), 防诱导安装恶意包
    # 后把任意路径/命令注入启动参数. 版本号白名单只查格式不查大小
    # (任意 x.y.z, 数值无上限; 旧 LoomHub + 新引擎兼容).
    if v and not _VERSION_RE.match(str(v)):
        return "版本号须为 x.y.z 或 x.y.z.betaN 格式 (实际: %r)" % v
    if main and not _MAIN_NAME_RE.match(main):
        return "main 不合主程序名白名单: %r" % main
    if main_exe and not _MAIN_NAME_RE.match(main_exe):
        return "main_exe 不合主程序名白名单: %r" % main_exe
    if not main and not main_exe:
        return "main/main_exe 至少填一项"
    return None


def discover_interpreter(directory):
    """分析一个解释器目录, 返回 dict 或 None.
    读 解释器.json 拿版本/主程序名; 主程序 .exe 优先于 .py 判定 kind."""
    meta = load_json(os.path.join(directory, META_NAME))
    if meta is None:
        return None
    name = meta.get('name') or APP_NAME
    version = meta.get('version') or os.path.basename(os.path.normpath(directory))
    main = meta.get('main') or ""
    main_exe = meta.get('main_exe') or ""
    if validate_meta(meta, version) is not None:
        return None
    py_path = os.path.join(directory, main) if main else None
    exe_path = os.path.join(directory, main_exe) if main_exe else None
    if exe_path and os.path.isfile(exe_path):
        kind, path, main_name = 'exe', exe_path, main_exe
    elif py_path and os.path.isfile(py_path):
        kind, path, main_name = 'py', py_path, main
    else:
        return None   # 元数据在但主程序缺失, 视为未完成安装
    return {"name": name, "version": version, "kind": kind, "dir": directory,
            "main": main_name, "path": path,
            "main_py": py_path, "main_exe": exe_path,   # 双路径 (open_py 启动器设置用)
            # 2026-11-09: 源码版引擎要求的 Python 版本（如 3.13.15）。
            # 以前没记录 -> 从 Hub 启动源码引擎会落到系统默认 python（3.12），
            # 而新版源码引擎要求 3.13。编译版（kind=exe）不读这个字段。
            "python_version": str(meta.get('python_version') or '').strip()}


def user_install_root():
    r"""非管理员可用的引擎安装根: %LOCALAPPDATA%ProgramsLoom。

    Hub 自身安装器早就支持用户级（PrivilegesRequired=lowest + {autopf}），
    但引擎安装根一直是写死 Program Files —— 两套口径不一致（2026-11-10 修）。
    """
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'Programs', APP_NAME)


def root_writable(path):
    """path（或它最近的已存在祖先）是否可写。只看属性，不真的创建。"""
    try:
        p = os.path.abspath(str(path or ''))
    except (OSError, ValueError):
        return False
    if not p:
        return False
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return bool(p) and os.path.isdir(p) and os.access(p, os.W_OK)


def hub_install_dir():
    """LoomHub 自身所在目录（判定安装位置性质用）。

    两种运行形态都要处理：
      · PyInstaller onedir 安装版：sys.frozen=True，sys.executable 就是 <安装目录>\\LoomHub.exe；
      · 源码运行：sys.executable 是 python.exe（与 Hub 安装位置无关）→ 回退 HUB_DIR。
    """
    if getattr(sys, 'frozen', False):
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            if exe_dir:
                return exe_dir
        except Exception:
            pass
    return HUB_DIR


def hub_install_kind(program_dir=None):
    r"""LoomHub 自身安装位置的性质: 'system' | 'user' | 'portable'。

    2026-11-13 人类裁决：引擎**默认安装根跟随 Hub 自身位置**——
      · system   : Hub 在 ProgramFiles / ProgramFiles(x86) 下（管理员安装）
      · user     : Hub 在 %LOCALAPPDATA% / %USERPROFILE% 下（普通用户安装）
      · portable : 其它（例如解压在 D 盘）
    program_dir 仅供测试注入；默认取 hub_install_dir()。
    """
    try:
        d = os.path.normcase(os.path.abspath(str(program_dir or hub_install_dir() or '')))
    except (OSError, ValueError):
        return 'portable'
    if not d:
        return 'portable'

    def _under(base):
        try:
            b = os.path.normcase(os.path.abspath(str(base)))
        except (OSError, ValueError):
            return False
        return bool(b) and (d == b or d.startswith(b.rstrip('\\/') + os.sep))

    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'):
        v = os.environ.get(env)
        if v and _under(v):
            return 'system'
    for env in ('LOCALAPPDATA', 'USERPROFILE'):
        v = os.environ.get(env)
        if v and _under(v):
            return 'user'
    return 'portable'


def recommended_install_root(program_dir=None):
    r"""推荐的引擎安装根（跟随 LoomHub 自身安装性质，2026-11-13 裁决）。

    system   -> Program Files\\Loom（DEFAULT_INSTALL_ROOT）
    user / portable -> %LOCALAPPDATA%\\Programs\\Loom（user_install_root）
    推荐位置不可写时退回另一个（装得下去优先于口味）。
    """
    kind = hub_install_kind(program_dir)
    if kind == 'system':
        first, second = DEFAULT_INSTALL_ROOT, user_install_root()
    else:
        first, second = user_install_root(), DEFAULT_INSTALL_ROOT
    if root_writable(first):
        return first
    if root_writable(second):
        return second
    return first


def default_install_root():
    r"""默认引擎安装根：**先按推荐位置**（跟随 Hub 安装性质），再走可写自适应。

    2026-11-13 裁决：默认值不再无条件优先 Program Files —— Hub 装在用户目录/便携目录时，
    推荐用户目录；Hub 装在 Program Files（管理员安装）时仍推荐 Program Files。
    两级都不可写时保持旧行为回退 DEFAULT_INSTALL_ROOT（保留 Program Files 在允许集合里）。
    """
    rec = recommended_install_root()
    if root_writable(rec):
        return rec
    if root_writable(DEFAULT_INSTALL_ROOT):
        return DEFAULT_INSTALL_ROOT
    u = user_install_root()
    if root_writable(u):
        return u
    return DEFAULT_INSTALL_ROOT


def saved_install_root():
    """用户层保存的安装根（空串 = 没设过）。"""
    try:
        return str(load_hub_settings().get('install_root') or '').strip()
    except (OSError, ValueError):
        return ''


def scan_install_roots(roots):
    """多根扫描 + 按 dir 去重 + 版本升序（f: 同时覆盖 Program Files 与用户目录）。"""
    out, seen = [], set()
    for r in roots:
        if not r:
            continue
        try:
            found = scan_install_root(r)
        except OSError:
            continue
        for info in found:
            key = os.path.normcase(os.path.abspath(info.get('dir') or ''))
            if key in seen:
                continue
            seen.add(key)
            out.append(info)
    out.sort(key=lambda x: _version_key(x.get('version', '0')))
    return out


def scan_install_root(root=DEFAULT_INSTALL_ROOT):
    r"""扫描解释器安装根目录 (C:\Program Files\Loom), 按版本号子目录逐个分析.
    返回已安装解释器列表 (按版本号升序)."""
    result = []
    if not os.path.isdir(root):
        return result
    for entry in sorted(os.listdir(root)):
        sub = os.path.join(root, entry)
        if not os.path.isdir(sub):
            continue
        info = discover_interpreter(sub)
        if info is None:
            # 2026-11-10 d): 自家发布包布局是 <root>/<ver>/Loom/解释器.json
            # （顶层还有 Loom.bat / python/），旧实现只看 <sub>/解释器.json ->
            # 对真实发布包一律返回 []，"扫描"按钮形同虚设。
            inner = os.path.join(sub, 'Loom')
            if os.path.isdir(inner):
                info = discover_interpreter(inner)
        if info:
            result.append(info)
    result.sort(key=lambda x: _version_key(x.get('version', '0')))
    return result


# ---------------- 解释器配置 (interpreters.json) ----------------
def _ensure_parent(path):
    """台账写前建父目录（用户层目录可能首次不存在）；失败上抛（不静默）。"""
    up = _hub_userpaths()
    if up is not None and hasattr(up, 'ensure_parent'):
        up.ensure_parent(path)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def _is_default_path(path, default_fn):
    try:
        return os.path.abspath(path) == os.path.abspath(default_fn())
    except Exception:
        return False


def _maybe_migrate_ledger(path, legacy_path, key):
    """首次运行: 把程序目录里的旧台账搬进用户目录（保留旧文件，条目全带）。

    只在 path 就是"默认用户层路径"时生效 —— 测试把 INTERPRETERS_FILE 指到临时目录时
    不应发生迁移（否则用例之间会互相污染）。
    """
    default_fn = (default_interpreters_file if key == 'interpreters'
                  else default_projects_file)
    if not _is_default_path(path, default_fn):
        return
    if os.path.exists(path) or not legacy_path or not os.path.isfile(legacy_path):
        return
    try:
        with open(legacy_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print('[台账] 旧文件解析失败，跳过迁移 (%r): %s' % (e, legacy_path))
        return
    if not isinstance(data, dict):
        print('[台账] 旧文件格式不符，跳过迁移: %s' % legacy_path)
        return
    try:
        _ensure_parent(path)
        save_json_atomic(path, data)
        print('[台账] 已把旧文件迁移到用户目录: %s -> %s（%d 条）'
              % (legacy_path, path, len(data.get(key) or [])))
    except Exception as e:
        # 迁移失败不致命: 本次以空台账启动，旧文件原样留着，下次可再迁
        print('[台账] 迁移失败（本次以空台账启动，旧文件保持不动）: %r' % (e,))


def refresh_interpreters():
    """按各目录下的 解释器.json **重新识别**已登记解释器（2026-11-09 新增）。

    为什么需要：引擎目录可能被**原地替换**（源码版 -> 编译版，或换了版本），
    而台账里记的是登记那一刻的 kind/main/main_exe。旧台账会继续声称「源码版、主程序 Loom.py」，
    于是 Hub 显示成源码版、点开项目时去找早已不存在的 Loom.py/python —— 表现为「拉不起场景」。

    返回 (刷新后的列表, 是否有变化)。目录消失/主程序缺失的条目**直接移除**（不静默留死条目）。
    """
    old = load_interpreters()
    out = []
    for it in old:
        d = it.get('dir')
        info = discover_interpreter(d) if d and os.path.isdir(d) else None
        if info is not None:
            # 2026-11-09 Bug1 修复: 保留"默认"标记。
            # discover_interpreter() 只从 解释器.json 取 name/version/kind/main，
            # **天生没有 default 键**；以前这里直接 out.append(info) 会把
            # set_default 刚写下的 default 抹掉（set_default -> _refresh -> 被自己擦），
            # 于是 UI 永远看不到 ★、default_interpreter() 退回"取第一条"。
            if it.get('default'):
                info['default'] = True
            # 重新识别成功即"新鲜"：旧条目的 stale 标记随之清除（info 无此键）
            out.append(info)                    # 目录还在且元数据有效 -> 按现状重写 kind/main
        else:
            keep = dict(it)
            keep['stale'] = True                # 目录缺失/元数据不全: 保留但标记, 不静默删
            out.append(keep)
    changed = out != old
    if changed:
        try:
            save_interpreters(out)
            n_stale = sum(1 for x in out if x.get('stale'))
            print('[解释器] 台账已刷新: %d 条 (失效 %d 条)' % (len(out), n_stale))
        except OSError as e:
            print('[解释器] 台账刷新写盘失败: %r（本次仅内存生效）' % (e,))
    return out, changed


def interpreter_problem(info):
    """返回「这个解释器现在能不能用来启动」的问题描述（None = 可用）。

    2026-11-09: 引擎目录被原地替换（源码版 -> 编译版）后，旧台账仍指向 Loom.py，
    双击项目会静默失败。启动前必须显式校验并给出可执行的提示。
    """
    if not isinstance(info, dict):
        return '没有解释器'
    if info.get('stale'):
        return ('解释器已失效（%s）：目录或主程序已不存在，'
                '请在 Hub 里重新扫描 / 重新安装该版本' % (info.get('dir') or '<空>'))
    return None


def load_interpreters():
    _maybe_migrate_ledger(INTERPRETERS_FILE, LEGACY_INTERPRETERS_FILE, 'interpreters')
    data = load_json(INTERPRETERS_FILE)
    return data.get('interpreters', []) if data else []


def save_interpreters(interpreters):
    _ensure_parent(INTERPRETERS_FILE)
    save_json_atomic(INTERPRETERS_FILE, {"interpreters": interpreters})


def add_interpreter(info):
    """登记一个解释器 (同 dir 覆盖), 保存后返回最新列表."""
    lst = [x for x in load_interpreters() if x.get('dir') != info.get('dir')]
    lst.append(info)
    save_interpreters(lst)
    return lst


def set_default_interpreter(info):
    """把指定解释器设为默认 (其余清 default). 返回最新列表."""
    lst = load_interpreters()
    for x in lst:
        x['default'] = bool(info and x.get('dir') == info.get('dir'))
    save_interpreters(lst)
    return lst


def default_interpreter():
    """返回默认解释器; 无显式默认时取列表第一个."""
    lst = load_interpreters()
    for x in lst:
        if x.get('default'):
            return x
    return lst[0] if lst else None


def remove_interpreter(info):
    """从配置移除一个解释器 (不删磁盘文件). 返回最新列表."""
    lst = [x for x in load_interpreters() if x.get('dir') != info.get('dir')]
    save_interpreters(lst)
    return lst


# ---------------- 项目配置 (projects.json) ----------------
def load_projects():
    _maybe_migrate_ledger(PROJECTS_FILE, LEGACY_PROJECTS_FILE, 'projects')
    data = load_json(PROJECTS_FILE)
    return data.get('projects', []) if data else []


def save_projects(projects):
    _ensure_parent(PROJECTS_FILE)
    save_json_atomic(PROJECTS_FILE, {"projects": projects})


def add_project(name, scene, version=None, engine_dir=None):
    """登记项目 (同 scene 覆盖). 返回最新列表.

    2026-10-19 A2 归属模型: 加 engine_dir 字段（该项目的归属引擎根目录）.
    - engine_dir=None: 尝试从 scene 路径推断（在某个 /Projects/ 或 /保存/ 下）
    - 推断失败: 保持 None（视为"外部项目"）
    """
    if engine_dir is None:
        engine_dir = infer_engine_dir(scene)
    lst = [x for x in load_projects() if x.get('scene') != scene]
    lst.append({
        "name": name,
        "scene": scene,
        "version": version,
        "engine_dir": engine_dir,   # 2026-10-19 归属引擎
    })
    save_projects(lst)
    return lst


def infer_engine_dir(scene_path):
    """从 scene 路径推断归属引擎根目录.
    规则: 路径形如 <engine_dir>/Projects/xxx.json 或 <engine_dir>/保存/xxx.json
          则返回 <engine_dir>; 否则返回 None.
    """
    if not scene_path:
        return None
    try:
        norm = os.path.abspath(scene_path)
    except Exception:
        return None
    for sub in (SAVE_DIR_NAME, LEGACY_SAVE_DIR_NAME):
        sep = os.sep + sub + os.sep
        idx = norm.find(sep)
        if idx > 0:
            return norm[:idx]
    return None


def remove_project(scene):
    """从列表移除项目 (不删磁盘文件). 返回最新列表."""
    lst = [x for x in load_projects() if x.get('scene') != scene]
    save_projects(lst)
    return lst


# ---------------- 项目发现 / 保存目录扫描 (2026-08-12) ----------------
# 2026-10-19 用户拍板 B2: 项目目录从"保存"改为"Projects"（Unity 习惯，更直观）
# 兼容：scan 时同时扫 保存/ 和 Projects/（老场景文件不会消失）
SAVE_DIR_NAME = "Projects"
LEGACY_SAVE_DIR_NAME = "保存"
SCENE_SUFFIX = "_场景"       # 新建场景默认命名 <名>_场景.json


def interpreter_save_dir(info=None):
    """解释器目录下的默认项目文件夹 (Loom 编辑器保存场景的位置).
    info 缺省取默认解释器; 无解释器返回 None. 目录可能尚未创建, 返回路径即可.
    2026-10-19 B2: 默认 "Projects"（旧版是 "保存"）."""
    info = info or default_interpreter()
    if info is None or not info.get('dir'):
        return None
    return os.path.join(info['dir'], SAVE_DIR_NAME)


def interpreter_legacy_save_dir(info=None):
    """旧版保存目录（"保存/"）—— 迁移/扫描时兼容用（2026-10-19 B2）."""
    info = info or default_interpreter()
    if info is None or not info.get('dir'):
        return None
    return os.path.join(info['dir'], LEGACY_SAVE_DIR_NAME)


def discover_project(directory):
    """分析一个目录, 找项目场景文件 (如同 discover_interpreter 之于解释器).
    优先 <目录名>_场景.json (编辑器默认命名), 否则按名取第一个 *.json.
    返回 (name, scene_path) 或 None (目录不存在/无场景文件)."""
    if not directory or not os.path.isdir(directory):
        return None
    base = os.path.basename(os.path.normpath(directory))
    jsons = sorted(f for f in os.listdir(directory)
                   if f.lower().endswith('.json')
                   and os.path.isfile(os.path.join(directory, f)))
    if not jsons:
        return None
    for f in jsons:
        if f.startswith(base + SCENE_SUFFIX):
            return base, os.path.join(directory, f)
    return os.path.splitext(jsons[0])[0], os.path.join(directory, jsons[0])


def scan_save_dir_projects(save_dir=None, engine_dir=None):
    """扫描项目目录下的场景文件, 全部登记为项目 (同 scene 幂等覆盖).

    save_dir : 显式指定扫描目录（None = 从 engine_dir 推断）
    engine_dir: 归属引擎根目录（None = 默认解释器）

    2026-10-19 B2: 同时扫描 Projects/ 和旧版 保存/（向后兼容）.
    返回本次登记的 [(name, scene)].
    """
    # 解析 engine_dir
    if engine_dir is None and save_dir is None:
        info = default_interpreter()
        if info is not None:
            engine_dir = info.get('dir')
    # 收集待扫描目录
    dirs = []
    if save_dir:
        dirs.append(save_dir)
    elif engine_dir:
        dirs.append(os.path.join(engine_dir, SAVE_DIR_NAME))
        # 兼容旧版：如果 Projects/ 还没建，扫旧版 保存/
        legacy = os.path.join(engine_dir, LEGACY_SAVE_DIR_NAME)
        if os.path.isdir(legacy) and legacy not in dirs:
            dirs.append(legacy)
    added = []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            path = os.path.join(d, f)
            if f.lower().endswith('.json') and os.path.isfile(path):
                base = os.path.splitext(f)[0]
                name = (base[:-len(SCENE_SUFFIX)]
                        if base.endswith(SCENE_SUFFIX) else base)
                add_project(name, path, engine_dir=engine_dir)
                added.append((name, path))
    return added


# ---------------- 系统默认 Python + 启动命令 ----------------
def _py_launcher_python():
    r"""从 .py 文件关联 (Python.File\shell\open\command) 解析系统默认 python 路径.
    用户把 .py 默认打开应用绑定到某个 Python, 这就是"系统默认环境";
    **注意**: 系统默认可能仍是旧版（如 3.12），而新版源码引擎要求 3.13 ——
    源码版按 解释器.json 的 python_version 精确挑解释器（见 resolve_python_for）。
    找不到则返回 None."""
    import re
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Classes\Python.File\shell\open\command")
        cmd, _ = winreg.QueryValueEx(key, "")
        m = re.search(r'"([^"]+\.exe)"', cmd)
        if m and os.path.isfile(m.group(1)):
            return m.group(1)
    except Exception:
        pass
    return None


_PY_RESOLVE_CACHE = {}


def bundled_python(engine_dir):
    r"""源码包布局下的**包内解释器**：<发布根>pythonpython.exe。

    发布包结构（package_engine 产出）:
        <发布根>LoomLoom.py      <- 登记的解释器目录 engine_dir
        <发布根>pythonpython.exe <- 自足运行时（pip --target 装的依赖都在里面）

    2026-11-10 Q2=A 人类裁决：包内 Python 是**权威** —— 以前系统解释器会把它顶掉，
    结果包内依赖（pip --target 装进 pythonLibsite-packages 的）用不到，
    engine.py 直接 ModuleNotFoundError；再叠上 pythonw + LOOM_QUIET，
    用户只看到「已启动」。只有包内缺失/不可执行时才回退系统解释器。
    """
    if not engine_dir:
        return None
    root = os.path.dirname(os.path.abspath(engine_dir))   # <发布根>
    exe = os.path.join(root, 'python', 'python.exe')
    if not os.path.isfile(exe):
        return None
    # 自足性判据：必须带 site-packages（依赖装在这里）；明明是空壳就别当权威
    if not os.path.isdir(os.path.join(root, 'python', 'Lib', 'site-packages')):
        return None
    return exe


def python_xy(spec):
    """'3.13.15' / '3.13' / 'python3.13' -> '3.13'；认不出返回 ''。"""
    m = re.search(r'(\d+)\.(\d+)', str(spec or ''))
    return '%s.%s' % (m.group(1), m.group(2)) if m else ''


def resolve_python_for(spec, use_cache=True):
    r"""按 解释器.json 的 python_version 找可用的 python.exe（绝对路径或 None）。

    2026-11-09: 源码版引擎要求 3.13（系统默认 .py 关联仍是 3.12），但**不改系统默认**
    —— 只在启动这一个引擎时精确挑解释器。顺序：
      ① %LOCALAPPDATA%ProgramsPythonPythonXYpython.exe 等常见安装目录
      ② py -X.Y 启动器问出 sys.executable
      ③ 当前进程解释器正好是该版本
    """
    xy = python_xy(spec)
    if not xy:
        return None
    if use_cache and xy in _PY_RESOLVE_CACHE:
        # 2026-11-09 A-04④: 缓存必须复核存在性 —— Python 被卸载/移动后
        # 以前会一直返回死路径（实测删除后仍返回）。
        hit = _PY_RESOLVE_CACHE[xy]
        if hit and os.path.isfile(hit):
            return hit
        _PY_RESOLVE_CACHE.pop(xy, None)
    tag = 'Python' + xy.replace('.', '')
    bases = []
    la = os.environ.get('LOCALAPPDATA')
    if la:
        bases.append(os.path.join(la, 'Programs', 'Python'))
    for k in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'):
        v = os.environ.get(k)
        if v:
            bases.append(v)
    bases.append('C:\\')
    for base in bases:
        for cand in (os.path.join(base, tag, 'python.exe'),
                     os.path.join(base, 'Python' + xy.replace('.', ''), 'python.exe')):
            if os.path.isfile(cand):
                _PY_RESOLVE_CACHE[xy] = cand
                return cand
    launcher = shutil.which('py')
    if launcher:
        try:
            r = subprocess.run([launcher, '-%s' % xy, '-c',
                                'import sys;print(sys.executable)'],
                               capture_output=True, text=True, timeout=8)
            lines = (r.stdout or '').strip().splitlines()
            if r.returncode == 0 and lines and os.path.isfile(lines[-1]):
                _PY_RESOLVE_CACHE[xy] = lines[-1]
                return lines[-1]
        except (OSError, subprocess.SubprocessError):
            pass
    # ③ 当前解释器是否正好是该版本。
    # 2026-11-10 Q5=B 人类裁决：**不再起子进程询问版本** —— 冻结版里
    # sys.executable 指向 LoomHub.exe，拉起它等于再开一个 Hub 抢焦点。
    # 直接读 sys.version_info；冻结态更不能用 Hub 自己当 Python（返回 None）。
    if getattr(sys, 'frozen', False):
        return None
    try:
        cur = '%d.%d' % (sys.version_info[0], sys.version_info[1])
    except (AttributeError, TypeError, IndexError):
        return None
    if cur == xy and os.path.isfile(sys.executable):
        _PY_RESOLVE_CACHE[xy] = sys.executable
        return sys.executable
    return None


def scene_version(default=10):
    """场景序列化版本：以 Loom/sceneio.SCENE_VERSION 为单一事实源。

    2026-11-09 A-04⑧: Hub 两处新建场景曾分别写 v8（controller）与 v10（commands），
    与 sceneio 现行版本（v10）不一致。这里统一收口；sceneio 不可导入时回退 default。
    """
    try:
        import sceneio
        return int(getattr(sceneio, 'SCENE_VERSION', default))
    except (ImportError, TypeError, ValueError):
        return default


def probe_started(proc, wait=1.5):
    """启动后短窗口内查存活，返回 (alive, exit_code_or_None)。

    2026-11-09 A-04⑤: 启动走 pythonw + LOOM_QUIET，子进程立刻崩掉时 Popen 本身
    不报错 —— 以前一律显示"已启动"，用户以为起来了。这里用 poll() 探一次。
    """
    deadline = time.time() + max(0.0, float(wait))
    while True:
        rc = proc.poll()
        if rc is not None:
            return False, rc
        if time.time() >= deadline:
            return True, None
        time.sleep(0.05)


def python_source(info):
    """这次启动会用哪种 Python：'exe' / 'bundled' / 'declared' / 'default'。

    供 UI/命令层说明用（也是 Q2=A 的断言锚点）。
    """
    if not info or info.get('kind') == 'exe':
        return 'exe'
    if bundled_python(info.get('dir')):
        return 'bundled'
    want = str(info.get('python_version') or '').strip()
    if want and resolve_python_for(want):
        return 'declared'
    return 'default'


def _release_python_dir(engine_dir):
    if not engine_dir:
        return None
    d = os.path.join(os.path.dirname(os.path.abspath(engine_dir)), 'python')
    return d if os.path.isdir(d) else None


def interp_python_note(info):
    """启动源码引擎时的 Python 版本提示（空串 = 无需提示）。

    返回非空表示"引擎要求 X，本机没找到匹配解释器，已回退默认"。
    """
    if not info or info.get('kind') == 'exe':
        return ''
    if bundled_python(info.get('dir')):
        return ''                    # 包内自足运行时，不需要任何提示
    # 发布布局里 python/ 目录在，但不可用（缺 python.exe / 缺 site-packages）
    # -> 明确告知"包内运行时不可用，已回退"，否则用户只会看到「已启动」
    _pydir = _release_python_dir(info.get('dir'))
    if _pydir and not bundled_python(info.get('dir')):
        return ('引擎包内 python 不可用（%s），已回退系统解释器 —— '
                '依赖可能缺失，建议用 LoomHub 重装该引擎版本' % _pydir)
    want = str(info.get('python_version') or '').strip()
    if not want:
        # 元数据没声明版本：仍按系统默认 Python 启动，但要让用户知道原因
        return '引擎元数据未声明 python_version，使用系统默认 Python 启动'
    if resolve_python_for(want):
        return ''
    return ('引擎要求 Python %s，本机未找到匹配解释器，已回退默认 Python'
            '（可能启动失败，请安装 Python %s 或 py -%s）'
            % (want, python_xy(want) or want, python_xy(want) or want))


def default_python(engine_dir=None):
    """系统默认 python 命令. 2026-08-20 安全加固 (Qoder 报告低危8):
    优先当前进程自己的解释器 (sys.executable, 最可信, 不受 PATH 污染),
    再回退 .py 默认打开应用绑定的解释器; PATH 兜底最后才用.

    2026-10-19 关键修复（PyInstaller 打包后启动 Loom 失败根因）:
      - LoomHub 打包成 exe 后 sys.executable = LoomHub.exe，不是 python
      - 直接用它启动 Loom.py 会"再启动一个 LoomHub"，被单实例锁拦截 -> 看起来没反应
      - 修复：检测 sys.frozen 跳过 sys.executable；优先用引擎自带嵌入式 python

    engine_dir: 引擎源码目录（如 <engine>/Loom），用于定位同级 <engine>/python/python.exe
    """
    import sys
    # 1. 引擎自带嵌入式 Python 优先（发布包 zip 设计如此：开箱即用）
    if engine_dir:
        try:
            py_dir = os.path.join(os.path.dirname(os.path.abspath(engine_dir)), 'python')
            emb = os.path.join(py_dir, 'python.exe')
            if os.path.isfile(emb):
                return emb
        except Exception:
            pass
    # 2. PyInstaller 打包环境：sys.executable = LoomHub.exe，不能用
    if not getattr(sys, 'frozen', False):
        if getattr(sys, 'executable', None):
            return sys.executable
    # 3. 系统 py 启动器
    p = _py_launcher_python()
    if p:
        return p
    # 4. PATH
    p = shutil.which('python')
    if p:
        return p
    return 'python'


def python_version(cmd=None, engine_dir=None):
    """返回默认 python 的版本字符串 (如 '3.13.15'), 不可用返回 None.

    2026-10-19: 加 engine_dir 参数（PyInstaller 环境 sys.executable = LoomHub.exe 时，
    必须传引擎目录才能拿到嵌入式 python 版本）."""
    try:
        exe = cmd or default_python(engine_dir=engine_dir)
        out = subprocess.run([exe, "--version"],
                             capture_output=True, text=True, timeout=10)
        txt = (out.stdout or out.stderr).strip()
        if "Python" in txt:
            return txt.split("Python ", 1)[1].strip()
        return None
    except Exception:
        return None


def build_launch_command(info, scene_path=None, mode='open', prefer=None):
    """构造启动解释器命令 (list).

    注意（2026-11-09 A-04⑥，改注释而不是改结构）: 本函数**不是零副作用** ——
    源码版引擎若声明了 python_version，会调用 resolve_python_for() 解析解释器，
    首次可能起最多 2 个子进程（py 启动器 + 当前解释器，超时 8s/5s，结果缓存且
    带存在性复核）。理由：解析结果必须与"这一次启动"绑在一起，放到后台线程会让
    UI 先发出一个用错解释器的命令；而缓存 + 5~8s 上限把最坏卡顿收敛到一次性。
    .py 默认仍用系统默认 python；.exe 直接运行.
    mode: 'open' = 编辑器打开项目场景 / 'run' = 播放场景 / None = 纯启动编辑器.
    prefer: None=按 kind 默认 / 'py'=优先 .py 源码 / 'exe'=优先 .exe 封装
    (启动器设置 open_py, 2026-08-14; 无对应文件时回退按 kind)."""
    # 2026-10-19 启动路径 bug 修复：所有路径经 resolve_runtime_path 解析成绝对路径，
    # 避免 Popen(cwd=相对) + argv[1]=相对 在子进程里二次拼接出错。
    main_py = resolve_runtime_path(info.get('main_py'))
    main_exe = resolve_runtime_path(info.get('main_exe'))
    main_path = resolve_runtime_path(info.get('path'))
    # 2026-10-19: 传 engine_dir 让 default_python 优先用引擎自带嵌入式 Python
    # 顺序（2026-11-10 Q2=A + 11-09 python_version 口径合并）：
    #   ① 包内 pythonpython.exe（自足包）—— **权威**，系统解释器不得顶替
    #   ② 否则系统默认 python
    #   ③ 源码版声明了 python_version 且能解析 -> 用匹配版本
    #   ④ 都拿不到 -> 系统默认（并给提示）
    # 编译版（kind=exe）走 main_exe，与 Python 版本无关，不受影响。
    _bundled = bundled_python(info.get('dir'))
    py_exe = _bundled or default_python(engine_dir=info.get('dir'))
    if not _bundled and str(info.get('kind') or 'py') != 'exe':
        _want = str(info.get('python_version') or '').strip()
        if _want:
            _matched = resolve_python_for(_want)
            if _matched:
                py_exe = _matched
    if prefer == 'py' and main_py and os.path.isfile(main_py):
        cmd = [py_exe, main_py]
    elif prefer == 'exe' and main_exe and os.path.isfile(main_exe):
        cmd = [main_exe]
    elif info.get('kind') == 'exe':
        cmd = [main_path]
    else:
        cmd = [py_exe, main_path]
    if scene_path:
        cmd += ['--open' if mode == 'open' else '--run', scene_path]
    # 2026-11-08 D3=A 人类裁决: 本函数**只做纯命令拼装**，不再在此追加 --agent。
    # 原因: 它是被单测逐元素断言其返回值的纯函数，"打开编辑器就带 Agent 桥"属于
    # 调用方的业务决定（hub_controller.open_project 负责追加），塞在这里会让
    # "纯拼装"契约与"编辑器要带 Agent"契约在同一个返回值上打架。
    return cmd


# ---------------- Hub 设置（用户层收口, 契约 2026-11-08 §2/§4/§7） ----------------
# 为什么不能继续写"程序目录\设置.json"：LoomHub 默认装到 {autopf}\LoomHub，
# 普通用户对安装目录只有读权限（契约 §0）。旧实现 load 静默回落、save 抛异常，
# 表现为"设置面板改了没保存/一重启就丢"。
# 分层：默认 <- 模板(安装目录里的 设置.json, 只读) <- 用户层 delta。
HUB_SETTINGS_NAME = "设置.json"
DEFAULT_HUB_SETTINGS = {
    "gui": "TkHubView",
    "open_py": True,
    # 2026-11-09 H1: 离屏 GL 回读兜底。现场 A/B（同场景同引擎）：
    #   直连 55/59/61 FPS、TPS 23.7；remote-mode 38/38/41 FPS、TPS 18.9。
    # 因此**默认 off**（不再无条件注入 LOOM_REMOTE_MODE=1）；on 留给确实白屏的机器，
    # auto 留给引擎侧自动降级（beta5 的 E2 再做，Hub 侧对 auto 也不注入）。
    "remote_mode": "off",
    # 2026-11-10: 引擎安装根（空 = 用自适应默认）。写用户层 delta，重启后仍生效。
    "install_root": "",
    # 2026-11-09 H2: 自更新检查（后台线程 / 24h 最多一次 / 失败静默）
    "check_update_enabled": True,
}
REMOTE_MODES = ("auto", "off", "on")


def _userpaths():
    """用户目录收口模块；不可用时返回 None（磁盘异常等极端情况）。

    2026-11-08 第 5b 批: 改为优先 hub_userpaths（见本文件顶部的 _hub_userpaths）。
    以前只认 Loom 的 userpaths，而它不在 LoomHub 安装包的可导入路径上 -> 安装版里
    静默退化成"写程序目录"，这就是"设置改了没保存"的真因。
    """
    return _hub_userpaths()


def hub_settings_template():
    r"""模板层（只读）: <LoomHub 程序目录>\设置.json（随安装包更新）。"""
    return os.path.join(HUB_DIR, HUB_SETTINGS_NAME)


def hub_settings_file():
    r"""用户层（可写）: %LOCALAPPDATA%\Loom\hub\settings.json。"""
    up = _userpaths()
    if up is None:
        return hub_settings_template()   # 降级：保持旧行为，不崩
    return up.hub_settings()


def _settings_values(d):
    """统一"新格式 {schema,values}"与"旧格式 plain dict"。"""
    if not isinstance(d, dict):
        return {}
    if "schema" in d and isinstance(d.get("values"), dict):
        return dict(d["values"])
    return dict(d)


def _read_settings_layer(path, what):
    """读一层设置：缺文件 -> {}；坏 JSON -> 备份 + {}（出声，不静默）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _settings_values(json.load(f))
    except FileNotFoundError:
        return {}
    except Exception as e:
        print("[设置] %s 损坏 (%r): %s -> 备份后按默认" % (what, e, path))
        up = _userpaths()
        try:
            dst = up.backup_path(path) if up is not None else path + ".bak"
            os.replace(path, dst)
        except Exception as e2:
            print("[设置] 备份失败 (%r)，继续按默认运行" % (e2,))
        return {}


def _hub_settings_base():
    """默认 + 模板层 = "用户没改过"的基线（delta 判定用）。"""
    base = dict(DEFAULT_HUB_SETTINGS)
    base.update(_read_settings_layer(hub_settings_template(), "模板 设置.json"))
    return base


def hub_settings_delta(settings):
    """算出应写进用户层的 delta（只存用户真正改过的键）。"""
    base = _hub_settings_base()
    return {k: v for k, v in dict(settings or {}).items()
            if k not in base or base[k] != v}


def _maybe_migrate_legacy_settings():
    """首次运行: 把程序目录里的旧 设置.json 的"非默认键"搬进用户层。

    旧文件**保留不动**（可能是随版本下发的模板，也可能是老版本写进去的用户设置）。
    迁移失败只打印，不阻断启动（用户层随后仍可正常保存）。
    """
    tpl = hub_settings_template()
    upath = hub_settings_file()
    if os.path.abspath(upath) == os.path.abspath(tpl):
        return            # 降级路径：只有一份文件，没什么可搬
    if os.path.exists(upath):
        return            # 用户层已存在 -> 以用户层为准
    legacy_path = LEGACY_SETTINGS_FILE
    if not legacy_path or not os.path.isfile(legacy_path):
        return
    legacy = _read_settings_layer(legacy_path, '旧 设置.json')
    delta = {k: v for k, v in legacy.items()
             if k not in DEFAULT_HUB_SETTINGS or DEFAULT_HUB_SETTINGS[k] != v}
    if not delta:
        return
    try:
        save_hub_settings(dict(DEFAULT_HUB_SETTINGS, **legacy))
        print('[设置] 已把旧设置迁移到用户目录: %s -> %s（%s）'
              % (legacy_path, upath, sorted(delta)))
    except Exception as e:
        print('[设置] 旧设置迁移失败（不影响本次启动，用户层可随后保存）: %r' % (e,))


def hub_remote_mode(settings=None):
    """Hub 设置 remote_mode 归一：auto|off|on；非法值回落 off（默认 off）。"""
    s = load_hub_settings() if settings is None else (settings or {})
    v = str(s.get("remote_mode") or "off").strip().lower()
    return v if v in REMOTE_MODES else "off"


def apply_launch_env(env, settings=None):
    """按 Hub 设置决定是否给子进程注入 LOOM_REMOTE_MODE（H1 的唯一实现点）。

    · off / auto -> **不注入**（auto 的自动降级由引擎侧 beta5 E2 实现）
    · on         -> 注入 '1'
    两条启动路径（GUI open_project 与命令层 launch_spec）都调这里，保证一致；
    也保证环境里残留的值不会漏进子进程（先 pop 再按设置决定）。
    """
    mode = hub_remote_mode(settings)
    env.pop("LOOM_REMOTE_MODE", None)
    if mode == "on":
        env["LOOM_REMOTE_MODE"] = "1"
    return env


def load_hub_settings():
    """读 Hub 设置 = 默认 <- 模板 <- 用户层 delta（契约 §4 合并规则）。

    旧位置（安装目录里的 设置.json）本身就是"模板层"，仍然被读取，所以老值继续
    生效、无需搬迁；用户之后改的键写进用户层 delta，优先级高于模板（升级换模板
    也不会覆盖用户的选择）。
    """
    _maybe_migrate_legacy_settings()
    merged = _hub_settings_base()
    upath = hub_settings_file()
    if os.path.abspath(upath) == os.path.abspath(hub_settings_template()):
        return merged            # 降级路径：只有一份文件，已合并
    merged.update(_read_settings_layer(upath, "用户 设置.json"))
    return merged


def save_hub_settings(settings):
    """写 Hub 设置：只写 delta，tmp + os.replace 原子写；失败**上抛**（契约 §7）。"""
    path = hub_settings_file()
    up = _userpaths()
    payload = {
        "schema": 1,
        "app": "loomhub",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "values": hub_settings_delta(settings),
    }
    parent = os.path.dirname(os.path.abspath(path))
    if up is not None:
        up.ensure_dir(parent)
    else:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path
