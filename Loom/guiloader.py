# -*- coding: utf-8 -*-
"""
guiloader.py — Loom / LoomHub 可插拔 GUI 加载器 (2026-08-14)
============================================================
让两个程序支持"放文件即换界面"：

  Loom 自定义 GUI   : <程序目录>/GUI/XXXGUI.py        (文件名以 GUI.py 结尾, 不以 HubGUI.py 结尾)
  LoomHub 自定义 GUI: <程序目录>/GUI/XXXHubGUI.py     (文件名以 HubGUI.py 结尾)

接入标准（GUI 标准接入方法）：
  1. 文件名后缀符合上面规则（扫描只认后缀，避免把别的 .py 当 GUI）。
  2. 文件头部（前 8 行内）含前部标识：  `# gui: loom`  或  `# gui: loomhub`
     （只做文本解析、不 import —— 只有标识合法的文件才进可用列表，避免导入坏文件崩溃）。
  3. 实现对应契约：Loom→`ui.editor_ui.IEditorView`；LoomHub→`hub_controller.IHubView`。
  4. 提供工厂：`def build_gui(controller=None)` 返回视图实例。

可选头部： `# gui-name: 显示名`、`# gui-desc: 描述`。

程序目录 = 源码时 Loom.py / LoomHub.py 所在目录；编译版 = exe 所在目录
（统一用 `os.path.dirname(os.path.abspath(sys.argv[0]))`，与 game_player 同款）。
设置文件（2026-11-08 用户配置目录契约）:
  模板层 = `<程序目录>\设置.json` —— **只读**（发布夹/引擎目录，随版本更新）
  用户层 = `%LOCALAPPDATA%\Loom\{engine,hub}\settings.json` —— 只存 delta
  合并   = 默认 <- 模板 <- 用户层；写入一律 tmp + os.replace，失败上抛。
"""
import importlib.util
import json
import os
import sys

# 程序标识 -> 官方 GUI id / 文件后缀规则 / 前部标识
# 2026-08-17: loomhub 官方默认 = TkHubView (tkinter) —— pygame LoomHubGUI 因 SDL
# 窗口进程级污染中文输入法候选框被弃用 (见记忆 sdl-window-contaminates-ime).
OFFICIAL = {'loom': 'LoomGUI', 'loomhub': 'TkHubView'}
SUFFIX = {'loom': 'GUI.py', 'loomhub': 'HubGUI.py'}
MARKER = {'loom': '#gui:loom', 'loomhub': '#gui:loomhub'}   # 归一化(去空格)后比较

DEFAULT_SETTINGS = {
    'loom': {'gui': 'LoomGUI', 'save_dir': '',
             'parallel_enable': True, 'script_cores': 2, 'show_grid': True,
             'fps_limit': 'unlimited', 'precise_limit': True,
             'cam_speed': 1.0, 'gravity': -9.8,
             'logic_fps': 30,   # 分离批5: 逻辑帧=最高同步 (物理为帧内自动子步; 物理步长=内部参数 phys_substep_dt, 不向用户暴露)
             'interp_mode': 'interpolate',   # 方案二: 渲染位姿 'interpolate'(默认)/'extrapolate' (落点帧自动回退)
             'frame_buffer_tps': False,   # TPS 缓冲实验 (2026-09-06): 逻辑帧预取; 闸门 logic_fps>=30
             'frame_buffer_fps': False,   # FPS 缓冲实验 (2026-09-06): 渲染帧预画; 闸门 fps_limit>=60 且非无上限/auto
             'render_api': 'vulkan'},   # 播放器/发布游戏默认渲染 API (编辑器选)
    'loomhub': {'gui': 'TkHubView', 'open_py': True},
}

# 编辑器帧率上限档位 (2026-08-19): 档位 id -> 渲染循环周期 ms.
# 档位模式 (30-240): 校准开 (precise_limit, 默认 True) 时帧首对齐固定节拍网格
# (loom_gui._wait_until 混合等待, Panda3D wait_until 语义) — QTimer 到达抖动
# 分量消除, 实际节律贴目标周期 (限帧器校准, 2026-09-05 方案一).
# 'unlimited' = 无上限: 不做 pacing (kivy maxfps=0 同款, 无目标周期; QTimer 1ms
# 仅作唤醒源), 抖动源=逻辑帧落点双峰, 由帧长观测 (get_frame_jitter) 量化 +
# 外推模式 (interp_mode=extrapolate) 缓解.
# 'auto' = 按设备检测 (对齐 Unity 社区按 SystemInfo 硬件分级写帧率表的实践,
# 见 device_fps_limit).
FPS_LIMITS = {'30': 33, '60': 16, '90': 11, '120': 8, '240': 4, 'unlimited': 1}
FPS_OPTIONS = [('30fps', '30'), ('60fps', '60'), ('90fps', '90'),
               ('120fps', '120'), ('240fps', '240'), ('无上限', 'unlimited'),
               ('自动（按设备）', 'auto')]


def device_fps_limit():
    """按设备硬件给推荐帧率档位 (对齐 Unity 社区"设备帧率表"实践):
    CPU 逻辑核心 + 系统物理内存 -> 30/60/120/240. 游戏/编辑器帧率上限表,
    低端设备限制帧率避免卡顿 (用户 GPU/CPU 不同开放不同档位的思路)."""
    import ctypes
    import multiprocessing
    try:
        cores = multiprocessing.cpu_count()
    except Exception:
        cores = 8
    mem_gb = 0.0
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong),
                        ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong),
                        ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        mem_gb = ms.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    if cores <= 4 or mem_gb < 8:
        return '30'
    if cores <= 8 or mem_gb < 16:
        return '60'
    if cores <= 16 or mem_gb < 32:
        return '120'
    return '240'


def program_dir(program, base=None):
    """程序目录: base 优先(测试用), 否则 sys.argv[0] 所在目录 (源码=程序目录/编译版=exe 目录)."""
    if base is not None:
        return os.path.abspath(base)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def gui_folder(program, base=None):
    """自定义 GUI 存放文件夹 = <程序目录>/GUI."""
    return os.path.join(program_dir(program, base), 'GUI')


def _userpaths():
    """用户目录收口模块（契约 §2）。不可用时退回旧语义（LoomHub 单独分发时）。"""
    try:
        import userpaths
        return userpaths
    except Exception:
        return None


def settings_path(program, base=None):
    """设置.json 的**模板**（只读）路径.

    base 显式给出 = 测试/工具的目录覆盖（旧语义: 该目录既是模板也是用户层）。
    base 为 None = 发布夹/程序目录里的 设置.json（运行时只读）。
    """
    if base is not None:
        return os.path.join(os.path.abspath(base), '设置.json')
    return os.path.join(program_dir(program), '设置.json')


def user_settings_path(program, base=None):
    """设置.json 的**用户层**（可写）路径.

    契约: %LOCALAPPDATA%\Loom\engine\settings.json (loom) /
          %LOCALAPPDATA%\Loom\hub\settings.json (loomhub)。
    base 显式给出时与模板同路径（测试隔离用，保持旧行为）。
    """
    if base is not None:
        return os.path.join(os.path.abspath(base), '设置.json')
    up = _userpaths()
    if up is None:
        return settings_path(program, base)
    return up.hub_settings() if program == 'loomhub' else up.engine_settings()


def _extract(d):
    """统一"新格式 {schema,values}"与"旧格式 plain dict"。"""
    if not isinstance(d, dict):
        return {}
    if 'schema' in d and isinstance(d.get('values'), dict):
        return dict(d['values'])
    return dict(d)


def _read_layer(path, what='配置'):
    """读一层设置: 缺文件 -> {}；坏 JSON -> 备份 + {}（出声，不静默）。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return _extract(json.load(f))
    except FileNotFoundError:
        return {}
    except Exception as e:
        print('[设置] %s 损坏 (%r): %s -> 备份后按默认' % (what, e, path))
        up = _userpaths()
        try:
            dst = up.backup_path(path) if up is not None else path + '.bak'
            os.replace(path, dst)
        except Exception as e2:
            print('[设置] 备份失败 (%r)，继续按默认运行' % (e2,))
        return {}


def load_settings(program, base=None):
    """读设置 = 默认 <- 模板 <- 用户层 delta.

    坏文件不会让调用方崩（返回默认），但会打印一次原因并留备份。
    base 显式给出时保持旧语义（该目录一份文件，直接覆盖）。
    """
    s = dict(DEFAULT_SETTINGS[program])
    s.update(_read_layer(settings_path(program, base), '模板 设置.json'))
    if base is None:
        s.update(_read_layer(user_settings_path(program, base), '用户 设置.json'))
    return s


def save_settings(program, settings, base=None):
    """原子写设置（tmp + os.replace）。失败上抛（契约 §7）。

    新语义: 只把**与默认+模板不同的键**写进用户层 {schema,values}；
    base 显式给出时保持旧语义（整份写该目录的 设置.json）。
    """
    path = user_settings_path(program, base)
    if base is not None:
        payload = dict(settings)
    else:
        base_layer = dict(DEFAULT_SETTINGS[program])
        base_layer.update(_read_layer(settings_path(program, base), '模板 设置.json'))
        delta = {k: v for k, v in dict(settings).items()
                 if k not in base_layer or base_layer[k] != v}
        import time as _time
        payload = {'schema': 1, 'app': program,
                   'updated_at': _time.strftime('%Y-%m-%d %H:%M:%S'),
                   'values': delta}
    up = _userpaths()
    d = os.path.dirname(os.path.abspath(path))
    if up is not None:
        up.ensure_dir(d)
    else:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def _suffix_ok(program, fname):
    """文件名后缀规则: Loom 认 GUI.py 且不收 HubGUI.py; LoomHub 只认 HubGUI.py."""
    if program == 'loom':
        return fname.endswith('GUI.py') and not fname.endswith('HubGUI.py')
    return fname.endswith('HubGUI.py')


def _parse_header(path):
    """读文件前 8 行, 文本解析出 (归一化标识, name, desc). 不 import.

    2026-11-07 P3: 旧实现 strip() 不去 BOM 字符, 且只去掉空格 -> 带 BOM
    或 tab 的合法头 (# gui: <tab> loom) 被误判为无标识. 这里先剥 BOM,
    再按 "# key: value" 解析, key 内允许空格/tab.
    """
    marker = name = desc = None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f):
                if i >= 8:
                    break
                # 2026-11-07 P3: strip() 不去 BOM; 先剥 BOM, 再按 "# key: value"
                # 解析, key 内允许空格/tab. 标识值取第一个空白分隔 token,
                # 兼容 "# gui:	loom" / "# gui: loom  # 注释".
                raw = line.lstrip('\ufeff').strip()
                if not raw.startswith('#'):
                    continue
                body = raw[1:].strip()
                key, sep, _ = body.lower().partition(':')
                if not sep:
                    continue
                key = ''.join(key.split())
                val = body.split(':', 1)[1].strip()   # 保留 name/desc 原大小写
                if key == 'gui-name':
                    name = val
                elif key == 'gui-desc':
                    desc = val
                elif key == 'gui' and val:
                    marker = '#gui:' + val.lower().split()[0]   # 归一化: #gui:loom
    except Exception:
        return None, None, None
    return marker, name, desc


def scan_guis(program, base=None):
    """可用 GUI 列表: 官方项恒在 + GUI/ 下后缀与标识都合法的自定义项.
    返回 [{id,name,desc,path,is_official}, ...] (自定义按文件名排序)."""
    out = [{'id': OFFICIAL[program], 'name': OFFICIAL[program],
            'desc': '官方界面', 'path': None, 'is_official': True}]
    folder = gui_folder(program, base)
    if not os.path.isdir(folder):
        return out
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith('.py') or not _suffix_ok(program, fname):
            continue
        path = os.path.join(folder, fname)
        marker, name, desc = _parse_header(path)
        if marker != MARKER[program]:
            continue
        out.append({'id': fname[:-3], 'name': name or fname[:-3], 'desc': desc or '',
                    'path': path, 'is_official': False})
    return out


def load_gui(program, gui_id, controller=None, base=None):
    """按 id 加载 GUI 视图实例. 官方懒 import 实例化; 自定义 importlib 加载 + build_gui.
    任何错误(文件不存在/import 失败/缺 build_gui)上抛, 由调用方 resolve 回退官方."""
    if gui_id == OFFICIAL[program]:
        if program == 'loom':
            # 官方 GUI = LoomGUI (Qt 原生视图); EditorApp 默认实例化 (同 _official)
            return None
        from hub_view_tk import TkHubView
        return TkHubView(controller)
    # 自定义: 在 scan 结果里找 (复用后缀+标识校验, 防止直接指定任意文件)
    cand = {g['id']: g for g in scan_guis(program, base) if not g['is_official']}
    info = cand.get(gui_id)
    if info is None:
        raise ValueError("GUI 不存在或标识不合法: %s" % gui_id)
    spec = importlib.util.spec_from_file_location(gui_id, info['path'])
    if spec is None or spec.loader is None:
        raise ValueError("无法加载 GUI 文件: %s" % info['path'])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # 坏文件 import 失败会抛异常
    factory = getattr(mod, 'build_gui', None)
    if not callable(factory):
        raise ValueError("GUI %s 缺 build_gui(controller) 工厂" % gui_id)
    return factory(controller)


def _official(program, controller):
    """官方视图: Loom 返回 None (EditorApp 自己建 LoomGUI); LoomHub 返回 TkHubView 实例."""
    if program == 'loom':
        return None
    from hub_view_tk import TkHubView
    return TkHubView(controller)


def resolve_gui(program, controller=None, base=None):
    """启动解析: 读设置选 GUI -> 加载; 失败则打印错误 + 写回设置改官方 + 回退官方.
    Loom 官方返回 None (EditorApp 默认 LoomGUI); 自定义返回实例."""
    s = load_settings(program, base)
    chosen = s.get('gui') or OFFICIAL[program]
    if chosen == OFFICIAL[program]:
        return _official(program, controller)
    try:
        return load_gui(program, chosen, controller, base)
    except Exception as e:
        print("[GUI] 加载「%s」失败 (%s)，已回退官方 %s" % (chosen, e, OFFICIAL[program]))
        s['gui'] = OFFICIAL[program]
        try:
            save_settings(program, s, base)
        except Exception:
            pass
        return _official(program, controller)
