#define ProjectRoot AddBackslash(SourcePath) + "..\.."
#ifndef MyAppVersion
  #define MyAppVersion "0.3.2"
#endif

[Setup]
AppId={{BFC6F5E8-9D81-4A8E-9A75-6B78486A31A4}
AppName=SonoForge
AppVersion={#MyAppVersion}
AppVerName=SonoForge {#MyAppVersion}
AppPublisher=SonoForge contributors
AppPublisherURL=https://github.com/areatu/SonoForge
AppSupportURL=https://github.com/areatu/SonoForge/issues
AppUpdatesURL=https://github.com/areatu/SonoForge/releases
DefaultDirName={autopf}\SonoForge
DefaultGroupName=SonoForge
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=no
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
CreateUninstallRegKey=yes
UninstallDisplayName=SonoForge
UninstallDisplayIcon={app}\SonoForge.exe
SetupIconFile="{#ProjectRoot}\src\echo_personal_tool\resources\logo.ico"
LicenseFile="{#ProjectRoot}\LICENSE"
OutputDir="{#ProjectRoot}\dist"
OutputBaseFilename=SonoForge-Setup-{#MyAppVersion}-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=SonoForge contributors
VersionInfoDescription=SonoForge setup
VersionInfoProductName=SonoForge
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#ProjectRoot}\dist\SonoForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SonoForge\SonoForge"; Filename: "{app}\SonoForge.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\SonoForge"; Filename: "{app}\SonoForge.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\SonoForge.exe"; Description: "Launch SonoForge"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Name: "{app}"; Type: dirifempty

[Code]
var
  RemoveUserData: Boolean;

function InitializeUninstall(): Boolean;
var
  DataForm: TSetupForm;
  InfoLabel: TNewStaticText;
  DataCheckBox: TNewCheckBox;
  UninstallButton: TNewButton;
  CancelButton: TNewButton;
begin
  RemoveUserData := False;

  { Silent uninstall has no explicit consent UI, so always preserve user data. }
  if UninstallSilent then begin
    Result := True;
    Exit;
  end;

  Result := False;
  DataForm := CreateCustomForm(ScaleX(440), ScaleY(190), False, False);
  try
    DataForm.Caption := 'Uninstall SonoForge';
    DataForm.BorderStyle := bsDialog;
    DataForm.Position := poScreenCenter;

    InfoLabel := TNewStaticText.Create(DataForm);
    InfoLabel.Parent := DataForm;
    InfoLabel.Left := ScaleX(12);
    InfoLabel.Top := ScaleY(12);
    InfoLabel.Width := ScaleX(416);
    InfoLabel.Height := ScaleY(70);
    InfoLabel.AutoSize := False;
    InfoLabel.Caption :=
      'SonoForge user data is kept by default.' + #13#10 +
      'To also delete this Windows account''s data,' + #13#10 +
      'select the checkbox below:' + #13#10 +
      ExpandConstant('{localappdata}\SonoForge');

    DataCheckBox := TNewCheckBox.Create(DataForm);
    DataCheckBox.Parent := DataForm;
    DataCheckBox.Left := ScaleX(12);
    DataCheckBox.Top := ScaleY(88);
    DataCheckBox.Width := ScaleX(416);
    DataCheckBox.Height := ScaleY(24);
    DataCheckBox.Caption := 'Also remove SonoForge user data';
    DataCheckBox.Checked := False;

    UninstallButton := TNewButton.Create(DataForm);
    UninstallButton.Parent := DataForm;
    UninstallButton.Left := ScaleX(236);
    UninstallButton.Top := ScaleY(142);
    UninstallButton.Width := ScaleX(96);
    UninstallButton.Height := ScaleY(28);
    UninstallButton.Caption := 'Uninstall';
    UninstallButton.ModalResult := mrOk;
    UninstallButton.Default := True;

    CancelButton := TNewButton.Create(DataForm);
    CancelButton.Parent := DataForm;
    CancelButton.Left := ScaleX(340);
    CancelButton.Top := ScaleY(142);
    CancelButton.Width := ScaleX(88);
    CancelButton.Height := ScaleY(28);
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;

    if DataForm.ShowModal = mrOk then begin
      RemoveUserData := DataCheckBox.Checked;
      Result := True;
    end;
  finally
    DataForm.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then begin
    DataDir := ExpandConstant('{localappdata}\SonoForge');
    if DirExists(DataDir) then begin
      if not DelTree(DataDir, True, True, True) then begin
        Log('Could not completely remove SonoForge user data from: ' + DataDir);
        if not UninstallSilent then
          MsgBox('Could not completely remove SonoForge user data from:' + #13#10 + DataDir,
            mbError, MB_OK);
      end;
    end;
  end;
end;
