; DevPrompt AI 桌面端安装脚本（Inno Setup 7.1.0，版本经 jrsoftware.org 核实，MUST-24b）
;
; 覆盖安装即升级：固定 AppId + 固定 DefaultDirName，重跑安装包原地覆盖文件。
; PrivilegesRequired=lowest：装到 {localappdata}\Programs，免 UAC。
; CloseApplications：覆盖安装前关闭正在运行的应用（否则 exe 被占用写不进去）。
;
; 版本号由 desktop/scripts/build-desktop.ps1 经 /DMyAppVersion= 注入
; （唯一来源 pyproject.toml 的 version，不手抄）；缺省值仅供本地手动编译兜底。

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppName "DevPrompt AI"
#define MyAppExeName "DevPrompt AI.exe"

[Setup]
AppId={{8F2C4E1A-3B5D-4F6E-9A7C-D1E2F3A4B5C6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=DevPromptAISetup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName},devprompt-ai-desktop.exe
RestartApplications=no
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; 安装器自身的版本元数据：无签名的二进制带元数据，SmartScreen/杀软误报率更低
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=DevPrompt AI
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}.0

[Languages]
Name: chinesesimplified; MessagesFile: compiler:Languages\ChineseSimplified.isl

[Tasks]
Name: desktopicon; Description: 创建桌面快捷方式; GroupDescription: 附加任务:

[Files]
Source: ..\dist\stage\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\{#MyAppName}; Filename: {app}\{#MyAppExeName}
Name: {group}\卸载 {#MyAppName}; Filename: {uninstallexe}
; 每用户安装（PrivilegesRequired=lowest）不能写 {commondesktop}（公共桌面，需管理员，
; 实测 IPersistFile::Save 0x80070005 拒绝访问）；桌面快捷方式走 {userdesktop}
Name: {userdesktop}\{#MyAppName}; Filename: {app}\{#MyAppExeName}; Tasks: desktopicon

[Run]
Filename: {app}\{#MyAppExeName}; Description: 启动 {#MyAppName}; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; sidecar 的 LOG_DIR 默认 ./ .logs（相对其 CWD=resources\sidecar），
; 安装器不认识这些运行时产物，卸载时显式清理
Type: filesandordirs; Name: {app}\resources\sidecar\.logs
