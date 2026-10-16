# -*- coding: utf-8 -*-
r"""
hub_install.py — LoomHub 解释器安装

两种安装方式:
  1) 本地 .zip 包安装: 选 zip -> 解压到 <安装根>/<版本号>/ -> 校验元数据 -> 登记到配置.
  2) 远程下载安装 (预留接口, 未接服务器): RemoteDownloader 占位, 后续实现 download().
默认安装根 = C:\Program Files\Loom (解释器默认目录名 = 项目名 Loom, 多版本按版本号分目录).
"""
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


def install_from_zip(zip_path, version, target_root=DEFAULT_INSTALL_ROOT):
    """把解释器 .zip 安装到 <target_root>/<version>/ 并登记到配置.

    返回安装目录; 失败抛 InstallError (不写入配置).
    zip 内应含解释器主程序 + 解释器.json (元数据); 允许包内多一层目录 (自动找)."""
    if not zip_path or not os.path.isfile(zip_path):
        raise InstallError("找不到 zip 文件: %s" % zip_path)
    version = str(version).strip()
    # 2026-08-20 安全加固 (Qoder 报告低危4): 版本号格式白名单 ——
    # 版本号直接拼安装路径, 未清洗可经 "..\.." 越权写任意目录
    # (RemoteDownloader 远程安装预留路径, 必须现在堵住).
    # 2026-08-22: 支持 x.y.z.betaN 内测版 (同 hub_config._VERSION_RE, 合同第九节).
    if not _VERSION_RE.match(version):
        raise InstallError("版本号格式非法 (需 x.y.z 或 x.y.z.betaN): %s" % version)
    target = os.path.join(target_root, version)
    try:
        os.makedirs(target, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, target)
    except (zipfile.BadZipFile, OSError, InstallError) as e:
        raise InstallError("解压失败: %s" % e)
    # 校验: 目标目录下应有解释器 (直接或包内一层子目录)
    info = discover_interpreter(target)
    if info is None:
        # zip 顶层可能包了一层目录 (如 <版本号>/), 把该子目录内容整体提升到 target
        for entry in os.listdir(target):
            sub = os.path.join(target, entry)
            if os.path.isdir(sub) and discover_interpreter(sub) is not None:
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
                break
    if info is None:
        raise InstallError("压缩包里没有找到解释器 (缺少 %s 或主程序)" % META_NAME)
    add_interpreter(info)
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
