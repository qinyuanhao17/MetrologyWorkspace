; Build only from a verified isolated tag payload. Runtime /NOINTEGRATION=1
; permits install/reinstall/uninstall validation without touching user shortcuts
; or the installed application's Add/Remove Programs entry.
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ReleaseOutputDir
  #error ReleaseOutputDir is required
#endif
#ifndef ReleaseVersion
  #define ReleaseVersion "5.1.0"
#endif
#ifndef ReleaseFileVersion
  #define ReleaseFileVersion "5.1.0.0"
#endif

[Setup]
AppId={{7A19E7E1-53A3-4C47-B7E9-A5B44D5D3100}
AppName=Metrology Workspace
AppVersion={#ReleaseVersion}
AppPublisher=qinyuanhao17
AppPublisherURL=https://github.com/qinyuanhao17/MetrologyWorkspace
DefaultDirName={localappdata}\Programs\MetrologyWorkspace
DefaultGroupName=Metrology Workspace
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
VersionInfoVersion={#ReleaseFileVersion}
CreateUninstallRegKey=IntegrationEnabled
UsePreviousAppDir=no
OutputDir={#ReleaseOutputDir}
OutputBaseFilename=MetrologyWorkspace-v{#ReleaseVersion}-Windows-x64-Setup
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MetrologyWorkspace.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Metrology Workspace"; Filename: "{app}\MetrologyWorkspace.exe"; WorkingDir: "{app}"; Check: IntegrationEnabled

[Code]
function IntegrationEnabled: Boolean;
begin
  Result := ExpandConstant('{param:NOINTEGRATION|0}') <> '1';
end;
