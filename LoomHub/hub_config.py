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
            "main_py": py_path, "main_exe": exe_path}   # 双路径 (open_py 启动器设置用)


def scan_install_root(root=DEFAULT_INSTALL_ROOT):
    r"""扫描解释器安装根目录 (C:\Program Files\Loom), 按版本号子目录逐个分析.
    返回已安装解释器列表 (按版本号升序)."""
    result = []
    if not os.path.isdir(root):
        return result
    for entry in sorted(os.listdir(root)):
        sub = os.path.join(root, entry)
        if os.path.isdir(sub):
            info = discover_interpreter(sub)
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


# ---------------- 项目名清洗 ----------------
_FILENAME_ILLEGAL = set('\\/:*?"<>|')   # Windows 文件名非法字符


def sanitize_name(name):
    """把项目名清洗为 Windows 安全的文件名字段: 非法字符 (\\/:*?"<>|) 替换为 _,
    再去首尾空白. 返回清洗后字符串 (可能为空, 由调用方决定是否拦截).
    全角符号 (如中文冒号：) 不是 Windows 非法字符, 保持原样."""
    return ''.join('_' if ch in _FILENAME_ILLEGAL else ch
                   for ch in str(name)).strip()


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
    用户已把 .py 默认打开应用绑定到 3.12.10, 这就是"系统默认环境";
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
    """返回默认 python 的版本字符串 (如 '3.12.10'), 不可用返回 None.

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
    .py 用系统默认 python (UI 会提醒"使用系统默认环境"); .exe 直接运行.
    mode: 'open' = 编辑器打开项目场景 / 'run' = 播放场景 / None = 纯启动编辑器.
    prefer: None=按 kind 默认 / 'py'=优先 .py 源码 / 'exe'=优先 .exe 封装
    (启动器设置 open_py, 2026-08-14; 无对应文件时回退按 kind)."""
    # 2026-10-19 启动路径 bug 修复：所有路径经 resolve_runtime_path 解析成绝对路径，
    # 避免 Popen(cwd=相对) + argv[1]=相对 在子进程里二次拼接出错。
    main_py = resolve_runtime_path(info.get('main_py'))
    main_exe = resolve_runtime_path(info.get('main_exe'))
    main_path = resolve_runtime_path(info.get('path'))
    # 2026-10-19: 传 engine_dir 让 default_python 优先用引擎自带嵌入式 Python
    py_exe = default_python(engine_dir=info.get('dir'))
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
DEFAULT_HUB_SETTINGS = {"gui": "TkHubView", "open_py": True}


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
