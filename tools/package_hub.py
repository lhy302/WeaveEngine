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


def load_version(override=None):
    """LoomHub 版本号 = LoomHub/版本.json（**唯一真源**，人类裁决 2026-11-08 · N5=A）。

    为什么删掉原来的 DEFAULT_VERSION 静默回落：
      · 旧实现在 版本.json 缺失时会**回写** {version: '0.1.0'} 并返回它，而
        release_github 的缺省 HUB_VERSION 是 0.1.2 -> 两条链各说一个版本号，
        独立验收实测能产出版本号互不匹配的产物（N5 事实源漏口）。
      · 打包动作隐式改源码文件本身不可审计：发出去的版本号会取决于上一次构建的副作用。
    现在：缺文件 / 缺字段 / 坏 JSON 一律**明确报错退出**（非 0），绝不猜、也绝不回写。
    """
    if override:
        return str(override).strip()
    if not os.path.isfile(VERSION_FILE):
        raise SystemExit(
            '[错误] 缺少版本真源: %s\n'
            '  该文件是 LoomHub 版本号的唯一来源 —— release_github 的缺省 '
            'HUB_VERSION 与 installer.iss 的 MyAppVersion 都必须与它相等。\n'
            '  修复: 新建该文件并写入 {"version": "0.1.2"}\n'
            '        或显式传 --version <x.y.z>（本次不写回该文件）。' % VERSION_FILE)
    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:      # 权限/IO + JSON/编码错误；其余照常上抛
        raise SystemExit('[错误] 版本真源不可读/不是合法 JSON: %r (%s)'
                         % (e, VERSION_FILE))
    v = str(data.get('version') or '').strip() if isinstance(data, dict) else ''
    if not v:
        raise SystemExit('[错误] 版本真源缺少 version 字段: %s' % VERSION_FILE)
    return v


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
    # 2026-11-09 H2: 把版本真源一起打进产物 —— 安装版 LoomHub 要能自报版本
    # （hub_update.local_version() 从 _MEIPASS/版本身边找 版本.json）。
    if os.path.isfile(VERSION_FILE):
        cmd += ['--add-data', '%s%s%s' % (VERSION_FILE, os.pathsep, '.')]
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
; 2026-11-08: 允许命令行 /ALLUSERS（自动化覆盖安装到 Program Files 用）。
; 只有 dialog 时, 静默安装会默认落 %%LOCALAPPDATA%%\Programs, 与既有安装并存成两份。
PrivilegesRequiredOverridesAllowed=dialog commandline
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[InstallDelete]
; 2026-11-08: 覆盖安装时必须清掉 PyInstaller 的 _internal/ 旧文件。
; 只覆盖不删除会让旧版残留的 .pyd/.dll/模块混进新版本, 典型后果是"升级后反而起不来"。
; 实测证据: 0.1.1 -> 0.1.2 覆盖后, _internal 里仍留着 0.1.1 写的 interpreters.json/projects.json。
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; 2026-10-19 方案 B: --onedir 模式产物 = exe + _internal/ 目录，整个打进来
Source: "build_hub\LoomHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
{ 2026-11-08 用户配置目录契约: LoomHub 的设置/台账改存 %%LOCALAPPDATA%%\Loom\hub。
  卸载时询问是否一并删除；默认按钮 = 否（保留），静默卸载一律保留。
  注意: 只删 LoomHub 自己的 hub 子树，绝不动引擎的 engine/ 与游戏存档。 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserCfg: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  UserCfg := ExpandConstant('{localappdata}\Loom\hub');
  if not DirExists(UserCfg) then
    Exit;
  if UninstallSilent then
    Exit;
  if MsgBox('是否同时删除 LoomHub 的用户配置？' + #13#10 + #13#10
            + UserCfg + #13#10 + #13#10
            + '选择"否"= 保留（默认）。保留后重装或换版本仍沿用你的设置。',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(UserCfg, True, True, True);
end;
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
