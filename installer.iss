; Inno Setup 安装包脚本：档案机构监测工作台
[Setup]
AppId={{7C4A2E9F-3B18-4D6E-9A55-Dangan0Mon01}}
AppName=档案机构监测工作台
AppVersion=1.0
AppPublisher=档案机构监测工作台
DefaultDirName={autopf}\DanganOrgMonitor
DefaultGroupName=档案机构监测工作台
UninstallDisplayName=档案机构监测工作台
OutputDir=installer
OutputBaseFilename=DanganOrgMonitor-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
; 程序运行时持有该互斥体：安装前若检测到会提示"程序正在运行"
AppMutex=DanganOrgMonitorMutex

[Languages]
Name: "cn"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加任务:"

[Files]
Source: "dist\DanganOrgMonitor.exe"; DestDir: "{app}"
; 预置全国基线数据，仅在用户目录不存在时复制，卸载时保留用户数据
Source: "data.db"; DestDir: "{userappdata}\档案机构监测工作台"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\档案机构监测工作台"; Filename: "{app}\DanganOrgMonitor.exe"
Name: "{group}\卸载档案机构监测工作台"; Filename: "{uninstallexe}"
Name: "{autodesktop}\档案机构监测工作台"; Filename: "{app}\DanganOrgMonitor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DanganOrgMonitor.exe"; Description: "运行 档案机构监测工作台"; Flags: postinstall nowait skipifsilent

[Code]
// 复制文件前静默结束正在运行的旧版程序，
// 避免 exe 被占用导致 DeleteFile failed code 5（拒绝访问）
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /f /im DanganOrgMonitor.exe >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(800);  // 留出系统释放文件句柄的时间
end;

// 卸载前同样先结束程序，避免卸载残留
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /f /im DanganOrgMonitor.exe >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(800);
  Result := True;
end;
