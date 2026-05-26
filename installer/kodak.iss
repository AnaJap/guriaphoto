; Inno Setup 6 script — packages the flet `build/windows` folder into a single
; Kodak-Setup-x.y.z.exe installer with Start-menu + optional desktop shortcuts.
;
; Compile (done automatically by .github/workflows/build-windows.yml):
;   ISCC /DAppVersion=1.0.0 installer\kodak.iss
;
; NOTE: MyAppExeName must match the launcher produced by `flet build windows`.
; It is derived from [tool.flet] product ("Kodak") → "Kodak.exe". If the first
; CI run's "Show build output" step lists a different name, update it here.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define MyAppName "გურიაფოტო კოდაკი"
#define MyAppPublisher "Guriaphoto"
#define MyAppExeName "Kodak.exe"

[Setup]
; Stable, app-unique GUID (do not reuse across different apps).
AppId={{8F3A1C2E-7B4D-4E9A-9C1F-0A1B2C3D4E5F}}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Kodak
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=Output
OutputBaseFilename=Kodak-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Pull in the entire bundled app folder (exe + Flutter DLLs + data/ with the
; embedded Python runtime and dependencies). SourceDir is the .iss location,
; so this points at <repo>/build/windows.
Source: "..\build\windows\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
