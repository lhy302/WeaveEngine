# -*- coding: utf-8 -*-
"""package_hub.py — LoomHub 安装包打包器（2026-10-19）

产物：tools/dist/LoomHub-<version>-Setup.exe
流程：PyInstaller -> Inno Setup
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB_DIR = os.path.join(ROOT, 'LoomHub')
DIST_DIR = os.path.join(ROOT, 'tools', 'dist')
BUILD_DIR = os.path.join(ROOT, 'tools', 'build_hub')
VERSION_FILE = os.path.join(HUB_DIR, '版本.json')
ISS_FILE = os.path.join(ROOT, 'tools', 'installer.iss')
DEFAULT_VERSION = '0.1.0'


def load_version(override=None):
    if override:
        return override
    if os.path.isfile(VERSION_FILE):
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('version', DEFAULT_VERSION)
    with open(VERSION_FILE, 'w', encoding='utf-8') as f:
        json.dump({'version': DEFAULT_VERSION}, f, ensure_ascii=False, indent=2)
    return DEFAULT_VERSION


def find_iscc():
    for exe in ('ISCC.exe', 'iscc'):
        p = shutil.which(exe)
        if p:
            return p
    # Inno Setup 7/6/8 常见安装位置（优先 7，因为用户已装 7）
    for ver in ('7', '6', '8'):
        for pf in (r'C:\Program Files', r'C:\Program Files (x86)'):
            c = os.path.join(pf, 'Inno Setup %s' % ver, 'ISCC.exe')
            if os.path.isfile(c):
                return c
    return None


def run_pyinstaller(version):
    os.makedirs(BUILD_DIR, exist_ok=True)
    entry = os.path.join(HUB_DIR, 'LoomHub.py')
    if not os.path.isfile(entry):
        raise SystemExit('[错误] 找不到入口: %s' % entry)
    splash_path = os.path.join(ROOT, 'tools', 'build_assets', 'splash.png')
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean',
        # 2026-10-19 方案 B: --onedir（0.3 秒启动）替代 --onefile（2~5 秒解压）
        # 用户报告"连点开 17 个窗口"根因是 onefile 启动慢 + 用户以为没反应。
        # onedir 直接从磁盘读 _internal/ 子目录，秒开。单实例锁仍是兜底防线。
        '--onedir', '--windowed',
        '--name', 'LoomHub',
        '--distpath', BUILD_DIR,
        '--workpath', os.path.join(BUILD_DIR, '_work'),
        '--specpath', BUILD_DIR,
        '--paths', HUB_DIR,
        '--paths', os.path.join(ROOT, 'Loom'),
        '--hidden-import', 'tkinter',
        '--hidden-import', 'tkinter.simpledialog',
        '--hidden-import', 'tkinter.messagebox',
        '--hidden-import', 'parallel',
        '--hidden-import', 'guiloader',
        '--hidden-import', 'filedialog',
        '--hidden-import', 'hub_commands',
        '--hidden-import', 'hub_console',
        '--hidden-import', 'hub_view_tk',
        '--hidden-import', 'hub_controller',
        '--hidden-import', 'hub_config',
        '--hidden-import', 'hub_install',
        '--hidden-import', 'hub_single_instance',
    ]
    # splash 图存在才加（缺图也能打，只是没启动画面）
    if os.path.isfile(splash_path):
        cmd += ['--splash', splash_path]
    cmd.append(entry)
    print('[打包] PyInstaller 运行中...')
    subprocess.check_call(cmd, cwd=ROOT)
    # onedir 产物 = BUILD_DIR/LoomHub/LoomHub.exe + _internal/
    exe_path = os.path.join(BUILD_DIR, 'LoomHub', 'LoomHub.exe')
    if not os.path.isfile(exe_path):
        raise SystemExit('[错误] PyInstaller 未产出 exe: %s' % exe_path)
    print('[打包] LoomHub.exe: %.2f MB' % (os.path.getsize(exe_path) / (1024 * 1024)))
    return exe_path



ISS_TEMPLATE = r'''; installer.iss — LoomHub 安装程序（由 package_hub.py 自动生成）
#define MyAppName "LoomHub"
#define MyAppVersion "%(version)s"
#define MyAppPublisher "lhy302"
#define MyAppURL "https://github.com/lhy302/WeaveEngine"
#define MyAppExeName "LoomHub.exe"

[Setup]
AppId={{8D2B5F1A-3C6E-4A29-9B3F-1A5E2C7D4B6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=LoomHub-{#MyAppVersion}-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[Files]
; 2026-10-19 方案 B: --onedir 模式产物 = exe + _internal/ 目录，整个打进来
Source: "build_hub\LoomHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
'''


def write_iss(version):
    os.makedirs(os.path.dirname(ISS_FILE), exist_ok=True)
    with open(ISS_FILE, 'w', encoding='utf-8') as f:
        f.write(ISS_TEMPLATE % {'version': version})


def run_inno(version):
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit('[错误] 未找到 Inno Setup 编译器 (ISCC.exe)。下载: https://jrsoftware.org/isdl.php')
    print('[打包] Inno Setup: %s' % iscc)
    subprocess.check_call([iscc, ISS_FILE], cwd=os.path.join(ROOT, 'tools'))
    setup_path = os.path.join(DIST_DIR, 'LoomHub-%s-Setup.exe' % version)
    if not os.path.isfile(setup_path):
        raise SystemExit('[错误] Inno Setup 未产出安装包: %s' % setup_path)
    print('[打包] 安装包: %s (%.2f MB)' % (setup_path, os.path.getsize(setup_path) / (1024 * 1024)))
    return setup_path


def main():
    parser = argparse.ArgumentParser(description='LoomHub 安装包打包器')
    parser.add_argument('--version', help='覆盖版本号')
    parser.add_argument('--skip-exe', action='store_true', help='跳过 PyInstaller')
    args = parser.parse_args()
    version = load_version(args.version)
    print('=' * 60)
    print('LoomHub 安装包打包 — 版本 %s' % version)
    print('=' * 60)
    if not args.skip_exe:
        run_pyinstaller(version)
    write_iss(version)
    setup_path = run_inno(version)
    print()
    print('下一步:')
    print('  1) 本地测试: 双击 %s' % setup_path)
    print('  2) 上传: GitHub Releases -> tag hub-v%s -> 上传该 exe' % version)


if __name__ == '__main__':
    main()
