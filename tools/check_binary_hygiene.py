#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""tools/check_binary_hygiene.py — 二进制发布形态体检（durable，防退化）。

为什么存在（2026-11-13 360 误报整改）：
  360 只报 build_game.exe，根因三条叠加：
    ① 它是唯一 --mode=onefile 的产物（自解压到 %TEMP% 再执行 = 投放器特征）；
    ② 三个 exe 全都没有版本资源（CompanyName/ProductName/FileDescription/FileVersion 全空）；
    ③ 全部未签名（无证书，本就不靠签名解决）。
  裁决：构建器改 onedir + 给三个 exe 补版本资源。本脚本把这两条变成可执行判据：
  以后谁把 exe 改回 onefile、或构建时漏了版本资源，一条命令就能抓到并非 0 退出。

判据：
  1) 版本资源：CompanyName / ProductName / FileDescription / FileVersion 必须非空
     （ctypes 走 Win32 version.dll 真读 PE 的 RT_VERSION；读不到时退化为对文件
      做 UTF-16LE 串扫描，两种都是真读文件，不猜）；
  2) 形态：单文件且 > 15MB 时打印 '⚠ 疑似 onefile'；若同目录也没有 <name>.dist/
     就判不合格（onedir 的 exe 永远在 <out>/<name>.dist/ 里，巨型单文件只可能是
     onefile —— 本次整改的核心判据）；
     例外：同目录有 python3*.dll（Nuitka standalone 签名）时视为「平铺 onedir」
     —— 发布包里 Loom/builder/ 就是这种形态（build_game.dist 内容平铺），
     不认这一条会把合规的发布包反判成 onefile。
  3) 报告：每个 exe 打印 sha256 与字节数/大小。

用法：
  py -3.13 tools/check_binary_hygiene.py <exe> [<exe> ...]
  py -3.13 tools/check_binary_hygiene.py --dir C:\loom_build\builder\build_game.dist
  py -3.13 tools/check_binary_hygiene.py \
      C:\loom_build\engine\build_entry.dist\Loom.exe \
      C:\loom_build\builder\build_game.dist\build_game.exe \
      D:\...\player_runtime\game_player.dist\MyGame.exe
退出码：0 = 全部合格；1 = 有不合格项（版本资源缺失 / 疑似 onefile）；2 = 用法错误。
"""
import argparse
import hashlib
import os
import re
import struct
import sys

MIN_ONEFILE_MB = 15.0
REQUIRED_FIELDS = ('CompanyName', 'ProductName', 'FileDescription', 'FileVersion')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_version_ctypes(path):
    """ctypes 读 PE 版本资源 -> ({Field: value}, 说明)。字段名保持 Win32 原名。"""
    if os.name != 'nt':
        return {}, 'ctypes 版本 API 仅 Windows 可用'
    import ctypes
    from ctypes import wintypes
    try:
        ver = ctypes.WinDLL('version')
    except OSError as e:
        return {}, '加载 version.dll 失败: %r' % (e,)
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR,
                                            ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                        wintypes.DWORD, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL

    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return {}, 'GetFileVersionInfoSizeW=0（该 exe 没有任何版本资源）'
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return {}, 'GetFileVersionInfoW 失败'
    buf_ptr = ctypes.cast(buf, ctypes.c_void_p)

    def query(sub, chars=False):
        """取一段资源原始字节。chars=True 表示 ln 的单位是**字符**（Win32 文档：
        字符串值按字符计数，不是字节；按字节读会截断成半截 —— 实测 notepad.exe
        的 CompanyName 会被读成 'Microsoft C'）。"""
        lp = ctypes.c_void_p()
        ln = wintypes.UINT()
        if not ver.VerQueryValueW(buf_ptr, sub, ctypes.byref(lp),
                                  ctypes.byref(ln)):
            return None
        if not lp.value or not ln.value:
            return None
        nbytes = ln.value * 2 if chars else ln.value
        return ctypes.string_at(lp.value, nbytes)

    translations = []
    raw = query('\\VarFileInfo\\Translation')
    if raw:
        for i in range(0, len(raw) - 3, 4):
            lang, cp = struct.unpack_from('<HH', raw, i)
            translations.append((lang, cp))
    if not translations:
        return {}, '版本资源里没有 VarFileInfo\\Translation'

    out = {}
    for lang, cp in translations:
        for field in REQUIRED_FIELDS + ('Copyright',):
            if out.get(field):
                continue
            sub = '\\StringFileInfo\\%04x%04x\\%s' % (lang, cp, field)
            raw = query(sub, chars=True)
            if not raw:
                continue
            try:
                val = raw.decode('utf-16-le').split('\x00', 1)[0].strip()
            except Exception:
                continue
            if val:
                out[field] = val
        if all(out.get(f) for f in REQUIRED_FIELDS):
            break
    # StringFileInfo 缺 FileVersion 时退到 VS_FIXEDFILEINFO 的数值版本
    if not out.get('FileVersion'):
        raw = query('\\')
        if raw and len(raw) >= 16:
            ms, ls = struct.unpack_from('<II', raw, 8)
            out['FileVersion'] = '%d.%d.%d.%d' % (ms >> 16, ms & 0xFFFF,
                                                  ls >> 16, ls & 0xFFFF)
    return out, ''


def _read_version_scan(path):
    """兜底：把文件按 UTF-16LE 解出来扫版本串（真读文件，无需 Win32 API）。"""
    try:
        with open(path, 'rb') as f:
            blob = f.read()
    except OSError:
        return {}
    out = {}
    # 资源在文件里的偏移可能是奇数（4 字节对齐是相对节区），从 0/1 两个相位各扫一遍
    for off in (0, 1):
        text = blob[off:].decode('utf-16-le', errors='ignore')
        for field in REQUIRED_FIELDS + ('Copyright',):
            if out.get(field):
                continue
            m = re.search(re.escape(field) + '\x00+([^\x00]{1,300})', text)
            if not m:
                continue
            val = re.sub(r'\s+', ' ', m.group(1)).strip()
            if not val or val.startswith('%'):
                continue
            if field == 'FileVersion' and not re.match(r'^\d+(\.\d+){1,3}$', val):
                continue
            out[field] = val
        if all(out.get(f) for f in REQUIRED_FIELDS):
            break
    return out


def read_version_info(path):
    """返回 ({字段: 值}, 说明)。优先真读 RT_VERSION，失败时 UTF-16 串扫描兜底。"""
    info, why = _read_version_ctypes(path)
    if all(info.get(f) for f in REQUIRED_FIELDS):
        return info, why
    scan = _read_version_scan(path)
    if scan:
        merged = dict(scan)
        for k, v in info.items():
            if v:
                merged[k] = v
        note = 'ctypes 读取不完整（%s），已用 UTF-16LE 串扫描兜底' % (why or '字段不全')
        return merged, note
    return info, why


def print_form_and_fields(path, size, info, why):
    """打印版本资源与形态报告，返回不合格原因列表。"""
    problems = []
    print('=' * 76)
    print(path)
    print('  size   = %.2f MB (%d bytes)' % (size / 1048576.0, size))
    print('  sha256 = %s' % sha256_file(path))
    if why:
        print('  版本资源读取: %s' % why)
    for field in REQUIRED_FIELDS:
        val = (info.get(field) or '').strip()
        print('  %-15s = %s' % (field, val if val else '<空>'))
        if not val:
            problems.append('版本资源 %s 为空' % field)

    parent = os.path.dirname(os.path.abspath(path))
    in_dist = os.path.basename(parent).lower().endswith('.dist')
    stem = os.path.splitext(os.path.basename(path))[0]
    size_mb = size / 1048576.0
    if in_dist:
        print('  形态   = onedir（exe 位于 %s/ 内）' % os.path.basename(parent))
    else:
        print('  形态   = 单文件')
        if size_mb > MIN_ONEFILE_MB:
            print('  ⚠ 疑似 onefile（单文件 %.1fMB > %.0fMB）'
                  % (size_mb, MIN_ONEFILE_MB))
            sibling = os.path.join(parent, stem + '.dist')
            try:
                flat_py = sorted(n for n in os.listdir(parent)
                                 if n.lower().startswith('python3')
                                 and n.lower().endswith('.dll'))
            except OSError:
                flat_py = []
            if os.path.isdir(sibling):
                print('    同目录存在 %s.dist/：按"有 dist 伴生"放行' % stem)
            elif flat_py:
                print('    同目录有 %s：按"平铺 onedir（发布包 Loom/builder/ 布局）"放行'
                      % ', '.join(flat_py[:3]))
            else:
                problems.append('疑似 onefile: 单文件 %.1fMB 且同目录没有 %s.dist/'
                                % (size_mb, stem))
    return problems


def check_exe(path):
    if not os.path.isfile(path):
        print('=' * 76)
        print(path)
        print('  ✗ 文件不存在')
        return ['文件不存在']
    size = os.path.getsize(path)
    info, why = read_version_info(path)
    problems = print_form_and_fields(path, size, info, why)
    if problems:
        for p in problems:
            print('  ✗ %s' % p)
    else:
        print('  ✓ 合格')
    return problems


def _exes_in_dir(directory):
    return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                  if n.lower().endswith('.exe')
                  and os.path.isfile(os.path.join(directory, n)))


def main(argv=None):
    # 版本资源里可能有 ®/中文；Windows 控制台默认 GBK，直接 print 会 UnicodeEncodeError
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description='二进制发布形态体检：版本资源非空 + 不冒充 onefile')
    ap.add_argument('exes', nargs='*', help='要检查的 exe 路径（可多个）')
    ap.add_argument('--dir', action='append', default=[],
                    help='目录（检查其直接子级 *.exe；可重复给）')
    a = ap.parse_args(argv)

    targets = []
    for p in a.exes:
        targets.append(os.path.abspath(p))
    for d in a.dir:
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            print('ERROR 目录不存在: %s' % d)
            return 1
        found = _exes_in_dir(d)
        if not found:
            print('ERROR 目录里没有 .exe: %s' % d)
            return 1
        targets.extend(found)
    targets = list(dict.fromkeys(targets))
    if not targets:
        ap.print_help()
        return 2

    bad = 0
    for p in targets:
        if check_exe(p):
            bad += 1
    print('=' * 76)
    if bad:
        print('结论: %d/%d 不合格（形态/版本资源整改被破坏）'
              % (bad, len(targets)))
        return 1
    print('结论: %d/%d 全部合格' % (len(targets), len(targets)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
