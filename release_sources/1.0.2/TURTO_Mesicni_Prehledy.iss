#ifndef MyAppVersion
  #define MyAppVersion "1.0.2"
#endif

#define MyAppName "TURTO – Měsíční přehledy"
#define MyAppPublisher "TURTO s.r.o."
#define MyAppExeName "TURTO_Mesicni_Prehledy.exe"
#define MyUpdaterExeName "TURTO_Mesicni_Prehledy_Updater.exe"

[Setup]
AppId={{8B58E9D7-2C80-4E9A-8BB5-E113203173A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\TURTO Mesicni Prehledy
DefaultGroupName=TURTO – Měsíční přehledy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=..\..\dist\reporting-installer
OutputBaseFilename=TURTO_Mesicni_Prehledy_Setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern dynamic
SetupIconFile=..\..\_stage_102\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=no
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Vytvořit ikonu na ploše"; GroupDescription: "Další možnosti:"

[Files]
Source: "..\..\dist\TURTO Mesicni Prehledy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TURTO – Měsíční přehledy"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\TURTO – Měsíční přehledy"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Spustit TURTO – Měsíční přehledy"; Flags: nowait postinstall skipifsilent
