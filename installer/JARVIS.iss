; JARVIS installer — Inno Setup 6 script.
; Produces JARVIS_Setup.exe: a normal Windows installer.
;   * installs to %LocalAppData%\JARVIS (no admin / no UAC prompt)
;   * desktop icon (ticked by default) + Start Menu entry
;   * downloads all voices & AI models DURING installation (JARVIS.exe --prewarm)
;   * "Launch JARVIS" checkbox at the finish page
;   * full uninstaller; your settings & keys in %APPDATA%\JARVIS are kept
;
; Build it: install Inno Setup 6 (jrsoftware.org), then run
;   installer\build_installer.bat
; or open this file in Inno Setup and press Compile.

#define MyAppName "JARVIS"
#define MyAppVersion "1.0.0"
#define MyAppExeName "JARVIS.exe"

[Setup]
AppId={{3F2504E0-4F89-41D3-9A0C-0305E82C3301}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\{#MyAppName}
DisableDirPage=no
OutputDir=..
OutputBaseFilename=JARVIS_Setup
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\jarvis.ico
UninstallDisplayName={#MyAppName} — your personal AI

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\jarvis.ico"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\jarvis.ico"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\jarvis.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
; One-time downloads (whisper model, Piper voice, wake-word models) DURING install.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--prewarm"; StatusMsg: "Downloading voices and AI models (one-time, ~300 MB)..."; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch JARVIS now"; Flags: nowait postinstall skipifsilent
