; installer.iss — LoomHub 安装程序（由 package_hub.py 自动生成）
#define MyAppName "LoomHub"
#define MyAppVersion "0.1.2"
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

[InstallDelete]
; 2026-11-08 (beta3 回补审计): 覆盖安装 0.1.1 -> 0.1.2 时, PyInstaller onedir 的
; _internal\ 会残留旧版本的 .pyd/.dll/模块, 导致"升级后反而起不来"或行为诡异。
; 只清 PyInstaller 自己产出的目录, 不动用户在 {app} 下自己放的东西。
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
{ 2026-11-08 用户配置目录契约: LoomHub 设置改存 %LOCALAPPDATA%\Loom\hub。
  卸载时询问是否一并删除；默认按钮 = "否"（保留），静默卸载一律保留。
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
