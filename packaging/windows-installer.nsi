; Per-user offline installer. Payload is extracted from the verified portable ZIP.
; Build via build_installer.py; never package an unverified working-tree build.
Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!ifndef APP_VERSION
!define APP_VERSION "4.0.0"
!endif
Name "Metrology Workspace ${APP_VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\MetrologyWorkspace"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "Metrology Workspace"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey "FileDescription" "Metrology Workspace Windows x64 Setup"
VIAddVersionKey "LegalCopyright" "Metrology Workspace contributors"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MetrologyWorkspace"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
Var NoIntegration

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Windows x64 is required."
    Abort
  ${EndIf}
  StrCpy $NoIntegration 0
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/NOINTEGRATION" $1
  ${IfNot} ${Errors}
    StrCpy $NoIntegration 1
  ${EndIf}
FunctionEnd

Section "Metrology Workspace" Main
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "${PAYLOAD}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $NoIntegration == 0
    SetShellVarContext current
    CreateDirectory "$SMPROGRAMS\Metrology Workspace"
    CreateShortcut "$SMPROGRAMS\Metrology Workspace\Metrology Workspace.lnk" "$INSTDIR\MetrologyWorkspace.exe" "" "$INSTDIR\MetrologyWorkspace.exe"
    CreateShortcut "$SMPROGRAMS\Metrology Workspace\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "Metrology Workspace"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "qinyuanhao17"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\MetrologyWorkspace.exe"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
    WriteRegStr HKCU "${UNINSTALL_KEY}" "URLInfoAbout" "https://github.com/qinyuanhao17/MetrologyWorkspace"
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $0 == $INSTDIR
    Delete "$SMPROGRAMS\Metrology Workspace\Metrology Workspace.lnk"
    Delete "$SMPROGRAMS\Metrology Workspace\Uninstall.lnk"
    RMDir "$SMPROGRAMS\Metrology Workspace"
    DeleteRegKey HKCU "${UNINSTALL_KEY}"
  ${EndIf}
  ; Exact shipped files only; never recursively delete personal documents/settings.
  !include "${MANIFEST}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
