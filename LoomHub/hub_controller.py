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
        # 2026-11-09: 启动即按各目录的 解释器.json 重识别（引擎可能被原地替换成编译版）
        try:
            self.interpreters, _ = cfg.refresh_interpreters()
        except (OSError, ValueError):
            self.interpreters = cfg.load_interpreters()   # 已登记解释器列表 (动作后 _refresh)
        self.projects = cfg.load_projects()           # 已登记项目列表
        self.msg = ""                                 # 状态栏消息 (UI 显示)
        self.msg_level = 'ok'                         # 'ok' | 'err' | 'dim'
        self.py_ver = cfg.python_version()            # 系统默认 python 版本 (UI 提醒)
        # 2026-08-15 空闲 CPU: 默认解释器缓存 (UI 每帧读 default_interpreter, 别每帧读磁盘 JSON)
        self._default_interp = cfg.default_interpreter()
        # 2026-11-09: 「当前引擎」内存缓存（不落盘）。Tk Listbox 的 exportselection
        # 会让两个列表互相清空选中，所以"同时选中引擎+项目"物理上不可行 ——
        # 交互改为：左侧「选为当前引擎」记到内存，右侧「用当前引擎打开」读缓存。
        self.current_interp = None
        self._auto_scan_save_dir()                    # 启动默认扫描解释器保存目录

    # ---------------- 通用 ----------------
    def _refresh(self):
        """动作后重载配置列表 (UI 每帧读 self.interpreters/projects 即最新)."""
        try:
            self.interpreters, _ = cfg.refresh_interpreters()
        except (OSError, ValueError):
            self.interpreters = cfg.load_interpreters()
        self.projects = cfg.load_projects()
        self._default_interp = cfg.default_interpreter()
        # 当前引擎缓存按 dir 续命；条目被移除/失效则清空（避免 UI 显示一个不存在的引擎）
        if getattr(self, 'current_interp', None) and self.current_interp_cached() is None:
            self.current_interp = None

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

    def preview_zip(self, zip_path):
        """读取 zip 元数据（供 UI 预览对话框）.

        返回 {'ok': True, 'info': {...}, 'inner_prefix': 'Loom/'} 或
             {'ok': False, 'error': '...'}
        """
        info, prefix = inst.read_zip_metadata(zip_path)
        if info is None:
            return {'ok': False, 'error':
                    '压缩包里没有找到 %s（不是有效的 Loom 解释器包）' % cfg.META_NAME}
        return {'ok': True, 'info': info, 'inner_prefix': prefix}

    def do_install_zip(self, version=None, zip_path=None, target_root=None):
        """统一 zip 安装入口（2026-10-19 增强）.

        参数:
          version    : 版本号（None = 从 zip 元数据自动读）
          zip_path   : zip 路径（None = 弹系统文件对话框选）
          target_root: 安装根（None = 用 self.install_root）

        返回 dict:
          {'ok': True, 'installed_dir': '...', 'info': {...}, 'message': '...'}
          {'ok': False, 'message': '...'}
        """
        # 1) 选 zip
        if not zip_path:
            zip_path = filedialog.open_file(
                "选择 Loom 解释器安装包", initial_dir=None,
                filter_str=ZIP_FILTER)
            if not zip_path:
                self.set_msg("已取消安装", 'dim')
                return {'ok': False, 'message': '用户取消', 'cancelled': True}
        # 2) 读元数据（版本号缺失时）
        if not version:
            info, _ = inst.read_zip_metadata(zip_path)
            if info is None:
                self.set_msg("压缩包内缺少 %s，不是有效的 Loom 解释器包"
                             % cfg.META_NAME, 'err')
                return {'ok': False, 'message': '缺少元数据'}
            version = (info.get('version') or '').strip()
            if not version:
                self.set_msg("压缩包内 %s 缺少 version 字段" % cfg.META_NAME, 'err')
                return {'ok': False, 'message': '缺少 version 字段'}
        version = str(version).strip()
        # 3) 确定安装根
        if target_root is None:
            target_root = self.install_root
        # 4) 安装
        try:
            target = inst.install_from_zip(
                zip_path, version, target_root=target_root)
            self._refresh()
            # 2026-10-19: 安装后自检（防安全软件篡改 .py 导致启动崩溃）
            verify_ok, corrupted = inst._verify_install_integrity(target)
            if not verify_ok:
                msg = ("安装完成，但检测到 %d 个 .py 文件被安全软件篡改（全零字节）。"
                       "引擎可能无法启动。请关闭杀软后重装或加入白名单：%s"
                       % (len(corrupted),
                          '; '.join(os.path.basename(f) for f in corrupted[:3])))
                self.set_msg(msg, 'err')
                return {'ok': True, 'installed_dir': target,
                        'version': version, 'message': msg,
                        'verify_warnings': corrupted}
            self.set_msg("安装完成 → %s (已登记)" % target)
            return {'ok': True, 'installed_dir': target,
                    'version': version, 'message': '安装完成'}
        except inst.InstallError as e:
            self.set_msg("安装失败: %s" % e, 'err')
            return {'ok': False, 'message': str(e)}

    def set_default(self, interp):
        """把指定解释器设为默认 (interp 为登记项 dict 或 None)."""
        if not interp:
            return
        cfg.set_default_interpreter(interp)
        self._refresh()
        self.set_msg("默认解释器已设为 %s %s" % (interp['name'], interp['version']))

    def remove_interpreter(self, interp, delete_files=False):
        """从列表移除解释器.

        delete_files=False: 只从 interpreters.json 移除登记，磁盘保留（默认）
        delete_files=True : 同时物理删除解释器目录（危险，UI 侧必须二次确认）

        返回 dict: {'ok': bool, 'message': str, 'deleted_dir': str or None}
        """
        if not interp:
            return {'ok': False, 'message': '无解释器'}
        ver = interp.get('version', '?')
        # 先从列表移除
        cfg.remove_interpreter(interp)
        self._refresh()
        # 可选：物理删除
        deleted = None
        if delete_files:
            d = interp.get('dir')
            if d and os.path.isdir(d):
                try:
                    import shutil as _shutil
                    _shutil.rmtree(d, ignore_errors=False)
                    deleted = d
                    self.set_msg("已删除 %s 并移除登记（磁盘目录已清空）" % ver, 'dim')
                except Exception as e:
                    self.set_msg("已移除登记，但磁盘删除失败: %r" % (e,), 'err')
                    return {'ok': False, 'message': '磁盘删除失败: %r' % (e,)}
            else:
                self.set_msg("已移除登记 %s（目录不存在，无需删除）" % ver, 'dim')
        else:
            self.set_msg("已从列表移除 %s（磁盘文件保留）" % ver, 'dim')
        return {'ok': True, 'message': '已移除', 'deleted_dir': deleted}

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
        """导入项目目录（2026-10-19 C3: 强制复制到当前解释器 Projects/）.

        流程:
          1) 选源目录
          2) 发现场景文件
          3) 复制整个源目录到 <当前引擎>/Projects/<目录名>/
          4) 登记为项目, engine_dir=当前引擎

        没有默认解释器时降级为纯登记（外部项目）。
        """
        directory = filedialog.choose_directory(
            "选择要导入的项目目录（含场景文件）",
            initial_dir=self.default_save_dir())
        if not directory:
            return
        found = cfg.discover_project(directory)
        if found is None:
            self.set_msg("该目录没有项目场景文件 (*.json)", 'err')
            return
        name, scene = found
        interp = self.default_interpreter()
        if interp is None:
            # 降级：无解释器 -> 纯登记（外部项目）
            cfg.add_project(name, scene)
            self._refresh()
            self.set_msg("已导入项目 %s（无解释器，作为外部项目管理）" % name, 'dim')
            return
        # 有解释器 -> 强制复制
        engine_dir = interp.get('dir')
        projects_root = os.path.join(engine_dir, cfg.SAVE_DIR_NAME)
        try:
            os.makedirs(projects_root, exist_ok=True)
        except OSError as e:
            self.set_msg("无法创建 Projects 目录: %r" % (e,), 'err')
            return
        # 目标子目录（用源目录名，冲突时加后缀）
        src_dirname = os.path.basename(os.path.normpath(directory))
        target_subdir = os.path.join(projects_root, src_dirname)
        idx = 1
        while os.path.exists(target_subdir):
            target_subdir = os.path.join(projects_root, '%s_%d' % (src_dirname, idx))
            idx += 1
        # 复制（整目录）
        import shutil
        try:
            shutil.copytree(directory, target_subdir)
        except OSError as e:
            self.set_msg("复制项目失败: %r" % (e,), 'err')
            return
        # 找目标目录里的场景文件（保持同名）
        new_found = cfg.discover_project(target_subdir)
        if new_found is None:
            self.set_msg("复制后未找到场景文件（异常）", 'err')
            return
        new_name, new_scene = new_found
        cfg.add_project(new_name, new_scene, engine_dir=engine_dir)
        self._refresh()
        self.set_msg("已导入并复制项目 %s → %s"
                     % (new_name, target_subdir), 'ok')

    def scan_save_dir_projects(self):
        """扫描当前默认解释器项目目录, 把已有场景文件登记为项目."""
        interp = self.default_interpreter()
        engine_dir = interp.get('dir') if interp else None
        found = cfg.scan_save_dir_projects(engine_dir=engine_dir)
        if not found:
            self.set_msg("默认解释器项目目录下没有项目场景文件", 'dim')
            return
        self._refresh()
        self.set_msg("扫描到 %d 个项目并登记" % len(found))

    # ---------------- 2026-10-19 A2+D1 项目归属模型 ----------------
    def projects_for_engine(self, engine_dir, include_external=True):
        """返回带归属标记的项目列表（2026-10-19 A2 用户拍板）.

        engine_dir: 当前选中引擎根目录
        include_external: 是否包含"外部项目"（不属于任何引擎的项目）

        返回: [{name, scene, version, engine_dir,
               'is_current': bool,   # 属于当前引擎
               'is_external': bool,  # 不属于任何引擎
               'belongs_to': str},   # 归属版本描述（"0.1.0.beta1" 或 "外部"）
              ...]

        排序: 当前引擎项目优先, 外部次之, 其他引擎最后
        """
        cur_engine = os.path.abspath(engine_dir).rstrip('/\\' if os.sep == '/'
                                                        else '\\/') if engine_dir else None
        out = []
        for p in self.projects:
            p_engine = p.get('engine_dir')
            if not p_engine:
                # 尝试从 scene 推断（兼容旧数据）
                p_engine = cfg.infer_engine_dir(p.get('scene'))
            is_current = bool(p_engine and cur_engine
                              and os.path.normcase(os.path.normpath(p_engine))
                              == os.path.normcase(os.path.normpath(cur_engine)))
            is_external = not p_engine
            if is_external and not include_external:
                continue
            # 归属版本：从引擎配置里找匹配的
            belongs_to = '外部'
            if p_engine:
                for it in self.interpreters:
                    if os.path.normcase(os.path.normpath(it.get('dir', ''))) \
                       == os.path.normcase(os.path.normpath(p_engine)):
                        belongs_to = 'v' + it.get('version', '?')
                        break
                else:
                    belongs_to = os.path.basename(p_engine.rstrip('/\\')) or '未知'
            out.append({
                'name': p['name'],
                'scene': p['scene'],
                'version': p.get('version'),
                'engine_dir': p_engine,
                'is_current': is_current,
                'is_external': is_external,
                'belongs_to': belongs_to,
            })
        # 排序：当前引擎 > 外部 > 其他
        def _key(x):
            if x['is_current']:
                return (0, x['name'])
            if x['is_external']:
                return (1, x['name'])
            return (2, x['name'])
        out.sort(key=_key)
        return out

    def switch_to_interpreter(self, interp):
        """切换当前工作解释器（2026-10-19 D1: 自动扫描新引擎目录）.

        行为:
          1) 设为默认解释器
          2) 自动扫描该引擎的 Projects/ 和 保存/ 下的场景, 登记为项目
          3) 刷新列表
        返回 {'ok': bool, 'scanned': N, 'message': '...'}
        """
        if not interp:
            return {'ok': False, 'message': '无解释器'}
        # 设为默认
        self.set_default(interp)
        # 自动扫描
        engine_dir = interp.get('dir')
        if not engine_dir:
            return {'ok': False, 'message': '解释器目录缺失'}
        found = cfg.scan_save_dir_projects(engine_dir=engine_dir)
        self._refresh()
        msg = "已切换到 %s v%s，扫描到 %d 个项目" % (
            interp.get('name', '?'), interp.get('version', '?'), len(found))
        self.set_msg(msg, 'ok')
        return {'ok': True, 'scanned': len(found), 'message': msg}

    def _auto_scan_save_dir(self):
        """启动默认扫描解释器保存目录下的项目 (失败静默)."""
        try:
            found = cfg.scan_save_dir_projects()
            if found:
                self.projects = cfg.load_projects()
        except Exception:
            pass

    # ---------------- 当前引擎（内存缓存，2026-11-09） ----------------
    def set_current_interp(self, interp):
        """设为「当前引擎」（仅内存，不落盘；不影响 default 标记）。"""
        if not interp:
            self.current_interp = None
            self.set_msg("已清除当前引擎（将用默认引擎）", 'dim')
            return None
        self.current_interp = dict(interp)
        self.set_msg("当前引擎: %s v%s (%s)"
                     % (interp.get('name'), interp.get('version'), interp.get('kind')))
        return self.current_interp

    def current_interp_cached(self):
        """缓存的当前引擎（仍登记且未失效才返回；否则 None）。不回落默认。"""
        c = getattr(self, 'current_interp', None)
        if not c:
            return None
        want = os.path.normcase(os.path.abspath(c.get('dir') or ''))
        for it in (self.interpreters or cfg.load_interpreters()):
            if it.get('stale'):
                continue
            if os.path.normcase(os.path.abspath(it.get('dir') or '')) == want:
                return it            # 用粉丝带里的最新信息（kind/main 可能被重识别过）
        return None

    def current_interp_or_default(self):
        """缓存的当前引擎，没有就回退默认（UI 显示/其他调用点用）。"""
        return self.current_interp_cached() or cfg.default_interpreter()

    def interp_for_project(self, project):
        """为项目挑解释器（Bug2 修复）：显式 > 项目归属引擎 > 默认。

        projects.json 里本来就有 engine_dir（场景所在的 <引擎根>）；这样"项目记得
        自己用哪个引擎版本"，多版本并存时不会一律拿默认引擎去开别人的项目。
        """
        ed = (project or {}).get('engine_dir')
        if ed:
            try:
                want = os.path.normcase(os.path.abspath(ed))
            except (OSError, ValueError):
                want = None
            if want:
                lst = self.interpreters or cfg.load_interpreters()
                # ① engine_dir 就是解释器目录（<引擎根>/Loom）
                for it in lst:
                    if it.get('stale'):
                        continue
                    d = it.get('dir')
                    if d and os.path.normcase(os.path.abspath(d)) == want:
                        return it
                # ② engine_dir 是解释器目录的父目录（Projects/ 在 <引擎根>/ 下）。
                # 2026-11-09 P2-②: 同一引擎根下可能并存多个版本目录，取**版本最高**的那个
                # （以前按台账顺序返回第一个，实测会选中最旧的 beta4）。
                def _vk(x):
                    try:
                        return cfg._version_key(x.get('version', '0'))
                    except (TypeError, ValueError):
                        return (0, 0, 0, 0, 0)

                # 逐层放宽：先看"父目录"，再看"祖父目录"（场景在 <安装根>/Projects/
                # 而解释器在 <安装根>/<版本>/Loom 的布局）；每层若命中多个版本，
                # 取**版本最高**的那个，而不是台账里的第一个。
                for depth in (1, 2):
                    cands = []
                    for it in lst:
                        if it.get('stale') or not it.get('dir'):
                            continue
                        base = os.path.abspath(it['dir'])
                        for _ in range(depth):
                            base = os.path.dirname(base)
                        if os.path.normcase(base) == want:
                            cands.append(it)
                    if cands:
                        return max(cands, key=_vk)
        return cfg.default_interpreter()

    def open_project(self, project, interp=None):
        """启动编辑器打开项目场景 (subprocess, 不阻塞).

        打开优先级（2026-11-09 人类口径，顺序不许改）：
          1) 显式传入的 interp（UI「用当前引擎打开」传缓存的当前引擎）
          2) 内存缓存的「当前引擎」（set_current_interp / current_interp_cached）
          3) 项目 engine_dir 归属命中的已登记解释器
          4) 默认引擎（★）
        """
        if not project:
            self.set_msg("请先选一个项目", 'err')
            return
        if interp is None:
            interp = self.current_interp_cached()      # ②
        if interp is None:
            interp = self.interp_for_project(project)  # ③ + ④
        if interp is None:
            self.set_msg("还没有解释器: 请先扫描/导入/安装一个", 'err')
            return
        _prob = cfg.interpreter_problem(interp)
        if _prob:
            self.set_msg('无法启动: ' + _prob, 'err')
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
        # 2026-11-08 D3=A: "打开编辑器就带 Agent 桥"是**调用方**的业务决定
        # （build_launch_command 保持纯拼装）。恰好追加一次；--agent 让引擎侧
        # Loom/ui/loom_gui.py 起本地命令桥并写 .agent_port.json。
        if '--agent' not in cmd:
            cmd.append('--agent')
        env = dict(os.environ)
        # 2026-10-19 启动日志: LoomHub 启动的引擎静默（用户拍板）
        # 命令行直接启动 Loom.py 时无此环境变量，保留完整启动信息
        env['LOOM_QUIET'] = '1'
        # 2026-11-09 H1: 不再无条件注入 LOOM_REMOTE_MODE=1。
        # 现场 A/B（同场景同引擎）直连 55/59/61 FPS、TPS 23.7；remote-mode
        # 38/38/41 FPS、TPS 18.9 —— 离屏回读明显降帧，所以默认 off。
        # 是否注入由 Hub 设置 remote_mode（off|auto|on，默认 off）决定，
        # 与命令层 launch_spec 共用同一个实现，保证两条启动路径一致。
        cfg.apply_launch_env(env)
        # 2026-10-19 启动路径 bug 修复: cwd 也解析成绝对（否则子进程相对父进程 cwd 解析）
        cwd = cfg.resolve_runtime_path(interp.get('dir')) or cfg.HUB_DIR
        try:
            # 2026-10-20 白屏修复 P0-3 修正版：不用 CREATE_NO_WINDOW。
            # 根因：CREATE_NO_WINDOW 让 Windows 给 GUI 子进程传 STARTUPINFO.wShowWindow=SW_HIDE，
            # Qt 遵循这个状态把窗口藏到 (-25600,-25600) —— 用户看到白屏（其实是窗口被隐藏）。
            # 正确做法：优先用 pythonw.exe（无控制台但 GUI 正常显示），回退 python.exe 无 flag。
            cmd_to_run = list(cmd)
            if interp['kind'] == 'py' and cmd_to_run:
                py_exe = cmd_to_run[0]
                # 同目录找 pythonw.exe
                py_dir = os.path.dirname(py_exe)
                pyw = os.path.join(py_dir, 'pythonw.exe') if py_dir else None
                if pyw and os.path.isfile(pyw):
                    cmd_to_run[0] = pyw
            subprocess.Popen(cmd_to_run, cwd=cwd, env=env)
            note = "用系统默认 Python 环境启动" if interp['kind'] == 'py' else "直接运行 exe"
            self.set_msg("已启动: %s %s (%s) %s" % (interp['name'], interp['version'],
                                                    interp['kind'], note))
        except OSError as e:
            self.set_msg("启动失败: %s" % e, 'err')

    # ---------------- 自更新 (H2, 2026-11-09) ----------------
    # 三个动作都 UI 无关：任何 GUI / 命令层都可直接调；返回值给调用方决定怎么显示。
    def check_update(self, manual=False):
        """检查更新。返回 hub_update.check_update() 的结果。

        manual=False 时受 24h 节流 + check_update_enabled 设置约束（后台线程用）；
        manual=True 忽略节流（用户点"检查更新"）。失败**静默**（只写 update.log）。
        """
        try:
            import hub_update
        except Exception as e:                 # 模块缺失属硬错误，出声
            self.set_msg("自更新模块不可用: %r" % (e,), 'err')
            return {'ok': False, 'reason': '自更新模块不可用: %r' % (e,)}
        if not manual:
            s = cfg.load_hub_settings()
            if not s.get('check_update_enabled', True):
                return {'ok': False, 'reason': '检查更新已在设置里关闭', 'disabled': True}
            if not hub_update.due_for_check():
                return {'ok': False, 'reason': '24h 内已检查过', 'throttled': True}
        info = hub_update.check_update()
        if info.get('ok'):
            hub_update.mark_checked()
            # P2-③: 检查成功说明网络/接口已恢复，清掉上次失败提示，
            # 免得下次启动还显示一条早已过期的 FAIL。
            hub_update.mark_failure_seen()
        self.update_info = info
        if info.get('ok') and info.get('update'):
            up_ = info['update']
            self.set_msg("发现新版本 LoomHub %s（当前 %s）"
                         % (up_['version'], info.get('local') or '?'), 'ok')
        elif manual:
            self.set_msg(info.get('reason') or '已是最新版本', 'dim')
        return info

    def download_update(self, item=None):
        r"""下载更新包到 %LOCALAPPDATA%\Loom\hub\updates（校验 size/digest）。"""
        try:
            import hub_update
        except Exception as e:
            return {'ok': False, 'reason': '自更新模块不可用: %r' % (e,)}
        info = getattr(self, 'update_info', None) or {}
        item = item or info.get('update')
        if not item:
            return {'ok': False, 'reason': '没有可下载的更新（先 check_update）'}
        r = hub_update.download_update(item)
        if r.get('ok'):
            self.update_package = r.get('path')
            self.set_msg("更新包已下载: %s" % r.get('path'), 'ok')
        else:
            self.set_msg("下载失败: %s" % r.get('reason'), 'err')
        return r

    def has_update(self):
        """当前检查结果里是否有可安装的新版本（GUI 按钮 enable 状态用）。"""
        info = getattr(self, 'update_info', None) or {}
        return bool(info.get('update'))

    def download_and_install(self, item=None):
        """GUI 一键：下载 → 校验（必须过）→ 提交静默安装。

        下载/校验失败**绝不进入安装阶段**（失败原因由 download_update 写
        update.log 并放进 self.msg）。
        """
        r = self.download_update(item)
        if not r.get('ok'):
            return r
        return self.apply_update(r.get('path'))

    def apply_update(self, setup_path=None):
        """提交静默安装任务（写 updater 脚本 + 一次 UAC），成功即"暂时关闭"本进程。

        不自动启动 LoomHub（人类口径）；失败写 update.log 并返回 err 由 UI 提示。
        """
        try:
            import hub_update
        except Exception as e:
            return {'ok': False, 'reason': '自更新模块不可用: %r' % (e,)}
        path = setup_path or getattr(self, 'update_package', None)
        r = hub_update.apply_update(path)
        if r.get('ok'):
            self.set_msg("已提交安装任务，LoomHub 将暂时关闭", 'dim')
            self.update_pending_restart = True
            self._quit_for_update()
        else:
            self.set_msg("更新失败: %s（详见 %s）"
                         % (r.get('reason'), hub_update.log_path()), 'err')
        return r

    def _quit_for_update(self):
        """成功提交安装任务后让 Hub 主动退出（"暂时关闭"，不弹"请重启"）。"""
        import threading
        try:
            threading.Timer(0.5, lambda: os._exit(0)).start()
        except Exception as e:
            self.set_msg("提交成功，请手动关闭 LoomHub 后再安装（%r）" % (e,), 'dim')

    def start_background_tasks(self, delay=10.0):
        """启动期钩子（2026-11-09 P1-4）：接上"启动后检查 / 下次启动提示失败"。

        以前 maybe_start_update_check() 与 update_notice() 都没有调用点，
        等于自更新只有 API 没有行为。视图/入口在 UI 建好后调本方法一次。
        """
        note = None
        try:
            note = self.update_notice()
        except (OSError, ValueError) as e:
            try:
                import hub_update
                hub_update.log_line('启动期更新提示失败: %r' % (e,), level='FAIL')
            except (ImportError, OSError, ValueError):
                pass          # 连日志都写不了时只能放弃（不阻断启动）
        if note:
            self.set_msg(note, 'err')
        return self.maybe_start_update_check(delay)

    def maybe_start_update_check(self, delay=10.0):
        """启动后台检查（延迟 ~10s、24h 最多一次、失败静默）。返回线程或 None。"""
        if os.environ.get('LOOM_HUB_NO_UPDATE_CHECK'):
            return None            # 测试/CI 兜底开关：不起后台线程、不联网
        try:
            if not cfg.load_hub_settings().get('check_update_enabled', True):
                return None
        except (OSError, ValueError) as e:
            self.set_msg("读取更新设置失败: %r（本次跳过检查）" % (e,), 'dim')
            return None
        import threading

        def _worker():
            try:
                self.check_update(manual=False)
            except Exception as e:            # 后台线程不得把异常抛到主线程
                try:
                    import hub_update
                    hub_update.log_line('后台检查更新异常: %r' % (e,), level='FAIL')
                except Exception:
                    pass
        t = threading.Timer(float(delay), _worker)
        t.daemon = True
        t.start()
        return t

    def update_notice(self):
        """下次启动时的失败提示（读 update.log，提示后标记已读）。"""
        try:
            import hub_update
        except Exception:
            return None
        line = hub_update.take_pending_failure()
        if line:
            hub_update.mark_failure_seen()
            return "上次更新未完成：%s（详见 update.log）" % line
        return None

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
