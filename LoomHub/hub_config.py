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

APP_NAME = "Loom"          # 解释器名 = 项目名
HUB_NAME = "LoomHub"       # 项目管理器名 = 解释器名 + "Hub"
HUB_DIR = os.path.dirname(os.path.abspath(__file__))
INTERPRETERS_FILE = os.path.join(HUB_DIR, "interpreters.json")
PROJECTS_FILE = os.path.join(HUB_DIR, "projects.json")
PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")
DEFAULT_INSTALL_ROOT = os.path.join(PROGRAM_FILES, APP_NAME)   # C:\Program Files\Loom
META_NAME = "解释器.json"   # 解释器元数据文件名 (每个版本目录内)


# ---------------- 通用 JSON 读写 ----------------
def save_json_atomic(path, data):
    """原子写 JSON: 先写临时文件再 os.replace, 防中途断电损坏."""
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
def load_interpreters():
    data = load_json(INTERPRETERS_FILE)
    return data.get('interpreters', []) if data else []


def save_interpreters(interpreters):
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
    data = load_json(PROJECTS_FILE)
    return data.get('projects', []) if data else []


def save_projects(projects):
    save_json_atomic(PROJECTS_FILE, {"projects": projects})


def add_project(name, scene, version=None):
    """登记项目 (同 scene 覆盖). 返回最新列表."""
    lst = [x for x in load_projects() if x.get('scene') != scene]
    lst.append({"name": name, "scene": scene, "version": version})
    save_projects(lst)
    return lst


def remove_project(scene):
    """从列表移除项目 (不删磁盘文件). 返回最新列表."""
    lst = [x for x in load_projects() if x.get('scene') != scene]
    save_projects(lst)
    return lst


# ---------------- 项目发现 / 保存目录扫描 (2026-08-12) ----------------
SAVE_DIR_NAME = "保存"      # Loom 编辑器默认保存文件夹名 (editor.py DEFAULT_SAVE_DIR)
SCENE_SUFFIX = "_场景"       # 新建场景默认命名 <名>_场景.json


def interpreter_save_dir(info=None):
    """解释器目录下的默认保存文件夹 (Loom 编辑器保存场景的位置).
    info 缺省取默认解释器; 无解释器返回 None. 目录可能尚未创建, 返回路径即可."""
    info = info or default_interpreter()
    if info is None or not info.get('dir'):
        return None
    return os.path.join(info['dir'], SAVE_DIR_NAME)


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


def scan_save_dir_projects(save_dir=None):
    """扫描保存目录下的场景文件, 全部登记为项目 (同 scene 幂等覆盖).
    save_dir 缺省取默认解释器的保存目录. 返回本次登记的 [(name, scene)]."""
    d = save_dir or interpreter_save_dir()
    if not d or not os.path.isdir(d):
        return []
    added = []
    for f in sorted(os.listdir(d)):
        path = os.path.join(d, f)
        if f.lower().endswith('.json') and os.path.isfile(path):
            base = os.path.splitext(f)[0]
            name = base[:-len(SCENE_SUFFIX)] if base.endswith(SCENE_SUFFIX) else base
            add_project(name, path)
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


def default_python():
    """系统默认 python 命令. 2026-08-20 安全加固 (Qoder 报告低危8):
    优先当前进程自己的解释器 (sys.executable, 最可信, 不受 PATH 污染),
    再回退 .py 默认打开应用绑定的解释器; PATH 兜底最后才用."""
    import sys
    if getattr(sys, 'executable', None):
        return sys.executable
    p = _py_launcher_python()
    if p:
        return p
    p = shutil.which('python')
    if p:
        return p
    return 'python'


def python_version(cmd=None):
    """返回默认 python 的版本字符串 (如 '3.12.10'), 不可用返回 None."""
    try:
        out = subprocess.run([cmd or default_python(), "--version"],
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
    if prefer == 'py' and info.get('main_py') and os.path.isfile(info['main_py']):
        cmd = [default_python(), info['main_py']]
    elif prefer == 'exe' and info.get('main_exe') and os.path.isfile(info['main_exe']):
        cmd = [info['main_exe']]
    elif info.get('kind') == 'exe':
        cmd = [info['path']]
    else:
        cmd = [default_python(), info['path']]
    if scene_path:
        cmd += ['--open' if mode == 'open' else '--run', scene_path]
    return cmd
