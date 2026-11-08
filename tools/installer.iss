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
; 2026-11-08: 允许命令行 /ALLUSERS 覆盖（自动化覆盖安装到 Program Files 用）；
; 没有它时静默安装会默认落到 %LOCALAPPDATA%\Programs，与已有安装并存。
PrivilegesRequiredOverridesAllowed=dialog commandline
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
