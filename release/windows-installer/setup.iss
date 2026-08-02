; Inno Setup script for RemarkableSync Windows Installer
; Inno Setup 6.1 or later required (x64compatible architecture selector).
;
; Build locally (from the repo root):
;   iscc /DAppVersion=3.0.0 /DIsDev=1 release\windows-installer\setup.iss
;
; Build a signed release (suppresses the unsigned-build warning):
;   iscc /DAppVersion=3.0.0 /DIsDev=0 release\windows-installer\setup.iss
;
; Prerequisites:
;   1. PyInstaller one-folder output must exist at  dist\reMarkableSync\
;      Run:  pyinstaller --clean release\reMarkableSync.spec
;   2. Inno Setup 6.1+ must be installed (https://jrsoftware.org/isdl.php)
;      or available via:  choco install innosetup

; ---------------------------------------------------------------------------
; Compile-time constants – override with /Dname=value on the ISCC command line
; ---------------------------------------------------------------------------
#ifndef AppVersion
  #define AppVersion "3.0.0"
#endif

; IsDev = 1  →  show an "unsigned development build" warning at startup
; IsDev = 0  →  suppress the warning (use for properly code-signed releases)
#ifndef IsDev
  #define IsDev 1
#endif

#define AppName         "RemarkableSync"
#define AppExeName      "RemarkableSync.exe"
#define AppPublisher    "Jeff Steinbok"
#define AppURL          "https://github.com/JeffSteinbok/reMarkableSync"
#define StartupRegKey   "Software\Microsoft\Windows\CurrentVersion\Run"
#define StartupRegName  "reMarkableSync"

; Source root is two levels above this script (repo root)
#define SourceRoot      "..\.."

[Setup]
; Stable AppId – do NOT change; Inno Setup uses this GUID to detect and
; upgrade existing installations without uninstalling first.
AppId={{E6F3A1B2-4C5D-4E6F-A7B8-9C0D1E2F3A4B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; ---------------------------------------------------------------------------
; Per-user installation – no administrator rights required
; ---------------------------------------------------------------------------
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Default installation directory under the user's %LocalAppData%
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes

; ---------------------------------------------------------------------------
; Build output
; ---------------------------------------------------------------------------
; Source paths in [Files] are relative to SourceDir
SourceDir={#SourceRoot}
; OutputDir is relative to SourceDir (repo root), so "." places the installer
; in the repo root.  Override on the command line with /O<path> if needed.
OutputDir=.
OutputBaseFilename=RemarkableSync-Setup-{#AppVersion}

; ---------------------------------------------------------------------------
; Installer appearance and compatibility
; ---------------------------------------------------------------------------
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes

; Windows 10 or later (build 10240)
MinVersion=10.0.10240

; 64-bit Windows only (matches the PyInstaller build target)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ---------------------------------------------------------------------------
; Optional tasks presented to the user during setup
; ---------------------------------------------------------------------------
[Tasks]
Name: "desktopicon"; \
  Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; \
  Flags: unchecked

; ---------------------------------------------------------------------------
; Files – the complete PyInstaller one-folder bundle
; ---------------------------------------------------------------------------
[Files]
; Include every file produced by PyInstaller (exe + all supporting DLLs,
; Python runtime, and data files).  The source path is relative to SourceDir
; (repo root).
Source: "dist\reMarkableSync\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; ---------------------------------------------------------------------------
; Shortcuts
; ---------------------------------------------------------------------------
[Icons]
; Start Menu
Name: "{group}\{#AppName}"; \
  Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; \
  Filename: "{uninstallexe}"

; Optional desktop shortcut (user must opt in via the Tasks page)
Name: "{userdesktop}\{#AppName}"; \
  Filename: "{app}\{#AppExeName}"; \
  Tasks: desktopicon

; ---------------------------------------------------------------------------
; Post-install launch offer
; ---------------------------------------------------------------------------
[Run]
Filename: "{app}\{#AppExeName}"; \
  Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

; ---------------------------------------------------------------------------
; Uninstall
;
; IMPORTANT: {userappdata}\remarkablesync is intentionally NOT listed in
; [UninstallDelete].  The user's configuration, credentials, logs, and
; backups stored there are preserved when the application is uninstalled or
; upgraded.  Only the installation directory ({app}) is removed, which Inno
; Setup handles automatically.
; ---------------------------------------------------------------------------

; ---------------------------------------------------------------------------
; Pascal scripting
; ---------------------------------------------------------------------------
[Code]

// --------------------------------------------------------------------------
// InitializeSetup
//
// When IsDev=1 (compiled in at build time), warn the user before the wizard
// begins that this is an unsigned development build.  The user can abort.
// --------------------------------------------------------------------------
function InitializeSetup(): Boolean;
begin
  Result := True;

#if IsDev = 1
  if MsgBox(
       'WARNING: Unsigned Development Build' + #13#10 + #13#10 +
       'This installer was NOT signed with a code-signing certificate.' + #13#10 +
       'It was produced from a development or CI build and has not undergone' + #13#10 +
       'the same review process as an official release.' + #13#10 + #13#10 +
       'Only continue if you obtained this installer from a trusted source' + #13#10 +
       '(for example, a pull-request artifact from the official repository).' + #13#10 + #13#10 +
       'Do you want to continue with the installation?',
       mbConfirmation,
       MB_YESNO or MB_DEFBUTTON2) = IDNO then
  begin
    Result := False;
  end;
#endif
end;


// --------------------------------------------------------------------------
// CurStepChanged – ssPostInstall
//
// After the new files have been written, check whether the user previously
// enabled "Run at startup" from within the application (written to
// HKCU\...\Run\reMarkableSync).  If so, refresh the stored command so that
// it points to the newly installed executable.  This covers the case where
// the user upgrades or changes the installation directory.
// --------------------------------------------------------------------------
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExistingCmd: String;
  NewCmd: String;
begin
  if CurStep = ssPostInstall then
  begin
    if RegQueryStringValue(HKEY_CURRENT_USER,
                           '{#StartupRegKey}',
                           '{#StartupRegName}',
                           ExistingCmd) then
    begin
      // Rewrite the command so it references the freshly installed path.
      // Preserve the "watch --foreground" arguments that the app writes.
      NewCmd := '"' + ExpandConstant('{app}\{#AppExeName}') + '"' +
                ' watch --foreground';
      RegWriteStringValue(HKEY_CURRENT_USER,
                          '{#StartupRegKey}',
                          '{#StartupRegName}',
                          NewCmd);
    end;
  end;
end;
