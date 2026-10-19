# -*- coding: utf-8 -*-
"""
hub_controller.py — LoomHub 控制器 (UI 无关的命令层)   [UI 模块化 2026-08-13]

职责: 解释器/项目管理器的全部业务动作 (扫描/导入/安装/设默认/移除 + 项目
新建/导入/打开/移除/扫描). UI (IHubView 实现) 只调用这里的方法并显示
self.msg (状态栏消息) —— 换 UI 后端 (pygame 自绘 / tkinter / web...) 完全
不动本文件.

架构位置 (三层解耦, 依赖单向向下):
    UI 实现层  LoomHub.py (pygame) / hub_view_tk.py (tkinter)   [可替换]
    UI 接口层  IHubView (本文件定义契约)
    控制器层   HubController (本文件, 无 GUI 依赖, 可无头测试)
    数据层     hub_config.py / hub_install.py / filedialog.py (不动)

关键约定:
  - 本文件 不 import pygame / tkinter —— 可无头测试.
  - 文件对话框用 filedialog.py (ctypes 调系统原生 comdlg32/IFileOpenDialog),
    与 UI 后端无关, 换 UI 后对话框仍是系统原生 (合理).
  - 输入框 (改安装根/版本号) 由 UI 层负责弹出 (pygame view 用 tkinter,
    tk view 用自带), 拿到字符串后调这里对应的命令方法 (do_install_zip/
    set_install_root).
  - 消息等级 msg_level: 'ok'(正常/成功) | 'err'(失败) | 'dim'(中性提示),
    UI 自行映射为颜色 (旧的 msg_color 颜色元组已废弃, 颜色是显示层的事).
"""
import os
import subprocess
import sys

HUB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HUB_DIR)
sys.path.insert(0, os.path.join(HUB_DIR, '..', 'Loom'))  # 复用系统原生文件对话框

import hub_config as cfg
import hub_install as inst
import filedialog

ZIP_FILTER = "解释器安装包 (*.zip)\0*.zip\0所有文件 (*.*)\0*.*\0"


class HubController:
    """LoomHub 全部业务动作 + 状态 (与显示无关). UI 通过本实例读写一切."""

    def __init__(self):
        self.install_root = cfg.DEFAULT_INSTALL_ROOT
        self.interpreters = cfg.load_interpreters()   # 已登记解释器列表 (动作后 _refresh)
        self.projects = cfg.load_projects()           # 已登记项目列表
        self.msg = ""                                 # 状态栏消息 (UI 显示)
        self.msg_level = 'ok'                         # 'ok' | 'err' | 'dim'
        self.py_ver = cfg.python_version()            # 系统默认 python 版本 (UI 提醒)
        # 2026-08-15 空闲 CPU: 默认解释器缓存 (UI 每帧读 default_interpreter, 别每帧读磁盘 JSON)
        self._default_interp = cfg.default_interpreter()
        self._auto_scan_save_dir()                    # 启动默认扫描解释器保存目录

    # ---------------- 通用 ----------------
    def _refresh(self):
        """动作后重载配置列表 (UI 每帧读 self.interpreters/projects 即最新)."""
        self.interpreters = cfg.load_interpreters()
        self.projects = cfg.load_projects()
        self._default_interp = cfg.default_interpreter()

    def set_msg(self, text, level='ok'):
        self.msg = text
        self.msg_level = level

    # ---------------- 状态查询 (UI 读) ----------------
    def default_interpreter(self):
        """当前默认解释器 (None = 没有). 缓存值, _refresh 后最新 (避免每帧读磁盘)."""
        return self._default_interp

    def default_save_dir(self):
        """默认解释器的保存目录; 目录不存在则创建, 返回 None 表示没有解释器."""
        d = cfg.interpreter_save_dir()
        if not d:
            return None
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def unique_scene_name(self, directory):
        """保存目录里未占用的默认场景名: 新项目 / 新项目1 / ...
        (避免直接确定就覆盖已有)."""
        base, i = "新项目", 1
        while directory and os.path.isdir(directory) \
                and os.path.exists(os.path.join(directory, "%s.json" % base)):
            base = "新项目%d" % i
            i += 1
        return base

    def new_scene_file(self, path):
        """写入一个最小的空场景 (sceneio v8), 供'新建项目'创建初始场景."""
        data = {"version": 8,
                "camera": {"target": [0.0, 0.0, 0.0], "distance": 10.0,
                           "yaw": 0.6, "pitch": -0.35},
                "materials": [], "lights": [], "cameras": [],
                "active_camera": None, "objects": []}
        cfg.save_json_atomic(path, data)

    # ---------------- 解释器动作 ----------------
    def scan_interpreters(self):
        """扫描解释器安装根 (C:\\Program Files\\Loom), 全部登记."""
        found = cfg.scan_install_root()
        if not found:
            self.set_msg("C:\\Program Files\\%s 下没有找到已安装解释器" % cfg.APP_NAME, 'dim')
            return
        for it in found:
            cfg.add_interpreter(it)
        self._refresh()
        self.set_msg("扫描到 %d 个解释器版本并登记" % len(found))

    def import_interpreter_dir(self):
        """用系统对话框选解释器目录 (选中其中 解释器.json), 分析并登记."""
        meta = filedialog.open_file("选择解释器目录 (选中其中的 %s)" % cfg.META_NAME,
                                    initial_dir=None,
                                    filter_str="解释器元数据 (%s)\0%s\0所有文件 (*.*)\0*.*\0"
                                               % (cfg.META_NAME, cfg.META_NAME))
        if not meta:
            return
        directory = os.path.dirname(meta)
        info = cfg.discover_interpreter(directory)
        if info is None:
            self.set_msg("该目录不是有效的 Loom 解释器 (缺 %s 或主程序)" % cfg.META_NAME, 'err')
            return
        cfg.add_interpreter(info)
        self._refresh()
        self.set_msg("已导入解释器 %s %s (%s)" % (info['name'], info['version'], info['kind']))

    def do_install_zip(self, version):
        """安装 .zip 解释器包到安装根/<版本号>. version 由 UI 输入框拿到."""
        version = (version or "").strip()
        if not version:
            self.set_msg("版本号不能为空", 'err')
            return
        zip_path = filedialog.open_file("选择 Loom 解释器安装包", initial_dir=None,
                                        filter_str=ZIP_FILTER)
        if not zip_path:
            self.set_msg("已取消安装", 'dim')
            return
        try:
            target = inst.install_from_zip(zip_path, version, self.install_root)
            self._refresh()
            self.set_msg("安装完成 → %s (已登记)" % target)
        except inst.InstallError as e:
            self.set_msg("安装失败: %s" % e, 'err')

    def set_default(self, interp):
        """把指定解释器设为默认 (interp 为登记项 dict 或 None)."""
        if not interp:
            return
        cfg.set_default_interpreter(interp)
        self._refresh()
        self.set_msg("默认解释器已设为 %s %s" % (interp['name'], interp['version']))

    def remove_interpreter(self, interp):
        """从列表移除解释器 (不删磁盘文件)."""
        if not interp:
            return
        cfg.remove_interpreter(interp)
        self._refresh()
        self.set_msg("已从列表移除 %s (未删除磁盘文件)" % interp['version'], 'dim')

    # ---------------- 项目动作 ----------------
    def new_project(self):
        """用系统'保存文件'对话框创建项目场景 (创建的是文件, 不是文件夹).
        项目名 = 场景文件名 (去扩展名)."""
        dlg = self.default_save_dir()
        path = filedialog.save_file(
            "新建项目场景 (保存位置 = 项目目录)", initial_dir=dlg,
            default_name=self.unique_scene_name(dlg),
            filter_str="场景文件 (*.json)\0*.json\0所有文件 (*.*)\0*.*\0",
            default_ext="json")
        if not path:
            self.set_msg("已取消新建项目", 'dim')
            return
        self.do_new_project_file(path)

    def do_new_project_file(self, path):
        """在所选位置创建空场景文件并登记 (供测试/UI 直接调用, 绕过对话框)."""
        try:
            self.new_scene_file(path)
        except OSError as e:
            # 目标目录不可写 / 磁盘错误等: 提示而不是崩溃退出
            self.set_msg("创建项目失败: %s" % e, 'err')
            return
        name = os.path.splitext(os.path.basename(path))[0]
        cfg.add_project(name, path)
        self._refresh()
        self.set_msg("已创建项目 %s (%s)" % (name, os.path.basename(path)))

    def import_project_dir(self):
        """用系统目录对话框选项目目录, 发现其中的场景文件并登记."""
        directory = filedialog.choose_directory(
            "选择项目目录 (含场景文件)", initial_dir=self.default_save_dir())
        if not directory:
            return
        found = cfg.discover_project(directory)
        if found is None:
            self.set_msg("该目录没有项目场景文件 (*.json)", 'err')
            return
        name, scene = found
        cfg.add_project(name, scene)
        self._refresh()
        self.set_msg("已导入项目 %s (%s)" % (name, os.path.basename(scene)))

    def scan_save_dir_projects(self):
        """扫描默认解释器保存目录, 把已有场景文件登记为项目."""
        found = cfg.scan_save_dir_projects()
        if not found:
            self.set_msg("默认解释器保存目录下没有项目场景文件", 'dim')
            return
        self._refresh()
        self.set_msg("扫描到 %d 个项目并登记" % len(found))

    def _auto_scan_save_dir(self):
        """启动默认扫描解释器保存目录下的项目 (失败静默)."""
        try:
            found = cfg.scan_save_dir_projects()
            if found:
                self.projects = cfg.load_projects()
        except Exception:
            pass

    def open_project(self, project):
        """用默认解释器启动编辑器打开项目场景 (subprocess, 不阻塞)."""
        if not project:
            self.set_msg("请先选一个项目", 'err')
            return
        interp = cfg.default_interpreter()
        if interp is None:
            self.set_msg("还没有解释器: 请先扫描/导入/安装一个", 'err')
            return
        # 2026-08-20 安全加固 (Qoder 报告提示12): 场景路径校验 ——
        # projects.json 被篡改时避免用 --open 打开任意路径文件
        # 2026-10-19 启动路径 bug 修复: 相对路径按工作区根解析
        scene = cfg.resolve_runtime_path(project.get('scene'))
        if not scene or not os.path.isfile(scene):
            self.set_msg("项目场景文件不存在", 'err')
            return
        if not str(scene).lower().endswith('.json'):
            self.set_msg("非场景文件, 拒绝打开", 'err')
            return
        # 启动器设置: 设置面板里"打开项目用 .py/.exe" (open_py, 2026-08-14)
        prefer = None
        try:
            import guiloader
            prefer = 'py' if guiloader.load_settings('loomhub').get('open_py', True) else 'exe'
        except Exception:
            prefer = None
        cmd = cfg.build_launch_command(interp, scene, mode='open', prefer=prefer)
        env = dict(os.environ)
        # 2026-10-19 启动路径 bug 修复: cwd 也解析成绝对（否则子进程相对父进程 cwd 解析）
        cwd = cfg.resolve_runtime_path(interp.get('dir')) or cfg.HUB_DIR
        try:
            subprocess.Popen(cmd, cwd=cwd, env=env)
            note = "用系统默认 Python 环境启动" if interp['kind'] == 'py' else "直接运行 exe"
            self.set_msg("已启动: %s %s (%s) %s" % (interp['name'], interp['version'],
                                                    interp['kind'], note))
        except OSError as e:
            self.set_msg("启动失败: %s" % e, 'err')

    def remove_project(self, project):
        """从列表移除项目 (不删磁盘文件)."""
        if not project:
            return
        cfg.remove_project(project['scene'])
        self._refresh()
        self.set_msg("已从列表移除项目 (未删除磁盘文件)", 'dim')

    def set_install_root(self, root):
        """改安装根目录. 返回是否成功 (目录必须存在)."""
        root = (root or "").strip()
        if not root:
            return False
        if os.path.isdir(root):
            self.install_root = root
            self.set_msg("安装根已改为: %s" % root)
            return True
        self.set_msg("目录不存在: %s" % root, 'err')
        return False


# =====================================================================
# IHubView 契约 —— LoomHub 的 UI 接口标准 (UI 模块化)
# =====================================================================
class IHubView:
    """LoomHub 视图契约. 任何 UI 后端 (pygame 自绘 / tkinter / web...) 实现本接口:
       - attach(controller): 绑定 HubController (通常 __init__ 自动完成)
       - run(): 进入事件循环 (返回后程序退出)

       UI 通过 controller 的公开 API 读写全部状态 (禁止 import hub_config
       做业务, 禁止直接改配置):
         读:  controller.interpreters / .projects / .install_root / .msg /
               .msg_level / .py_ver / .default_interpreter() /
               .default_save_dir() / .unique_scene_name(dir)
         写(命令): scan_interpreters() / import_interpreter_dir() /
               do_install_zip(version) / set_default(interp) /
               remove_interpreter(interp) / new_project() /
               do_new_project_file(path) / import_project_dir() /
               scan_save_dir_projects() / open_project(project) /
               remove_project(project) / set_install_root(root)

       UI 负责 (显示层的事, 不进 controller): 列表选中状态 (sel_interp/
       sel_project)、按钮命中/布局、颜色映射、输入框弹出 (改安装根/版本号).
    """
    def attach(self, controller):
        raise NotImplementedError

    def run(self):
        raise NotImplementedError
