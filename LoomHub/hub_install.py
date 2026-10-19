# -*- coding: utf-8 -*-
r"""
hub_install.py — LoomHub 解释器安装

两种安装方式:
  1) 本地 .zip 包安装: 选 zip -> 解压到 <安装根>/<版本号>/ -> 校验元数据 -> 登记到配置.
  2) 远程下载安装 (预留接口, 未接服务器): RemoteDownloader 占位, 后续实现 download().
默认安装根 = C:\Program Files\Loom (解释器默认目录名 = 项目名 Loom, 多版本按版本号分目录).
"""
import json
import os
import zipfile

from hub_config import (DEFAULT_INSTALL_ROOT, META_NAME, add_interpreter,
                        discover_interpreter, _VERSION_RE)


class InstallError(Exception):
    """安装过程错误 (zip 损坏 / 缺解释器 / 无权限等)."""


def _safe_extract(zf, target_dir):
    """解压 zip, 防 Zip Slip (拒绝把文件解到目标目录之外).
    2026-08-20 安全加固 (Qoder 报告低危2): startswith 无分隔符边界,
    单层 ".." 归一化后可命中 target 的兄弟目录前缀 (如 1.0evil) 被误放行.
    改为: 必须等于 root 或位于 root + 分隔符 之下."""
    norm = os.path.normpath
    root = norm(target_dir)
    for member in zf.infolist():
        dst = norm(os.path.join(target_dir, member.filename))
        if dst != root and not dst.startswith(root + os.sep):
            raise InstallError("压缩包含越界路径: %s" % member.filename)
        zf.extract(member, target_dir)


def read_zip_metadata(zip_path):
    """读 zip 内的 解释器.json 元数据（不解压全包，只读这一个文件）.

    返回 (info_dict, inner_prefix) 或 (None, None):
      info_dict   : 解释器.json 解析后的 dict
      inner_prefix: zip 内解释器所在的前缀目录（如 'Loom/' 或 '' 表示根）
    """
    if not zip_path or not os.path.isfile(zip_path):
        return None, None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                # 找 "*/解释器.json" 或 "解释器.json"
                if name == META_NAME or name.endswith('/' + META_NAME):
                    with zf.open(name) as f:
                        try:
                            data = json.loads(f.read().decode('utf-8'))
                        except Exception:
                            return None, None
                    prefix = name[:-len(META_NAME)].rstrip('/')
                    if prefix:
                        prefix += '/'
                    return data, prefix
    except (zipfile.BadZipFile, OSError):
        return None, None
    return None, None


def _verify_install_integrity(target_dir):
    """2026-10-19 安装后自检: 检测 .py 文件是否被 AV 篡改成全零.

    背景: 部分安全软件（360 等）在 Program Files 下扫描 .py 时会
    把文件改成全零字节（+128 字节差异），导致引擎启动神秘崩溃。
    安装完成后立即检测，发现损坏时提示用户。

    返回 (ok, corrupted_files)
    """
    if not target_dir or not os.path.isdir(target_dir):
        return True, []
    corrupted = []
    try:
        for dirpath, dirnames, filenames in os.walk(target_dir):
            dirnames[:] = [d for d in dirnames
                           if d not in ('tests', '__pycache__', '保存',
                                        'Projects', 'assets', '.git')]
            for fn in filenames:
                if not fn.endswith('.py'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, 'rb') as f:
                        head = f.read(8192)
                    if len(head) >= 16 and head.count(b'\x00') == len(head):
                        corrupted.append(fp)
                except OSError:
                    pass
    except Exception:
        pass
    return (len(corrupted) == 0), corrupted


def _install_from_zip_impl(zip_path, version, target_root=None):
    """把解释器 .zip 安装到 <target_root>/<version>/ 并登记到配置.

    target_root: 安装根（None = 用 hub_config.DEFAULT_INSTALL_ROOT）

    返回实际登记的解释器目录（可能是 target 本身，也可能是 target/Loom）.

    2026-10-19 增强：
      - 支持自定义 target_root（原只允许固定默认根）
      - 兼容我们发布的 zip 结构（顶层 Loom/ + python/ + Loom.bat）：
        这种情况下直接登记 target_root/version/Loom，不复制残影
      - 兼容标准包内一层包裹（如 <version>/<dir>/解释器.json）：
        保持旧语义：把子目录内容提升到 target_root/version
    """
    if target_root is None:
        target_root = DEFAULT_INSTALL_ROOT
    if not zip_path or not os.path.isfile(zip_path):
        raise InstallError("找不到 zip 文件: %s" % zip_path)
    version = str(version).strip()
    if not _VERSION_RE.match(version):
        raise InstallError("版本号格式非法 (需 x.y.z 或 x.y.z.betaN): %s" % version)
    target = os.path.join(target_root, version)
    try:
        os.makedirs(target, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, target)
    except (zipfile.BadZipFile, OSError, InstallError) as e:
        raise InstallError("解压失败: %s" % e)

    # 情形 1: target 直接有解释器
    info = discover_interpreter(target)
    if info is not None:
        add_interpreter(info)
        return target

    # 情形 2: target 下有一层子目录含解释器
    subdirs_with_interp = []
    for entry in os.listdir(target):
        sub = os.path.join(target, entry)
        if os.path.isdir(sub):
            sub_info = discover_interpreter(sub)
            if sub_info is not None:
                subdirs_with_interp.append((entry, sub, sub_info))

    if not subdirs_with_interp:
        raise InstallError("压缩包里没有找到解释器 (缺少 %s 或主程序)" % META_NAME)

    if len(subdirs_with_interp) == 1:
        entry, sub, sub_info = subdirs_with_interp[0]
        # 判断是否为 "发布包结构"（target 下除了这个子目录还有其他文件，如 python/ Loom.bat）
        other_items = [n for n in os.listdir(target)
                       if os.path.join(target, n) != sub]
        is_release_package = bool(other_items) and entry == 'Loom'
        if is_release_package:
            # 发布包结构：登记 target/Loom，不动其他文件
            add_interpreter(sub_info)
            return sub
        # 标准包内包裹：提升到 target
        import shutil
        for item in os.listdir(sub):
            s = os.path.join(sub, item)
            d = os.path.join(target, item)
            try:
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            except OSError:
                pass
        info = discover_interpreter(target)
        if info is not None:
            add_interpreter(info)
            return target

    # 情形 3: 多个子目录都有解释器 —— 不确定该装哪个，报错
    raise InstallError("压缩包内有多个子目录含解释器, 无法确定安装哪个: %s"
                       % [e for e, _, _ in subdirs_with_interp])


def install_from_zip(zip_path, version, target_root=None):
    """公开安装入口（2026-10-19: 包装 _install_from_zip_impl + 完整性自检）.

    安装后自动检测 .py 文件是否被安全软件篡改成全零字节，
    发现时打印警告到 stderr（不抛异常，但用户可感知）。
    """
    target = _install_from_zip_impl(zip_path, version, target_root=target_root)
    # 安装后自检
    try:
        ok, corrupted = _verify_install_integrity(target)
        if not ok:
            import sys as _sys
            print('[警告] 检测到 %d 个 .py 文件被篡改（全零字节）:' % len(corrupted),
                  file=_sys.stderr)
            for fp in corrupted[:5]:
                print('  ' + fp, file=_sys.stderr)
            if len(corrupted) > 5:
                print('  ... 还有 %d 个' % (len(corrupted) - 5),
                      file=_sys.stderr)
            print('[警告] 请关闭安全软件后重新安装，或将安装目录加入白名单',
                  file=_sys.stderr)
    except Exception:
        pass
    return target


class RemoteDownloader:
    """远程下载解释器接口 (预留).

    目前没有稳定下载服务器, download() 抛 NotImplementedError.
    后续接入: 子类/替换实现 download(url, target_dir) -> 下载到本地 zip 路径,
    再交给 install_from_zip 走同一套安装流程即可.
    """
    def download(self, url, target_dir):
        raise NotImplementedError(
            "远程下载暂未开放: 请用本地 .zip 安装 (选择 zip 包直接安装)")
