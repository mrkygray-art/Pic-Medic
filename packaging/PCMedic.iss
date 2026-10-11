; Inno Setup script for PC Medic. Build with packaging\build.ps1 (it passes /DAppVersion=...).
; Installs for the current Windows account only, so no administrator approval is needed.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1B2E0A-4C7D-4E59-9B83-2D4A7C1F5E61}
AppName=PC Medic
AppVersion={#AppVersion}
AppVerName=PC Medic {#AppVersion}
AppPublisher=Ky Gray
AppPublisherURL=https://github.com/mrkygray-art/Pic-Medic
AppSupportURL=https://github.com/mrkygray-art/Pic-Medic/issues
AppUpdatesURL=https://github.com/mrkygray-art/Pic-Medic/releases
DefaultDirName={localappdata}\Programs\PC Medic
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PCMedic-Setup-{#AppVersion}
SetupIconFile=pcmedic.ico
UninstallDisplayIcon={app}\PCMedic.exe
UninstallDisplayName=PC Medic
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\dist\PCMedic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\PC Medic"; Filename: "{app}\PCMedic.exe"; Comment: "Check and fix your Windows computer"
Name: "{userdesktop}\PC Medic"; Filename: "{app}\PCMedic.exe"; Tasks: desktopicon; Comment: "Check and fix your Windows computer"

[Run]
Filename: "{app}\PCMedic.exe"; Description: "Open PC Medic now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop a running copy so its files can be removed. Saved data in %LOCALAPPDATA%\PC Medic is kept.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM PCMedic.exe /T"; Flags: runhidden; RunOnceId: "StopPCMedic"
