; Inno Setup script for StarPost (Windows installer).
;
; Wraps the PyInstaller folder bundle (dist\starpost\) produced by
;     pyinstaller packaging\starpost.spec
; into a single Setup.exe with Start-menu / optional desktop shortcuts and an
; uninstaller.
;
; Build it (from the repo root, after the PyInstaller bundle exists) with:
;     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\starpost.iss
;
; The version defaults to the value below but can be overridden on the command
; line to match pyproject.toml without editing this file, e.g.:
;     ISCC.exe /DMyAppVersion=1.4.0 packaging\starpost.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.4.0"
#endif

#define MyAppName "StarPost"
#define MyAppPublisher "Luca"
#define MyAppURL "https://github.com/luca-santoni/starpost"
#define MyAppExeName "starpost.exe"

[Setup]
; AppId uniquely identifies the application for upgrades/uninstall. Do not change.
AppId={{A5056CA5-E96E-4E05-911D-6A00D59DE794}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases/latest
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; The bundle is 64-bit only; install into the real Program Files on x64.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-machine install (writes to Program Files); requires elevation.
PrivilegesRequired=admin
; In-app updater support: if StarPost is still running when its installer starts
; (e.g. an update launched from within the app), close it automatically so its
; files can be replaced. The [Run] entry below relaunches it afterwards, so we
; don't also restart via Restart Manager (which would launch a second copy).
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
SetupIconFile=..\src\starpost\gui\resources\StarPost-logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Emit the installer next to the bundle as dist\StarPost-<version>-Setup.exe
OutputDir=..\dist
OutputBaseFilename=StarPost-{#MyAppVersion}-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller bundle (starpost.exe + the _internal runtime folder).
Source: "..\dist\starpost\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
