; Whisper Dictate community Windows installer template.
;
; Build the PyInstaller payload first, then compile this file with Inno Setup:
;   pyinstaller --noconfirm --clean WhisperDictate.spec
;   ISCC.exe /DMyAppVersion=1.2.3 packaging\windows\WhisperDictate.iss
;
; The payload is the same dist\WhisperDictate onedir tree used for the
; portable ZIP.  No model cache or model weights belong in that tree: the
; application acquires and caches its models on first use.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyPayloadDir
  #define MyPayloadDir "..\..\dist\WhisperDictate"
#endif

#define MyAppName "Whisper Dictate"
#define MyAppExeName "WhisperDictate.exe"
#define MyAppId "{{B1A2C3D4-8F4E-4B1A-9C7D-2E6F5A4B3C2D}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Whisper Dictate contributors
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableWelcomePage=no
OutputDir=..\..\dist\installer
OutputBaseFilename=WhisperDictate-{#MyAppVersion}-windows-x64-setup
SetupIconFile=..\..\icon.ico
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; This is intentionally a per-user install.  The application writes its
; config, log, history, and downloaded model cache at runtime; never elevate
; the installer or default it to a Program Files location.
PrivilegesRequired=lowest
; Leave the override list blank: no /ALLUSERS or elevation escape hatch.
PrivilegesRequiredOverridesAllowed=
ChangesEnvironment=no
Uninstallable=yes
UninstallDisplayName=Whisper Dictate {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Do not inherit a machine-wide path from an older installation.
UsePreviousAppDir=no
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Dirs]
; Explicitly keep the application directory writable for its runtime files.
Name: "{app}"; Permissions: users-modify

[Files]
; The wildcard consumes the versioned output name only at installer
; compilation; it does not download or stage models.  The Check function
; below is a packaging guard against accidentally adding a model cache.
Source: "{#MyPayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: IsAllowedPayloadFile

[Tasks]
Name: startmenuicon; Description: "{cm:CreateStartMenuShortcut}"; GroupDescription: "Shortcuts:"; Flags: checked
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
// Filter common model-cache paths/files if a maintainer accidentally points
// MyPayloadDir at a populated distribution directory.  Model acquisition is
// intentionally a first-run responsibility, never an installer step.
function IsAllowedPayloadFile(const Path: String): Boolean;
var
  LowerPath: String;
  Extension: String;
begin
  LowerPath := Lowercase(Path);
  Extension := Lowercase(ExtractFileExt(LowerPath));
  Result :=
    (Pos('\models\', LowerPath) = 0) and
    (Pos('\model-cache\', LowerPath) = 0) and
    (Pos('\huggingface\', LowerPath) = 0) and
    (Pos('pytorch_model', LowerPath) = 0) and
    (Extension <> '.safetensors') and
    (Extension <> '.gguf') and
    (Extension <> '.ckpt') and
    (Extension <> '.onnx') and
    (Extension <> '.pt') and
    (Extension <> '.pth') and
    (Extension <> '.bin');
end;
