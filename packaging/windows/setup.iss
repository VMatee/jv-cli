; Unsigned development installer. No services, elevation, firewall or state deletion.
[Setup]
AppId=JV.CLI.Windows
AppName=JV CLI
AppVersion={#AppVersion}
AppPublisher=JV
DefaultDirName={localappdata}\Programs\JV CLI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
UninstallDisplayIcon={app}\jvcli.exe
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
CloseApplications=no
RestartApplications=no
SetupLogging=no
WizardStyle=modern
DirExistsWarning=no

[Tasks]
Name: userpath; Description: "Add JV CLI to your user PATH (new terminals)"

[Files]
#include Inventory

[Code]
const
  INVALID_HANDLE_VALUE = $FFFFFFFF;
  MarkerKey = 'Software\JV\CLI';
var
  UseHandle: THandle;
  LockPath: String;
  OwnPath: Boolean;

function CreateFileW(Name: String; Access, Share: Cardinal; Security: Integer;
  Creation, Flags: Cardinal; Template: Integer): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function GetFileAttributesW(Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function SafeLocation: Boolean;
var P, Parent, State: String; A: Cardinal;
begin
  P := RemoveBackslashUnlessRoot(ExpandFileName(ExpandConstant('{app}')));
  State := RemoveBackslashUnlessRoot(ExpandConstant('{localappdata}\JV\jv-cli'));
  Result := (Length(P) > 3) and (Copy(P, 2, 2) = ':\') and
    (CompareText(P, State) <> 0) and
    (CompareText(Copy(P,1,Length(State)+1), State+'\') <> 0) and
    (CompareText(Copy(State,1,Length(P)+1), P+'\') <> 0);
  while Result and (Length(P) > 3) do begin
    A := GetFileAttributesW(P);
    if (A <> $FFFFFFFF) and ((A and $400) <> 0) then Result := False;
    Parent := ExtractFileDir(P);
    if Parent = P then Break;
    P := Parent;
  end;
end;

function LockApplication: Boolean;
begin
  LockPath := ExpandConstant('{app}\use.lock');
  UseHandle := CreateFileW(LockPath, $C0000000, 0, 0, 4, $80, 0);
  Result := UseHandle <> INVALID_HANDLE_VALUE;
end;

function SafeTree(Directory: String): Boolean;
var Find: TFindRec;
begin
  Result := True;
  if FindFirst(AddBackslash(Directory)+'*', Find) then begin
    try
      repeat
        if (Find.Name <> '.') and (Find.Name <> '..') then begin
          if (Find.Attributes and $400) <> 0 then begin Result := False; Exit; end;
          if ((Find.Attributes and $10) <> 0) and not SafeTree(AddBackslash(Directory)+Find.Name) then begin Result := False; Exit; end;
        end;
      until not FindNext(Find);
    finally FindClose(Find); end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Find: TFindRec; Existing: Boolean;
begin
  Result := '';
  if not SafeLocation then begin Result := 'Choose a local application directory separate from JV state, without reparse points.'; Exit; end;
  if not SafeTree(ExpandConstant('{app}')) then begin Result := 'Reparse points in the application directory are unsupported.'; Exit; end;
  // An unrelated nonempty directory is never an installation target.
  Existing := FileExists(ExpandConstant('{app}\BUILD.json')) and FileExists(ExpandConstant('{app}\PACKAGE.sha256'));
  if not Existing and FindFirst(ExpandConstant('{app}\*'), Find) then begin
    try
      repeat
        if (Find.Name <> '.') and (Find.Name <> '..') then begin
          Result := 'Choose an empty directory or an existing JV CLI installation.'; Exit;
        end;
      until not FindNext(Find);
    finally FindClose(Find); end;
  end;
  if not ForceDirectories(ExpandConstant('{app}')) then begin Result := 'Cannot create application directory.'; Exit; end;
  if not LockApplication then Result := 'JV CLI is active. Shut down all JV CLI processes before installing or upgrading.';
end;

function SplitString(Value, Delimiter: String): TArrayOfString;
var N, At: Integer;
begin
  SetArrayLength(Result, 0);
  repeat
    At := Pos(Delimiter, Value); N := GetArrayLength(Result);
    SetArrayLength(Result, N+1);
    if At = 0 then begin Result[N] := Value; Break; end;
    Result[N] := Copy(Value, 1, At-1); Delete(Value, 1, At);
  until False;
end;

function HasSegment(Value, Segment: String): Boolean;
var Parts: TArrayOfString; I: Integer;
begin
  Result := False; Parts := SplitString(Value, ';');
  for I := 0 to GetArrayLength(Parts)-1 do
    if CompareText(RemoveBackslashUnlessRoot(Trim(Parts[I])), Segment) = 0 then Result := True;
end;

procedure CurStepChanged(Step: TSetupStep);
var Value, App, Owned: String;
begin
  if Step = ssPostInstall then begin
    App := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
    RegQueryStringValue(HKCU, MarkerKey, 'PathAdded', Owned);
    OwnPath := CompareText(Owned, App) = 0;
    if WizardIsTaskSelected('userpath') then begin
      RegQueryStringValue(HKCU, 'Environment', 'Path', Value);
      if not HasSegment(Value, App) then begin
        RegWriteStringValue(HKCU, MarkerKey, 'PathBefore', Value);
        if (Value <> '') and (Copy(Value,Length(Value),1) <> ';') then Value := Value+';';
        if not RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Value+App) then RaiseException('Cannot update user PATH');
        RegWriteStringValue(HKCU, MarkerKey, 'PathAfter', Value+App);
        OwnPath := True;
      end;
    end;
    if OwnPath then RegWriteStringValue(HKCU, MarkerKey, 'PathAdded', App);
  end;
end;

procedure DeinitializeSetup;
begin
  if (UseHandle <> 0) and (UseHandle <> INVALID_HANDLE_VALUE) then CloseHandle(UseHandle);
end;

function InitializeUninstall: Boolean;
begin
  Result := SafeLocation and SafeTree(ExpandConstant('{app}')) and LockApplication;
  if not Result then SuppressibleMsgBox('JV CLI is active or its application path is unsafe. Shut it down before uninstalling.', mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var Value, Owned, App, Updated, Prior, Added: String; Parts: TArrayOfString; I, Kept: Integer;
begin
  if Step = usPostUninstall then begin
    App := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
    if RegQueryStringValue(HKCU, MarkerKey, 'PathAdded', Owned) and (CompareText(Owned, App) = 0) then begin
      RegQueryStringValue(HKCU, 'Environment', 'Path', Value);
      RegQueryStringValue(HKCU, MarkerKey, 'PathBefore', Prior);
      RegQueryStringValue(HKCU, MarkerKey, 'PathAfter', Added);
      Parts := SplitString(Value, ';'); Updated := ''; Kept := 0;
      for I := 0 to GetArrayLength(Parts)-1 do
        if CompareText(RemoveBackslashUnlessRoot(Trim(Parts[I])), App) <> 0 then begin
          if Kept > 0 then Updated := Updated+';';
          Updated := Updated+Parts[I]; Kept := Kept+1;
        end;
      if Value = Added then Updated := Prior;
      RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Updated);
      RegDeleteValue(HKCU, MarkerKey, 'PathAdded');
      RegDeleteValue(HKCU, MarkerKey, 'PathBefore');
      RegDeleteValue(HKCU, MarkerKey, 'PathAfter');
      RegDeleteKeyIfEmpty(HKCU, MarkerKey);
    end;
  end;
end;

procedure DeinitializeUninstall;
begin
  if (UseHandle <> 0) and (UseHandle <> INVALID_HANDLE_VALUE) then begin
    CloseHandle(UseHandle);
    DeleteFile(LockPath);
    RemoveDir(ExpandConstant('{app}')); // Empty only; never remove unknown files or user state.
  end;
end;
