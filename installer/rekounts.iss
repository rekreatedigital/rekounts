; Rekounts — Windows installer (Inno Setup 6.6+)
;
; Produces  dist\Rekounts-Setup-<version>.exe  from an already-built
; dist\Rekounts\ (see Rekounts.spec / build.bat — build.bat runs both steps).
;
; Compile:  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\rekounts.iss
;
; Three properties this script exists to guarantee, all of them checked in the
; steps below rather than assumed:
;
;   1. NO ADMIN. PrivilegesRequired=lowest and a {userpf} default directory mean
;      the installer never raises a UAC prompt. The app only ever writes to
;      %APPDATA%\Rekounts and HKCU, so there is nothing it needs elevation for,
;      and asking for it anyway is how a free dictation tool starts looking like
;      something you should not run.
;
;   2. YOUR DATA IS YOURS. Uninstalling removes the program and nothing else.
;      %APPDATA%\Rekounts — settings, dictation history, the downloaded speech
;      model — is left exactly where it is unless you tick a box that says, in
;      those words, that you want it deleted. Reinstalling over an existing
;      install never touches it at all.
;
;   3. ONE STARTUP MECHANISM. The "start at sign-in" checkbox writes the very
;      same HKCU Run value, under the same name, in the same format as the app's
;      own Settings → Launch at login switch (rekounts/startup.py). It is one
;      setting with two front doors, not two competing ones — so the app's
;      switch reads back ON afterwards, and turning it off in either place
;      turns it off.

#define AppName        "Rekounts"
#define AppPublisher   "Rekreate Digital"
#define AppUrl         "https://github.com/rekreatedigital/rekounts"
#define AppExeName     "Rekounts.exe"
#define AppUserModelID "RekreateDigital.Rekounts"

; Paths are relative to this file (installer\), so everything reaches up one level.
#define BuildDir  "..\dist\Rekounts"
#define AppExe    BuildDir + "\" + AppExeName

#if !FileExists(AppExe)
  #error Build the app first: run build.bat (expected ..\dist\Rekounts\Rekounts.exe).
#endif

; The version is READ FROM THE BUILT .exe rather than declared here. Rekounts.spec
; stamps it from rekounts/__init__.py, the one version literal in the project, so
; taking it from the binary makes it impossible to ship a Setup.exe whose name and
; Apps-&-Features entry disagree with the app inside it.
#define AppVersion GetStringFileInfo(AppExe, PRODUCT_VERSION)

; Kept byte-identical to rekounts/startup.py and rekounts/__main__.py. If either
; of those changes, this breaks quietly — hence tests/test_installer_script.py,
; which reads both files and fails when they drift apart.
#define RunKey          "Software\Microsoft\Windows\CurrentVersion\Run"
#define StartupApproved "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
#define RunValueName    "Rekounts"
#define AppMutexName    "Rekounts_SingleInstance"

[Setup]
; NEVER change AppId: it is the identity Windows uses to recognise an existing
; install. A new one turns every upgrade into a second, parallel installation.
AppId={{BEA63F29-0FE6-4389-997A-D4AC225A4184}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoCopyright=Copyright (C) 2026 {#AppPublisher}. GPL-3.0.

; --- per-user, no elevation -------------------------------------------------
PrivilegesRequired=lowest
; Deliberately NOT PrivilegesRequiredOverridesAllowed: there is no supported way
; to talk this installer into asking for admin, not even from the command line.
DefaultDirName={userpf}\{#AppName}
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

; --- the licence the user is agreeing to ------------------------------------
LicenseFile=..\LICENSE

; --- what comes out ---------------------------------------------------------
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
WizardStyle=modern
WizardSmallImageFile=wizard-small-*.bmp
Compression=lzma2/max
SolidCompression=yes

; --- what it will and will not run on ---------------------------------------
; The bundle is a CPU-only x64 build (see Rekounts.spec). x64compatible rather
; than x64os so it also installs on ARM64 Windows, which runs x64 under emulation.
ArchitecturesAllowed=x64compatible
MinVersion=10.0

; --- upgrading over a running copy ------------------------------------------
; AppMutex is the app's own single-instance mutex. Restart Manager
; (CloseApplications, on by default) only notices processes holding the files
; open; the mutex is what makes the "please close Rekounts" prompt reliable,
; including for the uninstaller.
AppMutex={#AppMutexName}
CloseApplications=yes
RestartApplications=no
SetupMutex={#AppName}Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "startupentry"; Description: "Start {#AppName} automatically when I sign in to Windows"; Flags: unchecked

[Files]
; The whole PyInstaller onedir tree. The speech model is NOT in here — it is
; downloaded once on first run, exactly as it is for a source install, which is
; why this stays a ~120 MB download instead of a ~600 MB one.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; AppUserModelID matches rekounts/ui/branding.py, so a pinned shortcut, the
; running app's taskbar button and the tray icon are all recognised as one app.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; The app's own launch-at-login entry, written in the app's own format (a quoted
; absolute path to the exe — see startup.default_command for a frozen build).
; Removal on uninstall is handled ONLY by RemoveStartupEntry in [Code], which
; guards against deleting a portable copy's autostart that points elsewhere.
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "{#RunValueName}"; \
    ValueData: """{app}\{#AppExeName}"""; Tasks: startupentry

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python writes __pycache__ folders under the bundle at runtime, and those are
; not in [Files], so without this the uninstaller leaves a skeleton of empty
; directories behind. Scoped to _internal (PyInstaller keeps everything except
; the exe there): a user who installed into a folder that already held other
; files keeps those files — never wildcard-delete {app} itself. Nothing here
; points anywhere near %APPDATA%.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
var
  RemoveUserDataChosen: Boolean;

function UserDataDir: String;
begin
  { %APPDATA%\Rekounts — rekounts/paths.py:app_data_dir(). }
  Result := ExpandConstant('{userappdata}\{#AppName}');
end;

{ --- launch at login ------------------------------------------------------ }

procedure ClearStartupApproval;
begin
  { Task Manager's Startup tab records a disable HERE, parallel to the Run key,
    and Windows honours it over the Run value. rekounts/startup.py clears it when
    you switch launch-at-login on, for exactly this reason: without it, ticking
    the box writes a Run entry that Windows then ignores, and the checkbox is a
    lie. Best-effort — a missing key is already the state we want. }
  RegDeleteValue(HKEY_CURRENT_USER, '{#StartupApproved}', '{#RunValueName}');
end;

procedure RemoveStartupEntry;
var
  Command: String;
begin
  { Removed whether the installer's checkbox or the app's own Settings switch
    wrote it — both name the installed exe — because a Run entry pointing at a
    deleted .exe is retried by Windows at every sign-in.

    But ONLY if it points into the directory being uninstalled. A portable (ZIP)
    copy running from somewhere else uses the same value name, and uninstalling
    this one must not silently switch that one's autostart off.

    (Written without the app-directory constant in braces: Pascal comments are
    brace-delimited too, so an Inno constant inside one ends the comment.) }
  if not RegQueryStringValue(HKEY_CURRENT_USER, '{#RunKey}', '{#RunValueName}',
                             Command) then
    Exit;
  if Pos(Lowercase(ExpandConstant('{app}')) + '\', Lowercase(Command)) = 0 then
    Exit;
  RegDeleteValue(HKEY_CURRENT_USER, '{#RunKey}', '{#RunValueName}');
  RegDeleteValue(HKEY_CURRENT_USER, '{#StartupApproved}', '{#RunValueName}');
end;

procedure InitializeWizard();
begin
  { Pre-tick the box for someone who already has launch-at-login on, so running
    the new installer over an old install does not quietly switch it off. }
  if RegValueExists(HKEY_CURRENT_USER, '{#RunKey}', '{#RunValueName}') then
    WizardSelectTasks('startupentry');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('startupentry') then
    ClearStartupApproval;
end;

{ --- uninstall ------------------------------------------------------------ }

function AskAboutUserData(var RemoveData: Boolean): Boolean;
var
  Form: TSetupForm;
  Intro, Detail: TNewStaticText;
  Box: TNewCheckBox;
  ContinueBtn, CancelBtn: TNewButton;
begin
  { Returns False if the user backed out of the uninstall entirely.
    RemoveData is only meaningful when it returns True. }
  Result := False;
  RemoveData := False;
  { Size is passed in, not assigned afterwards: ClientWidth/ClientHeight became
    read-only in Inno Setup 6.6. The two False flags mean the dialog is not
    resizable in either direction. }
  Form := CreateCustomForm(ScaleX(430), ScaleY(215), False, False);
  try
    Form.Caption := 'Uninstall {#AppName}';
    Form.Position := poScreenCenter;

    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.Left := ScaleX(16);
    Intro.Top := ScaleY(16);
    Intro.Width := Form.ClientWidth - ScaleX(32);
    Intro.WordWrap := True;
    Intro.AutoSize := True;
    Intro.Caption :=
      'Your settings, your dictation history and the speech model you ' +
      'downloaded are kept in:';

    Detail := TNewStaticText.Create(Form);
    Detail.Parent := Form;
    Detail.Left := ScaleX(16);
    Detail.Top := Intro.Top + Intro.Height + ScaleY(8);
    Detail.Width := Form.ClientWidth - ScaleX(32);
    Detail.WordWrap := True;
    Detail.AutoSize := True;
    Detail.Caption := UserDataDir + #13#10#13#10 +
      'Rekounts will leave that folder alone. Tick the box below only if you ' +
      'want it deleted as well — this cannot be undone.';

    Box := TNewCheckBox.Create(Form);
    Box.Parent := Form;
    Box.Left := ScaleX(16);
    Box.Top := Detail.Top + Detail.Height + ScaleY(14);
    Box.Width := Form.ClientWidth - ScaleX(32);
    Box.Height := ScaleY(20);
    Box.Checked := False;
    Box.Caption := 'Also delete my settings, history and downloaded model';

    ContinueBtn := TNewButton.Create(Form);
    ContinueBtn.Parent := Form;
    ContinueBtn.Width := ScaleX(95);
    ContinueBtn.Height := ScaleY(25);
    ContinueBtn.Left := Form.ClientWidth - ScaleX(16) - ContinueBtn.Width;
    ContinueBtn.Top := Form.ClientHeight - ScaleY(16) - ContinueBtn.Height;
    ContinueBtn.Caption := 'Continue';
    ContinueBtn.Default := True;
    ContinueBtn.ModalResult := mrOk;

    CancelBtn := TNewButton.Create(Form);
    CancelBtn.Parent := Form;
    CancelBtn.Width := ScaleX(95);
    CancelBtn.Height := ScaleY(25);
    CancelBtn.Left := ContinueBtn.Left - ScaleX(10) - CancelBtn.Width;
    CancelBtn.Top := ContinueBtn.Top;
    CancelBtn.Caption := 'Cancel';
    CancelBtn.Cancel := True;
    CancelBtn.ModalResult := mrCancel;

    if Form.ShowModal = mrOk then
    begin
      Result := True;
      RemoveData := Box.Checked;
    end;
  finally
    Form.Free;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  RemoveUserDataChosen := False;
  { A silent uninstall (/VERYSILENT, or an automated one) has nobody to ask, so
    it takes the answer that cannot destroy anything. }
  if UninstallSilent then
    Exit;
  if DirExists(UserDataDir) then
    Result := AskAboutUserData(RemoveUserDataChosen);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveStartupEntry;

  { After the program files are gone, so a failure here cannot leave a
    half-uninstalled app behind. }
  if (CurUninstallStep = usPostUninstall) and RemoveUserDataChosen then
    DelTree(UserDataDir, True, True, True);
end;
