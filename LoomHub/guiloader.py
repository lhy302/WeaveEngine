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
设置文件 = `<程序目录>\设置.json`（GUI 选择 + 各程序设置项，原子写）。
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
             'fps_limit': '120', 'cam_speed': 1.0},
    'loomhub': {'gui': 'TkHubView', 'open_py': True},
}

# 编辑器帧率上限档位 (2026-08-19): 档位 id -> 渲染循环周期 ms.
# 'unlimited' = 无上限 (1ms 最小周期, 硬件支持多少帧就多少帧, 对齐 Unity
# Application.targetFrameRate=-1 桌面默认). 'auto' = 按设备检测 (对齐 Unity
# 社区按 SystemInfo 硬件分级写帧率表的实践, 见 device_fps_limit).
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


def settings_path(program, base=None):
    r"""**模板/旧位置**路径: <程序目录>/设置.json。

    2026-11-08 第 5b 批: 安装形态下程序目录是 Program Files（Users=RX），
    引擎/Hub 的运行时可写层统一在 %LOCALAPPDATA%Loomhubsettings.json
    （见 hub_config.load_hub_settings / save_hub_settings）。本函数只用于
    "模板层/旧文件迁移源"与 base= 显式注入的测试隔离语义。
    """
    return os.path.join(program_dir(program, base), '设置.json')


def _hub_layer(program, base):
    """loomhub 且未显式给 base 时返回 hub_config 模块（用户层 + 模板层 + 迁移）。

    非 loomhub、或调用方给了 base（测试隔离）时返回 None —— 走旧的单文件语义。
    """
    if base is not None or program != 'loomhub':
        return None
    try:
        import hub_config
        return hub_config
    except Exception as e:      # 单文件分发等极端情况: 出声后回退，不静默
        print('[设置] 用户层不可用 (%r)，回退程序目录 设置.json' % (e,))
        return None


def load_settings(program, base=None):
    """读设置。

    2026-11-08 第 5b 批: loomhub 走 hub_config 的分层读取 ——
    默认 <- 安装目录模板(只读) <- %LOCALAPPDATA%\Loom\hub 的用户层 delta，
    并会把旧的 <程序目录>\设置.json 自动迁移进用户层（旧文件保留）。
    base= 显式给出时保持旧语义；坏文件回默认并打印原因（不静默）。
    """
    layer = _hub_layer(program, base)
    if layer is not None:
        return layer.load_hub_settings()
    s = dict(DEFAULT_SETTINGS[program])
    path = settings_path(program, base)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            s.update(d)
    except FileNotFoundError:
        pass
    except Exception as e:
        print('[设置] 读取失败 (%r): %s -> 按默认' % (e, path))
    return s


def save_settings(program, settings, base=None):
    """原子写设置。

    loomhub 且未给 base: 写用户层（只存与"默认+模板"不同的 delta），
    失败**上抛**给调用方（契约 §7，不再静默丢设置）。
    base 显式给出: 保持旧语义（整份写该目录的 设置.json，测试隔离用）。
    """
    layer = _hub_layer(program, base)
    if layer is not None:
        return layer.save_hub_settings(settings)
    path = settings_path(program, base)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
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
    """读文件前 8 行, 文本解析出 (归一化标识, name, desc). 不 import."""
    marker = name = desc = None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f):
                if i >= 8:
                    break
                low = line.strip().lower()
                if low.startswith('# gui-name:'):
                    name = line.split(':', 1)[1].strip()
                elif low.startswith('# gui-desc:'):
                    desc = line.split(':', 1)[1].strip()
                elif low.startswith('# gui:'):
                    marker = low.replace(' ', '')   # 归一化: #gui:loom
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
            from ui.LoomGUI import LoomGUI
            return LoomGUI(controller)
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
