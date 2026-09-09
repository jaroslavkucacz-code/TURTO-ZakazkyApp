#ifndef MyAppVersion
  #define MyAppVersion "8.0.0-preview.1"
#endif

#define MyAppName "TURTO CRM"
#define MyAppPublisher "TURTO s.r.o."
#define MyAppExeName "TURTO CRM.exe"

[Setup]
AppId={{D1556395-8E6D-49E0-B190-4C5A2D31C2D0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\TURTO CRM
DefaultGroupName=TURTO CRM
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=TURTO_CRM_Setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern dynamic
SetupIconFile=..\..\ZakazkyApp_base_6.1\turto_logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Vytvořit ikonu na ploše"; GroupDescription: "Další možnosti:"; Flags: unchecked

[Files]
Source: "..\..\dist\TURTO CRM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TURTO CRM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\TURTO CRM"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Spustit TURTO CRM"; Flags: nowait postinstall skipifsilent
