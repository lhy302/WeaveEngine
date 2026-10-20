# -*- coding: utf-8 -*-
"""package_engine.py — Loom 引擎发布包打包器（2026-10-19）

产物：tools/dist/Loom-<version>.zip
内容：Loom/ 运行时文件 + 嵌入式 Python 3.12 + 解释器.json
用法：py -3.12 tools/package_engine.py [--version X.Y.Z]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.join(ROOT, 'Loom')
DIST_DIR = os.path.join(ROOT, 'tools', 'dist')
META_PATH = os.path.join(ENGINE_DIR, '解释器.json')

EXCLUDE_DIRS = {'tests', '保存', 'Projects', '__pycache__', '.pytest_cache', 'assets'}
EXCLUDE_EXTS = {'.pyc', '.pyo', '.log', '.tmp'}
EXCLUDE_FILES = {'解释器.json.bak'}


def load_version(override=None):
    if override:
        return override
    with open(META_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)['version']


def collect_files(src_dir):
    out = []
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn in EXCLUDE_FILES:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXCLUDE_EXTS:
                continue
            abs_p = os.path.join(dirpath, fn)
            rel_p = os.path.relpath(abs_p, src_dir).replace('\\', '/')
            out.append((abs_p, rel_p))
    return out


def find_python_embed():
    env = os.environ.get('LOOM_PYEMBED_DIR')
    if env and os.path.isdir(env):
        return env
    local = os.path.join(ROOT, 'tools', 'python-embed')
    if os.path.isdir(local):
        return local
    for c in (os.path.expandvars(r'%LOCALAPPDATA%\Programs\Python\Python312'),
              r'C:\Python312'):
        if os.path.isfile(os.path.join(c, 'python.exe')):
            return c
    return None



def build_embed_pyzip(version, out_dir):
    py_root = find_python_embed()
    if py_root is None:
        raise SystemExit(
            '[错误] 找不到 Python 3.12 运行时。\n'
            '  请设置环境变量 LOOM_PYEMBED_DIR，或把 Python312 目录拷贝到 tools/python-embed/')
    print('[打包] 嵌入 Python: %s' % py_root)
    tmp_py = os.path.join(out_dir, '_python_tmp')
    if os.path.isdir(tmp_py):
        shutil.rmtree(tmp_py)
    # 只复制 Python 运行时本体，排除原 site-packages（避免带进不相关的大包）
    EXCL = {'__pycache__', 'test', 'tests', 'Doc', 'Tools', 'tcl', 'idlelib',
            'site-packages', 'Scripts'}
    def _ignore(d, names):
        return [n for n in names if n in EXCL]
    shutil.copytree(py_root, tmp_py, ignore=_ignore)
    # 重建干净的 site-packages + 只装 requirements.txt
    site_pkg = os.path.join(tmp_py, 'Lib', 'site-packages')
    os.makedirs(site_pkg, exist_ok=True)
    req_path = os.path.join(ROOT, 'requirements.txt')
    if os.path.isfile(req_path):
        print('[打包] 安装运行时依赖（仅 requirements.txt 声明的包）...')
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install',
            '-r', req_path, '--target', site_pkg,
            '-q', '--no-warn-script-location',
        ])
    return tmp_py


def write_launcher(out_dir):
    # 2026-10-20 白屏修复：用 pythonw.exe 替代 python.exe（无控制台窗口）。
    # python.exe 启动会弹 ConsoleWindowClass 抢在编辑器前面，用户误以为白屏。
    # 纯 ASCII 编码（Windows cmd 对 UTF-8 BAT 支持差，中文会乱码）。
    bat = ('@echo off\r\n'
           'setlocal\r\n'
           'cd /d "%~dp0"\r\n'
           '"%~dp0python\\pythonw.exe" "%~dp0Loom\\Loom.py" %*\r\n')
    with open(os.path.join(out_dir, 'Loom.bat'), 'w', encoding='ascii') as f:
        f.write(bat)


def write_meta_readme(out_dir, version):
    readme = ('Loom 引擎 %s\n================\n'
              '嵌入式 Python 运行时已内置，双击 Loom.bat 启动。\n\n'
              '目录结构:\n'
              '  Loom.bat          <- 双击启动\n'
              '  python/           <- 嵌入式 Python 3.12（含依赖）\n'
              '  Loom/             <- 引擎源码\n'
              '    Loom.py         <- 主程序\n'
              '    解释器.json     <- LoomHub 识别元数据\n') % version
    with open(os.path.join(out_dir, 'README.txt'), 'w', encoding='utf-8') as f:
        f.write(readme)



def make_zip(version):
    os.makedirs(DIST_DIR, exist_ok=True)
    tmp_dir = os.path.join(DIST_DIR, '_Loom_%s_tmp' % version)
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)
    print('[打包] 收集引擎文件...')
    engine_files = collect_files(ENGINE_DIR)
    print('[打包] 引擎文件数: %d' % len(engine_files))
    for abs_p, rel_p in engine_files:
        dst = os.path.join(tmp_dir, 'Loom', rel_p)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(abs_p, dst)
    print('[打包] 复制嵌入式 Python...')
    tmp_py = build_embed_pyzip(version, tmp_dir)
    target_py = os.path.join(tmp_dir, 'python')
    shutil.move(tmp_py, target_py)
    write_launcher(tmp_dir)
    write_meta_readme(tmp_dir, version)
    zip_path = os.path.join(DIST_DIR, 'Loom-%s.zip' % version)
    print('[打包] 写 zip: %s' % zip_path)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, _dirnames, filenames in os.walk(tmp_dir):
            for fn in filenames:
                abs_p = os.path.join(dirpath, fn)
                rel_p = os.path.relpath(abs_p, tmp_dir).replace('\\', '/')
                zf.write(abs_p, rel_p)
    # Windows 下 DLL 可能仍被占用，忽略清理失败（不影响 zip 产物）
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print('[打包] 完成: %s (%.2f MB)' % (zip_path, size_mb))
    return zip_path


def main():
    parser = argparse.ArgumentParser(description='Loom 引擎发布包打包器')
    parser.add_argument('--version', help='覆盖版本号（默认读 Loom/解释器.json）')
    args = parser.parse_args()
    version = load_version(args.version)
    print('=' * 60)
    print('Loom 引擎打包 — 版本 %s' % version)
    print('=' * 60)
    zip_path = make_zip(version)
    print()
    print('下一步:')
    print('  1) 测试: 解压 %s' % os.path.basename(zip_path))
    print('  2) 上传: GitHub Releases -> tag engine-v%s -> 上传 zip' % version)


if __name__ == '__main__':
    main()
