; 快截OCR (SnapOCR) 安装包脚本 —— per-user 安装，无需管理员权限
; 构建: iscc deploy\windows\snapocr.iss   （需先完成 PyInstaller 打包）

#define MyAppName "截图工具"
#define MyAppNameEn "SnapOCR"
#define MyAppVersion "1.0.0"
#define MyAppExeName "SnapOCR.exe"

[Setup]
AppId={{7E1A2C649B0D4E8FA2C1B5D3E9F00101}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} ({#MyAppNameEn})
AppPublisher=中共枣庄市委组织部
AppPublisherURL=http://www.zaozhuang.gov.cn
DefaultDirName={localappdata}\Programs\SnapOCR
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=SnapOCR-{#MyAppVersion}-win64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern dynamic
; dynamic：向导配色跟随系统亮/暗主题（Inno Setup 7 新增）。
; 不加 dynamic 时固定浅色，暗色系统上安装界面会刺眼（2026-10-26 用户反馈）。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\..\resources\app.ico
MinVersion=6.1sp1

[Languages]
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; 自启默认勾选（2026-10-26 用户要求）：安装页的选择是唯一事实源，
; 未勾选时由下方 CurStepChanged 清掉旧装机残留的 Run 键
Name: "autostart"; Description: "开机自动启动（后台托盘常驻）"

[Files]
Source: "..\..\dist\snapocr-win64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; VC++ 2015-2022 x64 运行库：onnxruntime 依赖，干净系统缺失会导致首次 OCR 直接崩溃。
; 把 vc_redist.x64.exe 放到本 .iss 同目录即可（缺失时跳过，不阻塞构建）。
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "SnapOCR"; ValueData: """{app}\{#MyAppExeName}"" --hidden"; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
; 静默安装运行库（shellexec 以便 vc_redist 自身清单触发 UAC 提权）
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/quiet /norestart"; \
    StatusMsg: "正在安装 Microsoft Visual C++ 运行库..."; \
    Flags: waituntilterminated shellexec; Check: VcRedistNeeded
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v SnapOCR /f"; Flags: runhidden; RunOnceId: "DelAutoStart"

[Code]
// 安装收尾：按安装页选择对齐注册表 Run 键——未勾选自启时清掉旧装机残留
// （否则上一版写入的 Run 键继续生效，"安装时没勾但开机仍自启"）。
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not WizardIsTaskSelected('autostart')) then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'SnapOCR');
end;

// 卸载前先结束常驻进程，避免文件被锁导致"Some elements could not be removed"
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{cmd}'), '/C taskkill /f /im SnapOCR.exe',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// VC++ 2015-2022 x64 是否已安装（注册表 Version 形如 14.38.33130.0）
function VcRedistInstalled(): Boolean;
var
  Version: string;
begin
  Result := RegQueryStringValue(HKLM,
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
    'Version', Version) and (CompareStr(Version, '14.29') >= 0);
end;

// 仅当"运行库文件存在 且 未安装"时才执行静默安装
function VcRedistNeeded(): Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\vc_redist.x64.exe'))
            and not VcRedistInstalled();
end;

[Messages]
SetupAppTitle=安装 - {#MyAppName}
WelcomeLabel2=这将安装 [name/ver] 到你的电脑。%n%n它是一款完全离线的截图+OCR工具：托盘常驻、快捷键框选、RapidOCR 本地识别，不上传任何数据。
