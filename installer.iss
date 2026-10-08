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
